import logging
import math
import re
from typing import ClassVar

from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.models import Customer
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.request_utils import get_client_ip
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.throttles import ProfileRateThrottle
from analytics.models import AuditLog
from profiles.models import AlternativeData, BusinessProfile, CustomerProfile
from profiles.serializers import (
    AlternativeDataSerializer,
    BusinessProfileSerializer,
    CustomerProfileSerializer,
)
from profiles.services.notification_preferences import (
    UnknownPreferenceKeysError,
    get_preferences,
    update_preferences,
)
from profiles.services.officer_profile import build_officer_customer_profile
from profiles.services.summary import get_profile_summary
from profiles.tasks import calculate_risk_score_task

logger = logging.getLogger("profiles")


def _active_customer_query():
    """Return the operational customer-state filter used by staff profile reads."""

    return {
        "role": "customer",
        "verified": True,
        "active": True,
        "$or": [
            {"account_state": "active"},
            {"account_state": {"$exists": False}},
        ],
    }


def _record_required_officer_audit(
    request,
    officer,
    *,
    action,
    customer_id=None,
    details=None,
):
    """Persist the audit required before returning staff profile information."""

    try:
        AuditLog.log_action(
            action=action,
            user_id=officer.id,
            user_type="loan_officer",
            user_email=officer.email,
            description=(
                "Loan officer accessed a customer profile"
                if customer_id
                else "Loan officer accessed the scoped customer profile directory"
            ),
            resource_type="customer_profile",
            resource_id=customer_id,
            details=details or {},
            ip_address=get_client_ip(request),
        )
        return True
    except Exception:
        logger.exception("Required officer profile-access audit failed")
        return False


