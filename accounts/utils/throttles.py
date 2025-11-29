from rest_framework.throttling import AnonRateThrottle


class SignUpRateThrottle(AnonRateThrottle):
    """IP-based throttling for signup endpoint: 5 requests per hour"""
    rate = '5/hour'


class LoginRateThrottle(AnonRateThrottle):
    """IP-based throttling for login endpoint: 10 requests per hour"""
    rate = '10/hour'


class OTPVerificationRateThrottle(AnonRateThrottle):
    """IP-based throttling for OTP verification: 10 requests per hour (approx 1 per 6 min)"""
    rate = '10/hour'


class OTPResendRateThrottle(AnonRateThrottle):
    """IP-based throttling for OTP resend: 3 requests per hour"""
    rate = '3/hour'
