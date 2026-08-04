import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.serializers.account_lifecycle_serializers import (
    AccountDeletionCancelSerializer,
    AccountDeletionRequestSerializer,
    EmailChangeConfirmSerializer,
    EmailChangeRequestSerializer,
    TwoFactorRecoveryRequestSerializer,
    TwoFactorRecoveryVerifySerializer,
)
from accounts.services.account_lifecycle_service import AccountLifecycleService
from accounts.services.security_event_service import SecurityEventService
from accounts.utils.exception_types import NON_FATAL_EXCEPTIONS
from accounts.utils.request_utils import get_client_ip
from accounts.utils.response_helpers import APIResponseHelper
from accounts.utils.throttles import (
    ForgotPasswordRateThrottle,
    LoginRateThrottle,
    OTPIdentifierRateThrottle,
    OTPVerificationRateThrottle,
)
from accounts.utils.user_detection import get_authenticated_user
from analytics.models import AuditLog

logger = logging.getLogger("authentication")


class EmailChangeRequestView(APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (LoginRateThrottle,)

    def post(self, request):
        serializer = EmailChangeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)

        user, user_type = get_authenticated_user(request)
        if not user or user_type != "customer":
            return APIResponseHelper.error_response(
                "Customer account not found",
                status.HTTP_404_NOT_FOUND,
            )

        try:
            success, message = AccountLifecycleService.request_email_change(
                user,
                new_email=serializer.validated_data["new_email"],
                password=serializer.validated_data["password"],
            )
            if not success:
                return APIResponseHelper.error_response(
                    message, status.HTTP_400_BAD_REQUEST
                )

            SecurityEventService.record(
                user=user,
                user_type="customer",
                action="email_change_requested",
                ip_address=get_client_ip(request),
                details={"pending_email": serializer.validated_data["new_email"]},
            )
            AuditLog.log_action(
                action="email_change_requested",
                user_id=user.id,
                user_type="customer",
                user_email=user.email,
                description="Customer requested an email change",
                details={"pending_email": serializer.validated_data["new_email"]},
                ip_address=get_client_ip(request),
            )
            return APIResponseHelper.success_response(message=message)
        except ValueError as exc:
            return APIResponseHelper.error_response(
                str(exc), status.HTTP_400_BAD_REQUEST
            )
        except NON_FATAL_EXCEPTIONS as exc:
            logger.error("Email change request failed: %s", exc)
            return APIResponseHelper.server_error_response(
                "Failed to request email change"
            )


class EmailChangeConfirmView(APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (OTPVerificationRateThrottle,)

    def post(self, request):
        serializer = EmailChangeConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)

        user, user_type = get_authenticated_user(request)
        if not user or user_type != "customer":
            return APIResponseHelper.error_response(
                "Customer account not found",
                status.HTTP_404_NOT_FOUND,
            )
        old_email = user.email
        pending_email = getattr(user, "pending_email", None)
        try:
            success, message = AccountLifecycleService.confirm_email_change(
                user,
                otp=serializer.validated_data["otp"],
            )
            if not success:
                return APIResponseHelper.error_response(
                    message, status.HTTP_400_BAD_REQUEST
                )

            refreshed = AccountLifecycleService.get_customer_by_id(user.id)
            if refreshed:
                SecurityEventService.record(
                    user=refreshed,
                    user_type="customer",
                    action="email_changed",
                    ip_address=get_client_ip(request),
                    details={
                        "old_email": old_email,
                        "new_email": refreshed.email,
                        "sessions_revoked": True,
                    },
                )
                AuditLog.log_action(
                    action="email_changed",
                    user_id=refreshed.id,
                    user_type="customer",
                    user_email=refreshed.email,
                    description="Customer email changed",
                    details={
                        "old_email": old_email,
                        "new_email": refreshed.email,
                        "requested_email": pending_email,
                        "sessions_revoked": True,
                    },
                    ip_address=get_client_ip(request),
                )
            return APIResponseHelper.success_response(message=message)
        except ValueError as exc:
            return APIResponseHelper.error_response(
                str(exc), status.HTTP_400_BAD_REQUEST
            )
        except NON_FATAL_EXCEPTIONS as exc:
            logger.error("Email change confirmation failed: %s", exc)
            return APIResponseHelper.server_error_response(
                "Failed to confirm email change"
            )


