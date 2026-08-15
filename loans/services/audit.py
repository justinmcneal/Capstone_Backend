"""Observable audit writes for loan-domain actions."""

import logging

from bson import ObjectId
from django.conf import settings

from analytics.models import AuditLog
from analytics.services.audit_writer import record_audit
from loans.metrics import LOAN_DOMAIN_EVENTS, increment

logger = logging.getLogger("loans.audit")

try:
    from prometheus_client import Counter

    LOAN_AUDIT_WRITE_FAILURES = Counter(
        "loan_audit_write_failures_total",
        "Loan audit records that could not be written",
        ("action",),
    )
except (ImportError, ValueError):  # duplicate metric registration in some test reloads
    LOAN_AUDIT_WRITE_FAILURES = None


class LoanAuditUnavailable(RuntimeError):
    """Raised when an operation must not expose data without an audit record."""


OFFICER_EVENT_SCOPE_POLICY_VERSION = "event-time-assignment-v1"


def _event_scope_officer_id(payload):
    """Snapshot the authorized officer when the event is created."""
    details = payload.get("details") or {}
    explicit = details.get("assigned_officer")
    if explicit:
        return str(explicit)

    loan_id = details.get("loan_id")
    if payload.get("resource_type") == "loan":
        loan_id = payload.get("resource_id")
    loan_id = str(loan_id or "").strip()
    if loan_id and ObjectId.is_valid(loan_id):
        try:
            application = settings.MONGODB["loan_applications"].find_one(
                {"_id": ObjectId(loan_id)}, {"assigned_officer": 1}
            )
            assigned = (application or {}).get("assigned_officer")
            if assigned:
                return str(assigned)
        except Exception:
            logger.exception("Unable to resolve event-time loan audit scope")

    if payload.get("user_type") == "loan_officer" and payload.get("user_id"):
        return str(payload["user_id"])
    return None


def record_loan_audit(*, required=False, **kwargs):
    """Write an audit event and surface failures through logs, metrics, and a queue.

    Normal financial mutations are not rolled back merely because their audit
    write failed. Sensitive reads can pass ``required=True`` to fail closed.
    """
    scoped_officer_id = _event_scope_officer_id(kwargs)
    if scoped_officer_id:
        kwargs = {
            **kwargs,
            "scope_officer_id": scoped_officer_id,
            "scope_policy_version": OFFICER_EVENT_SCOPE_POLICY_VERSION,
        }
    try:
        result = record_audit(
            domain="loans",
            required=required,
            unavailable_error=LoanAuditUnavailable,
            writer=AuditLog.log_action,
            **kwargs,
        )
        action = str(kwargs.get("action") or "")
        operation = (
            "payment" if "payment" in action or "payoff" in action
            else "disbursement" if "disbursement" in action
            else "transition" if action.startswith("loan_")
            else "other"
        )
        increment(LOAN_DOMAIN_EVENTS, operation=operation, outcome="recorded")
        return result
    except LoanAuditUnavailable:
        action = str(kwargs.get("action") or "unknown")
        if LOAN_AUDIT_WRITE_FAILURES is not None:
            LOAN_AUDIT_WRITE_FAILURES.labels(action=action).inc()
        raise
    except ValueError:
        raise
    except Exception as exc:  # audit storage must not hide the original outcome
        action = str(kwargs.get("action") or "unknown")
        if LOAN_AUDIT_WRITE_FAILURES is not None:
            LOAN_AUDIT_WRITE_FAILURES.labels(action=action).inc()
        logger.exception(
            "Loan audit write failed: action=%s resource_type=%s resource_id=%s",
            action,
            kwargs.get("resource_type"),
            kwargs.get("resource_id"),
        )
        if required:
            raise LoanAuditUnavailable(
                "The required access audit could not be recorded"
            ) from exc
        return None
