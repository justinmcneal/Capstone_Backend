import re
from datetime import datetime, timezone

from django.conf import settings
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from accounts.models import Customer
from accounts.services.otp_service import OTPService
from accounts.utils.email_utils import EmailUtils
from accounts.utils.exception_types import NON_FATAL_EXCEPTIONS
from accounts.utils.identity_policy import assert_email_available_globally
from accounts.utils.token_utils import TokenUtils


class RegistrationError(Exception):
    pass


class AuthService:

    @staticmethod
    def get_customer_by_email(email, normalize=True):
        if normalize:
            email = EmailUtils.normalize_email(email)

        customer = Customer.find_one({"email": email})
        if customer:
            return customer

        return Customer.find_one(
            {"email": re.compile(f"^{re.escape(email)}$", re.IGNORECASE)}
        )

    @staticmethod
    def get_customer_by_id(customer_id):
        from bson import ObjectId

        try:
            return Customer.find_one({"_id": ObjectId(customer_id)})
        except NON_FATAL_EXCEPTIONS:
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
    def verify_customer_otp(customer, provided_otp):
        consumed = OTPService.consume_otp(
            customer,
            provided_otp,
            "verification_token",
            "verification_token_expires",
            success_updates={"verified": True},
        )
        return customer if consumed else None

    @staticmethod
    def resend_customer_otp(customer):
        otp = OTPService.set_otp(
            customer, "verification_token", "verification_token_expires"
        )
        now = datetime.now(timezone.utc)
        encrypted_otp = customer.to_dict()["verification_token"]
        document = settings.MONGODB[customer.collection_name].find_one_and_update(
            {
                "_id": customer._id,
                "verified": False,
                "$or": [
                    {"verification_resend_count": {"$exists": False}},
                    {"verification_resend_count": {"$lt": 2}},
                ],
            },
            {
                "$set": {
                    "verification_token": encrypted_otp,
                    "verification_token_expires": customer.verification_token_expires,
                    "updated_at": now,
                },
                "$inc": {"verification_resend_count": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        customer.verification_resend_count = int(
            document.get("verification_resend_count", 0)
        )

        EmailUtils.send_verification_email(
            email=customer.email, first_name=customer.first_name, token=otp
        )
        return customer

    @staticmethod
    def register_customer(validated_data):
        try:
            normalized_email = assert_email_available_globally(validated_data["email"])

            customer = Customer(
                first_name=validated_data["first_name"],
                middle_name=validated_data.get("middle_name", ""),
                last_name=validated_data["last_name"],
                email=normalized_email,
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
        except NON_FATAL_EXCEPTIONS as e:
            raise RegistrationError(f"Registration failed: {e!s}") from e

    @staticmethod
    def create_customer_tokens(customer, token_type="signup", **kwargs):
        return TokenUtils.generate_jwt_tokens(
            customer, token_type=token_type, **kwargs
        )

    @staticmethod
    def create_temp_token(
        customer, token_type="no_remember_me", token_transport="body"
    ):
        """
        Create a temporary token for 2FA verification.
        This token is short-lived (5 minutes) and only valid for 2FA flow.
        """
        return TokenUtils.generate_2fa_temp_token(
            user_id=customer.id,
            email=customer.email,
            role="customer",
            token_type=token_type,
            security_version=getattr(customer, "security_version", 1),
            token_transport=token_transport,
        )

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

        last_login_attempt = EmailUtils.to_aware_utc(customer.last_login_attempt)
        last_attempt = datetime.now(timezone.utc) - last_login_attempt
        rate_limit_seconds = 0

        if last_attempt.total_seconds() < rate_limit_seconds:
            seconds_remaining = rate_limit_seconds - int(last_attempt.total_seconds())
            return (False, seconds_remaining)

        return (True, 0)

    @staticmethod
    def update_login_attempt(customer):
        now = datetime.now(timezone.utc)
        settings.MONGODB[customer.collection_name].update_one(
            {"_id": customer._id},
            {"$set": {"last_login_attempt": now, "updated_at": now}},
        )
        customer.last_login_attempt = now

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
