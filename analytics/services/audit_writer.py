"""Central durable audit writer and idempotent recovery queue."""

import logging
import uuid
from datetime import datetime, timezone

from django.conf import settings

from analytics.models import AuditLog
from config.field_encryption import decrypt_value, encrypt_value

logger = logging.getLogger("analytics.audit_writer")

AUDIT_PAYLOAD_KEYS = frozenset(
    {
        "action",
        "user_id",
        "user_type",
        "user_email",
        "description",
        "resource_type",
        "resource_id",
        "details",
        "ip_address",
        "event_id",
        "idempotency_key",
        "scope_officer_id",
        "scope_policy_version",
    }
)


class AuditWriteUnavailable(RuntimeError):
    """Raised when a required audit event cannot be made durable."""


def normalize_audit_payload(kwargs):
    payload = {key: value for key, value in kwargs.items() if key in AUDIT_PAYLOAD_KEYS}
    if "event_id" not in payload and "idempotency_key" not in payload:
        payload["event_id"] = f"evt_{uuid.uuid4().hex}"
    payload["details"] = payload.get("details") or {}
    return payload


def queue_audit_failure(*, domain, payload, error):
    """Persist an encrypted, replayable event without duplicating queue rows."""
    event_id = str(payload.get("event_id") or "")
    details = payload.get("details") or {}
    subject_id = details.get("customer_id")
    if not subject_id and payload.get("user_type") == "customer":
        subject_id = payload.get("user_id")
    now = datetime.now(timezone.utc)
    collection = settings.MONGODB["audit_write_failures"]
    collection.update_one(
        {"domain": str(domain), "event_id": event_id},
        {
            "$setOnInsert": {
                "domain": str(domain),
                "event_id": event_id,
                "action": str(payload.get("action") or "unknown"),
                "subject_index": AuditLog.blind_index(subject_id),
                "payload_encrypted": encrypt_value(payload),
                "occurred_at": now,
                "attempt_count": 0,
                "last_attempt_at": None,
                "resolved_at": None,
            },
            "$set": {"error_type": type(error).__name__},
        },
        upsert=True,
    )


def record_audit(*, domain, required=False, unavailable_error=None, writer=None, **kwargs):
    """Write an event or durably queue the exact idempotent replay payload."""
    payload = normalize_audit_payload(kwargs)
    write = writer or AuditLog.log_action
    try:
        return write(**payload)
    except ValueError:
        # Invalid schema/idempotency is a producer defect, not retryable storage work.
        raise
    except Exception as exc:
        logger.exception(
            "Audit write failed: domain=%s action=%s",
            domain,
            payload.get("action"),
        )
        queued = False
        try:
            queue_audit_failure(domain=domain, payload=payload, error=exc)
            queued = True
        except Exception:
            logger.exception("Audit recovery queue write also failed: domain=%s", domain)
        if required:
            error_class = unavailable_error or AuditWriteUnavailable
            message = "Required audit could not be recorded"
            if queued:
                message = "Required audit was queued for recovery"
            raise error_class(message) from exc
        return None


def reconcile_audit_failures(*, domains=None, limit=100):
    """Replay a bounded queue using the original event ID for exactly-once effect."""
    query = {"resolved_at": None}
    if domains:
        query["domain"] = {"$in": sorted(set(domains))}
    collection = settings.MONGODB["audit_write_failures"]
    now = datetime.now(timezone.utc)
    resolved = 0
    failed = 0
    for failure in collection.find(
        query,
        sort=[("occurred_at", 1), ("_id", 1)],
        limit=max(1, min(int(limit), 500)),
    ):
        encrypted_payload = failure.get("payload_encrypted")
        payload = (
            decrypt_value(encrypted_payload)
            if encrypted_payload is not None
            else failure.get("payload")
        )
        if not isinstance(payload, dict):
            collection.update_one(
                {"_id": failure["_id"], "resolved_at": None},
                {
                    "$inc": {"attempt_count": 1},
                    "$set": {
                        "last_attempt_at": now,
                        "error_type": "InvalidRecoveryPayload",
                    },
                },
            )
            failed += 1
            continue
        if "event_id" not in payload and "idempotency_key" not in payload:
            payload = {
                **payload,
                "event_id": f"evt_recovery_{failure['_id']}",
            }
        try:
            AuditLog.log_action(**normalize_audit_payload(payload))
        except Exception as exc:  # noqa: BLE001 - replay handles backend failures
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
            failed += 1
            continue
        collection.update_one(
            {"_id": failure["_id"], "resolved_at": None},
            {
                "$inc": {"attempt_count": 1},
                "$set": {"last_attempt_at": now, "resolved_at": now},
                "$unset": {"payload_encrypted": "", "payload": ""},
            },
        )
        resolved += 1
    return {"resolved": resolved, "failed": failed}
