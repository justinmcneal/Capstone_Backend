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
    ForgotPasswordRateThrottle
)
import logging

logger = logging.getLogger('authentication')

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ForgotPasswordRateThrottle]
    
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Forgot password validation failed from IP {request.META.get('REMOTE_ADDR')}")
            return APIResponseHelper.validation_error_response(serializer.errors)
        
        email = serializer.validated_data['email']
        success, message = PasswordService.initiate_password_reset(email)
        if not success:
            logger.error(f"Password reset initiation failed for {email}: {message}")
            return APIResponseHelper.server_error_response('Failed to initiate password reset')

        logger.info(f"Password reset request processed for {email} from IP {request.META.get('REMOTE_ADDR')}")
        return APIResponseHelper.success_response(message=message)

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
    """
    Change password for authenticated user (Customer or LoanOfficer).
    Requires old password verification.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)
        
        old_password = serializer.validated_data['old_password']
        new_password = serializer.validated_data['new_password']
        
        try:
            from accounts.utils.user_detection import get_authenticated_user
            
            user, user_type = get_authenticated_user(request)
            
            if not user:
                return APIResponseHelper.error_response('User not found', error_code=status.HTTP_404_NOT_FOUND)
            
            success, message = PasswordService.change_password(user, old_password, new_password)
            
            if success:
                # Clear must_change_password flag for loan officers
                if user_type == 'loan_officer' and hasattr(user, 'must_change_password') and user.must_change_password:
                    user.must_change_password = False
                    user.save()
                    logger.info(f"Cleared must_change_password flag for {user.email}")
                
                logger.info(f"Password changed for {user.email} ({user_type}) from IP {request.META.get('REMOTE_ADDR')}")
                return APIResponseHelper.success_response(message=message)
            
            logger.warning(f"Password change failed for {user.email} ({user_type})")
            return APIResponseHelper.error_response(message=message, error_code=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Password change error: {str(e)}")
            return APIResponseHelper.error_response(message=str(e), error_code=status.HTTP_400_BAD_REQUEST)
