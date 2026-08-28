"""Queue, deliver, and reconcile the shared notification outbox."""

import logging

from django.conf import settings

from notifications.models.delivery import NotificationDelivery
from notifications.models.device_token import DeviceToken
from notifications.models.notification import Notification
from notifications.services.notification_creator import _send_push_notification
from notifications.services.preference_policy import evaluate_email_policy
from notifications.services.websocket_service import (
    broadcast_notification_to_user,
    serialize_notification_for_ws,
)

logger = logging.getLogger("notifications.delivery")


def _options():
    return {
        "max_attempts": int(settings.NOTIFICATIONS_DELIVERY_MAX_ATTEMPTS),
        "backoff_seconds": int(settings.NOTIFICATIONS_DELIVERY_RETRY_BACKOFF_SECONDS),
        "lease_seconds": int(settings.NOTIFICATIONS_DELIVERY_LEASE_SECONDS),
    }


def queue_notification_delivery(*, event_key, event_type, recipient, channels, payload):
    """Persist intent before broker publication; reconciliation handles outages."""
    delivery = NotificationDelivery.ensure(
        event_key=event_key,
        event_type=event_type,
        recipient=recipient,
        channels=channels,
        payload=payload,
    )
    from notifications.tasks import deliver_notification_task

    try:
        deliver_notification_task.delay(delivery.id)
        queued = True
    except Exception:  # noqa: BLE001 - durable pending row is the recovery path
        queued = False
        logger.error("Notification delivery enqueue failed: delivery=%s", delivery.id)
    return {"delivery_id": delivery.id, "queued": queued}


def _ensure_inbox(delivery):
    payload = delivery.payload
    notification = Notification(
        user_id=delivery.recipient_user_id,
        user_type=delivery.recipient_user_type,
        recipient_email=delivery.recipient_email,
        recipient_name=delivery.recipient_name,
        notification_type=delivery.event_type,
        subject=payload.get("subject", ""),
        message=payload.get("message", ""),
        related_type=payload.get("related_type"),
        related_id=payload.get("related_id"),
        metadata=dict(payload.get("metadata", {}) or {}),
        channel="in_app",
        status="sent",
    )
    notification, created = Notification.create_idempotent(
        notification, f"shared-delivery:{delivery.id}"
    )
    if created:
        broadcast_notification_to_user(
            delivery.recipient_user_id,
            delivery.recipient_user_type,
            serialize_notification_for_ws(notification),
        )
    delivery.checkpoint(notification_id=notification.id)
    return notification


def _deliver_email(delivery):
    if delivery.email_status in {"delivered", "suppressed"}:
        return True
    decision = evaluate_email_policy(
        user_id=delivery.recipient_user_id,
        user_type=delivery.recipient_user_type,
        event_type=delivery.event_type,
    )
    delivery.checkpoint(
        policy_version=decision["policy_version"],
        preference_key=decision["preference_key"],
        preference_allowed=decision["allowed"],
        policy_decided_at=decision["decided_at"],
    )
    if not decision["allowed"]:
        delivery.checkpoint(email_status="suppressed")
        return True

    from notifications.services.email_sender import EmailSender

    payload = delivery.payload
    email = dict(payload.get("email", {}) or {})
    sent = EmailSender().send(
        delivery.recipient_email,
        email.get("subject") or payload.get("subject", ""),
        email.get("template_name", ""),
        dict(email.get("context", {}) or {}),
        None,
    )
    if not sent:
        return False
    delivery.checkpoint(email_status="delivered")
    return True


def _deliver_push(delivery, notification):
    if delivery.push_status in {"delivered", "not_requested"}:
        return True
    if not delivery.push_target_hashes:
        targets = DeviceToken.get_tokens_for_user(
            delivery.recipient_user_id, delivery.recipient_user_type
        )
        delivery.checkpoint(push_target_hashes=[item.token_hash for item in targets])
    pending = sorted(
        set(delivery.push_target_hashes)
        - set(delivery.push_delivered_hashes)
        - set(delivery.push_permanent_hashes)
    )
    if not pending:
        delivery.checkpoint(push_status="delivered")
        return True

    payload = (
        serialize_notification_for_ws(notification)
        if notification
        else {
            "id": delivery.payload.get("notification_id"),
            "notification_type": delivery.event_type,
            "related_type": delivery.payload.get("related_type"),
            "related_id": delivery.payload.get("related_id"),
        }
    )
    outcome = _send_push_notification(
        delivery.recipient_user_id,
        delivery.recipient_user_type,
        delivery.payload.get("subject", ""),
        delivery.payload.get("message", ""),
        payload,
        only_token_hashes=pending,
        include_details=True,
    )
    delivered = sorted(
        set(delivery.push_delivered_hashes) | set(outcome["succeeded_hashes"])
    )
    permanent = sorted(
        set(delivery.push_permanent_hashes) | set(outcome["permanent_failure_hashes"])
    )
    unresolved = set(pending) - set(delivered) - set(permanent)
    completed = not unresolved and not outcome["error_code"]
    delivery.checkpoint(
        push_delivered_hashes=delivered,
        push_permanent_hashes=permanent,
        push_status="delivered" if completed else "retry_wait",
    )
    return completed


def deliver_notification(delivery_id):
    options = _options()
    delivery = NotificationDelivery.claim(
        delivery_id, lease_seconds=options["lease_seconds"]
    )
    if not delivery:
        return "not_due"
    try:
        notification = None
        if "in_app" in delivery.channels:
            notification = _ensure_inbox(delivery)
        email_complete = (
            _deliver_email(delivery) if "email" in delivery.channels else True
        )
        push_complete = (
            _deliver_push(delivery, notification)
            if "push" in delivery.channels
            else True
        )
        if not email_complete or not push_complete:
            delivery.defer(
                "channel_retryable",
                max_attempts=options["max_attempts"],
                backoff_seconds=options["backoff_seconds"],
            )
            return (
                "failed"
                if delivery.attempt_count >= options["max_attempts"]
                else "retry_wait"
            )
        if delivery.channels == ["email"] and delivery.email_status == "suppressed":
            delivery.mark_suppressed()
            return "suppressed"
        delivery.mark_delivered()
        return "delivered"
    except Exception:
        logger.exception("Notification delivery failed: delivery=%s", delivery.id)
        delivery.defer(
            "delivery_failed",
            max_attempts=options["max_attempts"],
            backoff_seconds=options["backoff_seconds"],
        )
        return (
            "failed"
            if delivery.attempt_count >= options["max_attempts"]
            else "retry_wait"
        )


def reconcile_notification_deliveries(limit=100):
    outcomes = {
        "delivered": 0,
        "suppressed": 0,
        "retry_wait": 0,
        "failed": 0,
        "not_due": 0,
    }
    for delivery_id in NotificationDelivery.due_ids(limit=limit):
        outcome = deliver_notification(delivery_id)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return outcomes
