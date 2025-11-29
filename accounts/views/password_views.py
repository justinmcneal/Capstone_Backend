from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from accounts.serializers.password_serializers import (
    ForgotPasswordSerializer,
    VerifyResetOTPSerializer,
    ResetPasswordSerializer,
    ChangePasswordSerializer
)
from accounts.services.password_service import PasswordService
from accounts.utils.response_helpers import APIResponseHelper
from accounts.utils.throttles import (
    OTPVerificationRateThrottle,
    OTPResendRateThrottle
)
import logging

logger = logging.getLogger('authentication')

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPResendRateThrottle]
    
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Forgot password validation failed from IP {request.META.get('REMOTE_ADDR')}")
            return APIResponseHelper.validation_error_response(serializer.errors)
        
        email = serializer.validated_data['email']
        success, message = PasswordService.initiate_password_reset(email)
        
        if success:
            logger.info(f"Password reset OTP sent for {email} from IP {request.META.get('REMOTE_ADDR')}")
            return APIResponseHelper.success_response(message=message)
        
        logger.warning(f"Password reset failed for {email}: {message}")
        return APIResponseHelper.error_response(message=message, error_code=status.HTTP_404_NOT_FOUND)

class VerifyResetOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPVerificationRateThrottle]
    
    def post(self, request):
        serializer = VerifyResetOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)
        
        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']
        success, message = PasswordService.verify_reset_otp(email, otp)
        
        if success:
            logger.info(f"Password reset OTP verified for {email} from IP {request.META.get('REMOTE_ADDR')}")
            return APIResponseHelper.success_response(message=message)
        
        logger.warning(f"OTP verification failed for {email}: {message}")
        return APIResponseHelper.error_response(message=message, error_code=status.HTTP_400_BAD_REQUEST)

class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPVerificationRateThrottle]
    
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)
        
        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']
        new_password = serializer.validated_data['new_password']
        success, message = PasswordService.reset_password(email, otp, new_password)
        
        if success:
            logger.info(f"Password reset successful for {email} from IP {request.META.get('REMOTE_ADDR')}")
            return APIResponseHelper.success_response(message=message)
        
        logger.warning(f"Password reset failed for {email}: {message}")
        return APIResponseHelper.error_response(message=message, error_code=status.HTTP_400_BAD_REQUEST)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)
        
        old_password = serializer.validated_data['old_password']
        new_password = serializer.validated_data['new_password']
        
        try:
            customer_id = request.user.get('customer_id')
            from accounts.services.auth_service import AuthService
            customer = AuthService.get_customer_by_id(customer_id)
            
            if not customer:
                return APIResponseHelper.error_response('User not found', error_code=status.HTTP_404_NOT_FOUND)
            
            success, message = PasswordService.change_password(customer, old_password, new_password)
            
            if success:
                logger.info(f"Password changed for {customer.email} from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.success_response(message=message)
            logger.warning(f"Password change failed for {customer.email}")
            return APIResponseHelper.error_response(message=message, error_code=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Password change error: {str(e)}")
            return APIResponseHelper.error_response(message=str(e), error_code=status.HTTP_400_BAD_REQUEST)