from accounts.models import Customer
from accounts.utils.token_utils import TokenUtils
from mongoengine.errors import NotUniqueError
from accounts.utils.email_utils import EmailUtils
from datetime import datetime, timedelta

class AuthService:
    
    @staticmethod
    def get_customer_by_email(email, normalize=True):
        if normalize:
            email = EmailUtils.normalize_email(email)
        return Customer.objects(email=email).first()
    
    @staticmethod
    def get_customer_by_id(customer_id):
        return Customer.objects(id=customer_id).first()
    
    @staticmethod
    def serialize_customer_data(customer, include_last_name=False):
        data = {
            'id': str(customer.id),
            'first_name': customer.first_name,
            'email': customer.email,
            'verified': customer.verified
        }
        if include_last_name:
            data['last_name'] = customer.last_name
        return data
    
    @staticmethod
    def verify_customer_otp(customer):
        customer.verified = True
        customer.verification_token = None
        customer.verification_token_expires = None
        customer.save()
        return customer
    
    @staticmethod
    def resend_customer_otp(customer):
        otp = EmailUtils.generate_otp()
        customer.verification_token = otp
        customer.verification_token_expires = EmailUtils.get_otp_expiry()
        customer.verification_resend_count += 1
        customer.save()
        
        EmailUtils.send_verification_email(
            email=customer.email,
            first_name=customer.first_name,
            token=otp
        )
        return customer
    
    @staticmethod
    def register_customer(validated_data):
        try:
            # Use centralized customer lookup
            if AuthService.get_customer_by_email(validated_data['email']):
                raise ValueError('An account with this email already exists')
            otp = EmailUtils.generate_otp()

            customer = Customer(
                first_name=validated_data['first_name'],
                middle_name=validated_data.get('middle_name', ''),
                last_name=validated_data['last_name'],
                email=validated_data['email'],
                verified=False,
                verification_token=otp,
                verification_token_expires=EmailUtils.get_otp_expiry()
            )
            
            customer.set_password(validated_data['password'])            
            customer.save()

            EmailUtils.send_verification_email(
                email=customer.email,
                first_name=customer.first_name,
                token=otp
            )
            return customer
            
        except NotUniqueError:
            raise ValueError('An account with this email already exists')
        except Exception as e:
            raise Exception(f'Registration failed: {str(e)}')
    
    @staticmethod
    def create_customer_tokens(customer, token_type='signup'):
        return TokenUtils.generate_jwt_tokens(customer, token_type=token_type)
    
    @staticmethod
    def authenticate_customer(email, password):
        customer = AuthService.get_customer_by_email(email)
        if customer and customer.check_password(password):
            return customer
        return None
    
    @staticmethod
    def check_login_rate_limit(customer):
        if not customer.last_login_attempt:
            return (True, 0)
        
        last_attempt = datetime.utcnow() - customer.last_login_attempt
        rate_limit_seconds = 30

        if last_attempt.total_seconds() < rate_limit_seconds:
            seconds_remaining = rate_limit_seconds - int(last_attempt.total_seconds())
            return (False, seconds_remaining)
    
        return (True, 0)
    
    @staticmethod
    def update_login_attempt(customer):
        customer.last_login_attempt = datetime.utcnow()
        customer.save()
    
    @staticmethod
    def check_otp_rate_limit(customer):
        """Check if customer has exceeded OTP verification attempts (max 5)"""
        if customer.otp_attempt_count >= 5:
            if customer.otp_last_attempt:
                time_since_last = datetime.utcnow() - customer.otp_last_attempt
                # Reset after 10 minutes
                if time_since_last.total_seconds() < 600:
                    seconds_remaining = 600 - int(time_since_last.total_seconds())
                    return (False, seconds_remaining)
                else:
                    # Reset counter after cooldown
                    customer.otp_attempt_count = 0
                    customer.save()
                    return (True, 0)
            return (False, 0)
        return (True, 0)
    
    @staticmethod
    def increment_otp_attempt(customer):
        """Increment OTP verification attempt counter"""
        customer.otp_attempt_count += 1
        customer.otp_last_attempt = datetime.utcnow()
        customer.save()
    
    @staticmethod
    def reset_otp_attempts(customer):
        """Reset OTP attempts after successful verification"""
        customer.otp_attempt_count = 0
        customer.otp_last_attempt = None
        customer.save()