from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from accounts.models import Customer
from accounts.serializers import SignUpSerializer
from accounts.services import AuthService
from accounts.services.lockout_service import LockoutService
from accounts.utils.email_utils import EmailUtils
from accounts.utils.response_helpers import APIResponseHelper
from accounts.utils.token_utils import TokenUtils
from accounts.serializers.auth_serializers import LoginSerializer
from accounts.utils.throttles import SignUpRateThrottle, LoginRateThrottle, OTPVerificationRateThrottle, OTPResendRateThrottle
from analytics.models import AuditLog
import logging
from config.security_events import log_security_event

logger = logging.getLogger('authentication')

class SignUpView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SignUpRateThrottle]
    
    def post(self, request):
        serializer = SignUpSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            logger.warning(f"Signup validation failed from IP {request.META.get('REMOTE_ADDR')}")
            log_security_event(
                event='signup_validation_failed',
                outcome='blocked',
                request=request,
                details={'errors': serializer.errors}
            )
            return APIResponseHelper.validation_error_response(serializer.errors)
        
        try:
            customer = AuthService.register_customer(serializer.validated_data)
            logger.info(f"New user registered: {customer.email} from IP {request.META.get('REMOTE_ADDR')}")
            log_security_event(
                event='signup_completed',
                outcome='success',
                request=request,
                user_id=customer.id,
                user_role='customer',
                details={'email': customer.email}
            )
            
            # Log audit event
            AuditLog.log_action(
                action='user_registered',
                user_id=customer.id,
                user_type='customer',
                user_email=customer.email,
                description=f'New user registered: {customer.email}',
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            response_data = {
                'user': AuthService.serialize_customer_data(customer),
                'message': 'Account created! Please check your email for verification OTP.'
            }
            
            return APIResponseHelper.success_response(
                data=response_data,
                message='Registration successful!',
                status_code=status.HTTP_201_CREATED
            )
            
        except ValueError as e:
            logger.warning(f"Signup failed for email {serializer.validated_data.get('email')}: {str(e)}")
            log_security_event(
                event='signup_failed',
                outcome='blocked',
                request=request,
                details={'reason': str(e)}
            )
            return APIResponseHelper.error_response(str(e))
            
        except Exception as e:
            logger.error(f"Signup error from IP {request.META.get('REMOTE_ADDR')}: {str(e)}")
            log_security_event(
                event='signup_failed',
                outcome='error',
                request=request,
                details={'reason': str(e)}
            )
            return APIResponseHelper.server_error_response('An error occurred during registration')

class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]
    
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            logger.warning(f"Login validation failed from IP {request.META.get('REMOTE_ADDR')}")
            log_security_event(
                event='login_validation_failed',
                outcome='blocked',
                request=request,
                details={'errors': serializer.errors}
            )
            return APIResponseHelper.validation_error_response(serializer.errors)
        
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        remember_me = serializer.validated_data.get('remember_me', False)
        
        try:
            customer = AuthService.get_customer_by_email(email)
            if not customer:
                logger.warning(f"Login attempt for non-existent email: {email} from IP {request.META.get('REMOTE_ADDR')}")
                log_security_event(
                    event='password_hash_verification',
                    outcome='blocked',
                    request=request,
                    details={'reason': 'customer_not_found', 'email': email}
                )
                return APIResponseHelper.error_response(
                    'Invalid email or password',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            # Check account lockout
            is_locked, lockout_seconds = LockoutService.is_account_locked(customer)
            if is_locked:
                logger.warning(f"Login attempt for locked account: {email} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response(
                    f'Account is locked. Please try again in {lockout_seconds // 60} minutes.',
                    status.HTTP_423_LOCKED
                )
            
            # Check rate limiting
            allowed, seconds_remaining = AuthService.check_login_rate_limit(customer)
            if not allowed:
                logger.warning(f"Rate limit exceeded for user {email} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response(
                    f'Too many login attempts. Please try again in {seconds_remaining} seconds.',
                    status.HTTP_429_TOO_MANY_REQUESTS
                )
            
            AuthService.update_login_attempt(customer)
            
            if not customer.verified:
                logger.warning(f"Login attempt for unverified account: {email} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response(
                    'Please verify your email before logging in'
                )
            
            # Verify password
            if not customer.check_password(password):
                # Record failed attempt for lockout
                is_now_locked, _ = LockoutService.record_failed_attempt(customer)
                logger.warning(f"Failed login attempt for {email} from IP {request.META.get('REMOTE_ADDR')}")
                
                if is_now_locked:
                    return APIResponseHelper.error_response(
                        'Account locked due to too many failed attempts. Please try again in 15 minutes.',
                        status.HTTP_423_LOCKED
                    )
                
                return APIResponseHelper.error_response(
                    'Invalid email or password',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            # Reset lockout on successful password verification
            LockoutService.reset_lockout(customer)
            
            # Check if 2FA is enabled
            if customer.two_factor_enabled:
                # Create temporary token for 2FA verification
                temp_token = AuthService.create_temp_token(customer)
                logger.info(f"2FA required for {email} from IP {request.META.get('REMOTE_ADDR')}")
                
                return APIResponseHelper.success_response(
                    data={
                        'requires_2fa': True,
                        'temp_token': temp_token,
                        'message': 'Please enter your 2FA code'
                    },
                    message='2FA verification required'
                )
            
            # No 2FA, issue tokens directly
            token_type = 'remember_me' if remember_me else 'no_remember_me'
            tokens = AuthService.create_customer_tokens(customer, token_type=token_type)
            
            logger.info(f"Successful login for user {email} from IP {request.META.get('REMOTE_ADDR')}")
            log_security_event(
                event='login_completed',
                outcome='success',
                request=request,
                user_id=customer.id,
                user_role='customer',
                details={'email': customer.email}
            )
            
            # Log audit event
            AuditLog.log_action(
                action='user_login',
                user_id=customer.id,
                user_type='customer',
                user_email=customer.email,
                description=f'User {customer.email} logged in successfully',
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            response_data = {
                'user': AuthService.serialize_customer_data(customer, include_last_name=True),
                'access': tokens['access'],
                'refresh': tokens['refresh'],
                'remember_me': remember_me
            }
            
            return APIResponseHelper.success_response(
                data=response_data,
                message='Login successful'
            )
            
        except Exception as e:
            logger.error(f"Login error for {email} from IP {request.META.get('REMOTE_ADDR')}: {str(e)}")
            log_security_event(
                event='login_failed',
                outcome='error',
                request=request,
                details={'reason': str(e), 'email': email}
            )
            return APIResponseHelper.server_error_response('Login failed')


class VerifyOTP(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPVerificationRateThrottle]
    
    def post(self, request):
        email = request.data.get('email')
        otp = request.data.get('otp')

        if not email or not otp:
            logger.warning(f"OTP verification missing required fields from IP {request.META.get('REMOTE_ADDR')}")
            return APIResponseHelper.validation_error_response('Email and OTP are required')
        
        try:
            customer = AuthService.get_customer_by_email(email)
            if not customer:
                logger.warning(f"OTP verification for non-existent account: {email} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response('Account not found')
            
            if customer.verified:
                return APIResponseHelper.success_response('Account already verified')
            
            allowed, seconds_remaining = AuthService.check_otp_rate_limit(customer)
            if not allowed:
                logger.warning(f"OTP rate limit exceeded for {email} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response(
                    f'Too many OTP attempts. Please try again in {seconds_remaining} seconds.',
                    status.HTTP_429_TOO_MANY_REQUESTS
                )
            
            if EmailUtils.is_otp_expired(customer.verification_token_expires):
                logger.warning(f"Expired OTP verification attempt for {email} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response('OTP has expired')
            
            AuthService.increment_otp_attempt(customer)
            
            if customer.verification_token != otp:
                logger.warning(f"Invalid OTP attempt for {email} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response('Invalid OTP')
            
            customer = AuthService.verify_customer_otp(customer)
            AuthService.reset_otp_attempts(customer)
            tokens = AuthService.create_customer_tokens(customer)

            logger.info(f"OTP verified successfully for {email} from IP {request.META.get('REMOTE_ADDR')}")

            response = {
                'user': AuthService.serialize_customer_data(customer),
                'access': tokens['access'],
                'refresh': tokens['refresh']
            }

            return APIResponseHelper.success_response(
                data=response,
                message='Account verified successfully'
            )
        except Exception as e:
            logger.error(f"OTP verification error for {email} from IP {request.META.get('REMOTE_ADDR')}: {str(e)}")
            return APIResponseHelper.server_error_response('Verification failed')
        
class ResendOTP(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPResendRateThrottle]

    def post(self, request):
        email = request.data.get('email')
        
        if not email:
            logger.warning(f"OTP resend missing email from IP {request.META.get('REMOTE_ADDR')}")
            return APIResponseHelper.error_response('Email is required')
        
        try:
            customer = AuthService.get_customer_by_email(email)
            
            if not customer:
                logger.warning(f"OTP resend for non-existent account: {email} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response('Account not found')
            
            if customer.verified:
                return APIResponseHelper.error_response('Account already verified')
            
            # Check resend limit (max 2 times)
            if customer.verification_resend_count >= 2:
                logger.warning(f"OTP resend limit exceeded for {email} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response(
                    'Maximum resend limit reached. Please contact support.'
                )
            
            customer = AuthService.resend_customer_otp(customer)
            
            logger.info(f"OTP resent for {email} from IP {request.META.get('REMOTE_ADDR')}")
            
            return APIResponseHelper.success_response(
                message=f'OTP resent successfully. {2 - customer.verification_resend_count} attempts remaining.'
            )
            
        except Exception as e:
            logger.error(f"OTP resend error for {email} from IP {request.META.get('REMOTE_ADDR')}: {str(e)}")
            return APIResponseHelper.server_error_response('Failed to resend OTP')
        

class RefreshTokenView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Refresh access token and blacklist old refresh token"""
        refresh_token = request.data.get('refresh')
        
        if not refresh_token:
            logger.warning(f"Token refresh missing token from IP {request.META.get('REMOTE_ADDR')}")
            return APIResponseHelper.error_response('Refresh token is required')
        
        try:
            if TokenUtils.is_token_blacklisted(refresh_token):
                logger.warning(f"Attempt to use blacklisted token from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response(
                    'Token has been revoked',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            token = RefreshToken(refresh_token)
            
            TokenUtils.blacklist_token(refresh_token)
            
            customer_id = token['customer_id']
            customer = AuthService.get_customer_by_id(customer_id)
            
            if not customer:
                logger.warning(f"Token refresh for non-existent user {customer_id} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response('User not found')
            
            new_tokens = AuthService.create_customer_tokens(customer, token_type='no_remember_me')
            
            logger.info(f"Token refreshed for user {customer.email} from IP {request.META.get('REMOTE_ADDR')}")
            
            return APIResponseHelper.success_response(
                data=new_tokens,
                message='Token refreshed successfully'
            )
            
        except TokenError as e:
            logger.warning(f"Invalid token refresh attempt from IP {request.META.get('REMOTE_ADDR')}")
            return APIResponseHelper.error_response(
                'Invalid or expired token',
                status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            logger.error(f"Token refresh error from IP {request.META.get('REMOTE_ADDR')}: {str(e)}")
            return APIResponseHelper.server_error_response('Token refresh failed')
        
class LogoutView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Logout by blacklisting both access and refresh tokens"""
        refresh_token = request.data.get('refresh')
        access_token = request.data.get('access')
        
        # Also try to get access token from Authorization header
        if not access_token:
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('Bearer '):
                access_token = auth_header[7:]
        
        if not refresh_token:
            logger.warning(f"Logout attempt missing refresh token from IP {request.META.get('REMOTE_ADDR')}")
            return APIResponseHelper.error_response('Refresh token is required')
        
        try:
            # Blacklist both tokens
            if TokenUtils.blacklist_tokens_on_logout(access_token, refresh_token):
                logger.info(f"User logged out from IP {request.META.get('REMOTE_ADDR')}")
                
                # Log audit event
                AuditLog.log_action(
                    action='user_logout',
                    user_type='customer',
                    description='User logged out',
                    ip_address=request.META.get('REMOTE_ADDR', '')
                )
                
                return APIResponseHelper.success_response(
                    message='Logged out successfully'
                )
            else:
                logger.warning(f"Logout failed from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.error_response('Logout failed')
                
        except Exception as e:
            logger.error(f"Logout error from IP {request.META.get('REMOTE_ADDR')}: {str(e)}")
            return APIResponseHelper.server_error_response('Logout failed')
            return APIResponseHelper.server_error_response('Logout failed')
