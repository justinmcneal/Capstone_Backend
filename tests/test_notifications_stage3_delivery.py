"""Stage 3 durable, asynchronous, preference-aware delivery evidence."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from cryptography.fernet import Fernet

from accounts.models import Customer
from accounts.services.security_event_service import SecurityEventService
from config.celery import app
from config.field_encryption import _build_keyring, _get_fernet, is_encrypted_value
from notifications.models.delivery import NotificationDelivery
from notifications.models.device_token import DeviceToken
from notifications.models.notification import Notification
from notifications.services import assignment_events
from notifications.services.delivery import (
    deliver_notification,
    queue_notification_delivery,
    reconcile_notification_deliveries,
)
from notifications.services.email_sender import EmailSender
from notifications.services.notification_creator import (
    create_and_broadcast_notification,
)
from notifications.services.preference_policy import evaluate_email_policy


def _customer(*, loan_updates=True, payment_reminders=True, promotions=False):
    return Customer(
        first_name="Stage",
        last_name="Three",
        email=f"stage3-{ObjectId()}@example.test",
        password="hashed",
        verified=True,
        active=True,
        account_state="active",
        notification_preferences={
            "email_loan_updates": loan_updates,
            "email_payment_reminders": payment_reminders,
            "email_promotions": promotions,
        },
    ).save()


def _recipient(customer=None, *, user_id="customer-1", role="customer"):
    if customer:
        return {
            "id": customer.id,
            "user_type": "customer",
            "email": customer.email,
            "name": customer.full_name,
        }
    return {
        "id": user_id,
        "user_type": role,
        "email": f"{user_id}@example.test",
        "name": "Stage Three",
    }


def _payload(**values):
    return {
        "subject": "Durable notification",
        "message": "This intent survives a broker outage.",
        "related_type": "test",
        "related_id": "record-1",
        "metadata": {"source": "stage3"},
        **values,
    }


def _queue_without_worker(monkeypatch, **kwargs):
    delay = MagicMock()
    monkeypatch.setattr("notifications.tasks.deliver_notification_task.delay", delay)
    result = queue_notification_delivery(**kwargs)
    return result, delay


@pytest.fixture
def encrypted_fields(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = ()
    settings.FIELD_ENCRYPTION_STRICT_DECRYPTION = True
    _get_fernet.cache_clear()
    _build_keyring.cache_clear()
    yield
    _get_fernet.cache_clear()
    _build_keyring.cache_clear()


def test_canonical_tasks_are_registered_routed_and_worker_loss_safe(settings):
    app.loader.import_task_module("notifications.tasks")
    assert "notifications.deliver" in app.tasks
    assert "notifications.reconcile_deliveries" in app.tasks
    assert settings.CELERY_TASK_ROUTES["notifications.deliver"] == {
        "queue": "notifications"
    }
    annotation = settings.CELERY_TASK_ANNOTATIONS["notifications.deliver"]
    assert annotation["acks_late"] is True
    assert annotation["reject_on_worker_lost"] is True
    assert (
        app.conf.beat_schedule["reconcile-shared-notification-deliveries-every-minute"][
            "task"
        ]
        == "notifications.reconcile_deliveries"
    )


def test_delivery_payload_is_encrypted_and_idempotent(settings, encrypted_fields):
    recipient = _recipient()
    first = NotificationDelivery.ensure(
        event_key="event-1",
        event_type="password_changed",
        recipient=recipient,
        channels=["in_app", "push"],
        payload=_payload(),
    )
    second = NotificationDelivery.ensure(
        event_key="event-1",
        event_type="password_changed",
        recipient=recipient,
        channels=["in_app", "push"],
        payload=_payload(message="must not overwrite original intent"),
    )
    raw = settings.MONGODB[NotificationDelivery.collection_name].find_one(
        {"_id": first._id}
    )

    assert second.id == first.id
    assert is_encrypted_value(raw["payload"])
    assert (
        NotificationDelivery.from_dict(raw).payload["message"] == _payload()["message"]
    )


def test_broker_failure_leaves_pending_intent_for_reconciliation(monkeypatch, settings):
    monkeypatch.setattr(
        "notifications.tasks.deliver_notification_task.delay",
        MagicMock(side_effect=ConnectionError("broker unavailable")),
    )
    result = queue_notification_delivery(
        event_key="broker-failure",
        event_type="password_changed",
        recipient=_recipient(),
        channels=["in_app"],
        payload=_payload(),
    )

    assert result["queued"] is False
    raw = settings.MONGODB[NotificationDelivery.collection_name].find_one()
    assert raw["status"] == "pending"
    assert raw["attempt_count"] == 0


def test_inbox_replay_repairs_missing_push_publication(monkeypatch, settings):
    delay = MagicMock(side_effect=ConnectionError("broker unavailable"))
    monkeypatch.setattr("notifications.tasks.deliver_notification_task.delay", delay)
    monkeypatch.setattr(
        "notifications.services.notification_creator.broadcast_notification_to_user",
        lambda *args: None,
    )
    kwargs = {
        "user_id": "customer-1",
        "user_type": "customer",
        "notification_type": "password_changed",
        "subject": "Password changed",
        "message": "Your password changed.",
        "idempotency_key": "security-event-1",
    }

    first = create_and_broadcast_notification(**kwargs)
    second = create_and_broadcast_notification(**kwargs)

    assert second.id == first.id
    assert settings.MONGODB[Notification.collection_name].count_documents({}) == 1
    delivery = settings.MONGODB[NotificationDelivery.collection_name].find_one()
    assert delivery["event_key"] == f"notification-push:{first.id}"
    assert delivery["status"] == "pending"
    assert delay.call_count == 2


def test_atomic_claim_and_idempotent_inbox_delivery(monkeypatch, settings):
    result, delay = _queue_without_worker(
        monkeypatch,
        event_key="atomic-inbox",
        event_type="application_assigned",
        recipient=_recipient(user_id="officer-1", role="loan_officer"),
        channels=["in_app"],
        payload=_payload(),
    )
    delivery_id = result["delivery_id"]
    assert delay.call_args.args == (delivery_id,)

    claimed = NotificationDelivery.claim(delivery_id, lease_seconds=300)
    assert claimed is not None
    assert NotificationDelivery.claim(delivery_id, lease_seconds=300) is None
    settings.MONGODB[NotificationDelivery.collection_name].update_one(
        {"_id": claimed._id},
        {
            "$set": {
                "status": "pending",
                "next_attempt_at": datetime.now(timezone.utc),
                "lease_started_at": None,
            }
        },
    )

    assert deliver_notification(delivery_id) == "delivered"
    assert deliver_notification(delivery_id) == "not_due"
    assert settings.MONGODB[Notification.collection_name].count_documents({}) == 1


def test_stale_worker_lease_is_recovered_by_reconciliation(monkeypatch, settings):
    result, _delay = _queue_without_worker(
        monkeypatch,
        event_key="stale-lease",
        event_type="application_assigned",
        recipient=_recipient(user_id="officer-1", role="loan_officer"),
        channels=["in_app"],
        payload=_payload(),
    )
    settings.MONGODB[NotificationDelivery.collection_name].update_one(
        {"_id": ObjectId(result["delivery_id"])},
        {
            "$set": {
                "status": "sending",
                "next_attempt_at": None,
                "lease_started_at": datetime.now(timezone.utc) - timedelta(seconds=301),
            }
        },
    )

    outcomes = reconcile_notification_deliveries(limit=10)
    assert outcomes["delivered"] == 1


def test_optional_email_preference_denies_without_calling_provider(
    monkeypatch, settings
):
    customer = _customer(loan_updates=False)
    result, _delay = _queue_without_worker(
        monkeypatch,
        event_key="preference-denied",
        event_type="loan_approved",
        recipient=_recipient(customer),
        channels=["email"],
        payload=_payload(
            email={
                "subject": "Loan update",
                "template_name": "loan_approved",
                "context": {"name": customer.full_name, "loan_id": "loan-1"},
            }
        ),
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(EmailSender, "send", send)

    assert deliver_notification(result["delivery_id"]) == "suppressed"
    send.assert_not_called()
    raw = settings.MONGODB[NotificationDelivery.collection_name].find_one(
        {"_id": ObjectId(result["delivery_id"])}
    )
    assert raw["status"] == "suppressed"
    assert raw["preference_key"] == "email_loan_updates"
    assert raw["preference_allowed"] is False
    assert raw["policy_version"] == settings.NOTIFICATIONS_PREFERENCE_POLICY_VERSION


def test_allowed_email_retries_without_repeating_inbox_creation(monkeypatch, settings):
    customer = _customer(loan_updates=True)
    result, _delay = _queue_without_worker(
        monkeypatch,
        event_key="email-retry",
        event_type="loan_approved",
        recipient=_recipient(customer),
        channels=["in_app", "email"],
        payload=_payload(
            email={
                "subject": "Loan update",
                "template_name": "loan_approved",
                "context": {"name": customer.full_name, "loan_id": "loan-1"},
            }
        ),
    )
    send = MagicMock(side_effect=[False, True])
    monkeypatch.setattr(EmailSender, "send", send)

    assert deliver_notification(result["delivery_id"]) == "retry_wait"
    settings.MONGODB[NotificationDelivery.collection_name].update_one(
        {"_id": ObjectId(result["delivery_id"])},
        {"$set": {"next_attempt_at": datetime.now(timezone.utc)}},
    )
    assert deliver_notification(result["delivery_id"]) == "delivered"
    assert send.call_count == 2
    assert settings.MONGODB[Notification.collection_name].count_documents({}) == 1


def test_mandatory_security_email_ignores_optional_preferences(monkeypatch):
    customer = _customer(loan_updates=False, payment_reminders=False, promotions=False)
    decision = evaluate_email_policy(
        user_id=customer.id,
        user_type="customer",
        event_type="password_changed",
    )
    assert decision["allowed"] is True
    assert decision["preference_key"] is None


def test_domain_email_helper_suppresses_email_but_keeps_inbox_policy_record(
    monkeypatch,
):
    customer = _customer(loan_updates=False)
    notification = SimpleNamespace(id="notification-1")
    create = MagicMock(return_value=notification)
    send = MagicMock(return_value=True)
    monkeypatch.setattr(
        "notifications.services.email_sender.create_and_broadcast_notification", create
    )
    monkeypatch.setattr(EmailSender, "send", send)

    result = EmailSender().send_loan_approved(
        customer_email=customer.email,
        customer_name=customer.full_name,
        loan_id="loan-1",
        approved_amount="1000.00",
        customer_id=customer.id,
        delivery_key="loan-event-1",
    )

    assert result is True
    decision = send.call_args.kwargs["email_policy_decision"]
    assert decision["allowed"] is False
    assert create.call_args.kwargs["metadata"]["email_policy"]["allowed"] is False


def test_partial_push_retry_checkpoints_successful_tokens(monkeypatch, settings):
    first = DeviceToken.register(
        user_id="customer-1",
        user_type="customer",
        session_id="session-1",
        token="push-token-first-1234567890",
        platform="android",
    )
    second = DeviceToken.register(
        user_id="customer-1",
        user_type="customer",
        session_id="session-1",
        token="push-token-second-1234567890",
        platform="android",
    )
    result, _delay = _queue_without_worker(
        monkeypatch,
        event_key="push-retry",
        event_type="password_changed",
        recipient=_recipient(),
        channels=["push"],
        payload=_payload(notification_id="notification-1"),
    )
    push = MagicMock(
        side_effect=[
            {
                "attempted": 2,
                "succeeded": 1,
                "failed": 1,
                "deactivated": 0,
                "succeeded_hashes": [first.token_hash],
                "permanent_failure_hashes": [],
                "transient_failure_hashes": [second.token_hash],
                "error_code": "",
            },
            {
                "attempted": 1,
                "succeeded": 1,
                "failed": 0,
                "deactivated": 0,
                "succeeded_hashes": [second.token_hash],
                "permanent_failure_hashes": [],
                "transient_failure_hashes": [],
                "error_code": "",
            },
        ]
    )
    monkeypatch.setattr("notifications.services.delivery._send_push_notification", push)

    assert deliver_notification(result["delivery_id"]) == "retry_wait"
    first_call_hashes = set(push.call_args_list[0].kwargs["only_token_hashes"])
    assert first_call_hashes == {first.token_hash, second.token_hash}
    settings.MONGODB[NotificationDelivery.collection_name].update_one(
        {"_id": ObjectId(result["delivery_id"])},
        {"$set": {"next_attempt_at": datetime.now(timezone.utc)}},
    )
    assert deliver_notification(result["delivery_id"]) == "delivered"
    assert push.call_args_list[1].kwargs["only_token_hashes"] == [second.token_hash]


def test_assignment_and_security_producers_queue_durable_channels(monkeypatch):
    queued = []
    monkeypatch.setattr(
        assignment_events,
        "queue_notification_delivery",
        lambda **kwargs: queued.append(kwargs) or {"delivery_id": "delivery-1"},
    )
    assignment_events.publish_assignment_notifications(
        entity_name="Customer loan",
        assigned_by=_recipient(user_id="admin-1", role="admin"),
        assigned_to=_recipient(user_id="officer-1", role="loan_officer"),
        related_type="loan",
        related_id="loan-1",
        transition_id="transition-1",
    )
    assert len(queued) == 2
    assert all(item["channels"] == ["in_app"] for item in queued)

    queued.clear()
    monkeypatch.setattr(
        "notifications.services.delivery.queue_notification_delivery",
        lambda **kwargs: queued.append(kwargs) or {"delivery_id": "delivery-2"},
    )
    user = SimpleNamespace(
        id="customer-1",
        email="customer@example.test",
        full_name="Customer",
    )
    SecurityEventService.record(
        user=user,
        user_type="customer",
        action="password_changed",
        record_audit=False,
    )
    assert queued[0]["channels"] == ["in_app", "push"]
