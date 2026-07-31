import logging
from datetime import datetime, timedelta, timezone

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

        # Lock has expired, reset the lockout
        LockoutService.reset_lockout(customer)
        return (False, 0)

    @staticmethod
    def record_failed_attempt(customer) -> tuple:
        """
        Record a failed login attempt and lock account if threshold reached.

        Returns:
            tuple: (is_now_locked: bool, attempts_remaining: int)
        """
        customer.failed_login_attempts += 1
        attempts_remaining = (
            LockoutService.MAX_ATTEMPTS - customer.failed_login_attempts
        )

        if customer.failed_login_attempts >= LockoutService.MAX_ATTEMPTS:
            customer.locked_until = (
                datetime.now(timezone.utc) + LockoutService.LOCKOUT_DURATION
            )
            customer.save()
            logger.warning(
                f"Account locked for {customer.email} after {LockoutService.MAX_ATTEMPTS} failed attempts"
            )
            return (True, 0)

        customer.save()
        logger.info(
            f"Failed login attempt {customer.failed_login_attempts}/{LockoutService.MAX_ATTEMPTS} for {customer.email}"
        )
        return (False, attempts_remaining)

    @staticmethod
    def reset_lockout(customer):
        """
        Reset failed attempts and unlock account.
        Called on successful login or by admin.
        """
        customer.failed_login_attempts = 0
        customer.locked_until = None
        customer.save()
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
