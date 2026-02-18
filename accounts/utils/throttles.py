from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class SignUpRateThrottle(AnonRateThrottle):
    """IP-based throttling for signup endpoint: 5 requests per hour"""
    rate = '5/hour'


class LoginRateThrottle(AnonRateThrottle):
    """IP-based throttling for login endpoint: 10 requests per hour"""
    rate = '10/hour'


class OTPVerificationRateThrottle(AnonRateThrottle):
    """IP-based throttling for OTP verification: 5 requests per hour (production)"""
    rate = '5/hour'


class OTPResendRateThrottle(AnonRateThrottle):
    """IP-based throttling for OTP resend: 3 requests per hour (production)"""
    rate = '3/hour'


class TwoFactorRateThrottle(AnonRateThrottle):
    """IP-based throttling for 2FA verification: 5 requests per hour"""
    rate = '5/hour'


class PasswordResetRateThrottle(AnonRateThrottle):
    """IP-based throttling for password reset: 3 requests per hour"""
    rate = '3/hour'


class ForgotPasswordRateThrottle(AnonRateThrottle):
    """IP-based throttling for forgot password: 5 requests per hour"""
    rate = '5/hour'


class ChatRateThrottle(UserRateThrottle):
    """User-based throttling for AI chat endpoint."""
    rate = '60/hour'


class PreQualifyRateThrottle(UserRateThrottle):
    """User-based throttling for pre-qualification endpoint."""
    rate = '20/hour'
