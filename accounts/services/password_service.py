from accounts.services.auth_service import AuthService
from accounts.utils.email_utils import EmailUtils
from accounts.services.otp_service import OTPService
from accounts.models import LoanOfficer, Admin
import logging

logger = logging.getLogger('authentication')


class PasswordService:
    GENERIC_RESET_INIT_MESSAGE = (
        'If an account with this email exists, a password reset OTP has been sent.'
    )
    GENERIC_RESET_VERIFY_ERROR = 'Invalid email or OTP'
    RESET_ATTEMPT_FIELD = 'password_reset_attempt_count'
    RESET_LAST_ATTEMPT_FIELD = 'password_reset_last_attempt'

    @staticmethod
    def _find_user_by_email(email):
        """
        Search for a user across all models: Customer, LoanOfficer, and Admin.
        Returns (user, user_type) tuple, or (None, None) if not found.
        """
        email = email.lower().strip()
        
        # Check Customer first
        customer = AuthService.get_customer_by_email(email)
        if customer:
            return customer, 'customer'
        
        # Check LoanOfficer
        officer = LoanOfficer.find_one({'email': email})
        if officer:
            return officer, 'loan_officer'
        
        # Check Admin (by email)
        admin = Admin.find_one({'email': email})
        if admin:
            return admin, 'admin'
        
        return None, None

    @staticmethod
    def initiate_password_reset(email):
        user, user_type = PasswordService._find_user_by_email(email)
        if not user:
            logger.info(f"Password reset requested for unknown email: {email}")
            return (True, PasswordService.GENERIC_RESET_INIT_MESSAGE)

        # Check if account is active (for LoanOfficer and Admin)
        if user_type in ('loan_officer', 'admin') and hasattr(user, 'active') and not user.active:
            logger.info(f"Password reset requested for inactive account: {email} ({user_type})")
            return (True, PasswordService.GENERIC_RESET_INIT_MESSAGE)

        # Use password reset expiry (15 minutes) instead of default (10 minutes)
        otp = OTPService.set_otp(
            user, 
            'password_reset_otp', 
            'password_reset_otp_expires',
            expiry_minutes=OTPService.PASSWORD_RESET_EXPIRY_MINUTES
        )
        user.password_reset_attempt_count = 0
        user.password_reset_last_attempt = None
        user.save()

        # Get name for email
        first_name = getattr(user, 'first_name', None) or getattr(user, 'username', 'User')

        EmailUtils.send_password_reset_email(
            email=user.email,
            first_name=first_name,
            otp=otp
        )
        
        logger.info(f"Password reset OTP sent for {email} ({user_type})")
        return (True, PasswordService.GENERIC_RESET_INIT_MESSAGE)

    @staticmethod
    def _check_reset_otp_rate_limit(user):
        return OTPService.check_otp_rate_limit(
            user,
            PasswordService.RESET_ATTEMPT_FIELD,
            PasswordService.RESET_LAST_ATTEMPT_FIELD
        )

    @staticmethod
    def _increment_reset_otp_attempt(user):
        OTPService.increment_otp_attempt(
            user,
            PasswordService.RESET_ATTEMPT_FIELD,
            PasswordService.RESET_LAST_ATTEMPT_FIELD
        )

    @staticmethod
    def _reset_reset_otp_attempts(user):
        OTPService.reset_otp_attempts(
            user,
            PasswordService.RESET_ATTEMPT_FIELD,
            PasswordService.RESET_LAST_ATTEMPT_FIELD
        )

    @staticmethod
    def verify_reset_otp(email, otp):
        user, user_type = PasswordService._find_user_by_email(email)
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
                f'Too many OTP attempts. Please try again in {seconds_remaining} seconds.'
            )

        valid, message = OTPService.validate_otp(
            user, 
            otp, 
            'password_reset_otp', 
            'password_reset_otp_expires'
        )
        
        if not valid:
            PasswordService._increment_reset_otp_attempt(user)
            return (False, PasswordService.GENERIC_RESET_VERIFY_ERROR)

        PasswordService._reset_reset_otp_attempts(user)
        
        return (True, 'OTP verified successfully')
    
    @staticmethod
    def reset_password(email, otp, new_password):
        user, user_type = PasswordService._find_user_by_email(email)
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
                f'Too many OTP attempts. Please try again in {seconds_remaining} seconds.'
            )
        
        valid, message = OTPService.validate_otp(
            user, 
            otp, 
            'password_reset_otp', 
            'password_reset_otp_expires'
        )
        
        if not valid:
            PasswordService._increment_reset_otp_attempt(user)
            return (False, PasswordService.GENERIC_RESET_VERIFY_ERROR)

        PasswordService._reset_reset_otp_attempts(user)
        
        if user.check_password(new_password):
            return (False, 'New password must be different from the old password')
        
        user.set_password(new_password)
        OTPService.clear_otp(user, 'password_reset_otp', 'password_reset_otp_expires')
        
        # Clear must_change_password flag for loan officers
        if user_type == 'loan_officer' and hasattr(user, 'must_change_password'):
            user.must_change_password = False
            user.save()

        logger.info(f"Password reset successful for {email} ({user_type})")
        return (True, 'Password has been reset successfully')
    
    @staticmethod
    def change_password(customer, old_password, new_password):
        if not customer.check_password(old_password):
            return (False, 'Old password is incorrect')
        
        if customer.check_password(new_password):
            return (False, 'New password must be different from the old password')
        
        customer.set_password(new_password)
        customer.save()
        return (True, 'Password has been changed successfully')
