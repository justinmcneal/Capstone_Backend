from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


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
