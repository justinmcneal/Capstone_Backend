from rest_framework.throttling import AnonRateThrottle


class SignUpRateThrottle(AnonRateThrottle):
    """IP-based throttling for signup endpoint: 5 requests per hour"""
    rate = '5/hour'


class LoginRateThrottle(AnonRateThrottle):
    """IP-based throttling for login endpoint: 10 requests per hour"""
    rate = '10/hour'


class OTPVerificationRateThrottle(AnonRateThrottle):
    """IP-based throttling for OTP verification: 100 requests per hour for testing"""
    rate = '100/hour'  # Increased for testing


class OTPResendRateThrottle(AnonRateThrottle):
    """IP-based throttling for OTP resend: 100 requests per hour for testing"""
    rate = '100/hour'  # Increased for testing
