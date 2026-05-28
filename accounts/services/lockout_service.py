from datetime import datetime, timedelta
from accounts.models import Customer
import logging

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

        now = datetime.utcnow()
        if customer.locked_until > now:
            seconds_remaining = int((customer.locked_until - now).total_seconds())
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
            customer.locked_until = datetime.utcnow() + LockoutService.LOCKOUT_DURATION
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
    def admin_unlock(customer_email: str) -> bool:
        """
        Admin function to unlock a customer account.

        Returns:
            bool: True if account was unlocked, False if not found
        """
        customer = Customer.find_one({"email": customer_email})
        if not customer:
            return False

        LockoutService.reset_lockout(customer)
        logger.info(f"Admin unlocked account for {customer_email}")
        return True
