from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from datetime import datetime

from accounts.authentication import CustomJWTAuthentication
from accounts.services.consent_service import ConsentService
from accounts.serializers.consent_serializers import (
    ConsentCreateSerializer,
    ConsentUpdateSerializer,
)
from accounts.utils.response_helpers import success_response, error_response
import logging

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


class ConsentView(APIView):
    """
    API view for managing user consent.

    Endpoints:
    - GET: Get current consent status
    - POST: Record initial consent
    - PUT: Update consent preferences
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

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
            user = request.user
            user_id = user.customer_id
            user_type = user.role if hasattr(user, "role") else "customer"

            consent_status = ConsentService.get_consent_status(user_id, user_type)

            return success_response(
                data=consent_status, message="Consent status retrieved successfully"
            )
        except Exception as e:
            logger.error(f"Error retrieving consent: {str(e)}")
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
            serializer = ConsentCreateSerializer(data=request.data)

            if not serializer.is_valid():
                return error_response(
                    message="Invalid consent data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            user = request.user
            user_id = user.customer_id
            user_type = user.role if hasattr(user, "role") else "customer"
            ip_address = get_client_ip(request)

            from accounts.models.consent import Consent

            previous_state = None
            existing = Consent.find_by_user(user_id, user_type)
            if existing:
                previous_state = {
                    "data_consent": existing.data_consent,
                    "ai_consent": existing.ai_consent,
                    "consent_version": existing.consent_version,
                }

            consent = ConsentService.record_consent(
                user_id=user_id,
                user_type=user_type,
                data_consent=serializer.validated_data["data_consent"],
                ai_consent=serializer.validated_data["ai_consent"],
                ip_address=ip_address,
            )

            # Blockchain sync — consent (background thread, no Celery needed)
            try:
                from loans.blockchain.sync import sync_consent

                consent_timestamp = (
                    consent.updated_at or consent.consent_date or datetime.utcnow()
                )
                sync_consent(
                    user_id=str(user_id),
                    user_type=user_type,
                    data_consent=consent.data_consent,
                    ai_consent=consent.ai_consent,
                    consent_version=consent.consent_version,
                    consent_timestamp=_to_iso(consent_timestamp),
                    previous_state=previous_state,
                )
            except Exception as e:
                logger.warning(f"Blockchain sync skipped for consent {user_id}: {e}")

            response_data = {
                "data_consent": consent.data_consent,
                "ai_consent": consent.ai_consent,
                "consent_date": consent.consent_date,
                "can_access_ai": consent.can_access_ai,
            }

            # Blockchain sync — consent record
            try:
                from loans.blockchain.sync import sync_consent

                sync_consent(
                    user_id=user_id,
                    user_type=user_type,
                    data_consent=consent.data_consent,
                    ai_consent=consent.ai_consent,
                    consent_version=consent.consent_version,
                    consent_timestamp=consent.consent_date or consent.updated_at,
                    previous_state=None,
                )
            except Exception as e:
                logger.warning(f"Blockchain sync skipped for consent {user_id}: {e}")

            return success_response(
                data=response_data,
                message="Consent recorded successfully",
                status_code=status.HTTP_201_CREATED,
            )
        except Exception as e:
            logger.error(f"Error recording consent: {str(e)}")
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
            serializer = ConsentUpdateSerializer(data=request.data)

            if not serializer.is_valid():
                return error_response(
                    message="Invalid consent data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            user = request.user
            user_id = user.customer_id
            user_type = user.role if hasattr(user, "role") else "customer"
            ip_address = get_client_ip(request)

            from accounts.models.consent import Consent

            previous_state = None
            existing = Consent.find_by_user(user_id, user_type)
            if existing:
                previous_state = {
                    "data_consent": existing.data_consent,
                    "ai_consent": existing.ai_consent,
                    "consent_version": existing.consent_version,
                }

            consent = ConsentService.update_consent(
                user_id=user_id,
                user_type=user_type,
                updates=serializer.validated_data,
                ip_address=ip_address,
            )

            # Blockchain sync — consent (background thread, no Celery needed)
            try:
                from loans.blockchain.sync import sync_consent

                consent_timestamp = (
                    consent.updated_at or consent.consent_date or datetime.utcnow()
                )
                sync_consent(
                    user_id=str(user_id),
                    user_type=user_type,
                    data_consent=consent.data_consent,
                    ai_consent=consent.ai_consent,
                    consent_version=consent.consent_version,
                    consent_timestamp=_to_iso(consent_timestamp),
                    previous_state=previous_state,
                )
            except Exception as e:
                logger.warning(f"Blockchain sync skipped for consent {user_id}: {e}")

            response_data = {
                "data_consent": consent.data_consent,
                "ai_consent": consent.ai_consent,
                "updated_at": consent.updated_at,
                "can_access_ai": consent.can_access_ai,
            }

            # Blockchain sync — consent update
            try:
                from loans.blockchain.sync import sync_consent

                sync_consent(
                    user_id=user_id,
                    user_type=user_type,
                    data_consent=consent.data_consent,
                    ai_consent=consent.ai_consent,
                    consent_version=consent.consent_version,
                    consent_timestamp=consent.updated_at,
                    previous_state=previous_state,
                )
            except Exception as e:
                logger.warning(
                    f"Blockchain sync skipped for consent update {user_id}: {e}"
                )

            return success_response(
                data=response_data, message="Consent updated successfully"
            )
        except ValueError as e:
            return error_response(message=str(e), status_code=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error updating consent: {str(e)}")
            return error_response(
                message="Failed to update consent",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConsentRequiredMixin:
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
        user = request.user
        user_id = user.customer_id
        user_type = user.role if hasattr(user, "role") else "customer"

        if self.require_ai_consent:
            if not ConsentService.check_ai_consent(user_id, user_type):
                return False, error_response(
                    message="AI consent is required to use this feature",
                    code="CONSENT_REQUIRED",
                    errors={
                        "action_required": {
                            "endpoint": "/api/auth/consent/",
                            "method": "POST",
                            "required_fields": ["ai_consent"],
                        }
                    },
                    status_code=status.HTTP_403_FORBIDDEN,
                )

        if self.require_data_consent:
            if not ConsentService.check_data_consent(user_id, user_type):
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
        except Exception as exc:
            response = self.handle_exception(exc)

        self.response = self.finalize_response(request, response, *args, **kwargs)
        return self.response
