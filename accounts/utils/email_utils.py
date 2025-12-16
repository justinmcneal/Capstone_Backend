import secrets
import string
from datetime import datetime, timedelta
from accounts.services.email_service import email_service


class EmailUtils:

    @staticmethod
    def normalize_email(email):
        """Normalize email to lowercase and strip whitespace"""
        if not email:
            return None
        return email.lower().strip()

    @staticmethod
    def generate_otp(length=6):
        return ''.join(secrets.choice(string.digits) for _ in range(length))
    
    @staticmethod
    def get_otp_expiry():
        return datetime.utcnow() + timedelta(hours=12)
    
    @staticmethod
    def is_otp_expired(expiry_time):
        return datetime.utcnow() > expiry_time

    @staticmethod
    def send_verification_email(email, first_name, token):
        context = {
            'first_name': first_name,
            'otp': token
        }
        
        return email_service.send_template_email(
            to_emails=[email],
            subject='Verify Your Email Address',
            template_name='verification',
            context=context
        )
    
    @staticmethod
    def send_password_reset_email(email, first_name, otp):
        context = {
            'first_name': first_name,
            'otp': otp
        }
        
        return email_service.send_template_email(
            to_emails=[email],
            subject='Password Reset OTP',
            template_name='password_reset',
            context=context
        )

