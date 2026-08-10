"""Allowlisted, recoverable audit writes for sensitive document operations."""

import logging
from datetime import datetime, timezone

from django.conf import settings

from analytics.models import AuditLog

logger = logging.getLogger("documents.audit")

ALLOWED_DETAIL_KEYS = {
    "action",
    "customer_id",
    "document_type",
    "filter_customer_id",
    "filter_document_type",
    "filter_status",
    "page",
    "page_size",
    "reason_code",
    "replayed",
    "result_count",
    "revision",
    "size",
    "status",
    "upload_method",
    "upload_session_id",
}
PAYLOAD_KEYS = {
    "action",
    "user_id",
    "user_type",
    "description",
    "resource_type",
    "resource_id",
    "details",
    "ip_address",
}


class DocumentAuditUnavailable(RuntimeError):
    """Raised when a required sensitive-read audit cannot be made durable."""


def _allowlisted_payload(kwargs):
    payload = {key: value for key, value in kwargs.items() if key in PAYLOAD_KEYS}
    details = payload.get("details") or {}
    payload["details"] = {
        key: value for key, value in details.items() if key in ALLOWED_DETAIL_KEYS
    }
    return payload


def record_document_audit(*, required=False, **kwargs):
    payload = _allowlisted_payload(kwargs)
    try:
        return AuditLog.log_action(**payload)
    except Exception as exc:
        action = str(payload.get("action") or "unknown")
        logger.exception("Document audit write failed: action=%s", action)
        queued = False
        try:
            settings.MONGODB["audit_write_failures"].insert_one(
                {
                    "domain": "documents",
                    "action": action,
                    "payload": payload,
                    "error_type": type(exc).__name__,
                    "attempt_count": 0,
                    "occurred_at": datetime.now(timezone.utc),
                    "last_attempt_at": None,
                    "resolved_at": None,
                }
            )
            queued = True
        except Exception:
            logger.exception("Document audit failure queue write also failed")
        if required:
            message = "Required document audit could not be recorded"
            if queued:
                message = "Required document audit was queued for recovery"
            raise DocumentAuditUnavailable(message) from exc
        return None


def reconcile_document_audit_failures(limit=100):
    now = datetime.now(timezone.utc)
    collection = settings.MONGODB["audit_write_failures"]
    resolved = 0
    for failure in collection.find(
        {"domain": "documents", "resolved_at": None},
        sort=[("occurred_at", 1)],
        limit=max(1, min(int(limit), 500)),
    ):
        try:
            AuditLog.log_action(**_allowlisted_payload(failure.get("payload", {})))
        except Exception as exc:
            collection.update_one(
                {"_id": failure["_id"], "resolved_at": None},
                {
                    "$inc": {"attempt_count": 1},
                    "$set": {
                        "last_attempt_at": now,
                        "error_type": type(exc).__name__,
                    },
                },
            )
            continue
        collection.update_one(
            {"_id": failure["_id"], "resolved_at": None},
            {
                "$inc": {"attempt_count": 1},
                "$set": {"last_attempt_at": now, "resolved_at": now},
                "$unset": {"payload": ""},
            },
        )
        resolved += 1
    return resolved
