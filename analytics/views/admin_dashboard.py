"""
Admin Dashboard - System-wide analytics for admins.
"""
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from datetime import datetime, timedelta

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.views.admin_views import AdminRequiredMixin
from analytics.models import AuditLog
import logging

logger = logging.getLogger('analytics')


class AdminDashboardView(AdminRequiredMixin, APIView):
    """
    Admin dashboard with system-wide statistics.
    
    GET /api/analytics/admin/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        from accounts.models import Customer, Admin, LoanOfficer
        from loans.models import LoanApplication, LoanProduct
        from documents.models import Document
        from django.conf import settings
        
        db = settings.MONGODB
        
        # User counts - use correct collection names from models
        total_customers = db['customer'].count_documents({})  # Customer model uses 'customer'
        total_officers = db['loan_officers'].count_documents({})
        total_admins = db['admins'].count_documents({})
        
        # Loan stats - include ALL statuses for complete visibility
        loan_stats = {
            'total': db['loan_applications'].count_documents({}),
            'draft': db['loan_applications'].count_documents({'status': 'draft'}),
            'pending': db['loan_applications'].count_documents({'status': 'submitted'}),
            'under_review': db['loan_applications'].count_documents({'status': 'under_review'}),
            'approved': db['loan_applications'].count_documents({'status': 'approved'}),
            'rejected': db['loan_applications'].count_documents({'status': 'rejected'}),
            'disbursed': db['loan_applications'].count_documents({'status': 'disbursed'}),
            'cancelled': db['loan_applications'].count_documents({'status': 'cancelled'}),
        }
        
        # Document stats
        doc_stats = {
            'total': db['documents'].count_documents({}),
            'pending': db['documents'].count_documents({'status': 'pending'}),
            'verified': db['documents'].count_documents({'verified': True}),
        }
        
        # AI usage (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        ai_sessions = db['ai_interactions'].count_documents({
            'created_at': {'$gte': week_ago}
        })
        
        # Recent activity (last 10 audit logs)
        recent_logs = AuditLog.find_recent(limit=10)
        recent_activity = [{
            'action': log.action,
            'user_type': log.user_type,
            'description': log.description,
            'timestamp': log.timestamp.isoformat()
        } for log in recent_logs]
        
        # Loan products performance
        products = list(db['loan_products'].find({'active': True}))
        product_stats = []
        for p in products:
            approved = db['loan_applications'].count_documents({
                'product_id': str(p['_id']),
                'status': 'approved'
            })
            total = db['loan_applications'].count_documents({
                'product_id': str(p['_id'])
            })
            product_stats.append({
                'name': p['name'],
                'applications': total,
                'approved': approved,
                'approval_rate': f"{(approved/total*100):.1f}%" if total > 0 else "0%"
            })
        
        return success_response(
            data={
                'users': {
                    'customers': total_customers,
                    'loan_officers': total_officers,
                    'admins': total_admins,
                    'total': total_customers + total_officers + total_admins
                },
                'loans': loan_stats,
                'documents': doc_stats,
                'ai_usage': {
                    'sessions_last_7_days': ai_sessions
                },
                'products': product_stats,
                'recent_activity': recent_activity
            },
            message="Admin dashboard data retrieved"
        )


class AuditLogsView(AdminRequiredMixin, APIView):
    """
    View audit logs (admin only).
    
    GET /api/analytics/audit-logs/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        import re
        
        # Pagination parameters
        page = int(request.query_params.get('page', 1))
        page_size = min(int(request.query_params.get('page_size', 20)), 200)
        
        # Filter parameters
        action_filter = request.query_params.get('action')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        search = request.query_params.get('search', '').strip()
        
        # Get all logs with filters (no limit to get accurate total)
        logs = AuditLog.find_with_filters(
            action=action_filter,
            date_from=date_from,
            date_to=date_to,
            limit=10000  # Limit to 10000 as it was having an error
        )
        
        # Filter by search term (description, user_email, action)
        if search:
            search_regex = re.compile(re.escape(search), re.IGNORECASE)
            logs = [
                log for log in logs
                if search_regex.search(log.description or '') or
                   search_regex.search(log.user_email or '') or
                   search_regex.search(log.action or '')
            ]
        
        # Get total before pagination
        total = len(logs)
        
        # Paginate
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_logs = logs[start_idx:end_idx]
        
        logs_data = [{
            'id': log.id,
            'user_id': log.user_id,
            'user_type': log.user_type,
            'action': log.action,
            'description': log.description,
            'resource_type': log.resource_type,
            'resource_id': log.resource_id,
            'ip_address': log.ip_address,
            'timestamp': log.timestamp.isoformat()
        } for log in paginated_logs]
        
        return success_response(
            data={
                'logs': logs_data,
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': (total + page_size - 1) // page_size if total > 0 else 1
            },
            message="Audit logs retrieved"
        )
