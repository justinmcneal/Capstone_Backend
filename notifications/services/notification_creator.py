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
    metadata=None,
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
        metadata=dict(metadata or {}),
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

    notification_data = serialize_notification_for_ws(notification)
    if created:
        logger.info("Created notification %s", notification.id)
        broadcast_notification_to_user(user_id, user_type, notification_data)

    # Push intent is persisted even on an idempotent replay. This closes the
    # crash window between inbox creation and broker publication.
    if user_id:
        from notifications.services.delivery import queue_notification_delivery

        queue_notification_delivery(
            event_key=f"notification-push:{notification.id}",
            event_type=notification_type,
            recipient={
                "id": user_id,
                "user_type": user_type,
                "email": recipient_email,
                "name": recipient_name,
            },
            channels=["push"],
            payload={
                "subject": subject,
                "message": message,
                "related_type": related_type,
                "related_id": related_id,
                "metadata": dict(metadata or {}),
                "notification_id": notification.id,
            },
        )

    return notification


def _send_push_notification(
    user_id,
    user_type,
    title,
    body,
    data_payload,
    *,
    only_token_hashes=None,
    include_details=False,
):
    def result(details=None, *, error_code=""):
        details = details or {}
        value = {
            "attempted": int(details.get("attempted", 0)),
            "succeeded": int(details.get("succeeded", 0)),
            "failed": int(details.get("failed", 0)),
            "deactivated": int(details.get("deactivated", 0)),
        }
        if include_details:
            value.update(
                {
                    "succeeded_hashes": list(details.get("succeeded_hashes", [])),
                    "permanent_failure_hashes": list(
                        details.get("permanent_failure_hashes", [])
                    ),
                    "transient_failure_hashes": list(
                        details.get("transient_failure_hashes", [])
                    ),
                    "error_code": error_code,
                }
            )
        return value

    if not user_id or firebase_admin is None or messaging is None:
        return result(error_code="provider_unavailable")

    try:
        # Check if Firebase is initialized, initialize if not (requires credentials in env or default service account)
        if not firebase_admin._apps:
            try:
                firebase_admin.initialize_app()
            except Exception as exc:  # noqa: BLE001 - Firebase init guard
                logger.warning(
                    "Could not initialize firebase admin: error_type=%s",
                    type(exc).__name__,
                )
                return result(error_code="provider_initialization_failed")

        tokens = DeviceToken.get_tokens_for_user(user_id, user_type)
        missing_hashes = []
        if only_token_hashes is not None:
            selected = {str(value) for value in only_token_hashes}
            tokens = [item for item in tokens if item.token_hash in selected]
            missing_hashes = sorted(selected - {item.token_hash for item in tokens})
        if not tokens:
            return result({"permanent_failure_hashes": missing_hashes})

        batch_size = int(settings.NOTIFICATIONS_FCM_BATCH_SIZE)
        totals = {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "deactivated": 0,
            "succeeded_hashes": [],
            "permanent_failure_hashes": list(missing_hashes),
            "transient_failure_hashes": [],
        }

        # Ensure data payload values are strings (FCM requirement)
        stringified_data = {k: str(v) for k, v in data_payload.items() if v is not None}

        for start in range(0, len(tokens), batch_size):
            batch = tokens[start : start + batch_size]
            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                data=stringified_data,
                tokens=[item.token for item in batch],
            )
            try:
                response = messaging.send_each_for_multicast(message)
            except Exception as exc:  # noqa: BLE001 - batch remains retryable
                logger.warning(
                    "FCM batch delivery failed: error_type=%s", type(exc).__name__
                )
                batch_hashes = [item.token_hash for item in batch]
                totals["attempted"] += len(batch)
                totals["failed"] += len(batch)
                totals["transient_failure_hashes"].extend(batch_hashes)
                continue
            totals["attempted"] += len(batch)
            totals["succeeded"] += int(response.success_count)
            totals["failed"] += int(response.failure_count)

            attempted_hashes = [item.token_hash for item in batch]
            DeviceToken.touch_hashes(attempted_hashes)
            permanent_failures = []
            for token_record, send_response in zip(batch, response.responses):
                if send_response.success:
                    totals["succeeded_hashes"].append(token_record.token_hash)
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
                    totals["permanent_failure_hashes"].append(token_record.token_hash)
                else:
                    totals["transient_failure_hashes"].append(token_record.token_hash)
            totals["deactivated"] += DeviceToken.deactivate_hashes(
                permanent_failures, "provider_permanent_failure"
            )
        return result(totals)

    except Exception as exc:  # noqa: BLE001 - Push delivery guard
        logger.error(
            "Push notification delivery failed: error_type=%s", type(exc).__name__
        )
        return result(error_code="provider_delivery_failed")
