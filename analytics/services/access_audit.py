"""Fail-closed audit recording for privileged Analytics reads."""

import logging

from analytics.models import AuditLog

logger = logging.getLogger("analytics")


class AnalyticsAccessAuditError(RuntimeError):
    """Raised when a privileged Analytics response cannot be audited."""


def record_privileged_read(*, actor, actor_type: str, endpoint: str):
    """Record an access without copying query strings or sensitive actor fields."""
    actor_id = str(getattr(actor, "id", "") or "").strip()
    try:
        return AuditLog.log_action(
            action="analytics_privileged_read",
            user_id=actor_id or None,
            user_type=actor_type,
            description="Privileged Analytics endpoint accessed",
            resource_type="analytics_endpoint",
            resource_id=endpoint,
        )
    except Exception as exc:
        logger.exception("Privileged Analytics access audit failed")
        raise AnalyticsAccessAuditError(
            "Privileged Analytics access could not be audited"
        ) from exc
