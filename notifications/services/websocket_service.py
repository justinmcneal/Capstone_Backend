import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

from notifications.metrics import (
    NOTIFICATION_BROADCAST_OUTCOMES,
    increment,
)
from notifications.models.notification import serialize_utc_datetime
from notifications.ownership import notification_group_name

logger = logging.getLogger("notifications")


def broadcast_notification_to_user(user_id, user_type, notification_data):
    if not settings.WEBSOCKET_ENABLED:
        return

    try:
        channel_layer = get_channel_layer()
        user_group = notification_group_name(user_id, user_type)
        if not user_group:
            logger.error(
                "Cannot broadcast notification without a valid owner: role=%s",
                user_type,
            )
            return

        async_to_sync(channel_layer.group_send)(
            user_group, {"type": "notification_message", "data": notification_data}
        )
        increment(
            NOTIFICATION_BROADCAST_OUTCOMES, kind="notification", outcome="published"
        )

        logger.info("Notification broadcast via WebSocket: role=%s", user_type)
    except Exception as exc:  # noqa: BLE001
        increment(
            NOTIFICATION_BROADCAST_OUTCOMES, kind="notification", outcome="failed"
        )
        logger.error(
            "Failed to broadcast notification via WebSocket: error_type=%s",
            type(exc).__name__,
        )


def broadcast_inbox_state_to_user(user_id, user_type, action, **data):
    """Tell every connected client to reconcile an owner-scoped inbox mutation."""
    if not settings.WEBSOCKET_ENABLED:
        return False
    user_group = notification_group_name(user_id, user_type)
    if not user_group:
        return False
    try:
        async_to_sync(get_channel_layer().group_send)(
            user_group,
            {
                "type": "inbox_state_message",
                "data": {"action": action, **data},
            },
        )
        increment(NOTIFICATION_BROADCAST_OUTCOMES, kind="state", outcome="published")
        return True
    except Exception as exc:  # noqa: BLE001
        increment(NOTIFICATION_BROADCAST_OUTCOMES, kind="state", outcome="failed")
        logger.error(
            "Failed to broadcast inbox state: error_type=%s", type(exc).__name__
        )
        return False


def serialize_notification_for_ws(notification):
    return {
        "id": notification.id,
        "notification_type": notification.notification_type,
        "subject": notification.subject,
        "message": notification.message,
        "related_type": notification.related_type,
        "related_id": str(notification.related_id) if notification.related_id else None,
        "metadata": getattr(notification, "metadata", {}),
        "channel": notification.channel,
        "status": notification.delivery_status,
        "delivery_status": notification.delivery_status,
        "is_read": notification.is_read,
        "created_at": serialize_utc_datetime(notification.created_at),
        "sent_at": serialize_utc_datetime(notification.sent_at),
        "read_at": serialize_utc_datetime(notification.read_at),
    }
