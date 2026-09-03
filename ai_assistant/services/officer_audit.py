"""Metadata-only audit helpers for officer AI access and outcomes."""

import logging
from analytics.models import AuditLog
from analytics.services.audit_writer import normalize_audit_payload, queue_audit_failure
from ai_assistant.services.officer_review_brief import validate_review_brief

logger = logging.getLogger("ai_assistant")

AUDIT_DOMAIN = "ai_assistant"
SCOPE_POLICY_VERSION = "event-time-assignment-v1"
OFFICER_DIAGNOSTIC_CODES = frozenset(
    {
        "AI_OFFICER_OK",
        "AI_OFFICER_REQUEST_ACCEPTED",
        "AI_OFFICER_SCOPE_LIMITED",
        "AI_PROVIDER_ERROR",
        "AI_PROVIDER_BUSY",
        "AI_PROVIDER_CIRCUIT_OPEN",
        "AI_PROVIDER_PLANNER_INVALID",
        "AI_PROVIDER_TIMEOUT",
        "AI_PROVIDER_UNAVAILABLE",
        "AI_PROVIDER_STREAM_MALFORMED",
        "AI_PROVIDER_STREAM_TRUNCATED",
        "AI_OFFICER_CONSENT_CHANGED",
        "AI_OFFICER_SCOPE_CHANGED",
        "AI_OFFICER_TOOL_READ_FAILED",
        "AI_OFFICER_TOOL_UNKNOWN",
        "AI_OFFICER_TOOL_VALIDATION_FAILED",
        "AI_AUDIT_UNAVAILABLE",
        "AI_STREAM_ERROR",
        "AI_STREAM_INCOMPLETE",
        "AI_PROVIDER_STREAM_OUTPUT_LIMIT",
        "AI_PROVIDER_STREAM_DURATION_LIMIT",
        "tool_read_unavailable",
        "unsupported_domain_value",
        "evidence_truncated",
        "evidence_inconsistent",
        "brief_contract_invalid",
    }
)


class OfficerAIAuditUnavailable(RuntimeError):
    """Raised when required access metadata cannot be made durable."""


def _payload(action, scope, request_id, language, details):
    officer_index = AuditLog.blind_index(scope.officer_id)
    application_index = AuditLog.blind_index(scope.application_id)
    return normalize_audit_payload(
        {
            "action": action,
            "user_id": officer_index,
            "user_type": "loan_officer",
            "user_email": "",
            "description": "Loan officer AI assistant access metadata",
            "resource_type": "loan_application",
            "resource_id": application_index,
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
        "application_index": AuditLog.blind_index(scope.application_id),
        "request_id": request_id,
        "language": language,
        "outcome": "authorized",
        "route": "unresolved",
        "routing_source": "pending",
        "scope_outcome": "ambiguous",
        "tool_names": [],
        "tool_count": 0,
        "duration_ms": 0,
        "provider_available": "unknown",
        "diagnostic_code": "AI_OFFICER_REQUEST_ACCEPTED",
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
    diagnostic_code=None,
    route="unresolved",
    routing_source="unknown",
    scope_outcome="ambiguous",
    provider_available="unknown",
):
    names = list(tool_names or [])
    details = {
        "application_index": AuditLog.blind_index(scope.application_id),
        "request_id": request_id,
        "language": language,
        "outcome": str(outcome),
        "route": route if route in {
            "application_readiness",
            "profile_readiness",
            "document_status",
            "repayment_summary",
            "out_of_scope",
            "ambiguous",
            "unresolved",
        } else "unresolved",
        "routing_source": routing_source if routing_source in {
            "deterministic",
            "classifier",
            "pending",
            "unknown",
        } else "unknown",
        "scope_outcome": scope_outcome if scope_outcome in {
            "in_scope",
            "out_of_scope",
            "ambiguous",
            "policy",
        } else "ambiguous",
        "tool_names": names,
        "tool_count": len(names),
        "duration_ms": max(0, int(duration_ms or 0)),
        "provider_available": provider_available if provider_available in {
            "available",
            "unavailable",
            "not_required",
            "unknown",
        } else "unknown",
        "diagnostic_code": (
            diagnostic_code
            if diagnostic_code in OFFICER_DIAGNOSTIC_CODES
            else (
                "AI_OFFICER_OK"
                if outcome == "success"
                else (
                    str(outcome)
                    if str(outcome) in OFFICER_DIAGNOSTIC_CODES
                    else "AI_PROVIDER_ERROR"
                )
            )
        ),
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


def record_officer_ai_feedback(scope, request_id, language, *, rating):
    """Record a brief rating without retaining the officer's comment text."""
    safe_rating = rating if rating in {"up", "down"} else "unknown"
    details = {
        "application_index": AuditLog.blind_index(scope.application_id),
        "request_id": request_id,
        "language": language,
        "outcome": "success",
        "rating": safe_rating,
        "diagnostic_code": "AI_OFFICER_OK",
    }
    return _write_or_queue(
        _payload(
            "ai_officer_feedback_recorded",
            scope,
            request_id,
            language,
            details,
        ),
        required=False,
    )


def record_officer_review_brief(
    scope,
    request_id,
    language,
    *,
    brief,
    route="unresolved",
    routing_source="unknown",
    scope_outcome="ambiguous",
    tool_names=None,
    duration_ms=0,
    provider_available="unknown",
    diagnostic_code="AI_OFFICER_OK",
):
    """Persist review-brief state without retaining any rendered content."""
    validated = validate_review_brief(brief)
    details = {
        "application_index": AuditLog.blind_index(scope.application_id),
        "request_id": request_id,
        "language": language,
        "review_state": validated["review_state"],
        "route": route if route in {
            "application_readiness", "profile_readiness", "document_status",
            "repayment_summary", "out_of_scope", "ambiguous", "unresolved",
        } else "unresolved",
        "routing_source": routing_source if routing_source in {
            "deterministic", "classifier", "pending", "unknown",
        } else "unknown",
        "scope_outcome": scope_outcome if scope_outcome in {
            "in_scope", "out_of_scope", "ambiguous", "policy",
        } else "ambiguous",
        "tool_names": list(tool_names or []),
        "tool_count": len(tool_names or []),
        "duration_ms": max(0, int(duration_ms or 0)),
        "provider_available": provider_available if provider_available in {
            "available", "unavailable", "not_required", "unknown",
        } else "unknown",
        "diagnostic_code": (
            diagnostic_code
            if diagnostic_code in OFFICER_DIAGNOSTIC_CODES
            else "AI_OFFICER_OK"
        ),
    }
    return _write_or_queue(
        _payload(
            "ai_officer_review_brief_viewed",
            scope,
            request_id,
            language,
            details,
        ),
        required=True,
    )
