from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import parse_bool
from profiles.models import CustomerProfile, BusinessProfile, AlternativeData
from profiles.serializers import (
    CustomerProfileSerializer,
    BusinessProfileSerializer,
    AlternativeDataSerializer
)
from analytics.models import AuditLog
import logging

logger = logging.getLogger('profiles')


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
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
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
                    'id': profile.id,
                    'customer_id': str(profile.customer_id) if profile.customer_id else '',
                    'date_of_birth': profile.date_of_birth.isoformat() if profile.date_of_birth else None,
                    'gender': profile.gender,
                    'civil_status': profile.civil_status,
                    'nationality': profile.nationality,
                    'mobile_number': profile.mobile_number,
                    'address_line1': profile.address_line1,
                    'address_line2': profile.address_line2,
                    'barangay': profile.barangay,
                    'city_municipality': profile.city_municipality,
                    'province': profile.province,
                    'zip_code': profile.zip_code,
                    'emergency_contact_name': profile.emergency_contact_name,
                    'emergency_contact_phone': profile.emergency_contact_phone,
                    'emergency_contact_relationship': profile.emergency_contact_relationship,
                    'profile_completed': profile.profile_completed,
                    'completion_percentage': profile.completion_percentage
                },
                message="Profile retrieved successfully"
            )
        except Exception as e:
            logger.error(f"Error retrieving profile: {str(e)}")
            return error_response(
                message="Failed to retrieve profile",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
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
                    status_code=status.HTTP_400_BAD_REQUEST
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
                action='profile_updated',
                user_id=customer_id,
                user_type='customer',
                description='Personal profile updated',
                resource_type='profile',
                resource_id=profile.id,
                details={'completion': profile.completion_percentage},
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            return success_response(
                data={
                    'profile_completed': profile.profile_completed,
                    'completion_percentage': profile.completion_percentage
                },
                message="Profile updated successfully"
            )
        except Exception as e:
            logger.error(f"Error updating profile: {str(e)}")
            return error_response(
                message="Failed to update profile",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BusinessProfileView(CustomerProfileAccessMixin, APIView):
    """
    API view for managing business/MSME profile.
    
    GET /api/profile/business/ - Get business profile
    PUT /api/profile/business/ - Update business profile
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
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
                    'id': profile.id,
                    'customer_id': str(profile.customer_id) if profile.customer_id else '',
                    'business_name': profile.business_name,
                    'business_type': profile.business_type,
                    'business_type_other': profile.business_type_other,
                    'business_description': profile.business_description,
                    'business_address': profile.business_address,
                    'business_barangay': profile.business_barangay,
                    'business_city': profile.business_city,
                    'business_province': profile.business_province,
                    'business_age_months': profile.business_age_months,
                    'is_registered': profile.is_registered,
                    'registration_type': profile.registration_type,
                    'registration_number': profile.registration_number,
                    'estimated_monthly_income': profile.estimated_monthly_income,
                    'income_range': profile.income_range,
                    'estimated_monthly_expenses': profile.estimated_monthly_expenses,
                    'number_of_employees': profile.number_of_employees
                },
                message="Business profile retrieved successfully"
            )
        except Exception as e:
            logger.error(f"Error retrieving business profile: {str(e)}")
            return error_response(
                message="Failed to retrieve business profile",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
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
                    status_code=status.HTTP_400_BAD_REQUEST
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
                action='profile_updated',
                user_id=customer_id,
                user_type='customer',
                description='Business profile updated',
                resource_type='business_profile',
                resource_id=profile.id,
                details={'business_name': profile.business_name},
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            return success_response(
                message="Business profile updated successfully"
            )
        except Exception as e:
            logger.error(f"Error updating business profile: {str(e)}")
            return error_response(
                message="Failed to update business profile",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AlternativeDataView(CustomerProfileAccessMixin, APIView):
    """
    API view for managing alternative credit data.
    
    GET /api/profile/alternative-data/ - Get alternative data
    PUT /api/profile/alternative-data/ - Update alternative data
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
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
                    'id': data.id,
                    'customer_id': str(data.customer_id) if data.customer_id else '',
                    # Education & Employment
                    'education_level': data.education_level,
                    'employment_status': data.employment_status,
                    'years_of_experience': data.years_of_experience,
                    # Housing
                    'housing_status': data.housing_status,
                    'years_at_current_address': data.years_at_current_address,
                    'monthly_rent': data.monthly_rent,
                    # Dependents
                    'number_of_dependents': data.number_of_dependents,
                    'household_income': data.household_income,
                    # Existing Credit
                    'has_existing_loans': data.has_existing_loans,
                    'existing_loan_amount': data.existing_loan_amount,
                    'existing_loan_source': data.existing_loan_source,
                    'loan_payment_history': data.loan_payment_history,
                    # Digital Footprint
                    'has_bank_account': data.has_bank_account,
                    'bank_account_duration': data.bank_account_duration,
                    'has_ewallet': data.has_ewallet,
                    'ewallet_usage': data.ewallet_usage,
                    # Utility
                    'pays_utilities': data.pays_utilities,
                    'utility_payment_history': data.utility_payment_history,
                    # Social Capital
                    'is_coop_member': data.is_coop_member,
                    'community_involvement': data.community_involvement,
                    # Risk Score (if calculated)
                    'risk_score': data.risk_score,
                    'risk_category': data.risk_category,
                    'score_calculated_at': data.score_calculated_at.isoformat() if data.score_calculated_at else None
                },
                message="Alternative data retrieved successfully"
            )
        except Exception as e:
            logger.error(f"Error retrieving alternative data: {str(e)}")
            return error_response(
                message="Failed to retrieve alternative data",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
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
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            user = request.user
            customer_id = user.customer_id
            
            alt_data = AlternativeData.get_or_create(customer_id)
            
            data = serializer.validated_data
            for field, value in data.items():
                if hasattr(alt_data, field):
                    setattr(alt_data, field, value)
            
            alt_data.save()
            
            logger.info(f"Alternative data updated for customer {customer_id}")
            
            # Audit log
            AuditLog.log_action(
                action='profile_updated',
                user_id=customer_id,
                user_type='customer',
                description='Alternative data updated',
                resource_type='alternative_data',
                resource_id=alt_data.id,
                details={'risk_score': alt_data.risk_score},
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            return success_response(
                message="Alternative data updated successfully"
            )
        except Exception as e:
            logger.error(f"Error updating alternative data: {str(e)}")
            return error_response(
                message="Failed to update alternative data",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProfileSummaryView(CustomerProfileAccessMixin, APIView):
    """
    API view for getting a summary of all profile data.
    
    GET /api/profile/summary/ - Get complete profile summary
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get complete profile summary including completion status"""
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            user = request.user
            customer_id = user.customer_id
            
            # Get all profiles
            personal = CustomerProfile.get_or_create(customer_id)
            business = BusinessProfile.get_or_create(customer_id)
            alternative = AlternativeData.get_or_create(customer_id)
            
            # Get documents
            from documents.models import Document
            documents = Document.find_by_customer(customer_id)
            
            # Calculate profile completion
            personal_complete = personal.profile_completed
            business_complete = bool(business.business_type and business.income_range)
            alternative_complete = bool(alternative.education_level and alternative.housing_status)
            
            # Calculate document status
            total_docs = len(documents)
            approved_docs = len([d for d in documents if d.status == 'approved'])
            pending_docs = len([
                d for d in documents if d.status in ['pending', 'needs_review']
            ])
            rejected_docs = len([d for d in documents if d.status == 'rejected'])
            reupload_requested_docs = len([d for d in documents if d.reupload_requested])
            
            # Determine if all uploaded documents are approved
            documents_ready = total_docs > 0 and approved_docs == total_docs
            
            # Calculate overall readiness
            profiles_complete = personal_complete and business_complete and alternative_complete
            
            # Documents section is tracked separately (optional for profile completion)
            documents_complete = total_docs > 0 and approved_docs > 0
            
            # Profile completion is based on 3 required sections only.
            sections_complete = sum([personal_complete, business_complete, alternative_complete])
            overall_percentage = int((sections_complete / 3) * 100)
            
            # "Ready for loan" at profile stage means core profile is complete.
            # Product-specific documents are enforced later during loan application.
            ready_for_loan = profiles_complete
            
            return success_response(
                data={
                    'customer_id': customer_id,
                    'personal_profile': {
                        'completed': personal_complete,
                        'completion_percentage': personal.completion_percentage
                    },
                    'business_profile': {
                        'completed': business_complete,
                        'has_business_type': bool(business.business_type),
                        'has_income_info': bool(business.income_range or business.estimated_monthly_income)
                    },
                    'alternative_data': {
                        'completed': alternative_complete,
                        'has_risk_score': bool(alternative.risk_score),
                        'risk_category': alternative.risk_category
                    },
                    'documents': {
                        'total': total_docs,
                        'approved': approved_docs,
                        'pending': pending_docs,
                        'rejected': rejected_docs,
                        'reupload_requested': reupload_requested_docs,
                        'all_approved': documents_ready,
                        'has_documents': total_docs > 0
                    },
                    'overall': {
                        'profiles_complete': profiles_complete,
                        'sections_complete': sections_complete,
                        'total_sections': 3,
                        'documents_complete': documents_complete,
                        'documents_verified': documents_ready,
                        'ready_for_loan': ready_for_loan,
                        'completion_percentage': overall_percentage,
                        'completed_section_names': self._get_completed_section_names(
                            personal_complete, business_complete, alternative_complete, documents_complete
                        ),
                        'missing': [] if ready_for_loan else self._get_missing_items(
                            personal_complete, business_complete, alternative_complete
                        )
                    }
                },
                message="Profile summary retrieved successfully"
            )
        except Exception as e:
            logger.error(f"Error retrieving profile summary: {str(e)}")
            return error_response(
                message="Failed to retrieve profile summary",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _get_missing_items(self, personal_complete, business_complete, alternative_complete):
        """Helper to generate list of missing requirements"""
        missing = []
        if not personal_complete:
            missing.append('Complete personal profile')
        if not business_complete:
            missing.append('Complete business profile')
        if not alternative_complete:
            missing.append('Complete alternative data')
        return missing
    
    def _get_completed_section_names(self, personal_complete, business_complete, alternative_complete, documents_complete):
        """Helper to generate list of completed section names"""
        completed = []
        if personal_complete:
            completed.append('Personal Information')
        if business_complete:
            completed.append('Business Information')
        if alternative_complete:
            completed.append('Alternative Data')
        if documents_complete:
            completed.append('Documents')
        return completed



class NotificationPreferencesView(CustomerProfileAccessMixin, APIView):
    """
    Manage notification preferences.
    
    GET /api/profile/notifications/
    PUT /api/profile/notifications/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
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
                message="Customer not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        prefs = getattr(customer, 'notification_preferences', {
            'email_loan_updates': True,
            'email_payment_reminders': True,
            'email_promotions': False
        })
        
        return success_response(
            data={'preferences': prefs},
            message="Notification preferences retrieved"
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
                message="Customer not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # Get preferences from request
        prefs = request.data.get('preferences', {})
        if not isinstance(prefs, dict):
            return error_response(
                message="preferences must be an object",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate and update
        valid_keys = ['email_loan_updates', 'email_payment_reminders', 'email_promotions']
        unknown_keys = [key for key in prefs.keys() if key not in valid_keys]
        if unknown_keys:
            return error_response(
                message="Unknown notification preference keys",
                errors={'preferences': f"Unsupported keys: {', '.join(sorted(unknown_keys))}"},
                status_code=status.HTTP_400_BAD_REQUEST
            )

        current_prefs = getattr(customer, 'notification_preferences', {})
        
        for key in valid_keys:
            if key in prefs:
                is_valid, parsed_value, parse_error = parse_bool(prefs[key], f"preferences.{key}")
                if not is_valid:
                    return error_response(
                        message="Invalid notification preference value",
                        errors={key: parse_error},
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                current_prefs[key] = parsed_value
        
        customer.notification_preferences = current_prefs
        customer.save()
        
        logger.info(f"Notification preferences updated for {user.customer_id}")
        
        return success_response(
            data={'preferences': current_prefs},
            message="Notification preferences updated"
        )
