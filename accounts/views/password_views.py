import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from accounts.serializers.password_serializers import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    VerifyResetOTPSerializer,
)
from accounts.services.password_service import PasswordService
from accounts.services.security_event_service import SecurityEventService
from accounts.utils.exception_types import NON_FATAL_EXCEPTIONS
from accounts.utils.request_utils import get_client_ip
from accounts.utils.response_helpers import APIResponseHelper
from accounts.utils.throttles import (
    ForgotPasswordRateThrottle,
    OTPIdentifierRateThrottle,
    OTPVerificationRateThrottle,
)

logger = logging.getLogger("authentication")


class ForgotPasswordView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()
    throttle_classes = (
        ForgotPasswordRateThrottle,
        OTPIdentifierRateThrottle,
    )

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                f"Forgot password validation failed from IP {request.META.get('REMOTE_ADDR')}"
            )
            return APIResponseHelper.validation_error_response(serializer.errors)

        email = serializer.validated_data["email"]
        role = serializer.validated_data.get("role")
        success, message = PasswordService.initiate_password_reset(
            email, role, ip_address=get_client_ip(request)
        )
        if not success:
            logger.error(f"Password reset initiation failed for {email}: {message}")
            return APIResponseHelper.server_error_response(
                "Failed to initiate password reset"
            )

        logger.info(
            f"Password reset request processed for {email} from IP {request.META.get('REMOTE_ADDR')}"
        )
        return APIResponseHelper.success_response(message=message)


class VerifyResetOTPView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()
    throttle_classes = (
        OTPVerificationRateThrottle,
        OTPIdentifierRateThrottle,
    )

    def post(self, request):
        serializer = VerifyResetOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)

        email = serializer.validated_data["email"]
        otp = serializer.validated_data["otp"]
        role = serializer.validated_data.get("role")
        success, message = PasswordService.verify_reset_otp(email, otp, role)

        if success:
            logger.info(
                f"Password reset OTP verified for {email} from IP {request.META.get('REMOTE_ADDR')}"
            )
            return APIResponseHelper.success_response(message=message)

        logger.warning(f"OTP verification failed for {email}: {message}")
        return APIResponseHelper.error_response(
            message=message, error_code=status.HTTP_400_BAD_REQUEST
        )


class ResetPasswordView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()
    throttle_classes = (
        OTPVerificationRateThrottle,
        OTPIdentifierRateThrottle,
    )

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)

        email = serializer.validated_data["email"]
        otp = serializer.validated_data["otp"]
        new_password = serializer.validated_data["new_password"]
        role = serializer.validated_data.get("role")
        success, message = PasswordService.reset_password(
            email, otp, new_password, role
        )

        if success:
            user, user_type = PasswordService._find_user_by_email(email, role)
            if user:
                SecurityEventService.record(
                    user=user,
                    user_type=user_type,
                    action="password_reset_completed",
                    ip_address=get_client_ip(request),
                    details={"sessions_revoked": True},
                )
            logger.info(
                f"Password reset successful for {email} from IP {request.META.get('REMOTE_ADDR')}"
            )
            return APIResponseHelper.success_response(message=message)

        logger.warning(f"Password reset failed for {email}: {message}")
        return APIResponseHelper.error_response(
            message=message, error_code=status.HTTP_400_BAD_REQUEST
        )


class ChangePasswordView(APIView):
    """
    Change password for authenticated user (Customer or LoanOfficer).
    Requires old password verification.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)

        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]

        try:
            from accounts.utils.user_detection import get_authenticated_user

            user, user_type = get_authenticated_user(request)

            if not user:
                return APIResponseHelper.error_response(
                    "User not found", error_code=status.HTTP_404_NOT_FOUND
                )

            success, message = PasswordService.change_password(
                user, old_password, new_password
            )

            if success:
                SecurityEventService.record(
                    user=user,
                    user_type=user_type,
                    action="password_changed",
                    ip_address=get_client_ip(request),
                    details={"sessions_revoked": True},
                )

                logger.info(
                    f"Password changed for {user.email} ({user_type}) from IP {request.META.get('REMOTE_ADDR')}"
                )
                return APIResponseHelper.success_response(message=message)

            logger.warning(f"Password change failed for {user.email} ({user_type})")
            return APIResponseHelper.error_response(
                message=message, error_code=status.HTTP_400_BAD_REQUEST
            )
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Password change error: {e!s}")
            return APIResponseHelper.error_response(
                message=str(e), error_code=status.HTTP_400_BAD_REQUEST
            )
