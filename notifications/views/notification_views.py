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
from bson.errors import InvalidId
from django.conf import settings
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.validation_utils import parse_optional_bool, sanitize_text
from config.views import error_response, success_response
from notifications.models.device_token import (
    DeviceToken,
    DeviceTokenLimitExceeded,
    DeviceTokenOwnershipConflict,
)
from notifications.models.notification import (
    Notification,
    get_db,
    serialize_utc_datetime,
)
from notifications.ownership import (
    build_notification_owner_query as _build_notification_owner_query,
)
from notifications.ownership import (
    notification_owner_identity,
)
from notifications.services.inbox import (
    bounded_owner_ids,
    mark_notification_read,
    with_unread_state,
)
from notifications.throttles import (
    NotificationDeviceTokenRateThrottle,
    NotificationReadRateThrottle,
    NotificationWriteRateThrottle,
)

logger = logging.getLogger("notifications")
NOTIFICATION_LIST_QUERY_PARAMS = {"page", "page_size", "unread", "channel"}


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
    throttle_classes: ClassVar[list] = [NotificationReadRateThrottle]

    def get(self, request):
        has_permission, result = self.require_roles(
            request,
            {"customer", "loan_officer", "admin", "super_admin"},
        )
        if not has_permission:
            return result

        unknown_params = sorted(
            set(request.query_params.keys()) - NOTIFICATION_LIST_QUERY_PARAMS
        )
        if unknown_params:
            return error_response(
                message="Unknown notification query parameter",
                errors={
                    "query": f"Unsupported parameters: {', '.join(unknown_params)}"
                },
                code="NOTIFICATION_QUERY_INVALID",
                status_code=http_status.HTTP_400_BAD_REQUEST,
            )

        # Parse query params
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 20))
        except (TypeError, ValueError):
            return error_response(
                message="Invalid pagination parameters",
                errors={"pagination": "page and page_size must be integers"},
                status_code=http_status.HTTP_400_BAD_REQUEST,
            )
        if page < 1 or not 1 <= page_size <= 100:
            return error_response(
                message="Invalid pagination parameters",
                errors={
                    "pagination": "page must be at least 1 and page_size must be between 1 and 100"
                },
                status_code=http_status.HTTP_400_BAD_REQUEST,
            )
        skip = (page - 1) * page_size
        if skip > settings.NOTIFICATIONS_MAX_OFFSET:
            return error_response(
                message="Notification page exceeds the supported offset",
                errors={
                    "page": (
                        f"The requested offset exceeds {settings.NOTIFICATIONS_MAX_OFFSET}; "
                        "use a lower page"
                    )
                },
                code="NOTIFICATION_OFFSET_LIMIT_EXCEEDED",
                status_code=http_status.HTTP_400_BAD_REQUEST,
            )

        unread_raw = request.query_params.get("unread")
        unread_valid, unread_value, unread_error = parse_optional_bool(
            unread_raw, "unread"
        )
        if not unread_valid:
            return error_response(
                message="Invalid unread filter",
                errors={"unread": unread_error},
                status_code=http_status.HTTP_400_BAD_REQUEST,
            )
        unread_only = unread_value is True

        channel_filter = sanitize_text(request.query_params.get("channel", "")).lower()
        if channel_filter and channel_filter not in {"email", "in_app"}:
            return error_response(
                message="Invalid channel filter",
                errors={"channel": "channel must be either email or in_app"},
                status_code=http_status.HTTP_400_BAD_REQUEST,
            )

        # Build query
        db = get_db()
        collection = db[Notification.collection_name]

        query = _build_notification_owner_query(request.user)
        if unread_only:
            query = with_unread_state(query)
        if channel_filter:
            query["channel"] = channel_filter

        # Get total count for pagination
        total_count = collection.count_documents(query)
        total_pages = math.ceil(total_count / page_size)

        # Fetch notifications with pagination
        cursor = (
            collection.find(query).sort("created_at", -1).skip(skip).limit(page_size)
        )

        notifications = []
        for doc in cursor:
            notification = Notification.from_dict(doc)
            notifications.append(
                {
                    "id": notification.id,
                    "notification_type": notification.notification_type,
                    "subject": notification.subject,
                    "message": notification.message,
                    "related_type": notification.related_type,
                    "related_id": _serialize_related_id(notification.related_id),
                    "metadata": notification.metadata,
                    "channel": notification.channel,
                    "status": notification.delivery_status,
                    "delivery_status": notification.delivery_status,
                    "is_read": notification.is_read,
                    "created_at": serialize_utc_datetime(notification.created_at),
                    "sent_at": serialize_utc_datetime(notification.sent_at),
                    "read_at": serialize_utc_datetime(notification.read_at),
                }
            )

        # Get unread count
        unread_query = _build_notification_owner_query(request.user)
        unread_query = with_unread_state(unread_query)
        unread_count = collection.count_documents(unread_query)

        return success_response(
            data={
                "notifications": notifications,
                "unread_count": unread_count,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_items": total_count,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_previous": page > 1,
                },
            },
            message="Notifications retrieved successfully",
        )


