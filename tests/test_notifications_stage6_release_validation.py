"""Offline evidence for the fail-closed Notifications Stage 6 gate."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from notifications.services.operations import (
    EXPECTED_NOTIFICATION_INDEXES,
    notification_release_readiness,
)
from notifications.services.persistence import NOTIFICATION_VALIDATORS


def _clean_inventory():
    from notifications.services.operations import INVENTORY_BLOCKERS

    return {
        "complete": True,
        **{name: 0 for name in INVENTORY_BLOCKERS},
    }


def test_release_command_is_read_only_and_fails_closed(settings):
    report = {"ready": False, "checks": {"deployment_mongodb_verified": False}}
    with patch(
        "notifications.management.commands.notifications_release_check."
        "notification_release_readiness",
        return_value=report,
    ) as readiness, pytest.raises(CommandError, match="readiness checks failed"):
        call_command("notifications_release_check", stdout=StringIO())
    readiness.assert_called_once_with(settings.MONGODB)


def test_release_gate_passes_only_with_all_bound_evidence(settings, monkeypatch):
    settings.DEBUG = False
    settings.FIELD_ENCRYPTION_KEY = "configured"
    settings.FIELD_ENCRYPTION_STRICT_DECRYPTION = True
    settings.PROMETHEUS_METRICS_ENABLED = True
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.CELERY_BROKER_URL = "redis://broker/0"
    settings.CELERY_RESULT_BACKEND = "redis://broker/0"
    settings.CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}
    }
    settings.WEBSOCKET_ENABLED = True
    settings.ALLOWED_HOSTS = ["api.example.test"]
    settings.CORS_ALLOW_ALL_ORIGINS = False
    settings.AUTH_COOKIE_SECURE = True
    settings.AUTH_COOKIE_HTTPONLY = True
    settings.SESSION_COOKIE_SECURE = True
    settings.SESSION_COOKIE_HTTPONLY = True
    settings.CSRF_COOKIE_SECURE = True
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings.EMAIL_HOST = "smtp.example.test"
    settings.EMAIL_HOST_USER = "synthetic@example.test"
    settings.DEFAULT_FROM_EMAIL = "synthetic@example.test"
    for name in (
        "NOTIFICATIONS_RETENTION_POLICY_APPROVED",
        "NOTIFICATIONS_DEPLOYMENT_MONGODB_VERIFIED",
        "NOTIFICATIONS_REDIS_CHANNELS_CELERY_VERIFIED",
        "NOTIFICATIONS_SMTP_VERIFIED",
        "NOTIFICATIONS_FIREBASE_VERIFIED",
        "NOTIFICATIONS_HTTPS_WSS_LOAD_VERIFIED",
        "NOTIFICATIONS_BACKUP_RESTORE_VERIFIED",
        "NOTIFICATIONS_SECRET_ROTATION_VERIFIED",
        "NOTIFICATIONS_INCIDENT_ROLLBACK_APPROVED",
        "NOTIFICATIONS_MONITORING_ALERTS_VERIFIED",
        "NOTIFICATIONS_FULL_SUITE_SMOKE_VERIFIED",
    ):
        setattr(settings, name, True)
    monkeypatch.setattr(
        "notifications.services.operations.inventory_notification_data",
        lambda db=None, limit=10_000: _clean_inventory(),
    )
    monkeypatch.setattr(
        "notifications.services.operations.notification_health_summary",
        lambda db=None: {"ready": True, "status": "ready"},
    )

    database = MagicMock()

    def command(argument, *args, **kwargs):
        if argument == "ping":
            return {"ok": 1}
        if isinstance(argument, dict) and argument.get("listCollections") == 1:
            assert argument["filter"]["name"] in NOTIFICATION_VALIDATORS
            return {
                "cursor": {
                    "firstBatch": [{"options": {"validator": {"$jsonSchema": {}}}}]
                }
            }
        raise AssertionError(f"Unexpected command: {argument!r}")

    database.command.side_effect = command
    collections = {}
    for collection, names in EXPECTED_NOTIFICATION_INDEXES.items():
        collections[collection] = MagicMock()
        collections[collection].index_information.return_value = {
            name: {} for name in names
        }
    database.__getitem__.side_effect = collections.__getitem__

    report = notification_release_readiness(database)

    assert report["ready"] is True, report
    assert all(report["checks"].values())
    assert all(report["index_checks"].values())
    assert all(report["validator_checks"].values())


def test_unavailable_database_is_safe_and_fails_every_database_gate(settings):
    database = MagicMock()
    database.command.side_effect = RuntimeError("mongodb://secret/private")

    report = notification_release_readiness(database)

    assert report["ready"] is False
    assert report["checks"]["mongodb_connected"] is False
    assert report["checks"]["required_indexes_present"] is False
    assert report["checks"]["validators_present"] is False
    assert report["checks"]["inventory_clean_and_complete"] is False
    assert report["inventory"]["status"] == "mongodb_unavailable"
    assert "mongodb://secret/private" not in repr(report)


def test_inventory_accepts_database_that_forbids_truth_testing(settings):
    class Database:
        def __bool__(self):
            raise NotImplementedError

        def __getitem__(self, name):
            return settings.MONGODB[name]

    from notifications.services.persistence import inventory_notification_data

    report = inventory_notification_data(db=Database(), limit=10)
    assert report["complete"] is True
    assert report["limit"] == 10


def test_schema_install_fails_closed_when_inventory_is_incomplete():
    with patch(
        "notifications.management.commands.install_notification_schema."
        "inventory_notification_data",
        return_value={"complete": False},
    ), pytest.raises(CommandError, match="inventory is not clean"):
        call_command("install_notification_schema", apply=True, stdout=StringIO())
