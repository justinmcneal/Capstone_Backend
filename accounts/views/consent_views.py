import logging
from datetime import datetime, timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.models import Customer
from accounts.serializers.consent_serializers import (
    ConsentCreateSerializer,
    ConsentUpdateSerializer,
)
from accounts.services.consent_service import (
    ConsentMutationBusyError,
    ConsentPolicyError,
    ConsentRoleError,
    ConsentService,
)
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.exception_types import NON_FATAL_EXCEPTIONS
from accounts.utils.response_helpers import error_response, success_response

logger = logging.getLogger("consent")


def get_client_ip(request):
    """Extract client IP address from request"""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def _to_iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _sync_consent_secondary(consent, user_id, user_type):
    """Dispatch the optional blockchain mirror without affecting local success."""
    try:
        from loans.blockchain.sync import sync_consent

        consent_timestamp = consent.updated_at or datetime.now(timezone.utc)
        sync_consent(
            user_id=str(user_id),
            user_type=user_type,
            data_consent=consent.data_consent,
            ai_consent=consent.ai_consent,
            consent_version=consent.consent_version,
            consent_timestamp=_to_iso(consent_timestamp),
            previous_state=getattr(consent, "previous_state", None),
        )
    except Exception as exc:  # noqa: BLE001 - blockchain is a secondary mirror
        logger.warning("Blockchain consent sync skipped for %s: %s", user_id, exc)


