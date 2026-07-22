import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings
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

        logger.info(f"Notification broadcast to user {user_id} via WebSocket")
    except Exception as e:
        logger.error(f"Failed to broadcast notification via WebSocket: {e}")


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
        "status": notification.status,
        "is_read": notification.status == "read",
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }
