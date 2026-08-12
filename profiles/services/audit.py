"""Observable and recoverable audit writes for the Profiles domain."""

from analytics.models import AuditLog
from analytics.services.audit_writer import record_audit
from profiles.metrics import PROFILE_AUDIT_FAILURES, increment


class ProfileAuditUnavailable(RuntimeError):
    """Raised when sensitive data must not be returned without an audit."""


def record_profile_audit(*, required=False, **kwargs):
    try:
        return record_audit(
            domain="profiles",
            required=required,
            unavailable_error=ProfileAuditUnavailable,
            writer=AuditLog.log_action,
            **kwargs,
        )
    except ProfileAuditUnavailable:
        action = str(kwargs.get("action") or "unknown")
        increment(PROFILE_AUDIT_FAILURES, action=action)
        raise