class AccountExportView(APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        user, user_type = get_authenticated_user(request)
        if not user or user_type != "customer":
            return APIResponseHelper.error_response(
                "Customer account not found",
                status.HTTP_404_NOT_FOUND,
            )
        try:
            payload = AccountLifecycleService.export_customer_data(user)
            return APIResponseHelper.success_response(
                data=payload,
                message="Account export generated",
            )
        except NON_FATAL_EXCEPTIONS as exc:
            logger.error("Account export failed: %s", exc)
            return APIResponseHelper.server_error_response(
                "Failed to generate account export"
            )


class AccountDeletionRequestView(APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (LoginRateThrottle,)

    def post(self, request):
        serializer = AccountDeletionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)

        user, user_type = get_authenticated_user(request)
        if not user or user_type != "customer":
            return APIResponseHelper.error_response(
                "Customer account not found",
                status.HTTP_404_NOT_FOUND,
            )
        updated = AccountLifecycleService.request_deletion(
            user,
            reason=serializer.validated_data.get("reason", ""),
        )
        if not updated:
            return APIResponseHelper.error_response(
                "Unable to request account deletion",
                status.HTTP_400_BAD_REQUEST,
            )

        SecurityEventService.record(
            user=updated,
            user_type="customer",
            action="account_deletion_requested",
            ip_address=get_client_ip(request),
            details={
                "scheduled_for": (
                    updated.deletion_scheduled_for.isoformat()
                    if updated.deletion_scheduled_for
                    else None
                ),
                "sessions_revoked": True,
            },
        )
        AuditLog.log_action(
            action="account_deletion_requested",
            user_id=updated.id,
            user_type="customer",
            user_email=updated.email,
            description="Customer requested account deletion",
            details={
                "scheduled_for": (
                    updated.deletion_scheduled_for.isoformat()
                    if updated.deletion_scheduled_for
                    else None
                )
            },
            ip_address=get_client_ip(request),
        )
        return APIResponseHelper.success_response(
            data={
                "account_state": updated.account_state,
                "deletion_scheduled_for": (
                    updated.deletion_scheduled_for.isoformat()
                    if updated.deletion_scheduled_for
                    else None
                ),
            },
            message="Account deletion requested successfully",
        )


class AccountDeletionCancelView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (ForgotPasswordRateThrottle, OTPIdentifierRateThrottle)

    def post(self, request):
        serializer = AccountDeletionCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)

        updated = AccountLifecycleService.cancel_deletion_with_password(
            serializer.validated_data["email"],
            serializer.validated_data["password"],
        )
        if not updated:
            return APIResponseHelper.success_response(
                message=AccountLifecycleService.DELETION_CANCELLATION_GENERIC_MESSAGE
            )

        SecurityEventService.record(
            user=updated,
            user_type="customer",
            action="account_deletion_cancelled",
            ip_address=get_client_ip(request),
            details={"sessions_revoked": True},
        )
        AuditLog.log_action(
            action="account_deletion_cancelled",
            user_id=updated.id,
            user_type="customer",
            user_email=updated.email,
            description="Customer cancelled account deletion request",
            ip_address=get_client_ip(request),
        )
        return APIResponseHelper.success_response(
            data={"account_state": updated.account_state},
            message="Account deletion request cancelled",
        )


class TwoFactorRecoveryRequestView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()
    throttle_classes = (ForgotPasswordRateThrottle, OTPIdentifierRateThrottle)

    def post(self, request):
        serializer = TwoFactorRecoveryRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)

        success, customer, message = (
            AccountLifecycleService.request_two_factor_recovery(
                serializer.validated_data["email"],
                serializer.validated_data["password"],
            )
        )
        if not success:
            return APIResponseHelper.error_response(
                message, status.HTTP_400_BAD_REQUEST
            )
        if customer:
            SecurityEventService.record(
                user=customer,
                user_type="customer",
                action="two_factor_recovery_requested",
                ip_address=get_client_ip(request),
            )
            AuditLog.log_action(
                action="two_factor_recovery_requested",
                user_id=customer.id,
                user_type="customer",
                user_email=customer.email,
                description="Customer initiated two-factor recovery",
                ip_address=get_client_ip(request),
            )
        return APIResponseHelper.success_response(message=message)


class TwoFactorRecoveryVerifyView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()
    throttle_classes = (OTPVerificationRateThrottle, OTPIdentifierRateThrottle)

    def post(self, request):
        serializer = TwoFactorRecoveryVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)

        success, customer, message = AccountLifecycleService.verify_two_factor_recovery(
            serializer.validated_data["email"],
            serializer.validated_data["otp"],
        )
        if not success:
            return APIResponseHelper.error_response(
                message, status.HTTP_400_BAD_REQUEST
            )
        if customer:
            AuditLog.log_action(
                action="two_factor_recovery_requested",
                user_id=customer.id,
                user_type="customer",
                user_email=customer.email,
                description="Customer verified two-factor recovery request",
                details={"verified": True},
                ip_address=get_client_ip(request),
            )
        return APIResponseHelper.success_response(message=message)
