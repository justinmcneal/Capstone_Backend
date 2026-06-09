from datetime import datetime, timedelta, timezone
from accounts.utils.email_utils import EmailUtils


class OTPService:
    """Centralized service for all OTP-related operations"""

    # OTP Configuration - Security Best Practices
    OTP_LENGTH = 6
    OTP_EXPIRY_MINUTES = 10  # Email verification OTP: 10 minutes
    PASSWORD_RESET_EXPIRY_MINUTES = 15  # Password reset OTP: 15 minutes
    MAX_OTP_ATTEMPTS = 5  # Max wrong attempts before cooldown
    OTP_COOLDOWN_SECONDS = 600  # 10 minutes cooldown after max attempts

    @staticmethod
    def generate_otp(length=None):
        return EmailUtils.generate_otp(length or OTPService.OTP_LENGTH)

    @staticmethod
    def get_otp_expiry(minutes=None):
        """Get OTP expiry time. Default is OTP_EXPIRY_MINUTES (10 min)."""
        expiry_minutes = minutes or OTPService.OTP_EXPIRY_MINUTES
        return datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)

    @staticmethod
    def is_otp_expired(expiry_time):
        return EmailUtils.is_otp_expired(expiry_time)

    @staticmethod
    def check_otp_rate_limit(
        customer,
        attempt_field="otp_attempt_count",
        last_attempt_field="otp_last_attempt",
    ):
        attempt_count = getattr(customer, attempt_field, 0)
        last_attempt = getattr(customer, last_attempt_field, None)

        if attempt_count >= OTPService.MAX_OTP_ATTEMPTS:
            if last_attempt:
                last_attempt = EmailUtils.to_aware_utc(last_attempt)
                time_since_last = datetime.now(timezone.utc) - last_attempt
                if time_since_last.total_seconds() < OTPService.OTP_COOLDOWN_SECONDS:
                    seconds_remaining = OTPService.OTP_COOLDOWN_SECONDS - int(
                        time_since_last.total_seconds()
                    )
                    return (False, seconds_remaining)
                else:
                    # Reset counter after cooldown
                    setattr(customer, attempt_field, 0)
                    customer.save()
                    return (True, 0)
            return (False, 0)
        return (True, 0)

    @staticmethod
    def increment_otp_attempt(
        customer,
        attempt_field="otp_attempt_count",
        last_attempt_field="otp_last_attempt",
    ):
        current_count = getattr(customer, attempt_field, 0)
        setattr(customer, attempt_field, current_count + 1)
        setattr(customer, last_attempt_field, datetime.now(timezone.utc))
        customer.save()

    @staticmethod
    def reset_otp_attempts(
        customer,
        attempt_field="otp_attempt_count",
        last_attempt_field="otp_last_attempt",
    ):
        setattr(customer, attempt_field, 0)
        setattr(customer, last_attempt_field, None)
        customer.save()

    @staticmethod
    def validate_otp(
        customer,
        provided_otp,
        otp_field="verification_token",
        expiry_field="verification_token_expires",
    ):
        stored_otp = getattr(customer, otp_field, None)
        expiry_time = getattr(customer, expiry_field, None)

        if not stored_otp:
            return (False, "No OTP found for this account")

        if OTPService.is_otp_expired(expiry_time):
            return (False, "OTP has expired")

        if stored_otp != provided_otp:
            return (False, "Invalid OTP")

        return (True, "OTP is valid")

    @staticmethod
    def set_otp(
        customer,
        otp_field="verification_token",
        expiry_field="verification_token_expires",
        expiry_minutes=None,
    ):
        """Set OTP for customer with optional custom expiry time."""
        otp = OTPService.generate_otp()
        setattr(customer, otp_field, otp)
        setattr(customer, expiry_field, OTPService.get_otp_expiry(expiry_minutes))
        return otp

    @staticmethod
    def clear_otp(
        customer,
        otp_field="verification_token",
        expiry_field="verification_token_expires",
    ):
        setattr(customer, otp_field, None)
        setattr(customer, expiry_field, None)
        customer.save()
