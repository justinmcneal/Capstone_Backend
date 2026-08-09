"""Observable and recoverable audit writes for the Profiles domain."""

import logging
from datetime import datetime, timezone

from django.conf import settings

from analytics.models import AuditLog
from profiles.metrics import PROFILE_AUDIT_FAILURES, increment

logger = logging.getLogger("profiles.audit")


class ProfileAuditUnavailable(RuntimeError):
    """Raised when sensitive data must not be returned without an audit."""


def record_profile_audit(*, required=False, **kwargs):
    try:
        return AuditLog.log_action(**kwargs)
    except Exception as exc:
        action = str(kwargs.get("action") or "unknown")
        increment(PROFILE_AUDIT_FAILURES, action=action)
        logger.exception(
            "Profile audit write failed: action=%s resource_type=%s resource_id=%s",
            action,
            kwargs.get("resource_type"),
            kwargs.get("resource_id"),
        )
        try:
            settings.MONGODB["audit_write_failures"].insert_one(
                {
                    "domain": "profiles",
                    "action": action,
                    "payload": {
                        key: value
                        for key, value in kwargs.items()
                        if key
                        in {
                            "action",
                            "user_id",
                            "user_type",
                            "user_email",
                            "description",
                            "resource_type",
                            "resource_id",
                            "details",
                            "ip_address",
                        }
                    },
                    "error_type": type(exc).__name__,
                    "attempt_count": 0,
                    "occurred_at": datetime.now(timezone.utc),
                    "last_attempt_at": None,
                    "resolved_at": None,
                }
            )
        except Exception:
            logger.exception("Profile audit failure queue write also failed")
        if required:
            raise ProfileAuditUnavailable(
                "The required profile audit could not be recorded"
            ) from exc
        return None
