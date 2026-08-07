import logging
import re
from datetime import datetime, timedelta, timezone

from django.conf import settings
from pymongo import ReturnDocument

from accounts.models import Admin, LoanOfficer
from accounts.services.auth_service import AuthService
from accounts.services.otp_service import OTPService
from accounts.services.security_event_service import SecurityEventService
from accounts.tasks import queue_password_reset_delivery
from accounts.utils.identity_policy import find_accounts_by_email
from accounts.utils.token_utils import TokenUtils

logger = logging.getLogger("authentication")


class PasswordService:
    GENERIC_RESET_INIT_MESSAGE = (
        "If an account with this email exists, a password reset OTP has been sent."
    )
    GENERIC_RESET_VERIFY_ERROR = "Invalid email or OTP"
    RESET_ATTEMPT_FIELD = "password_reset_attempt_count"
    RESET_LAST_ATTEMPT_FIELD = "password_reset_last_attempt"
    RESET_ISSUE_COOLDOWN_SECONDS = 60
    RESET_ISSUE_WINDOW_SECONDS = 3600
    MAX_RESET_ISSUES_PER_WINDOW = 5

    @staticmethod
    def _find_by_email(model, email):
        normalized_email = email.lower().strip()
        user = model.find_one({"email": normalized_email})
        if user:
            return user

        return model.find_one(
            {"email": re.compile(f"^{re.escape(normalized_email)}$", re.IGNORECASE)}
        )

    @staticmethod
    def _find_user_by_email(email, requested_user_type=None):
        """
        Search for a user across all models: Customer, LoanOfficer, and Admin.
        Returns (user, user_type) tuple, or (None, None) if not found.
        """
        email = email.lower().strip()

        if requested_user_type == "customer":
            return AuthService.get_customer_by_email(email), "customer"
        if requested_user_type == "loan_officer":
            return PasswordService._find_by_email(LoanOfficer, email), "loan_officer"
        if requested_user_type == "admin":
            return PasswordService._find_by_email(Admin, email), "admin"

        matches = find_accounts_by_email(email)
        if len(matches) != 1:
            # A role is mandatory when legacy data contains the same email in
            # more than one account collection. Never choose a role by order.
            return None, None

        user_type, user = next(iter(matches.items()))
        return user, user_type

    @staticmethod
    def initiate_password_reset(email, requested_user_type=None, ip_address=""):
        user, user_type = PasswordService._find_user_by_email(
            email, requested_user_type
        )
        if not user:
            logger.info(f"Password reset requested for unknown email: {email}")
            return (True, PasswordService.GENERIC_RESET_INIT_MESSAGE)

        # Check if account is active (for LoanOfficer and Admin)
        if (
            user_type in ("loan_officer", "admin")
            and hasattr(user, "active")
            and not user.active
        ):
            logger.info(
                f"Password reset requested for inactive account: {email} ({user_type})"
            )
            return (True, PasswordService.GENERIC_RESET_INIT_MESSAGE)

        now = datetime.now(timezone.utc)
        collection = settings.MONGODB[user.collection_name]
        window_cutoff = now - timedelta(
            seconds=PasswordService.RESET_ISSUE_WINDOW_SECONDS
        )
        collection.update_one(
            {
                "_id": user._id,
                "$or": [
                    {"password_reset_window_started_at": {"$exists": False}},
                    {"password_reset_window_started_at": None},
                    {"password_reset_window_started_at": {"$lte": window_cutoff}},
                ],
            },
            {
                "$set": {
                    "password_reset_window_started_at": now,
                    "password_reset_issue_count": 0,
                    "updated_at": now,
                }
            },
        )

        # Use password reset expiry (15 minutes) instead of default (10 minutes).
        OTPService.set_otp(
            user,
            "password_reset_otp",
            "password_reset_otp_expires",
            expiry_minutes=OTPService.PASSWORD_RESET_EXPIRY_MINUTES,
        )
        encrypted_otp = user.to_dict()["password_reset_otp"]
        cooldown_cutoff = now - timedelta(
            seconds=PasswordService.RESET_ISSUE_COOLDOWN_SECONDS
        )
        issued = collection.find_one_and_update(
            {
                "_id": user._id,
                "$and": [
                    {
                        "$or": [
                            {"password_reset_last_sent_at": {"$exists": False}},
                            {"password_reset_last_sent_at": None},
                            {"password_reset_last_sent_at": {"$lte": cooldown_cutoff}},
                        ]
                    },
                    {
                        "$or": [
                            {"password_reset_issue_count": {"$exists": False}},
                            {
                                "password_reset_issue_count": {
                                    "$lt": PasswordService.MAX_RESET_ISSUES_PER_WINDOW
                                }
                            },
                        ]
                    },
                ],
            },
            {
                "$set": {
                    "password_reset_otp": encrypted_otp,
                    "password_reset_otp_expires": user.password_reset_otp_expires,
                    "password_reset_attempt_count": 0,
                    "password_reset_last_attempt": None,
                    "password_reset_last_sent_at": now,
                    "password_reset_delivery_status": "pending",
                    "password_reset_delivery_attempts": 0,
                    "password_reset_delivery_last_error": "",
                    "password_reset_delivery_updated_at": now,
                    "password_reset_delivery_next_attempt_at": now,
                    "updated_at": now,
                },
                "$inc": {"password_reset_issue_count": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if issued is None:
            logger.info(
                "Password reset issuance suppressed by cooldown for %s (%s)",
                email,
                user_type,
            )
            return (True, PasswordService.GENERIC_RESET_INIT_MESSAGE)

        queued = queue_password_reset_delivery(
            user_id=str(user.id),
            user_type=user_type,
            expected_expiry=issued["password_reset_otp_expires"],
        )
        logger.info(
            "Password reset OTP delivery %s for %s (%s)",
            "queued" if queued else "pending reconciliation",
            email,
            user_type,
        )
        SecurityEventService.record(
            user=user,
            user_type=user_type,
            action="password_reset_requested",
            ip_address=ip_address,
            details={"delivery": "queued" if queued else "pending_reconciliation"},
        )
        return (True, PasswordService.GENERIC_RESET_INIT_MESSAGE)

    @staticmethod
    def _check_reset_otp_rate_limit(user):
        return OTPService.check_otp_rate_limit(
            user,
            PasswordService.RESET_ATTEMPT_FIELD,
            PasswordService.RESET_LAST_ATTEMPT_FIELD,
        )

    @staticmethod
    def _increment_reset_otp_attempt(user):
        OTPService.increment_otp_attempt(
            user,
            PasswordService.RESET_ATTEMPT_FIELD,
            PasswordService.RESET_LAST_ATTEMPT_FIELD,
        )

    @staticmethod
    def _reset_reset_otp_attempts(user):
        OTPService.reset_otp_attempts(
            user,
            PasswordService.RESET_ATTEMPT_FIELD,
            PasswordService.RESET_LAST_ATTEMPT_FIELD,
        )

    @staticmethod
    def verify_reset_otp(email, otp, requested_user_type=None):
        user, user_type = PasswordService._find_user_by_email(
            email, requested_user_type
        )
        if not user:
            return (False, PasswordService.GENERIC_RESET_VERIFY_ERROR)

        allowed, seconds_remaining = PasswordService._check_reset_otp_rate_limit(user)
        if not allowed:
            logger.warning(
                f"Password reset OTP verify rate limit for {email} ({user_type}): "
                f"{seconds_remaining}s remaining"
            )
            return (
                False,
                f"Too many OTP attempts. Please try again in {seconds_remaining} seconds.",
            )

        valid, _message = OTPService.validate_otp(
            user, otp, "password_reset_otp", "password_reset_otp_expires"
        )

        if not valid:
            PasswordService._increment_reset_otp_attempt(user)
            return (False, PasswordService.GENERIC_RESET_VERIFY_ERROR)

        PasswordService._reset_reset_otp_attempts(user)

        return (True, "OTP verified successfully")

    @staticmethod
    def reset_password(email, otp, new_password, requested_user_type=None):
        user, user_type = PasswordService._find_user_by_email(
            email, requested_user_type
        )
        if not user:
            return (False, PasswordService.GENERIC_RESET_VERIFY_ERROR)

        allowed, seconds_remaining = PasswordService._check_reset_otp_rate_limit(user)
        if not allowed:
            logger.warning(
                f"Password reset rate limit for {email} ({user_type}): "
                f"{seconds_remaining}s remaining"
            )
            return (
                False,
                f"Too many OTP attempts. Please try again in {seconds_remaining} seconds.",
            )

        valid, _message = OTPService.validate_otp(
            user, otp, "password_reset_otp", "password_reset_otp_expires"
        )

        if not valid:
            PasswordService._increment_reset_otp_attempt(user)
            return (False, PasswordService.GENERIC_RESET_VERIFY_ERROR)

        if user.check_password(new_password):
            return (False, "New password must be different from the old password")

        user.set_password(new_password)
        now = datetime.now(timezone.utc)
        updates = {
            "password": user.password,
            "password_reset_otp": None,
            "password_reset_otp_expires": None,
            "password_reset_attempt_count": 0,
            "password_reset_last_attempt": None,
            "password_reset_delivery_status": "consumed",
            "password_reset_delivery_next_attempt_at": None,
            "password_reset_delivery_updated_at": now,
            "failed_login_attempts": 0,
            "locked_until": None,
            "updated_at": now,
        }
        if hasattr(user, "must_change_password"):
            updates["must_change_password"] = False

        document = settings.MONGODB[user.collection_name].find_one_and_update(
            {
                "_id": user._id,
                "password_reset_otp": {"$ne": None},
                "password_reset_otp_expires": user.password_reset_otp_expires,
            },
            {"$set": updates, "$inc": {"security_version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return (False, PasswordService.GENERIC_RESET_VERIFY_ERROR)

        user.security_version = int(document.get("security_version", 1))
        user.failed_login_attempts = 0
        user.locked_until = None
        if hasattr(user, "must_change_password"):
            user.must_change_password = False
        user.password_reset_otp = None
        user.password_reset_otp_expires = None
        if getattr(user, "id", None):
            TokenUtils.revoke_all_sessions(user.id, user_type)

        logger.info(f"Password reset successful for {email} ({user_type})")
        return (True, "Password has been reset successfully")

    @staticmethod
    def change_password(customer, old_password, new_password):
        if not customer.check_password(old_password):
            return (False, "Old password is incorrect")

        if customer.check_password(new_password):
            return (False, "New password must be different from the old password")

        customer.set_password(new_password)
        customer.security_version = int(getattr(customer, "security_version", 1)) + 1
        if hasattr(customer, "must_change_password"):
            customer.must_change_password = False
        customer.save()
        if getattr(customer, "id", None):
            TokenUtils.revoke_all_sessions(
                customer.id, getattr(customer, "role", "customer")
            )
        return (True, "Password has been changed successfully")
