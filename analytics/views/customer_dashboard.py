"""
Customer Dashboard - Personal stats for customers.
"""
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from django.conf import settings
import logging

logger = logging.getLogger('analytics')


class CustomerDashboardView(APIView):
    """
    Customer dashboard - personal statistics.
    
    GET /api/analytics/customer/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        customer_id = user.customer_id
        db = settings.MONGODB
        
        # My applications
        my_apps = {
            'total': db['loan_applications'].count_documents({'customer_id': str(customer_id)}),
            'pending': db['loan_applications'].count_documents({
                'customer_id': str(customer_id),
                'status': {'$in': ['submitted', 'under_review']}
            }),
            'approved': db['loan_applications'].count_documents({
                'customer_id': str(customer_id),
                'status': 'approved'
            }),
            'rejected': db['loan_applications'].count_documents({
                'customer_id': str(customer_id),
                'status': 'rejected'
            })
        }
        
        # My documents
        my_docs = {
            'total': db['documents'].count_documents({'customer_id': str(customer_id)}),
            'verified': db['documents'].count_documents({
                'customer_id': str(customer_id),
                'verified': True
            }),
            'pending': db['documents'].count_documents({
                'customer_id': str(customer_id),
                'status': 'pending'
            })
        }
        
        # Profile completion
        personal = db['customer_profiles'].find_one(
            {'customer_id': str(customer_id)},
            sort=[('updated_at', -1), ('created_at', -1)],
        )
        business = db['business_profiles'].find_one(
            {'customer_id': str(customer_id)},
            sort=[('updated_at', -1), ('created_at', -1)],
        )
        alternative = db['alternative_data'].find_one(
            {'customer_id': str(customer_id)},
            sort=[('updated_at', -1), ('created_at', -1)],
        )

        # Treat section as complete only when meaningful data exists,
        # not merely because an empty placeholder document exists.
        has_personal = bool((personal or {}).get('completion_percentage', 0) > 0)
        has_business = bool(
            (business or {}).get('business_type') and (
                (business or {}).get('income_range') or
                (business or {}).get('estimated_monthly_income')
            )
        )
        has_alternative = bool(
            (alternative or {}).get('education_level') and
            (alternative or {}).get('housing_status')
        )
        has_id = db['documents'].count_documents({
            'customer_id': str(customer_id),
            'document_type': 'valid_id'
        }) > 0
        
        profile_items = [has_personal, has_business, has_alternative, has_id]
        completion = (sum(profile_items) / len(profile_items)) * 100
        
        profile_completion = {
            'percentage': f"{completion:.0f}%",
            'personal_profile': has_personal,
            'business_profile': has_business,
            'alternative_data': has_alternative,
            'valid_id_uploaded': has_id
        }
        
        # AI interactions
        ai_sessions = db['ai_interactions'].count_documents({'customer_id': str(customer_id)})
        
        return success_response(
            data={
                'applications': my_apps,
                'documents': my_docs,
                'profile_completion': profile_completion,
                'ai_sessions': ai_sessions
            },
            message="Customer dashboard data retrieved"
        )
