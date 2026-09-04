"""Allowlisted, recoverable audit writes for sensitive document operations."""

from analytics.models import AuditLog
from analytics.services.audit_writer import reconcile_audit_failures, record_audit

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
    "search_applied",
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
    return record_audit(
        domain="documents",
        required=required,
        unavailable_error=DocumentAuditUnavailable,
        writer=AuditLog.log_action,
        **payload,
    )


def reconcile_document_audit_failures(limit=100):
    return reconcile_audit_failures(domains={"documents"}, limit=limit)["resolved"]
