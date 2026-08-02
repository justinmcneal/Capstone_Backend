import logging
from datetime import datetime, timedelta, timezone

from django.conf import settings
from pymongo import ReturnDocument

from accounts.utils.email_utils import EmailUtils

logger = logging.getLogger("authentication")


class LockoutService:
    """
    Service for handling account lockout protection after failed login attempts.

    Security features:
    - Locks account after MAX_ATTEMPTS failed password attempts
    - Auto-unlocks after LOCKOUT_DURATION
    - Provides admin unlock capability
    """

    MAX_ATTEMPTS = 5
    LOCKOUT_DURATION = timedelta(minutes=15)

    @staticmethod
    def is_account_locked(customer) -> tuple:
        """
        Check if the customer account is currently locked.

        Returns:
            tuple: (is_locked: bool, seconds_remaining: int)
        """
        if not customer.locked_until:
            return (False, 0)

        locked_until = EmailUtils.to_aware_utc(customer.locked_until)
        assert locked_until is not None  # to_aware_utc preserves non-None input
        now = datetime.now(timezone.utc)
        if locked_until > now:
            seconds_remaining = int((locked_until - now).total_seconds())
            return (True, seconds_remaining)

        # Clear only the expired value observed here. A concurrent request may
        # already have extended the lock and must not be overwritten.
        result = settings.MONGODB[customer.collection_name].update_one(
            {"_id": customer._id, "locked_until": {"$lte": now}},
            {
                "$set": {
                    "failed_login_attempts": 0,
                    "locked_until": None,
                    "updated_at": now,
                }
            },
        )
        if result.modified_count:
            customer.failed_login_attempts = 0
            customer.locked_until = None
        else:
            current = settings.MONGODB[customer.collection_name].find_one(
                {"_id": customer._id}, {"locked_until": 1}
            )
            current_lock = EmailUtils.to_aware_utc(
                (current or {}).get("locked_until")
            )
            if current_lock and current_lock > now:
                customer.locked_until = current_lock
                return (True, int((current_lock - now).total_seconds()))
        return (False, 0)

    @staticmethod
    def record_failed_attempt(customer, lockout_duration=None) -> tuple:
        """
        Record a failed login attempt and lock account if threshold reached.

        Returns:
            tuple: (is_now_locked: bool, attempts_remaining: int)
        """
        now = datetime.now(timezone.utc)
        collection = settings.MONGODB[customer.collection_name]
        document = collection.find_one_and_update(
            {"_id": customer._id},
            {
                "$inc": {"failed_login_attempts": 1},
                "$set": {"last_login_attempt": now, "updated_at": now},
            },
            return_document=ReturnDocument.AFTER,
        )
        failed_attempts = int((document or {}).get("failed_login_attempts", 1))
        customer.failed_login_attempts = failed_attempts
        customer.last_login_attempt = now
        attempts_remaining = max(
            LockoutService.MAX_ATTEMPTS - failed_attempts, 0
        )

        if failed_attempts >= LockoutService.MAX_ATTEMPTS:
            duration = lockout_duration or LockoutService.LOCKOUT_DURATION
            locked_until = now + duration
            collection.update_one(
                {
                    "_id": customer._id,
                    "failed_login_attempts": {"$gte": LockoutService.MAX_ATTEMPTS},
                },
                {"$max": {"locked_until": locked_until}},
            )
            customer.locked_until = locked_until
            logger.warning(
                f"Account locked for {customer.email} after {LockoutService.MAX_ATTEMPTS} failed attempts"
            )
            return (True, 0)

        logger.info(
            f"Failed login attempt {failed_attempts}/{LockoutService.MAX_ATTEMPTS} for {customer.email}"
        )
        return (False, attempts_remaining)

    @staticmethod
    def reset_lockout(customer, *, last_login_attempt=None):
        """
        Reset failed attempts and unlock account.
        Called on successful login or by admin.
        """
        now = datetime.now(timezone.utc)
        updates = {
            "failed_login_attempts": 0,
            "locked_until": None,
            "updated_at": now,
        }
        if last_login_attempt is not None:
            updates["last_login_attempt"] = last_login_attempt
            customer.last_login_attempt = last_login_attempt
        settings.MONGODB[customer.collection_name].update_one(
            {"_id": customer._id}, {"$set": updates}
        )
        customer.failed_login_attempts = 0
        customer.locked_until = None
        logger.info(f"Account lockout reset for {customer.email}")

    @staticmethod
    def admin_unlock(user_email: str, role: str = "customer") -> bool:
        """
        Admin function to unlock a user account.

        Args:
            user_email: Email of the account to unlock.
            role: Role of the account to unlock ('customer', 'loan_officer', 'admin').
                  Defaults to 'customer' for backward compatibility.

        Returns:
            bool: True if account was unlocked, False if not found
        """
        from accounts.models import Admin, Customer, LoanOfficer

        role = (role or "customer").strip().lower()

        if role == "loan_officer":
            user = LoanOfficer.find_one({"email": user_email})
        elif role in {"admin", "super_admin"}:
            user = Admin.find_one({"email": user_email})
        else:
            user = Customer.find_one({"email": user_email})

        if not user:
            return False

        LockoutService.reset_lockout(user)
        logger.info(f"Admin unlocked {role} account for {user_email}")
        return True
