from accounts.services.auth_service import AuthService
from accounts.utils.email_utils import EmailUtils
from accounts.services.otp_service import OTPService


class PasswordService:

    @staticmethod
    def initiate_password_reset(email):
        customer = AuthService.get_customer_by_email(email)
        if not customer:
            return (False, 'No account found with this email')

        otp = OTPService.set_otp(customer, 'password_reset_otp', 'password_reset_otp_expires')
        customer.password_reset_attempt_count = 0
        customer.password_reset_last_attempt = None
        customer.save()

        EmailUtils.send_password_reset_email(
            email=customer.email,
            first_name=customer.first_name,
            otp=otp
        )
        return (True, 'OTP has been sent to your email')

    @staticmethod
    def verify_reset_otp(email, otp):
        customer = AuthService.get_customer_by_email(email)
        if not customer:
            return (False, 'No account found with this email')

        valid, message = OTPService.validate_otp(
            customer, 
            otp, 
            'password_reset_otp', 
            'password_reset_otp_expires'
        )
        
        if not valid:
            return (False, message)
        
        return (True, 'OTP verified successfully')
    
    @staticmethod
    def reset_password(email, otp, new_password):
        customer = AuthService.get_customer_by_email(email)
        if not customer:
            return (False, 'No account found with this email')
        
        valid, message = OTPService.validate_otp(
            customer, 
            otp, 
            'password_reset_otp', 
            'password_reset_otp_expires'
        )
        
        if not valid:
            return (False, message)
        
        if customer.check_password(new_password):
            return (False, 'New password must be different from the old password')
        
        customer.set_password(new_password)
        OTPService.clear_otp(customer, 'password_reset_otp', 'password_reset_otp_expires')

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
