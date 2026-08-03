import logging
import re

from bson import ObjectId
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.models import Customer
from accounts.serializers.account_lifecycle_serializers import (
    CustomerStateUpdateSerializer,
    TwoFactorRecoveryDecisionSerializer,
)
from accounts.services.account_lifecycle_service import AccountLifecycleService
from accounts.services.lockout_service import LockoutService
from accounts.services.security_event_service import SecurityEventService
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.request_utils import get_client_ip
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.validation_utils import parse_optional_bool, sanitize_text
from analytics.models import AuditLog

logger = logging.getLogger("admin_auth")


class ManageUsersRequiredMixin(AccessControlMixin):
    def check_manage_users(self, request):
        return self.require_admin(
            request,
            required_permissions=["manage_users"],
            super_admin_only=False,
        )


class CustomerManagementView(ManageUsersRequiredMixin, APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        has_perm, result = self.check_manage_users(request)
        if not has_perm:
            return result

        search = sanitize_text(request.query_params.get("search", ""))
        active_raw = request.query_params.get("active")
        account_state = sanitize_text(request.query_params.get("account_state", "")).lower()
        query = {}

        if search:
            search_regex = re.compile(re.escape(search), re.IGNORECASE)
            query["$or"] = [
                {"first_name": {"$regex": search_regex}},
                {"middle_name": {"$regex": search_regex}},
                {"last_name": {"$regex": search_regex}},
                {"email": {"$regex": search_regex}},
            ]

        if account_state:
            query["account_state"] = account_state

        if active_raw is not None:
            is_valid, active_value, error_message = parse_optional_bool(active_raw, "active")
            if not is_valid:
                return error_response(
                    message="Invalid active filter",
                    errors={"active": error_message},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if active_value is not None:
                query["active"] = active_value

        customers = Customer.find(query)
        items = [
            {
                "id": customer.id,
                "first_name": customer.first_name,
                "middle_name": customer.middle_name,
                "last_name": customer.last_name,
                "email": customer.email,
                "active": customer.active,
                "account_state": getattr(customer, "account_state", "active"),
                "account_state_reason": getattr(customer, "account_state_reason", ""),
                "verified": customer.verified,
                "created_at": customer.created_at.isoformat() if customer.created_at else None,
                "updated_at": customer.updated_at.isoformat() if customer.updated_at else None,
            }
            for customer in customers
        ]
        return success_response(
            data={"customers": items, "total": len(items)},
            message="Customers retrieved successfully",
        )


class CustomerDetailView(ManageUsersRequiredMixin, APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def _load_customer(self, customer_id):
        if not ObjectId.is_valid(str(customer_id)):
            return None
        return Customer.find_one({"_id": ObjectId(str(customer_id))})

    def get(self, request, customer_id):
        has_perm, result = self.check_manage_users(request)
        if not has_perm:
            return result

        customer = self._load_customer(customer_id)
        if not customer:
            return error_response(
                message="Customer not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return success_response(
            data={
                "id": customer.id,
                "first_name": customer.first_name,
                "middle_name": customer.middle_name,
                "last_name": customer.last_name,
                "email": customer.email,
                "phone": customer.phone,
                "active": customer.active,
                "verified": customer.verified,
                "account_state": getattr(customer, "account_state", "active"),
                "account_state_reason": getattr(customer, "account_state_reason", ""),
                "account_state_changed_at": (
                    customer.account_state_changed_at.isoformat()
                    if getattr(customer, "account_state_changed_at", None)
                    else None
                ),
                "deletion_requested_at": (
                    customer.deletion_requested_at.isoformat()
                    if getattr(customer, "deletion_requested_at", None)
                    else None
                ),
                "deletion_scheduled_for": (
                    customer.deletion_scheduled_for.isoformat()
                    if getattr(customer, "deletion_scheduled_for", None)
                    else None
                ),
            },
            message="Customer retrieved successfully",
        )

    def patch(self, request, customer_id):
        has_perm, admin = self.check_manage_users(request)
        if not has_perm:
            return admin

        serializer = CustomerStateUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid customer state data",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        customer = self._load_customer(customer_id)
        if not customer:
            return error_response(
                message="Customer not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        previous_state = getattr(customer, "account_state", "active")
        updated = AccountLifecycleService.set_customer_state(
            customer,
            serializer.validated_data["account_state"],
            reason=serializer.validated_data.get("reason", ""),
        )
        if not updated:
            return error_response(
                message="Failed to update customer state",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        action = {
            "suspended": "account_suspended",
            "deactivated": "account_deactivated",
            "active": "admin_customer_unlock",
        }.get(updated.account_state, "account_deactivated")
        SecurityEventService.record(
            user=updated,
            user_type="customer",
            action=action,
            ip_address=get_client_ip(request),
            details={
                "previous_state": previous_state,
                "new_state": updated.account_state,
                "reason": serializer.validated_data.get("reason", ""),
                "sessions_revoked": updated.account_state in {"suspended", "deactivated"},
            },
        )
        AuditLog.log_action(
            action=action,
            user_id=admin.id,
            user_type="super_admin" if admin.super_admin else "admin",
            user_email=admin.email,
            description="Updated customer account state",
            resource_type="customer",
            resource_id=updated.id,
            details={
                "previous_state": previous_state,
                "new_state": updated.account_state,
                "reason": serializer.validated_data.get("reason", ""),
            },
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={
                "id": updated.id,
                "account_state": updated.account_state,
                "active": updated.active,
                "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
            },
            message="Customer state updated successfully",
        )


class CustomerUnlockView(ManageUsersRequiredMixin, APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def post(self, request, customer_id):
        has_perm, admin = self.check_manage_users(request)
        if not has_perm:
            return admin

        customer = AccountLifecycleService.get_customer_by_id(customer_id)
        if not customer:
            return error_response(
                message="Customer not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        unlocked = LockoutService.admin_unlock(customer.email, "customer")
        if not unlocked:
            return error_response(
                message="Failed to unlock customer account",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        SecurityEventService.record(
            user=customer,
            user_type="customer",
            action="admin_customer_unlock",
            ip_address=get_client_ip(request),
        )
        AuditLog.log_action(
            action="admin_customer_unlock",
            user_id=admin.id,
            user_type="super_admin" if admin.super_admin else "admin",
            user_email=admin.email,
            description="Unlocked customer account",
            resource_type="customer",
            resource_id=customer.id,
            details={"customer_email": customer.email},
            ip_address=get_client_ip(request),
        )
        return success_response(message="Customer account unlocked successfully")


class CustomerDeletionFinalizeView(ManageUsersRequiredMixin, APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def post(self, request, customer_id):
        has_perm, admin = self.check_manage_users(request)
        if not has_perm:
            return admin

        customer = AccountLifecycleService.get_customer_by_id(customer_id)
        if not customer:
            return error_response(
                message="Customer not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not AccountLifecycleService.is_deletion_due(customer):
            return error_response(
                message="Customer deletion is not yet due",
                code="deletion_not_due",
                status_code=status.HTTP_409_CONFLICT,
            )

        reason = sanitize_text(request.data.get("reason", ""))
        updated = AccountLifecycleService.finalize_deletion(customer, reason=reason)
        if not updated:
            return error_response(
                message="Failed to finalize customer deletion",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        SecurityEventService.record(
            user=updated,
            user_type="customer",
            action="account_deleted",
            ip_address=get_client_ip(request),
            details={"performed_by_admin": True},
        )
        AuditLog.log_action(
            action="account_deleted",
            user_id=admin.id,
            user_type="super_admin" if admin.super_admin else "admin",
            user_email=admin.email,
            description="Finalized customer account deletion",
            resource_type="customer",
            resource_id=updated.id,
            details={"reason": reason},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={
                "id": updated.id,
                "account_state": updated.account_state,
                "deleted_at": updated.deleted_at.isoformat() if updated.deleted_at else None,
            },
            message="Customer deletion finalized successfully",
        )


class TwoFactorRecoveryAdminView(ManageUsersRequiredMixin, APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        has_perm, result = self.check_manage_users(request)
        if not has_perm:
            return result
        return success_response(
            data={"requests": AccountLifecycleService.list_pending_two_factor_recovery()},
            message="Pending 2FA recovery requests retrieved",
        )

    def post(self, request, customer_id):
        has_perm, admin = self.check_manage_users(request)
        if not has_perm:
            return admin

        serializer = TwoFactorRecoveryDecisionSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid recovery decision data",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        customer = AccountLifecycleService.get_customer_by_id(customer_id)
        if not customer:
            return error_response(
                message="Customer not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if not AccountLifecycleService.is_two_factor_recovery_request_valid(customer):
            return error_response(
                message="No current verified 2FA recovery request for this customer",
                code="recovery_request_expired",
                status_code=status.HTTP_409_CONFLICT,
            )

        approve = serializer.validated_data["approve"]
        reason = serializer.validated_data.get("reason", "")
        updated = AccountLifecycleService.decide_two_factor_recovery(
            customer,
            approve=approve,
        )
        if not updated:
            return error_response(
                message="Failed to update 2FA recovery decision",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        action = (
            "two_factor_recovery_approved"
            if approve
            else "two_factor_recovery_rejected"
        )
        SecurityEventService.record(
            user=updated,
            user_type="customer",
            action=action,
            ip_address=get_client_ip(request),
            details={
                "reason": reason,
                "sessions_revoked": approve,
            },
        )
        AuditLog.log_action(
            action=action,
            user_id=admin.id,
            user_type="super_admin" if admin.super_admin else "admin",
            user_email=admin.email,
            description="Processed customer 2FA recovery request",
            resource_type="customer",
            resource_id=updated.id,
            details={"approved": approve, "reason": reason},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={
                "id": updated.id,
                "approved": approve,
                "two_factor_enabled": updated.two_factor_enabled,
            },
            message="2FA recovery request processed successfully",
        )
