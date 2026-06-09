import logging
from notifications.models.notification import Notification
from notifications.services.websocket_service import (
    broadcast_notification_to_user,
    serialize_notification_for_ws
)
from notifications.models.device_token import DeviceToken
import firebase_admin
from firebase_admin import messaging, credentials

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

    # 3. Send Push Notification via Firebase Cloud Messaging (FCM)
    _send_push_notification(user_id, subject, message, notification_data)

    return notification

def _send_push_notification(user_id, title, body, data_payload):
    if not user_id:
        return
        
    try:
        # Check if Firebase is initialized, initialize if not (requires credentials in env or default service account)
        if not firebase_admin._apps:
            try:
                firebase_admin.initialize_app()
            except Exception as e:
                logger.warning(f"Could not initialize firebase admin: {e}")
                return

        tokens = DeviceToken.get_tokens_for_user(user_id)
        if not tokens:
            return

        fcm_tokens = [t.token for t in tokens]
        
        # Ensure data payload values are strings (FCM requirement)
        stringified_data = {k: str(v) for k, v in data_payload.items() if v is not None}

        message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=stringified_data,
            tokens=fcm_tokens,
        )
        
        response = messaging.send_multicast(message)
        
        if response.failure_count > 0:
            responses = response.responses
            for idx, resp in enumerate(responses):
                if not resp.success:
                    # The order of responses corresponds to the order of the registration tokens.
                    failed_token = fcm_tokens[idx]
                    logger.error(f"Failed to send push to token {failed_token}: {resp.exception}")
                    # If token is unregistered, deactivate it
                    if isinstance(resp.exception, messaging.UnregisteredError):
                        DeviceToken.deactivate_token(failed_token)
                        logger.info(f"Deactivated stale token: {failed_token}")

    except Exception as e:
        logger.error(f"Push notification delivery failed: {e}")