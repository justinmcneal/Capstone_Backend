import logging

from django.conf import settings

from notifications.models.device_token import DeviceToken
from notifications.models.notification import Notification
from notifications.services.websocket_service import (
    broadcast_notification_to_user,
    serialize_notification_for_ws,
)

try:
    import firebase_admin
    from firebase_admin import messaging
except ImportError:  # Push delivery is optional for web-only deployments.
    firebase_admin = None
    messaging = None

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
    channel="in_app",
    idempotency_key=None,
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
        idempotency_key=idempotency_key,
    )
    created = True
    if idempotency_key:
        notification, created = Notification.create_idempotent(
            notification, idempotency_key
        )
    else:
        notification.save()

    if not created:
        return notification

    logger.info(f"Created notification {notification.id} for user {user_id}")

    notification_data = serialize_notification_for_ws(notification)
    broadcast_notification_to_user(user_id, user_type, notification_data)

    # 3. Send Push Notification via Firebase Cloud Messaging (FCM)
    _send_push_notification(user_id, user_type, subject, message, notification_data)

    return notification


def _send_push_notification(user_id, user_type, title, body, data_payload):
    if not user_id or firebase_admin is None or messaging is None:
        return {"attempted": 0, "succeeded": 0, "failed": 0, "deactivated": 0}

    try:
        # Check if Firebase is initialized, initialize if not (requires credentials in env or default service account)
        if not firebase_admin._apps:
            try:
                firebase_admin.initialize_app()
            except Exception as exc:  # noqa: BLE001 - Firebase init guard
                logger.warning("Could not initialize firebase admin: %s", exc)
                return {
                    "attempted": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "deactivated": 0,
                }

        tokens = DeviceToken.get_tokens_for_user(user_id, user_type)
        if not tokens:
            return {"attempted": 0, "succeeded": 0, "failed": 0, "deactivated": 0}

        batch_size = int(settings.NOTIFICATIONS_FCM_BATCH_SIZE)
        totals = {"attempted": 0, "succeeded": 0, "failed": 0, "deactivated": 0}

        # Ensure data payload values are strings (FCM requirement)
        stringified_data = {k: str(v) for k, v in data_payload.items() if v is not None}

        for start in range(0, len(tokens), batch_size):
            batch = tokens[start : start + batch_size]
            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                data=stringified_data,
                tokens=[item.token for item in batch],
            )
            response = messaging.send_each_for_multicast(message)
            totals["attempted"] += len(batch)
            totals["succeeded"] += int(response.success_count)
            totals["failed"] += int(response.failure_count)

            attempted_hashes = [item.token_hash for item in batch]
            DeviceToken.touch_hashes(attempted_hashes)
            permanent_failures = []
            for token_record, send_response in zip(batch, response.responses):
                if send_response.success:
                    continue
                exception = send_response.exception
                logger.warning(
                    "FCM token delivery failed: error_type=%s",
                    type(exception).__name__,
                )
                if isinstance(
                    exception,
                    (messaging.UnregisteredError, messaging.SenderIdMismatchError),
                ):
                    permanent_failures.append(token_record.token_hash)
            totals["deactivated"] += DeviceToken.deactivate_hashes(
                permanent_failures, "provider_permanent_failure"
            )
        return totals

    except Exception as exc:  # noqa: BLE001 - Push delivery guard
        logger.error(
            "Push notification delivery failed: error_type=%s", type(exc).__name__
        )
        return {"attempted": 0, "succeeded": 0, "failed": 0, "deactivated": 0}
