"""Stage 4 privacy lifecycle and MongoDB-shape evidence for Notifications."""

import json
import logging
from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command

from config import field_encryption
from config.celery import app as celery_app
from config.field_encryption import is_encrypted_value
from notifications.models.delivery import NotificationDelivery
from notifications.models.device_token import DeviceToken
from notifications.models.notification import Notification
from notifications.services.email_sender import EmailSender
from notifications.services.lifecycle import (
    delete_customer_notification_data,
    enforce_notification_retention,
    export_customer_notifications,
)
from notifications.services.persistence import (
    NOTIFICATION_VALIDATORS,
    inventory_notification_data,
)


@pytest.fixture(autouse=True)
def _clear_encryption_cache():
    yield
    field_encryption._build_keyring.cache_clear()
    field_encryption._get_fernet.cache_clear()


def _enable_encryption(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = ()
    settings.FIELD_ENCRYPTION_STRICT_DECRYPTION = True
    field_encryption._build_keyring.cache_clear()
    field_encryption._get_fernet.cache_clear()


def _notification(customer_id="customer-1", **values):
    payload = {
        "subject": "Private loan outcome",
        "message": "Your private application was approved.",
        **values,
    }
    return Notification(
        user_id=customer_id,
        user_type="customer",
        recipient_email="customer@example.test",
        recipient_name="Private Customer",
        notification_type="loan_approved",
        related_type="loan",
        related_id="loan-private-1",
        metadata={"customer_name": "Private Customer"},
        channel="in_app",
        status="sent",
        **payload,
    )


def test_core_notification_sensitive_fields_are_encrypted_and_key_is_hashed(settings):
    _enable_encryption(settings)
    notification, created = Notification.create_idempotent(
        _notification(), "loan:private-customer:transition-1"
    )
    raw = settings.MONGODB[Notification.collection_name].find_one(
        {"_id": notification._id}
    )

    assert created is True
    for field in Notification.encrypted_fields:
        if raw.get(field) not in (None, ""):
            assert is_encrypted_value(raw[field])
    assert raw["idempotency_key_hash"] == Notification.fingerprint(
        "loan:private-customer:transition-1"
    )
    assert "private-customer" not in json.dumps(raw, default=str)
    assert Notification.from_dict(raw).message == _notification().message


def test_export_is_bounded_decrypted_and_explicit_about_truncation(settings):
    _enable_encryption(settings)
    for index in range(3):
        _notification(subject=f"Outcome {index}").save()

    exported = export_customer_notifications(settings.MONGODB, "customer-1", limit=2)

    assert exported["total"] == 3
    assert exported["returned"] == 2
    assert exported["truncated"] is True
    assert exported["items"][0]["subject"].startswith("Outcome")
    assert "recipient_email" not in exported["items"][0]
    assert "idempotency_key" not in exported["items"][0]


def test_account_cleanup_erases_inbox_delivery_and_device_credentials(settings):
    _enable_encryption(settings)
    _notification().save()
    NotificationDelivery.ensure(
        event_key="cleanup-event",
        event_type="password_changed",
        recipient={
            "id": "customer-1",
            "user_type": "customer",
            "email": "customer@example.test",
            "name": "Private Customer",
        },
        channels=["push"],
        payload={"subject": "Security", "message": "Changed"},
    )
    DeviceToken.register(
        user_id="customer-1",
        user_type="customer",
        session_id="session-1",
        token="stage-four-device-token-1234567890",
        platform="android",
    )

    counts = delete_customer_notification_data(settings.MONGODB, "customer-1")

    assert counts["remaining"] == 0
    assert counts["notifications"] == 1
    assert counts["notification_deliveries"] == 1
    assert counts["device_tokens"] == 1
    assert (
        delete_customer_notification_data(settings.MONGODB, "customer-1")["remaining"]
        == 0
    )


def test_account_cleanup_pseudonymizes_a_legally_held_notification(settings):
    _enable_encryption(settings)
    held = _notification(legal_hold=True, legal_hold_reason="Active dispute").save()

    counts = delete_customer_notification_data(settings.MONGODB, "customer-1")
    raw = settings.MONGODB[Notification.collection_name].find_one({"_id": held._id})
    retained = Notification.from_dict(raw)

    assert counts["remaining"] == 0
    assert counts["notifications_pseudonymized"] == 1
    assert retained.user_id == counts["pseudonym"]
    assert retained.recipient_email == ""
    assert retained.recipient_name == ""
    assert retained.legal_hold is True


def test_retention_is_bounded_and_respects_legal_hold(settings):
    now = datetime.now(timezone.utc)
    due = _notification(
        retention_expires_at=now - timedelta(days=1), legal_hold=False
    ).save()
    held = _notification(
        retention_expires_at=now - timedelta(days=1), legal_hold=True
    ).save()
    future = _notification(
        retention_expires_at=now + timedelta(days=1), legal_hold=False
    ).save()
    result = enforce_notification_retention(limit=10, now=now)

    assert result["notifications_deleted"] == 1
    collection = settings.MONGODB[Notification.collection_name]
    assert collection.find_one({"_id": due._id}) is None
    assert collection.find_one({"_id": held._id}) is not None
    assert collection.find_one({"_id": future._id}) is not None


def test_inventory_and_backfill_are_dry_run_first(settings):
    created_at = datetime.now(timezone.utc) - timedelta(days=2)
    raw_id = (
        settings.MONGODB[Notification.collection_name]
        .insert_one(
            {
                "user_id": "legacy-customer",
                "notification_type": "loan_submitted",
                "status": "read",
                "channel": "in_app",
                "created_at": created_at,
                "subject": "legacy plaintext",
                "idempotency_key": "legacy-key",
            }
        )
        .inserted_id
    )
    settings.MONGODB[NotificationDelivery.collection_name].insert_one(
        {
            "event_key": "legacy-event-key",
            "recipient_key": "recipient-key",
        }
    )

    before = inventory_notification_data()
    output = StringIO()
    call_command("backfill_notification_data", stdout=output)
    unchanged = settings.MONGODB[Notification.collection_name].find_one({"_id": raw_id})

    assert before["legacy_read_status"] == 1
    assert before["missing_retention"] == 1
    assert "DRY-RUN" in output.getvalue()
    assert unchanged["status"] == "read"

    call_command("backfill_notification_data", apply=True, stdout=StringIO())
    repaired = settings.MONGODB[Notification.collection_name].find_one({"_id": raw_id})
    delivery = settings.MONGODB[NotificationDelivery.collection_name].find_one()
    assert repaired["user_type"] == "customer"
    assert repaired["is_read"] is True
    assert repaired["delivery_status"] == "unknown"
    repaired_retention = repaired["retention_expires_at"].replace(tzinfo=timezone.utc)
    assert repaired_retention > created_at
    assert repaired["idempotency_key_hash"] == Notification.fingerprint("legacy-key")
    assert delivery["event_key"] == Notification.fingerprint("legacy-event-key")


def test_indexes_validators_and_retention_task_are_declared(settings):
    Notification.create_indexes()
    DeviceToken.create_indexes()
    NotificationDelivery.create_indexes()
    index_names = set(
        settings.MONGODB[Notification.collection_name].index_information()
    )
    assert {
        "notification_owner_created_page",
        "notification_owner_read_page",
        "notification_owner_channel_page",
        "notification_retention_due",
        "unique_notification_idempotency_hash",
    } <= index_names
    assert set(NOTIFICATION_VALIDATORS) == {
        "notifications",
        "device_tokens",
        "notification_deliveries",
    }
    assert settings.CELERY_TASK_ROUTES["notifications.enforce_retention"] == {
        "queue": "notifications"
    }
    retention_schedule = celery_app.conf.beat_schedule[
        "enforce-notification-retention-daily"
    ]
    assert retention_schedule["task"] == "notifications.enforce_retention"
    celery_app.loader.import_task_module("notifications.tasks")
    assert "notifications.enforce_retention" in celery_app.tasks


def test_email_logs_and_stored_failure_do_not_expose_provider_or_recipient(
    monkeypatch, caplog
):
    class Email:
        def __init__(self, *args, **kwargs):
            pass

        def attach_alternative(self, *args, **kwargs):
            pass

        def send(self, **kwargs):
            raise RuntimeError("SMTP secret provider body")

    notification = type(
        "Record",
        (),
        {
            "id": "notification-1",
            "mark_failed": lambda self, value: setattr(self, "error", value),
        },
    )()
    monkeypatch.setattr(
        "notifications.services.email_sender.render_to_string", lambda *args: "body"
    )
    monkeypatch.setattr(
        "notifications.services.email_sender.EmailMultiAlternatives", Email
    )
    caplog.set_level(logging.INFO, logger="notifications")

    assert (
        EmailSender().send(
            "private@example.test",
            "Private subject",
            "loan_approved",
            {},
            notification,
        )
        is False
    )
    combined = caplog.text
    assert notification.error == "email_delivery_failed"
    assert "private@example.test" not in combined
    assert "Private subject" not in combined
    assert "SMTP secret provider body" not in combined