class ConsentView(AccessControlMixin, APIView):
    """
    API view for managing user consent.

    Endpoints:
    - GET: Get current consent status
    - POST: Record initial consent
    - PUT: Update consent preferences
    """

    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        """
        Get current consent status for the authenticated user.

        Returns:
            {
                "status": "success",
                "data": {
                    "data_consent": bool,
                    "ai_consent": bool,
                    "consent_date": datetime or null,
                    "updated_at": datetime,
                    "can_access_ai": bool
                }
            }
        """
        try:
            allowed, result = self.require_customer(request)
            if not allowed:
                return result
            user_id = result.id
            user_type = "customer"

            consent_status = ConsentService.get_consent_status(user_id, user_type)

            return success_response(
                data=consent_status, message="Consent status retrieved successfully"
            )
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Error retrieving consent: {e!s}")
            return error_response(
                message="Failed to retrieve consent status",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        """
        Record initial consent from user.

        Request body:
            {
                "data_consent": bool (required),
                "ai_consent": bool (required)
            }

        Returns:
            {
                "status": "success",
                "message": "Consent recorded successfully",
                "data": { consent status }
            }
        """
        try:
            allowed, result = self.require_customer(request)
            if not allowed:
                return result
            serializer = ConsentCreateSerializer(data=request.data)

            if not serializer.is_valid():
                return error_response(
                    message="Invalid consent data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            user_id = result.id
            user_type = "customer"
            ip_address = get_client_ip(request)

            consent = ConsentService.record_consent(
                user_id=user_id,
                user_type=user_type,
                data_consent=serializer.validated_data["data_consent"],
                ai_consent=serializer.validated_data["ai_consent"],
                ip_address=ip_address,
                consent_version=serializer.validated_data.get("consent_version"),
            )
            _sync_consent_secondary(consent, user_id, user_type)

            response_data = {
                "data_consent": consent.data_consent,
                "ai_consent": consent.ai_consent,
                "consent_date": consent.consent_date,
                "can_access_ai": consent.can_access_ai,
                "consent_version": consent.consent_version,
                "current_policy": ConsentService.current_policy(),
                "revision": consent.revision,
            }

            return success_response(
                data=response_data,
                message="Consent recorded successfully",
                status_code=status.HTTP_201_CREATED,
            )
        except ConsentPolicyError as exc:
            return error_response(
                message=str(exc),
                code="CONSENT_POLICY_REQUIRED",
                errors={"current_policy": ConsentService.current_policy()},
                status_code=status.HTTP_409_CONFLICT,
            )
        except (ConsentRoleError, ConsentMutationBusyError) as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_409_CONFLICT
            )
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Error recording consent: {e!s}")
            return error_response(
                message="Failed to record consent",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request):
        """
        Update consent preferences.

        Request body:
            {
                "data_consent": bool (optional),
                "ai_consent": bool (optional)
            }

        At least one field must be provided.

        Returns:
            {
                "status": "success",
                "message": "Consent updated successfully",
                "data": { consent status }
            }
        """
        try:
            allowed, result = self.require_customer(request)
            if not allowed:
                return result
            serializer = ConsentUpdateSerializer(data=request.data)

            if not serializer.is_valid():
                return error_response(
                    message="Invalid consent data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            user_id = result.id
            user_type = "customer"
            ip_address = get_client_ip(request)

            updates = {
                key: value
                for key, value in serializer.validated_data.items()
                if key in {"data_consent", "ai_consent"}
            }

            consent = ConsentService.update_consent(
                user_id=user_id,
                user_type=user_type,
                updates=updates,
                ip_address=ip_address,
                consent_version=serializer.validated_data.get("consent_version"),
            )
            _sync_consent_secondary(consent, user_id, user_type)

            response_data = {
                "data_consent": consent.data_consent,
                "ai_consent": consent.ai_consent,
                "updated_at": consent.updated_at,
                "can_access_ai": consent.can_access_ai,
                "consent_version": consent.consent_version,
                "current_policy": ConsentService.current_policy(),
                "revision": consent.revision,
            }

            return success_response(
                data=response_data, message="Consent updated successfully"
            )
        except ConsentPolicyError as exc:
            return error_response(
                message=str(exc),
                code="CONSENT_POLICY_REQUIRED",
                errors={"current_policy": ConsentService.current_policy()},
                status_code=status.HTTP_409_CONFLICT,
            )
        except ConsentMutationBusyError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_409_CONFLICT
            )
        except ValueError as e:
            return error_response(message=str(e), status_code=status.HTTP_404_NOT_FOUND)
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Error updating consent: {e!s}")
            return error_response(
                message="Failed to update consent",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConsentAuditView(AccessControlMixin, APIView):
    """Admin report of customers with and without AI consent."""

    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        try:
            has_permission, result = self.require_admin(request)
            if not has_permission:
                return result

            customers = Customer.find({}, sort=[("created_at", -1)])
            ai_consent_true = 0
            ai_consent_false = 0
            rows = []

            for customer in customers:
                consent_status = ConsentService.get_consent_status(
                    customer.id, "customer"
                )
                has_record = consent_status["has_consent_record"]
                ai_consent = consent_status["ai_consent"]
                data_consent = consent_status["data_consent"]

                if ai_consent:
                    ai_consent_true += 1
                else:
                    ai_consent_false += 1

                rows.append(
                    {
                        "customer_id": customer.id,
                        "full_name": customer.full_name,
                        "email": customer.email,
                        "verified": customer.verified,
                        "has_consent_record": has_record,
                        "data_consent": data_consent,
                        "ai_consent": ai_consent,
                        "consent_date": _to_iso(consent_status["consent_date"]),
                        "updated_at": _to_iso(consent_status["updated_at"]),
                        "consent_version": consent_status["consent_version"],
                        "requires_reconsent": consent_status["requires_reconsent"],
                        "can_access_ai": consent_status["can_access_ai"],
                    }
                )

            return success_response(
                data={
                    "summary": {
                        "total_customers": len(customers),
                        "ai_consent_true": ai_consent_true,
                        "ai_consent_false": ai_consent_false,
                        "missing_consent_records": sum(
                            1 for item in rows if not item["has_consent_record"]
                        ),
                    },
                    "customers": rows,
                },
                message="Consent audit retrieved successfully",
            )
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Error retrieving consent audit: {e!s}")
            return error_response(
                message="Failed to retrieve consent audit",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConsentHistoryView(AccessControlMixin, APIView):
    """
    Get authoritative append-only local consent history for the customer.
    """

    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        try:
            allowed, result = self.require_customer(request)
            if not allowed:
                return result
            history = [
                event.to_public_dict()
                for event in ConsentService.get_consent_history(
                    result.id, "customer"
                )
            ]

            return success_response(
                data={"history": history},
                message="Consent history retrieved successfully",
            )
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Error retrieving consent history: {e!s}")
            return error_response(
                message="Failed to retrieve consent history",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConsentRequiredMixin(AccessControlMixin):
    """
    Mixin to require AI consent for views that use AI features.

    Add this mixin to any view that requires AI consent:

        class MyAIView(ConsentRequiredMixin, APIView):
            require_ai_consent = True  # Default
            # or
            require_data_consent = True
    """

    require_ai_consent = True
    require_data_consent = False

    def check_consent(self, request):
        """
        Check if user has required consent.

        Returns:
            tuple: (has_consent: bool, error_response: Response or None)
        """
        has_customer_role, result = self.require_customer(request)
        if not has_customer_role:
            return False, result
        user_id = result.id
        user_type = "customer"

        if self.require_ai_consent and not ConsentService.check_ai_consent(user_id, user_type):
            return False, error_response(
                message="AI consent is required to use this feature",
                code="CONSENT_REQUIRED",
                errors={
                    "action_required": {
                        "endpoint": "/api/auth/consent/",
                        "method": "POST",
                        "required_fields": [
                            "data_consent",
                            "ai_consent",
                            "consent_version",
                        ],
                        "current_policy": ConsentService.current_policy(),
                    }
                },
                status_code=status.HTTP_403_FORBIDDEN,
            )

        if self.require_data_consent and not ConsentService.check_data_consent(user_id, user_type):
            return False, error_response(
                message="Data consent is required to use this feature",
                code="CONSENT_REQUIRED",
                errors={
                    "action_required": {
                        "endpoint": "/api/auth/consent/",
                        "method": "POST",
                        "required_fields": ["data_consent"],
                    }
                },
                status_code=status.HTTP_403_FORBIDDEN,
            )

        return True, None

    def dispatch(self, request, *args, **kwargs):
        """Run consent gate after DRF auth/permission checks but before handler execution."""
        self.args = args
        self.kwargs = kwargs
        request = self.initialize_request(request, *args, **kwargs)
        self.request = request
        self.headers = self.default_response_headers

        try:
            self.initial(request, *args, **kwargs)

            has_consent, error = self.check_consent(request)
            if not has_consent:
                response = error
            else:
                if request.method.lower() in self.http_method_names:
                    handler = getattr(
                        self, request.method.lower(), self.http_method_not_allowed
                    )
                else:
                    handler = self.http_method_not_allowed
                response = handler(request, *args, **kwargs)
        except NON_FATAL_EXCEPTIONS as exc:
            response = self.handle_exception(exc)

        self.response = self.finalize_response(request, response, *args, **kwargs)
        return self.response
