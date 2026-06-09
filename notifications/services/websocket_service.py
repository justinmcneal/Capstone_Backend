import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings

logger = logging.getLogger("notifications")


def broadcast_notification_to_user(user_id, notification_data):
    if not settings.WEBSOCKET_ENABLED:
        return

    try:
        channel_layer = get_channel_layer()
        user_group = f"notifications_{user_id}"

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
        "channel": notification.channel,
        "status": notification.status,
        "is_read": notification.status == "read",
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }