import secrets
import string
from datetime import datetime, timedelta, timezone


class EmailUtils:

    @staticmethod
    def normalize_email(email):
        """Normalize email to lowercase and strip whitespace"""
        if not email:
            return ""
        return email.lower().strip()

    @staticmethod
    def generate_otp(length=6):
        return "".join(secrets.choice(string.digits) for _ in range(length))

    @staticmethod
    def get_otp_expiry():
        return datetime.now(timezone.utc) + timedelta(hours=12)

    @staticmethod
    def is_otp_expired(expiry_time):
        return datetime.now(timezone.utc) > expiry_time

    @staticmethod
    def send_verification_email(email, first_name, token):
        from accounts.services.email_service import email_service

        context = {"first_name": first_name, "otp": token}

        return email_service.send_template_email(
            to_emails=[email],
            subject="Verify Your Email Address",
            template_name="verification",
            context=context,
        )

    @staticmethod
    def send_password_reset_email(email, first_name, otp):
        from accounts.services.email_service import email_service

        context = {"first_name": first_name, "otp": otp}

        return email_service.send_template_email(
            to_emails=[email],
            subject="Password Reset OTP",
            template_name="password_reset",
            context=context,
        )

    @staticmethod
    def send_officer_temporary_password_email(email, first_name, temporary_password):
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
