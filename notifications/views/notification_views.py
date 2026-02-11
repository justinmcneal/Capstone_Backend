"""
Notification Views - Customer-facing notification inbox API.

Endpoints:
    GET /api/notifications/                 - List notifications with pagination
    POST /api/notifications/{id}/read/      - Mark single notification as read  
    POST /api/notifications/mark-all-read/  - Mark all notifications as read
    GET /api/notifications/unread-count/    - Get unread notification count
"""
import logging
import math
from datetime import datetime

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import status as http_status

from accounts.authentication import CustomJWTAuthentication
from config.views import success_response, error_response
from notifications.models.notification import Notification, get_db

logger = logging.getLogger('notifications')


class NotificationListView(APIView):
    """
    List customer notifications with pagination.
    
    GET /api/notifications/
    Query params:
        - page (int): Page number (default: 1)
        - page_size (int): Items per page (default: 20, max: 100)
        - unread (bool): Filter to unread only (default: false)
        - channel (str): Filter by channel (email/in_app)
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        user_id = str(user.customer_id)
        
        # Parse query params
        try:
            page = int(request.query_params.get('page', 1))
            page_size = min(int(request.query_params.get('page_size', 20)), 100)
        except ValueError:
            page = 1
            page_size = 20
        
        unread_only = request.query_params.get('unread', '').lower() in ('true', '1', 'yes')
        channel_filter = request.query_params.get('channel')
        
        # Build query
        db = get_db()
        collection = db[Notification.collection_name]
        
        query = {'user_id': user_id}
        if unread_only:
            query['status'] = {'$nin': ['read']}
        if channel_filter:
            query['channel'] = channel_filter
        
        # Get total count for pagination
        total_count = collection.count_documents(query)
        total_pages = max(1, math.ceil(total_count / page_size))
        
        # Fetch notifications with pagination
        skip = (page - 1) * page_size
        cursor = collection.find(query).sort('created_at', -1).skip(skip).limit(page_size)
        
        notifications = []
        for doc in cursor:
            notification = Notification.from_dict(doc)
            notifications.append({
                'id': notification.id,
                'notification_type': notification.notification_type,
                'subject': notification.subject,
                'message': notification.message,
                'related_type': notification.related_type,
                'related_id': notification.related_id,
                'channel': notification.channel,
                'status': notification.status,
                'is_read': notification.status == 'read',
                'created_at': notification.created_at.isoformat() if notification.created_at else None,
                'sent_at': notification.sent_at.isoformat() if notification.sent_at else None,
            })
        
        # Get unread count
        unread_count = collection.count_documents({'user_id': user_id, 'status': {'$nin': ['read']}})
        
        return success_response(
            data={
                'notifications': notifications,
                'unread_count': unread_count,
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total_items': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_previous': page > 1,
                }
            },
            message="Notifications retrieved successfully"
        )


class NotificationMarkReadView(APIView):
    """
    Mark a single notification as read.
    
    POST /api/notifications/{id}/read/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, notification_id):
        user = request.user
        user_id = str(user.customer_id)
        
        # Find notification
        db = get_db()
        collection = db[Notification.collection_name]
        
        from bson import ObjectId
        try:
            doc = collection.find_one({
                '_id': ObjectId(notification_id),
                'user_id': user_id
            })
        except Exception:
            return error_response(
                message="Invalid notification ID",
                status_code=http_status.HTTP_400_BAD_REQUEST
            )
        
        if not doc:
            return error_response(
                message="Notification not found",
                status_code=http_status.HTTP_404_NOT_FOUND
            )
        
        # Mark as read
        collection.update_one(
            {'_id': doc['_id']},
            {'$set': {'status': 'read', 'read_at': datetime.utcnow()}}
        )
        
        logger.info(f"Notification {notification_id} marked as read by user {user_id}")
        
        return success_response(
            data={'notification_id': notification_id, 'status': 'read'},
            message="Notification marked as read"
        )


class NotificationMarkAllReadView(APIView):
    """
    Mark all notifications as read.
    
    POST /api/notifications/mark-all-read/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        user = request.user
        user_id = str(user.customer_id)
        
        # Mark all as read
        db = get_db()
        collection = db[Notification.collection_name]
        
        result = collection.update_many(
            {'user_id': user_id, 'status': {'$nin': ['read']}},
            {'$set': {'status': 'read', 'read_at': datetime.utcnow()}}
        )
        
        logger.info(f"Marked {result.modified_count} notifications as read for user {user_id}")
        
        return success_response(
            data={'marked_count': result.modified_count},
            message=f"{result.modified_count} notifications marked as read"
        )


class NotificationUnreadCountView(APIView):
    """
    Get unread notification count (for badge updates).
    
    GET /api/notifications/unread-count/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        user_id = str(user.customer_id)
        
        db = get_db()
        collection = db[Notification.collection_name]
        
        unread_count = collection.count_documents({
            'user_id': user_id,
            'status': {'$nin': ['read']}
        })
        
        return success_response(
            data={'unread_count': unread_count},
            message="Unread count retrieved"
        )
