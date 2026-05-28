from accounts.models import Customer
from accounts.utils.token_utils import TokenUtils
from accounts.utils.email_utils import EmailUtils
from accounts.services.otp_service import OTPService
from rest_framework_simplejwt.tokens import RefreshToken
from datetime import datetime, timedelta
from pymongo.errors import DuplicateKeyError


class AuthService:

    @staticmethod
    def get_customer_by_email(email, normalize=True):
        if normalize:
            email = EmailUtils.normalize_email(email)
        return Customer.find_one({"email": email})

    @staticmethod
    def get_customer_by_id(customer_id):
        from bson import ObjectId
        try:
            return Customer.find_one({"_id": ObjectId(customer_id)})
        except Exception:
            return None

    @staticmethod
    def serialize_customer_data(customer, include_last_name=False):
        data = {
            "id": str(customer.id),
            "first_name": customer.first_name,
            "email": customer.email,
            "verified": customer.verified,
            "role": customer.role,
            "two_factor_enabled": customer.two_factor_enabled,
            "language": getattr(customer, "language", "en"),
        }
        if include_last_name:
            data["last_name"] = customer.last_name
        return data

    @staticmethod
    def verify_customer_otp(customer):
        customer.verified = True
        OTPService.clear_otp(
            customer, "verification_token", "verification_token_expires"
        )
        return customer

    @staticmethod
    def resend_customer_otp(customer):
        otp = OTPService.set_otp(
            customer, "verification_token", "verification_token_expires"
        )
        customer.verification_resend_count += 1
        customer.save()

        EmailUtils.send_verification_email(
            email=customer.email, first_name=customer.first_name, token=otp
        )
        return customer

    @staticmethod
    def register_customer(validated_data):
        try:
            # Use centralized customer lookup
            if AuthService.get_customer_by_email(validated_data["email"]):
                raise ValueError("An account with this email already exists")

            customer = Customer(
                first_name=validated_data["first_name"],
                middle_name=validated_data.get("middle_name", ""),
                last_name=validated_data["last_name"],
                email=validated_data["email"],
                phone=validated_data.get("phone", ""),
                language=validated_data.get("language", "en"),
                verified=False,
            )

            # Use centralized OTP service
            otp = OTPService.set_otp(
                customer, "verification_token", "verification_token_expires"
            )

            customer.set_password(validated_data["password"])
            customer.save()

            EmailUtils.send_verification_email(
                email=customer.email, first_name=customer.first_name, token=otp
            )
            return customer

        except DuplicateKeyError:
            raise ValueError("An account with this email already exists")
        except ValueError:
            raise  # Propagate ValueError so SignUpView can return a proper 400 response
        except Exception as e:
            raise Exception(f"Registration failed: {str(e)}")

    @staticmethod
    def create_customer_tokens(customer, token_type="signup"):
        return TokenUtils.generate_jwt_tokens(customer, token_type=token_type)

    @staticmethod
    def create_temp_token(customer):
        """
        Create a temporary token for 2FA verification.
        This token is short-lived (5 minutes) and only valid for 2FA flow.
        """
        refresh = RefreshToken()
        refresh["customer_id"] = str(customer.id)
        refresh["email"] = customer.email
        refresh["temp_2fa"] = True  # Mark as temporary 2FA token
        refresh.set_exp(lifetime=timedelta(minutes=5))
        return str(refresh)

    @staticmethod
    def update_language(customer, language_code):
        """Update a customer's language preference. Accepts 'en' or 'tl'."""
        allowed = {"en", "tl"}
        if language_code not in allowed:
            raise ValueError(f"language must be one of: {', '.join(sorted(allowed))}")
        customer.language = language_code
        customer.save()
        return customer

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
        return OTPService.check_otp_rate_limit(
            customer, "otp_attempt_count", "otp_last_attempt"
        )

    @staticmethod
    def increment_otp_attempt(customer):
        OTPService.increment_otp_attempt(
            customer, "otp_attempt_count", "otp_last_attempt"
        )

    @staticmethod
    def reset_otp_attempts(customer):
        OTPService.reset_otp_attempts(customer, "otp_attempt_count", "otp_last_attempt")
