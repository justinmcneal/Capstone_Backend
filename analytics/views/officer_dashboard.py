"""
Loan Officer Dashboard - Review activity and queue stats.
"""
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from datetime import datetime, timedelta

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from django.conf import settings
import logging

logger = logging.getLogger('analytics')


class LoanOfficerRequiredMixin:
    """Mixin to require loan officer role"""
    
    def check_officer_permission(self, request):
        user = request.user
        if not hasattr(user, 'role') or user.role not in ['loan_officer', 'admin']:
            return False, error_response(
                message="Loan officer access required",
                status_code=status.HTTP_403_FORBIDDEN
            )
        return True, user


class OfficerDashboardView(LoanOfficerRequiredMixin, APIView):
    """
    Loan officer dashboard - their review activity.
    
    GET /api/analytics/officer/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result
        
        user = result
        officer_id = user.customer_id
        db = settings.MONGODB
        
        # Today's date range
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        # My reviews - applications I've reviewed
        my_approved = db['loan_applications'].count_documents({
            'assigned_officer': str(officer_id),
            'status': {'$in': ['approved', 'disbursed']}
        })
        my_rejected = db['loan_applications'].count_documents({
            'assigned_officer': str(officer_id),
            'status': 'rejected'
        })
        
        # Reviews today
        approved_today = db['loan_applications'].count_documents({
            'assigned_officer': str(officer_id),
            'status': {'$in': ['approved', 'disbursed']},
            'decision_date': {'$gte': today}
        })
        rejected_today = db['loan_applications'].count_documents({
            'assigned_officer': str(officer_id),
            'status': 'rejected',
            'decision_date': {'$gte': today}
        })
        
        # Pending queue - all applications waiting for any officer
        pending_queue = db['loan_applications'].count_documents({
            'status': {'$in': ['submitted', 'under_review']}
        })
        
        # Assigned to me
        my_queue = db['loan_applications'].count_documents({
            'assigned_officer': str(officer_id),
            'status': 'under_review'
        })
        
        # Approval rate
        total_reviewed = my_approved + my_rejected
        approval_rate = (my_approved / total_reviewed * 100) if total_reviewed > 0 else 0
        
        return success_response(
            data={
                'my_reviews': {
                    'total_approved': my_approved,
                    'total_rejected': my_rejected,
                    'approved_today': approved_today,
                    'rejected_today': rejected_today
                },
                'queue': {
                    'pending_total': pending_queue,
                    'assigned_to_me': my_queue
                },
                'performance': {
                    'total_reviewed': total_reviewed,
                    'approval_rate': f"{approval_rate:.1f}%"
                }
            },
            message="Officer dashboard data retrieved"
        )
