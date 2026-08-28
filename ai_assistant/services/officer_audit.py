"""Metadata-only audit helpers for officer AI access and outcomes."""

import logging

from analytics.models import AuditLog
from analytics.services.audit_writer import normalize_audit_payload, queue_audit_failure

logger = logging.getLogger("ai_assistant")

AUDIT_DOMAIN = "ai_assistant"
SCOPE_POLICY_VERSION = "event-time-assignment-v1"


class OfficerAIAuditUnavailable(RuntimeError):
    """Raised when required access metadata cannot be made durable."""


def _payload(action, scope, request_id, language, details):
    officer_index = AuditLog.blind_index(scope.officer_id)
    return normalize_audit_payload(
        {
            "action": action,
            "user_id": officer_index,
            "user_type": "loan_officer",
            "user_email": "",
            "description": "Loan officer AI assistant access metadata",
            "resource_type": "loan_application",
            "resource_id": scope.application_id,
            "details": details,
            "ip_address": "",
            "idempotency_key": f"officer-ai:{request_id}:{action}",
            "scope_officer_index": officer_index,
            "scope_policy_version": SCOPE_POLICY_VERSION,
        }
    )


def _write_or_queue(payload, *, required):
    try:
        return AuditLog.log_action(**payload)
    except ValueError as exc:
        logger.error(
            "Officer AI audit payload was rejected",
            extra={
                "request_id": payload.get("details", {}).get("request_id"),
                "action": payload.get("action"),
            },
        )
        if required:
            raise OfficerAIAuditUnavailable(
                "Required officer AI access audit is invalid"
            ) from exc
        return None
    except Exception as exc:
        try:
            queue_audit_failure(domain=AUDIT_DOMAIN, payload=payload, error=exc)
        except Exception as queue_exc:
            logger.error(
                "Officer AI audit could not be made durable",
                extra={
                    "request_id": payload.get("details", {}).get("request_id"),
                    "action": payload.get("action"),
                },
            )
            if required:
                raise OfficerAIAuditUnavailable(
                    "Required officer AI access audit is unavailable"
                ) from queue_exc
        return None


def record_officer_ai_access(scope, request_id, language):
    details = {
        "application_id": scope.application_id,
        "request_id": request_id,
        "language": language,
        "outcome": "authorized",
        "tool_names": [],
        "tool_count": 0,
        "duration_ms": 0,
    }
    return _write_or_queue(
        _payload(
            "ai_officer_assistant_access",
            scope,
            request_id,
            language,
            details,
        ),
        required=True,
    )


def record_officer_ai_result(
    scope,
    request_id,
    language,
    *,
    outcome,
    tool_names=None,
    duration_ms=0,
):
    names = list(tool_names or [])
    details = {
        "application_id": scope.application_id,
        "request_id": request_id,
        "language": language,
        "outcome": str(outcome),
        "tool_names": names,
        "tool_count": len(names),
        "duration_ms": max(0, int(duration_ms or 0)),
    }
    return _write_or_queue(
        _payload(
            "ai_officer_assistant_result",
            scope,
            request_id,
            language,
            details,
        ),
        required=False,
    )
