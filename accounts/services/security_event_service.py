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
        "email_change_requested": (
            "Email change requested",
            "A request to change your account email address was submitted.",
        ),
        "email_changed": (
            "Email address changed",
            "Your account email address was changed and active sessions were revoked.",
        ),
        "account_suspended": (
            "Account suspended",
            "Your account has been suspended. Please contact support for assistance.",
        ),
        "account_deactivated": (
            "Account deactivated",
            "Your account has been deactivated.",
        ),
        "account_deletion_requested": (
            "Account deletion requested",
            "Your account deletion request is scheduled and pending retention review.",
        ),
        "account_deletion_cancelled": (
            "Account deletion cancelled",
            "Your account deletion request has been cancelled and account access was restored.",
        ),
        "account_deleted": (
            "Account deleted",
            "Your account has been closed and personally identifiable fields were anonymized.",
        ),
        "two_factor_recovery_requested": (
            "2FA recovery requested",
            "A two-factor recovery request was submitted for your account.",
        ),
        "two_factor_recovery_approved": (
            "2FA recovery approved",
            "Your two-factor recovery request was approved and 2FA was reset.",
        ),
        "two_factor_recovery_rejected": (
            "2FA recovery rejected",
            "Your two-factor recovery request was reviewed and rejected.",
        ),
        "admin_customer_unlock": (
            "Account unlocked by administrator",
            "An administrator unlocked your account after lockout.",
        ),
        "new_device_login": (
            "New device sign-in",
            "A sign-in from a new device or network location was detected.",
        ),
        "admin_permissions_changed": (
            "Administrator privileges changed",
            "Your administrator permissions or privilege level was changed.",
        ),
    }

    @classmethod
    def record_new_device_login_if_first(
        cls,
        *,
        user,
        user_type: str,
        session_id: str,
        ip_address: str = "",
        device_info: str = "",
    ) -> None:
        from accounts.models.activity import ActiveSession

        prior_session = ActiveSession.find_one(
            {
                "user_id": str(user.id),
                "role": user_type,
                "session_id": {"$ne": str(session_id)},
                "ip_address": ip_address,
                "device_info": device_info,
            }
        )
        if prior_session:
            return

        cls.record(
            user=user,
            user_type=user_type,
            action="new_device_login",
            ip_address=ip_address,
            details={
                "session_id": str(session_id),
                "device_info": device_info,
            },
        )

    @classmethod
    def record(
        cls,
        *,
        user,
        user_type: str,
        action: str,
        ip_address: str = "",
        details: dict | None = None,
        record_audit: bool = True,
    ) -> None:
        subject, message = cls.EVENT_MESSAGES[action]
        if record_audit:
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
            except (
                Exception
            ) as exc:  # noqa: BLE001 - audit failure must not undo security state
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
