import logging
from notifications.models.notification import Notification
from notifications.services.websocket_service import (
    broadcast_notification_to_user,
    serialize_notification_for_ws
)

logger = logging.getLogger("notifications")


def create_and_broadcast_notification(
    user_id,
    user_type,
    notification_type,
    subject,
    message,
    recipient_email="",
    recipient_name="",
    related_type=None,
    related_id=None,
    channel="in_app"
):
    notification = Notification(
        user_id=str(user_id),
        user_type=user_type,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        notification_type=notification_type,
        subject=subject,
        message=message,
        related_type=related_type,
        related_id=related_id,
        channel=channel,
        status="sent",
    )
    notification.save()

    logger.info(f"Created notification {notification.id} for user {user_id}")

    notification_data = serialize_notification_for_ws(notification)
    broadcast_notification_to_user(user_id, notification_data)

    return notification