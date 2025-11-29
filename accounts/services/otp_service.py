from datetime import datetime, timedelta
from accounts.utils.email_utils import EmailUtils


class OTPService:
    """Centralized service for all OTP-related operations"""
    
    # OTP Configuration
    OTP_LENGTH = 6
    OTP_EXPIRY_HOURS = 12
    MAX_OTP_ATTEMPTS = 5
    OTP_COOLDOWN_SECONDS = 600  # 10 minutes
    
    @staticmethod
    def generate_otp(length=None):
        return EmailUtils.generate_otp(length or OTPService.OTP_LENGTH)
    
    @staticmethod
    def get_otp_expiry():
        return datetime.utcnow() + timedelta(hours=OTPService.OTP_EXPIRY_HOURS)
    
    @staticmethod
    def is_otp_expired(expiry_time):
        if not expiry_time:
            return True
        return datetime.utcnow() > expiry_time
    
    @staticmethod
    def check_otp_rate_limit(customer, attempt_field='otp_attempt_count', last_attempt_field='otp_last_attempt'):
        attempt_count = getattr(customer, attempt_field, 0)
        last_attempt = getattr(customer, last_attempt_field, None)
        
        if attempt_count >= OTPService.MAX_OTP_ATTEMPTS:
            if last_attempt:
                time_since_last = datetime.utcnow() - last_attempt
                if time_since_last.total_seconds() < OTPService.OTP_COOLDOWN_SECONDS:
                    seconds_remaining = OTPService.OTP_COOLDOWN_SECONDS - int(time_since_last.total_seconds())
                    return (False, seconds_remaining)
                else:
                    # Reset counter after cooldown
                    setattr(customer, attempt_field, 0)
                    customer.save()
                    return (True, 0)
            return (False, 0)
        return (True, 0)
    
    @staticmethod
    def increment_otp_attempt(customer, attempt_field='otp_attempt_count', last_attempt_field='otp_last_attempt'):
        current_count = getattr(customer, attempt_field, 0)
        setattr(customer, attempt_field, current_count + 1)
        setattr(customer, last_attempt_field, datetime.utcnow())
        customer.save()
    
    @staticmethod
    def reset_otp_attempts(customer, attempt_field='otp_attempt_count', last_attempt_field='otp_last_attempt'):
        setattr(customer, attempt_field, 0)
        setattr(customer, last_attempt_field, None)
        customer.save()
    
    @staticmethod
    def validate_otp(customer, provided_otp, otp_field='verification_token', expiry_field='verification_token_expires'):
        stored_otp = getattr(customer, otp_field, None)
        expiry_time = getattr(customer, expiry_field, None)
        
        if not stored_otp:
            return (False, 'No OTP found for this account')
        
        if OTPService.is_otp_expired(expiry_time):
            return (False, 'OTP has expired')
        
        if stored_otp != provided_otp:
            return (False, 'Invalid OTP')
        
        return (True, 'OTP is valid')
    
    @staticmethod
    def set_otp(customer, otp_field='verification_token', expiry_field='verification_token_expires'):
        otp = OTPService.generate_otp()
        setattr(customer, otp_field, otp)
        setattr(customer, expiry_field, OTPService.get_otp_expiry())
        return otp
    
    @staticmethod
    def clear_otp(customer, otp_field='verification_token', expiry_field='verification_token_expires'):
        setattr(customer, otp_field, None)
        setattr(customer, expiry_field, None)
        customer.save()
