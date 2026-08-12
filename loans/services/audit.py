"""Observable audit writes for loan-domain actions."""

import logging

from analytics.models import AuditLog
from analytics.services.audit_writer import record_audit

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


def record_loan_audit(*, required=False, **kwargs):
    """Write an audit event and surface failures through logs, metrics, and a queue.

    Normal financial mutations are not rolled back merely because their audit
    write failed. Sensitive reads can pass ``required=True`` to fail closed.
    """
    try:
        return record_audit(
            domain="loans",
            required=required,
            unavailable_error=LoanAuditUnavailable,
            writer=AuditLog.log_action,
            **kwargs,
        )
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
