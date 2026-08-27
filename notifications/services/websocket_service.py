import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

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
                "Cannot broadcast notification without a valid owner: %s/%s",
                user_type,
                user_id,
            )
            return

        async_to_sync(channel_layer.group_send)(
            user_group,
            {
                "type": "notification_message",
                "data": notification_data
            }
        )

        logger.info("Notification broadcast to user %s via WebSocket", user_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to broadcast notification via WebSocket: %s", exc)


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
