from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from accounts.models import Customer
from accounts.serializers import SignUpSerializer
from accounts.services import AuthService
from accounts.utils.email_utils import EmailUtils
from accounts.utils.response_helpers import APIResponseHelper
from accounts.utils.token_utils import TokenUtils
from accounts.serializers.auth_serializers import LoginSerializer

class SignUpView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = SignUpSerializer(data=request.data)        
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)
        
        try:
            customer = AuthService.register_customer(serializer.validated_data)
            
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
            return APIResponseHelper.error_response(str(e))
            
        except Exception as e:
            return APIResponseHelper.server_error_response('An error occurred during registration')

class LoginView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)
        
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        remember_me = serializer.validated_data.get('remember_me', False)
        
        try:
            customer = AuthService.get_customer_by_email(email)
            if not customer:
                return APIResponseHelper.error_response(
                    'Invalid email or password',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            allowed, seconds_remaining = AuthService.check_login_rate_limit(customer)
            if not allowed:
                return APIResponseHelper.error_response(
                    f'Too many login attempts. Please try again in {seconds_remaining} seconds.',
                    status.HTTP_429_TOO_MANY_REQUESTS
                )
            
            AuthService.update_login_attempt(customer)
            
            if not customer.verified:
                return APIResponseHelper.error_response(
                    'Please verify your email before logging in'
                )
            
            if not customer.check_password(password):
                return APIResponseHelper.error_response(
                    'Invalid email or password',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            token_type = 'remember_me' if remember_me else 'no_remember_me'
            tokens = AuthService.create_customer_tokens(customer, token_type=token_type)
            
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
            return APIResponseHelper.server_error_response('Login failed')


class VerifyOTP(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        email = request.data.get('email')
        otp = request.data.get('otp')

        if not email or not otp:
            return APIResponseHelper.validation_error_response('Email and OTP are required')
        
        try:
            # Use centralized customer lookup
            customer = AuthService.get_customer_by_email(email)
            if not customer:
                return APIResponseHelper.error_response('Account not found')
            
            if customer.verified:
                return APIResponseHelper.success_response('Account already verified')
            
            if EmailUtils.is_otp_expired(customer.verification_token_expires):
                return APIResponseHelper.error_response('OTP has expired')
            
            if customer.verification_token != otp:
                return APIResponseHelper.error_response('Invalid OTP')
            
            # Use centralized verification method
            customer = AuthService.verify_customer_otp(customer)
            tokens = AuthService.create_customer_tokens(customer)

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
            return APIResponseHelper.server_error_response('Verification failed')
        
class ResendOTP(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        
        if not email:
            return APIResponseHelper.error_response('Email is required')
        
        try:
            # Use centralized customer lookup
            customer = AuthService.get_customer_by_email(email)
            
            if not customer:
                return APIResponseHelper.error_response('Account not found')
            
            if customer.verified:
                return APIResponseHelper.error_response('Account already verified')
            
            # Check resend limit (max 2 times)
            if customer.verification_resend_count >= 2:
                return APIResponseHelper.error_response(
                    'Maximum resend limit reached. Please contact support.'
                )
            
            # Use centralized resend method
            customer = AuthService.resend_customer_otp(customer)
            
            return APIResponseHelper.success_response(
                message=f'OTP resent successfully. {2 - customer.verification_resend_count} attempts remaining.'
            )
            
        except Exception as e:
            return APIResponseHelper.server_error_response('Failed to resend OTP')
        

class RefreshTokenView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Refresh access token and blacklist old refresh token"""
        refresh_token = request.data.get('refresh')
        
        if not refresh_token:
            return APIResponseHelper.error_response('Refresh token is required')
        
        try:
            if TokenUtils.is_token_blacklisted(refresh_token):
                return APIResponseHelper.error_response(
                    'Token has been revoked',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            token = RefreshToken(refresh_token)
            
            TokenUtils.blacklist_token(refresh_token)
            
            customer_id = token['customer_id']
            customer = AuthService.get_customer_by_id(customer_id)
            
            if not customer:
                return APIResponseHelper.error_response('User not found')
            
            new_tokens = AuthService.create_customer_tokens(customer, token_type='no_remember_me')
            
            return APIResponseHelper.success_response(
                data=new_tokens,
                message='Token refreshed successfully'
            )
            
        except TokenError as e:
            return APIResponseHelper.error_response(
                'Invalid or expired token',
                status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            return APIResponseHelper.server_error_response('Token refresh failed')
        
class LogoutView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Logout by blacklisting refresh token"""
        refresh_token = request.data.get('refresh')
        
        if not refresh_token:
            return APIResponseHelper.error_response('Refresh token is required')
        
        try:
            # Blacklist the token
            if TokenUtils.blacklist_token(refresh_token):
                return APIResponseHelper.success_response(
                    message='Logged out successfully'
                )
            else:
                return APIResponseHelper.error_response('Logout failed')
                
        except Exception as e:
            return APIResponseHelper.server_error_response('Logout failed')