import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional


class EmailUtils:

    @staticmethod
    def normalize_email(email: Optional[str]) -> str:
        """Normalize email to lowercase and strip whitespace"""
        if not email:
            return ""
        return email.lower().strip()

    @staticmethod
    def generate_otp(length: int = 6) -> str:
        return "".join(secrets.choice(string.digits) for _ in range(length))

    @staticmethod
    def get_otp_expiry() -> datetime:
        return datetime.now(timezone.utc) + timedelta(hours=12)

    @staticmethod
    def to_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def is_otp_expired(expiry_time: Optional[datetime]) -> bool:
        expiry_time = EmailUtils.to_aware_utc(expiry_time)
        if not expiry_time:
            return True
        return datetime.now(timezone.utc) > expiry_time

    @staticmethod
    def send_verification_email(email: str, first_name: Optional[str], token: str) -> bool:
        from accounts.services.email_service import email_service

        context = {"first_name": first_name, "otp": token}

        return email_service.send_template_email(
            to_emails=[email],
            subject="Verify Your Email Address",
            template_name="verification",
            context=context,
        )

    @staticmethod
    def send_password_reset_email(email: str, first_name: Optional[str], otp: str) -> bool:
        from accounts.services.email_service import email_service

        context = {"first_name": first_name, "otp": otp}

        return email_service.send_template_email(
            to_emails=[email],
            subject="Password Reset OTP",
            template_name="password_reset",
            context=context,
        )

    @staticmethod
    def send_officer_temporary_password_email(email: str, first_name: Optional[str], temporary_password: str) -> bool:
        from accounts.services.email_service import email_service

        context = {
            "first_name": first_name or "Officer",
            "temporary_password": temporary_password,
        }

        return email_service.send_template_email(
            to_emails=[email],
            subject="Your Loan Officer Temporary Password",
            template_name="loan_officer_temp_password",
            context=context,
        )
