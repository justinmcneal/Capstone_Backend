import hashlib

from django.conf import settings
from rest_framework.throttling import (
    AnonRateThrottle,
    SimpleRateThrottle,
    UserRateThrottle,
)


class RequestValueRateThrottle(SimpleRateThrottle):
    """Throttle a normalized, hashed request value without storing PII in cache keys."""

    request_fields = ()

    def get_cache_key(self, request, view):
        value = self.get_request_value(request)
        if not value:
            return None
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}

    def get_request_value(self, request):
        for field in self.request_fields:
            raw_value = request.data.get(field)
            if raw_value is not None:
                value = str(raw_value).strip().lower()
                if value:
                    return value
        return ""


class LoginIdentifierRateThrottle(RequestValueRateThrottle):
    scope = "auth_login_identifier"
    rate = "100/hour"
    request_fields = ("email", "username")


class SignUpIdentifierRateThrottle(RequestValueRateThrottle):
    scope = "auth_signup_identifier"
    rate = "100/hour"
    request_fields = ("email",)


class OTPIdentifierRateThrottle(RequestValueRateThrottle):
    scope = "auth_otp_identifier"
    rate = "100/hour"
    request_fields = ("email",)


class TwoFactorTokenRateThrottle(RequestValueRateThrottle):
    scope = "auth_2fa_token"
    rate = "100/hour"
    request_fields = ("temp_token",)

    def get_request_value(self, request):
        value = super().get_request_value(request)
        if value:
            return value
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            return str(
                getattr(user, "id", None) or getattr(user, "customer_id", None) or ""
            )
        return ""


class RefreshTokenRateThrottle(RequestValueRateThrottle):
    scope = "auth_refresh_token"
    rate = "100/hour"
    request_fields = ("refresh", "refresh_token")

    def get_request_value(self, request):
        value = super().get_request_value(request)
        if value:
            return value
        cookie_name = getattr(settings, "AUTH_REFRESH_COOKIE_NAME", "refresh_token")
        return str(request.COOKIES.get(cookie_name) or "")


class SignUpRateThrottle(AnonRateThrottle):
    """IP-based throttling for signup endpoint: 5 requests per hour"""

    rate = "100/hour"


class LoginRateThrottle(AnonRateThrottle):
    """IP-based throttling for login endpoint: 10 requests per hour"""

    rate = "100/hour"


class LoanOfficerLoginRateThrottle(AnonRateThrottle):
    """IP-based throttling for loan officer login endpoint: 10 requests per hour"""

    rate = "100/hour"


class AdminLoginRateThrottle(AnonRateThrottle):
    """IP-based throttling for admin login endpoint: 10 requests per hour"""

    rate = "100/hour"


class OTPVerificationRateThrottle(AnonRateThrottle):
    """IP-based throttling for OTP verification: 5 requests per hour (production)"""

    rate = "100/hour"


class OTPResendRateThrottle(AnonRateThrottle):
    """IP-based throttling for OTP resend: 3 requests per hour (production)"""

    rate = "100/hour"


class TwoFactorRateThrottle(AnonRateThrottle):
    """IP-based throttling for 2FA verification: 10 requests per hour"""

    rate = "100/hour"


class PasswordResetRateThrottle(AnonRateThrottle):
    """IP-based throttling for password reset: 3 requests per hour"""

    rate = "100/hour"


class ForgotPasswordRateThrottle(AnonRateThrottle):
    """IP-based throttling for forgot password: 5 requests per hour"""

    rate = "100/hour"


class SafeUserRateThrottle(UserRateThrottle):
    """UserRateThrottle that safely checks for pk, customer_id, or id on custom user objects."""

    def get_cache_key(self, request, view):
        if request.user and getattr(request.user, "is_authenticated", False):
            ident = (
                getattr(request.user, "pk", None)
                or getattr(request.user, "customer_id", None)
                or getattr(request.user, "id", None)
            )
            if ident:
                return self.cache_format % {
                    "scope": self.scope,
                    "ident": ident,
                }
        return self.get_ident(request)


class ChatRateThrottle(SafeUserRateThrottle):
    """User-based throttling for AI chat endpoint."""

    rate = "1000/hour"


class PreQualifyRateThrottle(SafeUserRateThrottle):
    """User-based throttling for pre-qualification endpoint."""

    rate = "500/hour"


class ProfileRateThrottle(SafeUserRateThrottle):
    """User-based throttling for profile endpoints."""

    rate = "500/hour"


class DocumentUploadRateThrottle(SafeUserRateThrottle):
    """User-based throttling for document upload endpoints."""

    rate = "100/hour"


class AnalyticsReadRateThrottle(SafeUserRateThrottle):
    """Per-user protection for comparatively expensive Analytics reads."""

    scope = "analytics_read"
    rate = getattr(settings, "ANALYTICS_READ_RATE", "300/hour")
