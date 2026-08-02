import logging
from typing import ClassVar

from analytics.models import AuditLog

logger = logging.getLogger("authentication")


class SecurityEventService:
    """Record and notify users about account-security lifecycle changes."""

    EVENT_MESSAGES: ClassVar[dict[str, tuple[str, str]]] = {
        "two_factor_setup_started": (
            "Two-factor authentication setup started",
            "A new two-factor authentication setup was started for your account.",
        ),
        "two_factor_enabled": (
            "Two-factor authentication enabled",
            "Two-factor authentication was enabled for your account.",
        ),
        "two_factor_disabled": (
            "Two-factor authentication disabled",
            "Two-factor authentication was disabled for your account.",
        ),
        "two_factor_backup_codes_regenerated": (
            "Backup codes regenerated",
            "Your two-factor authentication backup codes were regenerated.",
        ),
        "two_factor_backup_code_used": (
            "Backup code used",
            "A two-factor authentication backup code was used to sign in.",
        ),
        "password_changed": (
            "Password changed",
            "Your account password was changed.",
        ),
        "password_reset_completed": (
            "Password reset completed",
            "Your account password was reset using the recovery workflow.",
        ),
        "sessions_terminated": (
            "Session access terminated",
            "One or more authenticated sessions were terminated for your account.",
        ),
    }

    @classmethod
    def record(
        cls,
        *,
        user,
        user_type: str,
        action: str,
        ip_address: str = "",
        details: dict | None = None,
    ) -> None:
        subject, message = cls.EVENT_MESSAGES[action]
        try:
            AuditLog.log_action(
                action=action,
                user_id=user.id,
                user_type=user_type,
                user_email=user.email,
                description=message,
                resource_type="account_security",
                resource_id=user.id,
                details=details or {},
                ip_address=ip_address,
            )
        except Exception as exc:  # noqa: BLE001 - audit failure must not undo security state
            logger.error("Failed to audit security event %s: %s", action, exc)

        try:
            from notifications.services.notification_creator import (
                create_and_broadcast_notification,
            )

            create_and_broadcast_notification(
                user_id=user.id,
                user_type=user_type,
                notification_type=action,
                subject=subject,
                message=message,
                recipient_email=user.email,
                recipient_name=getattr(user, "full_name", ""),
                related_type="account_security",
                related_id=user.id,
                channel="in_app",
            )
        except Exception as exc:  # noqa: BLE001 - notification is best-effort
            logger.error("Failed to notify security event %s: %s", action, exc)
