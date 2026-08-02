from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.conf import settings
from pymongo import ReturnDocument

from accounts.models import Customer
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
    def generate_otp(length: int | None = None) -> str:
        return EmailUtils.generate_otp(length or OTPService.OTP_LENGTH)

    @staticmethod
    def get_otp_expiry(minutes: int | None = None) -> datetime:
        """Get OTP expiry time. Default is OTP_EXPIRY_MINUTES (10 min)."""
        expiry_minutes = minutes or OTPService.OTP_EXPIRY_MINUTES
        return datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)

    @staticmethod
    def is_otp_expired(expiry_time: datetime | None) -> bool:
        return EmailUtils.is_otp_expired(expiry_time)

    @staticmethod
    def check_otp_rate_limit(
        customer: Customer,
        attempt_field: str = "otp_attempt_count",
        last_attempt_field: str = "otp_last_attempt",
    ) -> tuple[bool, int]:
        attempt_count = getattr(customer, attempt_field, 0)
        last_attempt = getattr(customer, last_attempt_field, None)

        if attempt_count >= OTPService.MAX_OTP_ATTEMPTS:
            if last_attempt:
                last_attempt = EmailUtils.to_aware_utc(last_attempt)
                assert last_attempt is not None  # to_aware_utc preserves non-None input
                time_since_last = datetime.now(timezone.utc) - last_attempt
                if time_since_last.total_seconds() < OTPService.OTP_COOLDOWN_SECONDS:
                    seconds_remaining = OTPService.OTP_COOLDOWN_SECONDS - int(
                        time_since_last.total_seconds()
                    )
                    return (False, seconds_remaining)
                else:
                    # Reset counter after cooldown
                    OTPService.reset_otp_attempts(
                        customer, attempt_field, last_attempt_field
                    )
                    return (True, 0)
            return (False, 0)
        return (True, 0)

    @staticmethod
    def increment_otp_attempt(
        customer: Customer,
        attempt_field: str = "otp_attempt_count",
        last_attempt_field: str = "otp_last_attempt",
    ) -> None:
        now = datetime.now(timezone.utc)
        document = settings.MONGODB[customer.collection_name].find_one_and_update(
            {"_id": customer._id},
            {
                "$inc": {attempt_field: 1},
                "$set": {last_attempt_field: now, "updated_at": now},
            },
            return_document=ReturnDocument.AFTER,
        )
        setattr(customer, attempt_field, int((document or {}).get(attempt_field, 1)))
        setattr(customer, last_attempt_field, now)

    @staticmethod
    def reset_otp_attempts(
        customer: Customer,
        attempt_field: str = "otp_attempt_count",
        last_attempt_field: str = "otp_last_attempt",
    ) -> None:
        now = datetime.now(timezone.utc)
        settings.MONGODB[customer.collection_name].update_one(
            {"_id": customer._id},
            {
                "$set": {
                    attempt_field: 0,
                    last_attempt_field: None,
                    "updated_at": now,
                }
            },
        )
        setattr(customer, attempt_field, 0)
        setattr(customer, last_attempt_field, None)

    @staticmethod
    def validate_otp(
        customer: Customer,
        provided_otp: str,
        otp_field: str = "verification_token",
        expiry_field: str = "verification_token_expires",
    ) -> tuple[bool, str]:
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
        customer: Customer,
        otp_field: str = "verification_token",
        expiry_field: str = "verification_token_expires",
        expiry_minutes: int | None = None,
    ) -> str:
        """Set OTP for customer with optional custom expiry time."""
        otp = OTPService.generate_otp()
        setattr(customer, otp_field, otp)
        setattr(customer, expiry_field, OTPService.get_otp_expiry(expiry_minutes))
        return otp

    @staticmethod
    def clear_otp(
        customer: Customer,
        otp_field: str = "verification_token",
        expiry_field: str = "verification_token_expires",
    ) -> None:
        now = datetime.now(timezone.utc)
        settings.MONGODB[customer.collection_name].update_one(
            {"_id": customer._id},
            {
                "$set": {
                    otp_field: None,
                    expiry_field: None,
                    "updated_at": now,
                }
            },
        )
        setattr(customer, otp_field, None)
        setattr(customer, expiry_field, None)

    @staticmethod
    def consume_otp(
        customer: Customer,
        provided_otp: str,
        otp_field: str,
        expiry_field: str,
        *,
        success_updates: dict | None = None,
    ) -> bool:
        """Validate and consume a one-time code with a single winning update."""
        valid, _message = OTPService.validate_otp(
            customer, provided_otp, otp_field, expiry_field
        )
        if not valid:
            return False

        expected_expiry = getattr(customer, expiry_field, None)
        now = datetime.now(timezone.utc)
        updates = {
            otp_field: None,
            expiry_field: None,
            "updated_at": now,
            **(success_updates or {}),
        }
        result = settings.MONGODB[customer.collection_name].update_one(
            {
                "_id": customer._id,
                otp_field: {"$ne": None},
                expiry_field: expected_expiry,
            },
            {"$set": updates},
        )
        if result.modified_count != 1:
            return False

        setattr(customer, otp_field, None)
        setattr(customer, expiry_field, None)
        for field, value in (success_updates or {}).items():
            setattr(customer, field, value)
        return True
