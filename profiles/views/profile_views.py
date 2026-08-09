import logging
import math
import re
from datetime import datetime
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
from profiles.models import (
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
    ProfileRevisionConflict,
)
from profiles.serializers import (
    AlternativeDataSerializer,
    BusinessProfileSerializer,
    CustomerProfileSerializer,
    NotificationPreferencesUpdateSerializer,
)
from profiles.services.notification_preferences import (
    get_preferences,
    update_preferences,
)
from profiles.services.officer_profile import build_officer_customer_profile
from profiles.services.summary import get_profile_summary
from profiles.tasks import enqueue_risk_score_calculation

logger = logging.getLogger("profiles")


def _date_only_iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat()


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


def _record_profile_mutation_audit(
    request,
    *,
    customer_id,
    action,
    description,
    resource_type,
    resource_id=None,
    details=None,
):
    """Record a customer mutation without changing an already-durable result."""

    try:
        AuditLog.log_action(
            action=action,
            user_id=customer_id,
            user_type="customer",
            user_email=getattr(request.user, "email", ""),
            description=description,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=get_client_ip(request),
        )
        return True
    except Exception:
        logger.exception(
            "Profile mutation audit failed after durable %s mutation for customer %s",
            resource_type,
            customer_id,
        )
        return False


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

            profile = CustomerProfile.find_by_customer(customer_id) or CustomerProfile(
                customer_id=str(customer_id)
            )
            profile.calculate_completion()

            return success_response(
                data={
                    "id": profile.id,
                    "customer_id": (
                        str(profile.customer_id) if profile.customer_id else ""
                    ),
                    "date_of_birth": _date_only_iso(profile.date_of_birth),
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
                    "profile_revision": profile.profile_revision,
                    "profile_completion_policy_version": (
                        profile.profile_completion_policy_version
                    ),
                    "profile_missing_fields": profile.profile_missing_fields,
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

            user = request.user
            customer_id = user.customer_id
            profile = CustomerProfile.find_by_customer(customer_id) or CustomerProfile(
                customer_id=str(customer_id)
            )
            serializer = CustomerProfileSerializer(
                instance=profile,
                data=request.data,
                partial=True,
            )
            if not serializer.is_valid():
                return error_response(
                    message="Invalid profile data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            created = not profile._id
            if created:
                profile = CustomerProfile.get_or_create(customer_id)

            # Update fields
            data = dict(serializer.validated_data)
            expected_revision = data.pop("profile_revision", None)
            profile = profile.update_fields(data, expected_revision)

            logger.info(f"Profile updated for customer {customer_id}")

            _record_profile_mutation_audit(
                request,
                customer_id=customer_id,
                action="profile_created" if created else "profile_updated",
                description=(
                    "Personal profile created" if created else "Personal profile updated"
                ),
                resource_type="customer_profile",
                resource_id=profile.id,
                details={
                    "profile_revision": profile.profile_revision,
                    "profile_completed": profile.profile_completed,
                },
            )

            return success_response(
                data={
                    "profile_completed": profile.profile_completed,
                    "completion_percentage": profile.completion_percentage,
                    "profile_revision": profile.profile_revision,
                    "profile_completion_policy_version": (
                        profile.profile_completion_policy_version
                    ),
                    "profile_missing_fields": profile.profile_missing_fields,
                },
                message="Profile updated successfully",
            )
        except ProfileRevisionConflict as exc:
            return error_response(
                message=str(exc),
                status_code=status.HTTP_409_CONFLICT,
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

            profile = BusinessProfile.find_by_customer(customer_id) or BusinessProfile(
                customer_id=str(customer_id)
            )
            profile.calculate_completion()

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
                    "profile_revision": profile.profile_revision,
                    "profile_completed": profile.profile_completed,
                    "completion_percentage": profile.completion_percentage,
                    "profile_completion_policy_version": (
                        profile.profile_completion_policy_version
                    ),
                    "profile_missing_fields": profile.profile_missing_fields,
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

            user = request.user
            customer_id = user.customer_id
            profile = BusinessProfile.find_by_customer(customer_id) or BusinessProfile(
                customer_id=str(customer_id)
            )
            serializer = BusinessProfileSerializer(
                instance=profile,
                data=request.data,
                partial=True,
            )
            if not serializer.is_valid():
                return error_response(
                    message="Invalid business profile data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            created = not profile._id
            if created:
                profile = BusinessProfile.get_or_create(customer_id)

            data = dict(serializer.validated_data)
            expected_revision = data.pop("profile_revision", None)
            profile = profile.update_fields(data, expected_revision)

            logger.info(f"Business profile updated for customer {customer_id}")

            _record_profile_mutation_audit(
                request,
                customer_id=customer_id,
                action="profile_created" if created else "profile_updated",
                description=(
                    "Business profile created" if created else "Business profile updated"
                ),
                resource_type="business_profile",
                resource_id=profile.id,
                details={
                    "profile_revision": profile.profile_revision,
                    "profile_completed": profile.profile_completed,
                },
            )

            return success_response(
                data={
                    "profile_revision": profile.profile_revision,
                    "profile_completed": profile.profile_completed,
                    "completion_percentage": profile.completion_percentage,
                    "profile_completion_policy_version": (
                        profile.profile_completion_policy_version
                    ),
                    "profile_missing_fields": profile.profile_missing_fields,
                },
                message="Business profile updated successfully",
            )
        except ProfileRevisionConflict as exc:
            return error_response(
                message=str(exc),
                status_code=status.HTTP_409_CONFLICT,
            )
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

            data = AlternativeData.find_by_customer(customer_id) or AlternativeData(
                customer_id=str(customer_id)
            )
            data.calculate_completion()

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
                    "risk_score_status": data.risk_score_status,
                    "risk_score_policy_version": data.risk_score_policy_version,
                    "risk_score_use": data.risk_score_use,
                    "risk_score_manual_review_required": (
                        data.risk_score_manual_review_required
                    ),
                    "risk_input_revision": data.risk_input_revision,
                    "risk_calculated_revision": data.risk_calculated_revision,
                    "risk_score_breakdown": data.risk_score_breakdown,
                    "risk_score_reason_codes": data.risk_score_reason_codes,
                    "risk_score_error_code": data.risk_score_error_code,
                    "risk_score_requested_at": (
                        data.risk_score_requested_at.isoformat()
                        if data.risk_score_requested_at
                        else None
                    ),
                    "risk_score_failed_at": (
                        data.risk_score_failed_at.isoformat()
                        if data.risk_score_failed_at
                        else None
                    ),
                    "profile_revision": data.profile_revision,
                    "profile_completed": data.profile_completed,
                    "completion_percentage": data.completion_percentage,
                    "profile_completion_policy_version": (
                        data.profile_completion_policy_version
                    ),
                    "profile_missing_fields": data.profile_missing_fields,
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

            user = request.user
            customer_id = user.customer_id
            alt_data = AlternativeData.find_by_customer(customer_id) or AlternativeData(
                customer_id=str(customer_id)
            )
            serializer = AlternativeDataSerializer(
                instance=alt_data,
                data=request.data,
                partial=True,
            )
            if not serializer.is_valid():
                return error_response(
                    message="Invalid alternative data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            created = not alt_data._id
            if created:
                alt_data = AlternativeData.get_or_create(customer_id)
            data = dict(serializer.validated_data)
            expected_revision = data.pop("profile_revision", None)
            alt_data = alt_data.update_inputs(data, expected_revision)
            enqueue_risk_score_calculation(
                customer_id,
                alt_data.risk_input_revision,
            )
            alt_data = AlternativeData.find_by_customer(customer_id)

            logger.info(f"Alternative data updated for customer {customer_id}")

            _record_profile_mutation_audit(
                request,
                customer_id=customer_id,
                action="profile_created" if created else "profile_updated",
                description=(
                    "Alternative data created" if created else "Alternative data updated"
                ),
                resource_type="alternative_data",
                resource_id=alt_data.id,
                details={
                    "risk_input_revision": alt_data.risk_input_revision,
                    "risk_score_status": alt_data.risk_score_status,
                    "profile_revision": alt_data.profile_revision,
                    "profile_completed": alt_data.profile_completed,
                    "completion_percentage": alt_data.completion_percentage,
                    "profile_completion_policy_version": (
                        alt_data.profile_completion_policy_version
                    ),
                    "profile_missing_fields": alt_data.profile_missing_fields,
                },
            )

            return success_response(
                data={
                    "risk_score_status": alt_data.risk_score_status,
                    "risk_input_revision": alt_data.risk_input_revision,
                    "profile_revision": alt_data.profile_revision,
                    "profile_completed": alt_data.profile_completed,
                    "completion_percentage": alt_data.completion_percentage,
                    "profile_completion_policy_version": (
                        alt_data.profile_completion_policy_version
                    ),
                    "profile_missing_fields": alt_data.profile_missing_fields,
                },
                message="Alternative data updated successfully",
            )
        except ProfileRevisionConflict as exc:
            return error_response(
                message=str(exc),
                status_code=status.HTTP_409_CONFLICT,
            )
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

        serializer = NotificationPreferencesUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid notification preferences",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            updated = update_preferences(
                customer,
                serializer.validated_data["preferences"],
            )
        except (TypeError, ValueError) as exc:
            return error_response(
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        _record_profile_mutation_audit(
            request,
            customer_id=user.customer_id,
            action="notification_preferences_updated",
            description="Notification preferences updated",
            resource_type="notification_preferences",
            resource_id=customer.id,
            details={
                "changed_keys": sorted(serializer.validated_data["preferences"]),
            },
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
