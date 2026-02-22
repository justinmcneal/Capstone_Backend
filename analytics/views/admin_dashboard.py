"""
Admin Dashboard - System-wide analytics for admins.
"""
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from datetime import datetime, timedelta
from bson import ObjectId

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text
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
    required_permissions = ['view_analytics']
    
    def get(self, request):
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

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
    required_permissions = ['view_logs']
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        import re

        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        def serialize_details(value):
            """Ensure details payload is JSON-serializable."""
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, ObjectId):
                return str(value)
            if isinstance(value, dict):
                return {k: serialize_details(v) for k, v in value.items()}
            if isinstance(value, list):
                return [serialize_details(v) for v in value]
            return value
        
        # Pagination parameters
        try:
            page = max(int(request.query_params.get('page', 1)), 1)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid page parameter",
                errors={'page': 'page must be an integer'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        try:
            page_size = min(max(int(request.query_params.get('page_size', 20)), 1), 200)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid page_size parameter",
                errors={'page_size': 'page_size must be an integer'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Filter parameters
        action_filter = sanitize_text(request.query_params.get('action', ''))
        action_group = sanitize_text(request.query_params.get('action_group', ''))
        user_id = sanitize_text(request.query_params.get('user_id', ''))
        user_type = sanitize_text(request.query_params.get('user_type', ''))
        date_from = sanitize_text(request.query_params.get('date_from', ''))
        date_to = sanitize_text(request.query_params.get('date_to', ''))
        search = sanitize_text(request.query_params.get('search', ''))
        
        # Get all logs with filters (no limit to get accurate total)
        logs = AuditLog.find_with_filters(
            action=action_filter or None,
            action_group=action_group or None,
            user_id=user_id or None,
            user_type=user_type or None,
            date_from=date_from or None,
            date_to=date_to or None,
            limit=10000
        )
        
        # Filter by search term (description, user_email, action, user_id, user_type)
        if search:
            search_regex = re.compile(re.escape(search), re.IGNORECASE)
            logs = [
                log for log in logs
                if search_regex.search(log.description or '') or
                   search_regex.search(log.user_email or '') or
                   search_regex.search(log.action or '') or
                   search_regex.search(log.user_id or '') or
                   search_regex.search(log.user_type or '')
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
            'user_email': log.user_email,
            'action': log.action,
            'description': log.description,
            'resource_type': log.resource_type,
            'resource_id': log.resource_id,
            'details': serialize_details(log.details or {}),
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


class AuditLogUsersView(AdminRequiredMixin, APIView):
    """
    List users present in audit logs for user-based filtering.

    GET /api/analytics/audit-logs/users/
    """
    required_permissions = ['view_logs']
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.conf import settings
        import re

        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        search = sanitize_text(request.query_params.get('search', ''))
        try:
            limit = min(max(int(request.query_params.get('limit', 200)), 1), 500)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid limit parameter",
                errors={'limit': 'limit must be an integer'},
                status_code=status.HTTP_400_BAD_REQUEST
            )

        collection = settings.MONGODB['audit_logs']
        match_stage = {'user_id': {'$nin': [None, '']}}
        if search:
            regex = {'$regex': re.escape(search), '$options': 'i'}
            match_stage['$or'] = [
                {'user_email': regex},
                {'user_type': regex},
                {'user_id': regex},
            ]

        pipeline = [
            {'$match': match_stage},
            {'$sort': {'timestamp': -1}},
            {
                '$group': {
                    '_id': '$user_id',
                    'user_id': {'$first': '$user_id'},
                    'user_type': {'$first': '$user_type'},
                    'user_email': {'$first': '$user_email'},
                    'latest_timestamp': {'$first': '$timestamp'},
                }
            },
            {'$sort': {'latest_timestamp': -1}},
            {'$limit': limit},
        ]

        users = []
        for doc in collection.aggregate(pipeline):
            user_id = doc.get('user_id')
            user_type = doc.get('user_type') or 'unknown'
            user_email = doc.get('user_email') or ''
            short_id = f"{user_id[:8]}..." if isinstance(user_id, str) else ''
            label = (
                f"{user_email} ({user_type})"
                if user_email
                else f"{user_type} ({short_id})"
            )
            users.append({
                'user_id': user_id,
                'user_type': user_type,
                'user_email': user_email,
                'label': label,
            })

        return success_response(
            data={'users': users},
            message="Audit log users retrieved",
        )


class AuditLogDetailView(AdminRequiredMixin, APIView):
    """
    Get full detail for a specific audit log entry.

    GET /api/analytics/audit-logs/<log_id>/
    """
    required_permissions = ['view_logs']
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, log_id):
        from django.conf import settings

        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        def serialize_details(value):
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, ObjectId):
                return str(value)
            if isinstance(value, dict):
                return {k: serialize_details(v) for k, v in value.items()}
            if isinstance(value, list):
                return [serialize_details(v) for v in value]
            return value

        try:
            oid = ObjectId(log_id)
        except Exception:
            return error_response(
                message="Invalid log ID",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        doc = settings.MONGODB['audit_logs'].find_one({'_id': oid})
        if not doc:
            return error_response(
                message="Audit log not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        log = AuditLog.from_dict(doc)
        return success_response(
            data={
                'id': log.id,
                'user_id': log.user_id,
                'user_type': log.user_type,
                'user_email': log.user_email,
                'action': log.action,
                'description': log.description,
                'resource_type': log.resource_type,
                'resource_id': log.resource_id,
                'details': serialize_details(log.details or {}),
                'ip_address': log.ip_address,
                'timestamp': log.timestamp.isoformat() if log.timestamp else None,
            },
            message="Audit log detail retrieved",
        )
