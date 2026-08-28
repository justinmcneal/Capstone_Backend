"""Stage 5 WebSocket resilience, synchronization, and operations evidence."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.urls import re_path

from config.celery import app as celery_app
from notifications.consumer import NotificationConsumer
from notifications.models.delivery import NotificationDelivery
from notifications.services.operations import (
    notification_health_summary,
    notification_operational_summary,
)


class _User:
    is_authenticated = True

    def __init__(self, customer_id="stage5-user"):
        self.customer_id = customer_id
        self.role = "customer"


def _app():
    return URLRouter([re_path(r"ws/notifications/$", NotificationConsumer.as_asgi())])


@pytest.fixture(autouse=True)
def _stage5_channel_layer(settings):
    settings.CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }
    NotificationConsumer._connections_by_owner.clear()
    yield
    NotificationConsumer._connections_by_owner.clear()


@pytest.mark.anyio
async def test_revoked_connection_closes_before_processing_action():
    communicator = WebsocketCommunicator(_app(), "/ws/notifications/")
    communicator.scope["user"] = _User()
    with patch.object(
        NotificationConsumer, "get_unread_count", new_callable=AsyncMock, return_value=0
    ), patch.object(
        NotificationConsumer,
        "connection_is_current",
        new_callable=AsyncMock,
        return_value=False,
    ):
        assert (await communicator.connect())[0] is True
        await communicator.receive_json_from()
        await communicator.send_json_to({"action": "ping"})
        assert await communicator.receive_output() == {
            "type": "websocket.close",
            "code": 4002,
        }
    await communicator.disconnect()


@pytest.mark.anyio
async def test_binary_or_oversized_frame_is_closed(settings):
    settings.NOTIFICATIONS_WS_MAX_MESSAGE_BYTES = 1024
    communicator = WebsocketCommunicator(_app(), "/ws/notifications/")
    communicator.scope["user"] = _User()
    with patch.object(
        NotificationConsumer, "get_unread_count", new_callable=AsyncMock, return_value=0
    ):
        assert (await communicator.connect())[0] is True
        established = await communicator.receive_json_from()
        assert established["data"]["sync_required"] is True
        assert established["data"]["contract_version"] == 2
        await communicator.send_to(text_data="x" * 1025)
        assert (await communicator.receive_output())["code"] == 4005
    await communicator.disconnect()


@pytest.mark.anyio
async def test_per_process_owner_connection_limit(settings):
    settings.NOTIFICATIONS_WS_MAX_CONNECTIONS_PER_USER = 1
    first = WebsocketCommunicator(_app(), "/ws/notifications/")
    second = WebsocketCommunicator(_app(), "/ws/notifications/")
    first.scope["user"] = _User()
    second.scope["user"] = _User()
    with patch.object(
        NotificationConsumer, "get_unread_count", new_callable=AsyncMock, return_value=0
    ):
        assert (await first.connect())[0] is True
        await first.receive_json_from()
        connected, code = await second.connect()
        assert connected is False
        assert code == 4004
    await first.disconnect()
    await second.disconnect()


@pytest.mark.anyio
async def test_mark_read_broadcasts_cross_device_state():
    first = WebsocketCommunicator(_app(), "/ws/notifications/")
    second = WebsocketCommunicator(_app(), "/ws/notifications/")
    first.scope["user"] = _User()
    second.scope["user"] = _User()
    with patch.object(
        NotificationConsumer, "get_unread_count", new_callable=AsyncMock, return_value=1
    ), patch.object(
        NotificationConsumer,
        "mark_notification_read",
        new_callable=AsyncMock,
        return_value={"success": True, "replayed": False},
    ):
        assert (await first.connect())[0] is True
        assert (await second.connect())[0] is True
        await first.receive_json_from()
        await second.receive_json_from()
        await first.send_json_to(
            {"action": "mark_read", "notification_id": "notification-1"}
        )
        assert (await first.receive_json_from())["type"] == "mark_read_response"
        first_state = await first.receive_json_from()
        second_state = await second.receive_json_from()
        assert first_state == second_state
        assert second_state == {
            "type": "inbox_state",
            "data": {
                "action": "mark_read",
                "notification_id": "notification-1",
                "replayed": False,
            },
        }
    await first.disconnect()
    await second.disconnect()


def test_operational_summary_and_health_are_identifier_free(settings):
    now = datetime.now(timezone.utc)
    settings.MONGODB[NotificationDelivery.collection_name].insert_many(
        [
            {"status": "pending", "created_at": now - timedelta(minutes=20)},
            {"status": "failed", "created_at": now - timedelta(minutes=1)},
        ]
    )
    summary = notification_operational_summary(settings.MONGODB)
    health = notification_health_summary(settings.MONGODB)
    assert summary["backlog"]["pending"] == 1
    assert summary["backlog"]["failed"] == 1
    assert summary["oldest_age_seconds"] >= 1200
    assert health["ready"] is False
    assert "stage5-user" not in json.dumps(health)


def test_stage5_task_and_monitoring_assets_are_declared(settings):
    assert settings.CELERY_TASK_ROUTES["notifications.collect_operational_metrics"] == {
        "queue": "notifications"
    }
    schedule = celery_app.conf.beat_schedule["collect-notification-operational-metrics"]
    assert schedule["task"] == "notifications.collect_operational_metrics"
    celery_app.loader.import_task_module("notifications.tasks")
    assert "notifications.collect_operational_metrics" in celery_app.tasks

    root = Path(settings.BASE_DIR) / "monitoring" / "notifications"
    required = {
        "prometheus-rules.yml",
        "prometheus-rules.test.yml",
        "prometheus-smoke.yml",
        "grafana-dashboard.json",
    }
    assert required == {item.name for item in root.iterdir() if item.is_file()}
    rules = (root / "prometheus-rules.yml").read_text()
    assert "NotificationsDeliveryBacklogOld" in rules
    assert "NotificationsWebSocketRevocations" in rules
    dashboard = json.loads((root / "grafana-dashboard.json").read_text())
    assert dashboard["uid"] == "capstone-notifications"
    assert len(dashboard["panels"]) >= 4