class NotificationMarkReadView(AccessControlMixin, APIView):
    """
    Mark a single notification as read.

    POST /api/notifications/{id}/read/
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes: ClassVar[list] = [NotificationWriteRateThrottle]

    def post(self, request, notification_id):
        has_permission, result = self.require_roles(
            request,
            {"customer", "loan_officer", "admin", "super_admin"},
        )
        if not has_permission:
            return result

        db = get_db()
        try:
            owner_query = _build_notification_owner_query(request.user)
            outcome = mark_notification_read(db, notification_id, owner_query)
        except (InvalidId, TypeError):
            return error_response(
                message="Invalid notification ID",
                status_code=http_status.HTTP_400_BAD_REQUEST,
            )

        if not outcome["found"]:
            return error_response(
                message="Notification not found",
                status_code=http_status.HTTP_404_NOT_FOUND,
            )
        if outcome.get("conflict"):
            return error_response(
                message="Notification read state changed concurrently",
                code="NOTIFICATION_STATE_CONFLICT",
                status_code=http_status.HTTP_409_CONFLICT,
            )

        logger.info(f"Notification {notification_id} marked as read")

        return success_response(
            data={
                "notification_id": notification_id,
                "is_read": True,
                "read_at": serialize_utc_datetime(outcome["document"].get("read_at")),
                "delivery_status": Notification.from_dict(
                    outcome["document"]
                ).delivery_status,
                "replayed": outcome["replayed"],
            },
            message="Notification marked as read",
        )


class NotificationMarkAllReadView(AccessControlMixin, APIView):
    """
    Mark all notifications as read.

    POST /api/notifications/mark-all-read/
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes: ClassVar[list] = [NotificationWriteRateThrottle]

    def post(self, request):
        has_permission, result = self.require_roles(
            request,
            {"customer", "loan_officer", "admin", "super_admin"},
        )
        if not has_permission:
            return result

        # Mark all as read
        db = get_db()
        collection = db[Notification.collection_name]

        owner_query = _build_notification_owner_query(request.user)
        update_query = with_unread_state(owner_query)
        ids = bounded_owner_ids(
            collection,
            update_query,
            limit=settings.NOTIFICATIONS_BULK_MUTATION_LIMIT,
        )
        if ids is None:
            return error_response(
                message="Inbox is too large for a synchronous mark-all operation",
                code="NOTIFICATION_BULK_LIMIT_EXCEEDED",
                status_code=http_status.HTTP_409_CONFLICT,
            )

        result = collection.update_many(
            {"_id": {"$in": ids}, **owner_query},
            {"$set": {"is_read": True, "read_at": datetime.now(timezone.utc)}},
        )

        logger.info(f"Marked {result.modified_count} notifications as read")

        return success_response(
            data={"marked_count": result.modified_count},
            message=f"{result.modified_count} notifications marked as read",
        )


class NotificationUnreadCountView(AccessControlMixin, APIView):
    """
    Get unread notification count (for badge updates).

    GET /api/notifications/unread-count/
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes: ClassVar[list] = [NotificationReadRateThrottle]

    def get(self, request):
        has_permission, result = self.require_roles(
            request,
            {"customer", "loan_officer", "admin", "super_admin"},
        )
        if not has_permission:
            return result

        db = get_db()
        collection = db[Notification.collection_name]

        unread_query = _build_notification_owner_query(request.user)
        unread_query = with_unread_state(unread_query)
        unread_count = collection.count_documents(unread_query)

        return success_response(
            data={"unread_count": unread_count}, message="Unread count retrieved"
        )


class NotificationDeleteView(AccessControlMixin, APIView):
    """
    Delete a single notification.

    DELETE /api/notifications/{id}/
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes: ClassVar[list] = [NotificationWriteRateThrottle]

    def delete(self, request, notification_id):
        has_permission, result = self.require_roles(
            request,
            {"customer", "loan_officer", "admin", "super_admin"},
        )
        if not has_permission:
            return result

        db = get_db()
        collection = db[Notification.collection_name]

        try:
            owner_query = _build_notification_owner_query(request.user)
            find_query = {"_id": ObjectId(notification_id)}
            if "$or" in owner_query:
                find_query["$or"] = owner_query["$or"]
            else:
                find_query.update(owner_query)

            owned = collection.find_one(find_query, {"legal_hold": 1})
            if owned and owned.get("legal_hold") is True:
                return error_response(
                    message="Notification is retained by an active legal hold",
                    code="NOTIFICATION_LEGAL_HOLD",
                    status_code=http_status.HTTP_409_CONFLICT,
                )
            find_query["legal_hold"] = {"$ne": True}

            result = collection.delete_one(find_query)
        except Exception:  # noqa: BLE001
            return error_response(
                message="Invalid notification ID",
                status_code=http_status.HTTP_400_BAD_REQUEST,
            )

        if result.deleted_count == 0:
            return error_response(
                message="Notification not found",
                status_code=http_status.HTTP_404_NOT_FOUND,
            )

        logger.info(f"Notification {notification_id} deleted")

        return success_response(
            data={"notification_id": notification_id, "status": "deleted"},
            message="Notification deleted successfully",
        )


