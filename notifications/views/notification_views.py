"""
Notification Views - Notification inbox API.

Endpoints:
    GET /api/notifications/                 - List notifications with pagination
    POST /api/notifications/{id}/read/      - Mark single notification as read  
    POST /api/notifications/mark-all-read/  - Mark all notifications as read
    GET /api/notifications/unread-count/    - Get unread notification count
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import ClassVar

from bson import ObjectId
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.validation_utils import parse_optional_bool, sanitize_text
from config.views import error_response, success_response
from notifications.models.device_token import DeviceToken
from notifications.models.notification import (
    Notification,
    get_db,
    serialize_utc_datetime,
)
from notifications.ownership import (
    build_notification_owner_query as _build_notification_owner_query,
)

logger = logging.getLogger('notifications')


def _serialize_related_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


class NotificationListView(AccessControlMixin, APIView):
    """
    List notifications with pagination.
    
    GET /api/notifications/
    Query params:
        - page (int): Page number (default: 1)
        - page_size (int): Items per page (default: 20, max: 100)
        - unread (bool): Filter to unread only (default: false)
        - channel (str): Filter by channel (email/in_app)
    """
    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    
    def get(self, request):
        has_permission, result = self.require_roles(
            request,
            {'customer', 'loan_officer', 'admin', 'super_admin'},
        )
        if not has_permission:
            return result

        # Parse query params
        try:
            page = int(request.query_params.get('page', 1))
            page_size = min(int(request.query_params.get('page_size', 20)), 100)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid pagination parameters",
                errors={'pagination': 'page and page_size must be integers'},
                status_code=http_status.HTTP_400_BAD_REQUEST
            )
        if page < 1 or page_size < 1:
            return error_response(
                message="Invalid pagination parameters",
                errors={'pagination': 'page and page_size must be at least 1'},
                status_code=http_status.HTTP_400_BAD_REQUEST
            )

        unread_raw = request.query_params.get('unread')
        unread_valid, unread_value, unread_error = parse_optional_bool(unread_raw, 'unread')
        if not unread_valid:
            return error_response(
                message="Invalid unread filter",
                errors={'unread': unread_error},
                status_code=http_status.HTTP_400_BAD_REQUEST
            )
        unread_only = unread_value is True

        channel_filter = sanitize_text(request.query_params.get('channel', '')).lower()
        if channel_filter and channel_filter not in {'email', 'in_app'}:
            return error_response(
                message="Invalid channel filter",
                errors={'channel': 'channel must be either email or in_app'},
                status_code=http_status.HTTP_400_BAD_REQUEST
            )
        
        # Build query
        db = get_db()
        collection = db[Notification.collection_name]
        
        query = _build_notification_owner_query(request.user)
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
                'related_id': _serialize_related_id(notification.related_id),
                'metadata': notification.metadata,
                'channel': notification.channel,
                'status': notification.status,
                'is_read': notification.status == 'read',
                'created_at': serialize_utc_datetime(notification.created_at),
                'sent_at': serialize_utc_datetime(notification.sent_at),
            })
        
        # Get unread count
        unread_query = _build_notification_owner_query(request.user)
        unread_query['status'] = {'$nin': ['read']}
        unread_count = collection.count_documents(unread_query)
        
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


class NotificationMarkReadView(AccessControlMixin, APIView):
    """
    Mark a single notification as read.
    
    POST /api/notifications/{id}/read/
    """
    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]

    def post(self, request, notification_id):
        has_permission, result = self.require_roles(
            request,
            {'customer', 'loan_officer', 'admin', 'super_admin'},
        )
        if not has_permission:
            return result

        # Find notification
        db = get_db()
        collection = db[Notification.collection_name]
        
        try:
            owner_query = _build_notification_owner_query(request.user)
            find_query = {'_id': ObjectId(notification_id)}
            if '$or' in owner_query:
                find_query['$or'] = owner_query['$or']
            else:
                find_query.update(owner_query)

            doc = collection.find_one({
                **find_query
            })
        except Exception:  # noqa: BLE001
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
            {'$set': {'status': 'read', 'read_at': datetime.now(timezone.utc)}}
        )
        
        logger.info(f"Notification {notification_id} marked as read")
        
        return success_response(
            data={'notification_id': notification_id, 'status': 'read'},
            message="Notification marked as read"
        )


class NotificationMarkAllReadView(AccessControlMixin, APIView):
    """
    Mark all notifications as read.
    
    POST /api/notifications/mark-all-read/
    """
    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    
    def post(self, request):
        has_permission, result = self.require_roles(
            request,
            {'customer', 'loan_officer', 'admin', 'super_admin'},
        )
        if not has_permission:
            return result

        # Mark all as read
        db = get_db()
        collection = db[Notification.collection_name]

        update_query = _build_notification_owner_query(request.user)
        update_query['status'] = {'$nin': ['read']}

        result = collection.update_many(
            update_query,
            {'$set': {'status': 'read', 'read_at': datetime.now(timezone.utc)}}
        )
        
        logger.info(f"Marked {result.modified_count} notifications as read")
        
        return success_response(
            data={'marked_count': result.modified_count},
            message=f"{result.modified_count} notifications marked as read"
        )


class NotificationUnreadCountView(AccessControlMixin, APIView):
    """
    Get unread notification count (for badge updates).
    
    GET /api/notifications/unread-count/
    """
    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    
    def get(self, request):
        has_permission, result = self.require_roles(
            request,
            {'customer', 'loan_officer', 'admin', 'super_admin'},
        )
        if not has_permission:
            return result

        db = get_db()
        collection = db[Notification.collection_name]

        unread_query = _build_notification_owner_query(request.user)
        unread_query['status'] = {'$nin': ['read']}
        unread_count = collection.count_documents(unread_query)
        
        return success_response(
            data={'unread_count': unread_count},
            message="Unread count retrieved"
        )

class NotificationDeleteView(AccessControlMixin, APIView):
    """
    Delete a single notification.
    
    DELETE /api/notifications/{id}/
    """
    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    
    def delete(self, request, notification_id):
        has_permission, result = self.require_roles(
            request,
            {'customer', 'loan_officer', 'admin', 'super_admin'},
        )
        if not has_permission:
            return result

        db = get_db()
        collection = db[Notification.collection_name]
        
        try:
            owner_query = _build_notification_owner_query(request.user)
            find_query = {'_id': ObjectId(notification_id)}
            if '$or' in owner_query:
                find_query['$or'] = owner_query['$or']
            else:
                find_query.update(owner_query)

            result = collection.delete_one(find_query)
        except Exception:  # noqa: BLE001
            return error_response(
                message="Invalid notification ID",
                status_code=http_status.HTTP_400_BAD_REQUEST
            )
        
        if result.deleted_count == 0:
            return error_response(
                message="Notification not found",
                status_code=http_status.HTTP_404_NOT_FOUND
            )
        
        logger.info(f"Notification {notification_id} deleted")
        
        return success_response(
            data={'notification_id': notification_id, 'status': 'deleted'},
            message="Notification deleted successfully"
        )


class NotificationClearAllView(AccessControlMixin, APIView):
    """
    Delete all notifications for the current user.
    
    DELETE /api/notifications/clear-all/
    """
    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    
    def delete(self, request):
        has_permission, result = self.require_roles(
            request,
            {'customer', 'loan_officer', 'admin', 'super_admin'},
        )
        if not has_permission:
            return result

        db = get_db()
        collection = db[Notification.collection_name]

        delete_query = _build_notification_owner_query(request.user)
        result = collection.delete_many(delete_query)
        
        logger.info(f"Deleted {result.deleted_count} notifications")
        
        return success_response(
            data={'deleted_count': result.deleted_count},
            message=f"{result.deleted_count} notifications deleted"
        )


class RegisterDeviceTokenView(AccessControlMixin, APIView):
    """
    Register FCM device token for push notifications.
    
    POST /api/notifications/register-token/
    Body:
        - token (str): The FCM device token
        - platform (str): Platform (android/ios/web)
    """
    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    
    def post(self, request):
        has_permission, result = self.require_roles(
            request,
            {'customer', 'loan_officer', 'admin', 'super_admin'},
        )
        if not has_permission:
            return result

        token = request.data.get('token')
        platform = request.data.get('platform', 'unknown')

        if not token:
            return error_response(
                message="Missing required field: token",
                status_code=http_status.HTTP_400_BAD_REQUEST
            )

        user_id = str(getattr(request.user, 'customer_id', '') or getattr(request.user, '_id', ''))
        
        device_token = DeviceToken(
            user_id=user_id,
            token=token,
            platform=platform,
            is_active=True
        )
        device_token.save()

        logger.info(f"Registered device token for user {user_id} on {platform}")

        return success_response(
            data={'status': 'registered'},
            message="Device token registered successfully"
        )
