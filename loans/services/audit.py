"""Observable audit writes for loan-domain actions."""

import logging
from datetime import datetime, timezone

from django.conf import settings

from analytics.models import AuditLog

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
        return AuditLog.log_action(**kwargs)
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
        try:
            settings.MONGODB["audit_write_failures"].insert_one(
                {
                    "domain": "loans",
                    "action": action,
                    "resource_type": kwargs.get("resource_type"),
                    "resource_id": str(kwargs.get("resource_id") or ""),
                    "user_id": str(kwargs.get("user_id") or ""),
                    "user_type": str(kwargs.get("user_type") or "system"),
                    "error_type": type(exc).__name__,
                    "occurred_at": datetime.now(timezone.utc),
                    "resolved_at": None,
                }
            )
        except Exception:
            logger.exception("Loan audit failure queue write also failed")
        if required:
            raise LoanAuditUnavailable(
                "The required access audit could not be recorded"
            ) from exc
        return None