def _audit_unavailable_response():
    return error_response(
        message="Unable to record required profile access audit",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class CustomerProfileAccessMixin(AccessControlMixin):
    """Restrict profile endpoints to customer accounts."""

    def check_customer_permission(self, request):
        return self.require_customer(request)


class CustomerProfileView(CustomerProfileAccessMixin, APIView):
    """
    API view for managing customer personal profile.

    GET /api/profile/ - Get profile
    PUT /api/profile/ - Update profile
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes = (ProfileRateThrottle,)

    def get(self, request):
        """Get customer profile"""
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            user = request.user
            customer_id = user.customer_id

            profile = CustomerProfile.get_or_create(customer_id)

            return success_response(
                data={
                    "id": profile.id,
                    "customer_id": (
                        str(profile.customer_id) if profile.customer_id else ""
                    ),
                    "date_of_birth": (
                        profile.date_of_birth.isoformat()
                        if profile.date_of_birth
                        else None
                    ),
                    "gender": profile.gender,
                    "civil_status": profile.civil_status,
                    "nationality": profile.nationality,
                    "mobile_number": profile.mobile_number,
                    "address_line1": profile.address_line1,
                    "address_line2": profile.address_line2,
                    "barangay": profile.barangay,
                    "city_municipality": profile.city_municipality,
                    "province": profile.province,
                    "zip_code": profile.zip_code,
                    "emergency_contact_name": profile.emergency_contact_name,
                    "emergency_contact_phone": profile.emergency_contact_phone,
                    "emergency_contact_relationship": profile.emergency_contact_relationship,
                    "wallet_address": profile.wallet_address,
                    "profile_completed": profile.profile_completed,
                    "completion_percentage": profile.completion_percentage,
                },
                message="Profile retrieved successfully",
            )
        except Exception:
            logger.exception("Error retrieving profile")
            return error_response(
                message="Failed to retrieve profile",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request):
        """Update customer profile"""
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            serializer = CustomerProfileSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid profile data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            user = request.user
            customer_id = user.customer_id

            profile = CustomerProfile.get_or_create(customer_id)

            # Update fields
            data = serializer.validated_data
            for field, value in data.items():
                if hasattr(profile, field):
                    setattr(profile, field, value)

            profile.save()

            logger.info(f"Profile updated for customer {customer_id}")

            # Audit log
            AuditLog.log_action(
                action="profile_updated",
                user_id=customer_id,
                user_type="customer",
                description="Personal profile updated",
                resource_type="profile",
                resource_id=profile.id,
                details={"completion": profile.completion_percentage},
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            return success_response(
                data={
                    "profile_completed": profile.profile_completed,
                    "completion_percentage": profile.completion_percentage,
                },
                message="Profile updated successfully",
            )
        except Exception:
            logger.exception("Error updating profile")
            return error_response(
                message="Failed to update profile",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class BusinessProfileView(CustomerProfileAccessMixin, APIView):
    """
    API view for managing business/MSME profile.

    GET /api/profile/business/ - Get business profile
    PUT /api/profile/business/ - Update business profile
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes = (ProfileRateThrottle,)

    def get(self, request):
        """Get business profile"""
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            user = request.user
            customer_id = user.customer_id

            profile = BusinessProfile.get_or_create(customer_id)

            return success_response(
                data={
                    "id": profile.id,
                    "customer_id": (
                        str(profile.customer_id) if profile.customer_id else ""
                    ),
                    "business_name": profile.business_name,
                    "business_type": profile.business_type,
                    "business_type_other": profile.business_type_other,
                    "business_description": profile.business_description,
                    "business_address": profile.business_address,
                    "business_barangay": profile.business_barangay,
                    "business_city": profile.business_city,
                    "business_province": profile.business_province,
                    "business_age_months": profile.business_age_months,
                    "is_registered": profile.is_registered,
                    "registration_type": profile.registration_type,
                    "registration_number": profile.registration_number,
                    "estimated_monthly_income": profile.estimated_monthly_income,
                    "income_range": profile.income_range,
                    "estimated_monthly_expenses": profile.estimated_monthly_expenses,
                    "number_of_employees": profile.number_of_employees,
                },
                message="Business profile retrieved successfully",
            )
        except Exception:
            logger.exception("Error retrieving business profile")
            return error_response(
                message="Failed to retrieve business profile",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request):
        """Update business profile"""
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            serializer = BusinessProfileSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid business profile data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            user = request.user
            customer_id = user.customer_id

            profile = BusinessProfile.get_or_create(customer_id)

            data = serializer.validated_data
            for field, value in data.items():
                if hasattr(profile, field):
                    setattr(profile, field, value)

            profile.save()

            logger.info(f"Business profile updated for customer {customer_id}")

            # Audit log
            AuditLog.log_action(
                action="profile_updated",
                user_id=customer_id,
                user_type="customer",
                description="Business profile updated",
                resource_type="business_profile",
                resource_id=profile.id,
                details={"business_name": profile.business_name},
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            return success_response(message="Business profile updated successfully")
        except Exception:
            logger.exception("Error updating business profile")
            return error_response(
                message="Failed to update business profile",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AlternativeDataView(CustomerProfileAccessMixin, APIView):
    """
    API view for managing alternative credit data.

    GET /api/profile/alternative-data/ - Get alternative data
    PUT /api/profile/alternative-data/ - Update alternative data
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes = (ProfileRateThrottle,)

    def get(self, request):
        """Get alternative credit data"""
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            user = request.user
            customer_id = user.customer_id

            data = AlternativeData.get_or_create(customer_id)

            return success_response(
                data={
                    "id": data.id,
                    "customer_id": str(data.customer_id) if data.customer_id else "",
                    # Education & Employment
                    "education_level": data.education_level,
                    "employment_status": data.employment_status,
                    "years_of_experience": data.years_of_experience,
                    # Housing
                    "housing_status": data.housing_status,
                    "years_at_current_address": data.years_at_current_address,
                    "monthly_rent": data.monthly_rent,
                    # Dependents
                    "number_of_dependents": data.number_of_dependents,
                    "household_income": data.household_income,
                    # Existing Credit
                    "has_existing_loans": data.has_existing_loans,
                    "existing_loan_amount": data.existing_loan_amount,
                    "existing_loan_source": data.existing_loan_source,
                    "loan_payment_history": data.loan_payment_history,
                    # Digital Footprint
                    "has_bank_account": data.has_bank_account,
                    "bank_account_duration": data.bank_account_duration,
                    "has_ewallet": data.has_ewallet,
                    "ewallet_usage": data.ewallet_usage,
                    # Utility
                    "pays_utilities": data.pays_utilities,
                    "utility_payment_history": data.utility_payment_history,
                    # Social Capital
                    "is_coop_member": data.is_coop_member,
                    "community_involvement": data.community_involvement,
                    # Risk Score (if calculated)
                    "risk_score": data.risk_score,
                    "risk_category": data.risk_category,
                    "score_calculated_at": (
                        data.score_calculated_at.isoformat()
                        if data.score_calculated_at
                        else None
                    ),
                },
                message="Alternative data retrieved successfully",
            )
        except Exception:
            logger.exception("Error retrieving alternative data")
            return error_response(
                message="Failed to retrieve alternative data",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request):
        """Update alternative credit data"""
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            serializer = AlternativeDataSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid alternative data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            user = request.user
            customer_id = user.customer_id

            alt_data = AlternativeData.get_or_create(customer_id)

            data = serializer.validated_data
            for field, value in data.items():
                if hasattr(alt_data, field):
                    setattr(alt_data, field, value)

            alt_data.save()

            try:
                calculate_risk_score_task.delay(customer_id)
            except (RuntimeError, ImportError):
                logger.debug("Risk score task skipped: Celery broker unavailable")

            logger.info(f"Alternative data updated for customer {customer_id}")

            # Audit log
            AuditLog.log_action(
                action="profile_updated",
                user_id=customer_id,
                user_type="customer",
                description="Alternative data updated",
                resource_type="alternative_data",
                resource_id=alt_data.id,
                details={"risk_score": alt_data.risk_score},
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            return success_response(message="Alternative data updated successfully")
        except Exception:
            logger.exception("Error updating alternative data")
            return error_response(
                message="Failed to update alternative data",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProfileSummaryView(CustomerProfileAccessMixin, APIView):
    """
    API view for getting a summary of all profile data.

    GET /api/profile/summary/ - Get complete profile summary
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes = (ProfileRateThrottle,)

    def get(self, request):
        """Get complete profile summary including completion status"""
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            customer_id = request.user.customer_id
            summary = get_profile_summary(customer_id)

            return success_response(
                data=summary,
                message="Profile summary retrieved successfully",
            )
        except Exception:
            logger.exception("Error retrieving profile summary")
            return error_response(
                message="Failed to retrieve profile summary",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class NotificationPreferencesView(CustomerProfileAccessMixin, APIView):
    """
    Manage notification preferences.

    GET /api/profile/notifications/
    PUT /api/profile/notifications/
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes = (ProfileRateThrottle,)

    def get(self, request):
        """Get notification preferences"""
        from accounts.services import AuthService

        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer = AuthService.get_customer_by_id(user.customer_id)

        if not customer:
            return error_response(
                message="Customer not found", status_code=status.HTTP_404_NOT_FOUND
            )

        prefs = get_preferences(customer)

        return success_response(
            data={"preferences": prefs}, message="Notification preferences retrieved"
        )

    def put(self, request):
        """Update notification preferences"""
        from accounts.services import AuthService

        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer = AuthService.get_customer_by_id(user.customer_id)

        if not customer:
            return error_response(
                message="Customer not found", status_code=status.HTTP_404_NOT_FOUND
            )

        prefs = request.data.get("preferences", {})
        if not isinstance(prefs, dict):
            return error_response(
                message="preferences must be an object",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            updated = update_preferences(customer, prefs)
        except UnknownPreferenceKeysError as exc:
            return error_response(
                message="Unknown notification preference keys",
                errors={
                    "preferences": f"Unsupported keys: {', '.join(sorted(exc.unknown_keys))}"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except ValueError as exc:
            return error_response(
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        return success_response(
            data={"preferences": updated},
            message="Notification preferences updated",
        )


class OfficerCustomerProfilesListView(AccessControlMixin, APIView):
    """Searchable, read-only customer directory for loan officers."""

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes = (ProfileRateThrottle,)

    def get(self, request):
        has_permission, officer = self.require_roles(request, {"loan_officer"})
        if not has_permission:
            return officer

        has_scope, scoped_customer_ids = self.get_officer_scoped_customer_ids(request)
        if not has_scope:
            return scoped_customer_ids

        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 20))
        except (TypeError, ValueError):
            return error_response(
                message="Invalid pagination parameters",
                errors={"page": "page and page_size must be integers"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if page < 1 or page_size < 1 or page_size > 100:
            return error_response(
                message="Invalid pagination parameters",
                errors={
                    "page": "page must be at least 1",
                    "page_size": "page_size must be between 1 and 100",
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        customer_id_variants = []
        for customer_id in scoped_customer_ids:
            customer_id_variants.extend(self._id_variants(customer_id))

        search = request.query_params.get("search", "").strip()
        query = {
            "$and": [
                _active_customer_query(),
                {"_id": {"$in": customer_id_variants}},
            ]
        }
        if search:
            search_regex = re.compile(re.escape(search), re.IGNORECASE)
            search_conditions = [
                {"first_name": search_regex},
                {"last_name": search_regex},
                {"email": search_regex},
            ]
            try:
                search_conditions.append({"_id": ObjectId(search)})
            except InvalidId:
                pass
            query["$and"].append({"$or": search_conditions})

        collection = settings.MONGODB[Customer.collection_name]
        total = collection.count_documents(query)
        skip = (page - 1) * page_size
        customers = Customer.find(
            query,
            sort=[("created_at", -1)],
            skip=skip,
            limit=page_size,
        )
        customer_items = []
        for customer in customers:
            if not customer:
                continue
            customer_items.append(
                {
                    "customer_id": customer.id,
                    "full_name": customer.full_name or "Unnamed customer",
                    "email": customer.email,
                }
            )

        if not _record_required_officer_audit(
            request,
            officer,
            action="profile_directory_viewed",
            details={
                "search_applied": bool(search),
                "page": page,
                "page_size": page_size,
                "result_count": len(customer_items),
            },
        ):
            return _audit_unavailable_response()

        return success_response(
            data={
                "customers": customer_items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": math.ceil(total / page_size) if total else 0,
            },
            message="Customer profiles retrieved successfully",
        )


class OfficerProfileView(AccessControlMixin, APIView):
    """
    Read-only profile access for loan officers.

    GET /api/officer/profiles/<customer_id>/
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes = (ProfileRateThrottle,)

    def get(self, request, customer_id):
        """Return the allow-listed profile fields for the requested customer."""
        has_permission, officer = self.require_roles(request, {"loan_officer"})
        if not has_permission:
            return officer

        try:
            customer_object_id = ObjectId(customer_id)
        except (InvalidId, TypeError):
            return error_response(
                message="Invalid customer ID",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        has_scope, scope_result = self.require_customer_scope_for_officer(
            request,
            customer_id,
            conceal_existence=True,
        )
        if not has_scope:
            if not _record_required_officer_audit(
                request,
                officer,
                action="profile_access_denied",
                customer_id=customer_id,
                details={"reason": "outside_officer_scope"},
            ):
                return _audit_unavailable_response()
            return scope_result

        customer_query = _active_customer_query()
        customer_query["_id"] = customer_object_id
        customer = Customer.find_one(customer_query)
        if not customer:
            if not _record_required_officer_audit(
                request,
                officer,
                action="profile_access_denied",
                customer_id=customer_id,
                details={"reason": "customer_unavailable"},
            ):
                return _audit_unavailable_response()
            return error_response(
                message="Customer not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not _record_required_officer_audit(
            request,
            officer,
            action="profile_sensitive_read",
            customer_id=customer_id,
            details={"scope_enforced": True},
        ):
            return _audit_unavailable_response()

        return success_response(
            data=build_officer_customer_profile(customer),
            message="Customer profile retrieved successfully",
        )