class NotificationClearAllView(AccessControlMixin, APIView):
    """
    Delete all notifications for the current user.

    DELETE /api/notifications/clear-all/
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    throttle_classes: ClassVar[list] = [NotificationWriteRateThrottle]

    def delete(self, request):
        has_permission, result = self.require_roles(
            request,
            {"customer", "loan_officer", "admin", "super_admin"},
        )
        if not has_permission:
            return result

        db = get_db()
        collection = db[Notification.collection_name]

        owner_query = _build_notification_owner_query(request.user)
        deletable_query = {"$and": [owner_query, {"legal_hold": {"$ne": True}}]}
        ids = bounded_owner_ids(
            collection,
            deletable_query,
            limit=settings.NOTIFICATIONS_BULK_MUTATION_LIMIT,
        )
        if ids is None:
            return error_response(
                message="Inbox is too large for a synchronous clear-all operation",
                code="NOTIFICATION_BULK_LIMIT_EXCEEDED",
                status_code=http_status.HTTP_409_CONFLICT,
            )
        result = collection.delete_many(
            {
                "$and": [
                    {"_id": {"$in": ids}},
                    owner_query,
                    {"legal_hold": {"$ne": True}},
                ]
            }
        )
        retained_count = collection.count_documents({**owner_query, "legal_hold": True})

        logger.info(f"Deleted {result.deleted_count} notifications")

        return success_response(
            data={
                "deleted_count": result.deleted_count,
                "retained_count": retained_count,
            },
            message=f"{result.deleted_count} notifications deleted",
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
    throttle_classes: ClassVar[list] = [NotificationDeviceTokenRateThrottle]

    def post(self, request):
        has_permission, result = self.require_roles(
            request,
            {"customer", "loan_officer", "admin", "super_admin"},
        )
        if not has_permission:
            return result

        user_id, user_type = notification_owner_identity(request.user)
        try:
            device_token = DeviceToken.register(
                user_id=user_id,
                user_type=user_type,
                session_id=getattr(request.user, "session_id", ""),
                token=request.data.get("token"),
                platform=request.data.get("platform"),
            )
        except DeviceTokenOwnershipConflict:
            return error_response(
                message="Device token is already registered to another account",
                code="DEVICE_TOKEN_OWNERSHIP_CONFLICT",
                status_code=http_status.HTTP_409_CONFLICT,
            )
        except DeviceTokenLimitExceeded:
            return error_response(
                message="Active device-token limit has been reached",
                code="DEVICE_TOKEN_LIMIT_EXCEEDED",
                status_code=http_status.HTTP_409_CONFLICT,
            )
        except (TypeError, ValueError) as exc:
            return error_response(
                message="Invalid device-token registration",
                errors={"device_token": str(exc)},
                code="DEVICE_TOKEN_INVALID",
                status_code=http_status.HTTP_400_BAD_REQUEST,
            )

        logger.info(
            "Registered device token: user_type=%s platform=%s",
            user_type,
            device_token.platform,
        )

        return success_response(
            data={
                "status": "registered",
                "device_token_id": device_token.id,
                "platform": device_token.platform,
            },
            message="Device token registered successfully",
        )

    def delete(self, request):
        """Deactivate one token owned by the authenticated account."""
        has_permission, result = self.require_roles(
            request,
            {"customer", "loan_officer", "admin", "super_admin"},
        )
        if not has_permission:
            return result

        user_id, user_type = notification_owner_identity(request.user)
        try:
            revoked = DeviceToken.deactivate_token_for_owner(
                token=request.data.get("token"),
                user_id=user_id,
                user_type=user_type,
            )
        except (TypeError, ValueError) as exc:
            return error_response(
                message="Invalid device token",
                errors={"token": str(exc)},
                code="DEVICE_TOKEN_INVALID",
                status_code=http_status.HTTP_400_BAD_REQUEST,
            )
        if not revoked:
            return error_response(
                message="Device token not found",
                status_code=http_status.HTTP_404_NOT_FOUND,
            )
        logger.info("Unregistered device token: user_type=%s", user_type)
        return success_response(
            data={"status": "unregistered"},
            message="Device token unregistered successfully",
        )
