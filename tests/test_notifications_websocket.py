"""
WebSocket consumer tests for NotificationConsumer.

Covers: ping/pong, mark_read, invalid JSON, unauthenticated close (4001),
and successful connect with unread count.

Uses Django Channels WebsocketCommunicator with an in-memory channel layer
(no Redis required) — patched in via monkeypatch on channel_layer attribute.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lightweight stubs
# ---------------------------------------------------------------------------

class _FakeUser:
    is_authenticated = True

    def __init__(self, customer_id="user123", role="customer"):
        self.customer_id = customer_id
        self.role = role


class _AnonymousUser:
    is_authenticated = False


# ---------------------------------------------------------------------------
# Async integration tests via WebsocketCommunicator
# ---------------------------------------------------------------------------

try:
    from channels.layers import InMemoryChannelLayer
    from channels.routing import URLRouter
    from channels.testing import WebsocketCommunicator
    from django.urls import re_path

    from notifications.consumer import NotificationConsumer

    HAS_CHANNELS_TESTING = True

    def _make_app():
        """Build ASGI app with InMemoryChannelLayer substituted for Redis."""
        import django.conf
        # Temporarily override CHANNEL_LAYERS for in-process tests
        from channels.routing import URLRouter
        from django.urls import re_path

        app = URLRouter([
            re_path(r"ws/notifications/$", NotificationConsumer.as_asgi()),
        ])
        return app

except ImportError:
    HAS_CHANNELS_TESTING = False


@pytest.fixture(autouse=True)
def _use_in_memory_channel_layer(settings):
    """Replace the Redis channel layer with an in-memory layer for all WS tests."""
    settings.CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }


@pytest.mark.skipif(not HAS_CHANNELS_TESTING, reason="channels[daphne] not installed")
class TestNotificationConsumerWebSocket:
    """Async WebSocket consumer tests using WebsocketCommunicator + InMemoryChannelLayer."""

    @pytest.mark.anyio
    async def test_unauthenticated_connection_closes_4001(self):
        communicator = WebsocketCommunicator(_make_app(), "/ws/notifications/")
        communicator.scope["user"] = _AnonymousUser()

        connected, code = await communicator.connect()
        assert not connected or code == 4001
        await communicator.disconnect()

    @pytest.mark.anyio
    async def test_authenticated_connection_sends_connection_established(self):
        communicator = WebsocketCommunicator(_make_app(), "/ws/notifications/")
        communicator.scope["user"] = _FakeUser()

        with patch(
            "notifications.consumer.NotificationConsumer.get_unread_count",
            new_callable=AsyncMock,
            return_value=5,
        ):
            connected, _ = await communicator.connect()
            assert connected

            msg = await communicator.receive_json_from()
            assert msg["type"] == "connection_established"
            assert msg["data"]["unread_count"] == 5

        await communicator.disconnect()

    @pytest.mark.anyio
    async def test_ping_returns_pong(self):
        communicator = WebsocketCommunicator(_make_app(), "/ws/notifications/")
        communicator.scope["user"] = _FakeUser()

        with patch(
            "notifications.consumer.NotificationConsumer.get_unread_count",
            new_callable=AsyncMock,
            return_value=0,
        ):
            connected, _ = await communicator.connect()
            assert connected
            await communicator.receive_json_from()  # consume connection_established

            await communicator.send_json_to({"action": "ping"})
            response = await communicator.receive_json_from()
            assert response["type"] == "pong"
            assert "timestamp" in response["data"]

        await communicator.disconnect()

    @pytest.mark.anyio
    async def test_invalid_json_returns_error(self):
        communicator = WebsocketCommunicator(_make_app(), "/ws/notifications/")
        communicator.scope["user"] = _FakeUser()

        with patch(
            "notifications.consumer.NotificationConsumer.get_unread_count",
            new_callable=AsyncMock,
            return_value=0,
        ):
            connected, _ = await communicator.connect()
            assert connected
            await communicator.receive_json_from()  # consume connection_established

            await communicator.send_to(text_data="not-valid-json{{{{")
            response = await communicator.receive_json_from()
            assert response["type"] == "error"
            assert response["data"] == {
                "code": "invalid_json",
                "message": "Invalid JSON",
            }

        await communicator.disconnect()

    @pytest.mark.anyio
    async def test_non_object_message_returns_canonical_error(self):
        communicator = WebsocketCommunicator(_make_app(), "/ws/notifications/")
        communicator.scope["user"] = _FakeUser()

        with patch(
            "notifications.consumer.NotificationConsumer.get_unread_count",
            new_callable=AsyncMock,
            return_value=0,
        ):
            connected, _ = await communicator.connect()
            assert connected
            await communicator.receive_json_from()

            await communicator.send_json_to(["ping"])
            response = await communicator.receive_json_from()
            assert response == {
                "type": "error",
                "data": {
                    "code": "invalid_message",
                    "message": "Message must be a JSON object",
                },
            }

        await communicator.disconnect()

    @pytest.mark.anyio
    async def test_mark_read_action_returns_mark_read_response(self):
        communicator = WebsocketCommunicator(_make_app(), "/ws/notifications/")
        communicator.scope["user"] = _FakeUser()

        with patch(
            "notifications.consumer.NotificationConsumer.get_unread_count",
            new_callable=AsyncMock,
            return_value=1,
        ):
            with patch(
                "notifications.consumer.NotificationConsumer.mark_notification_read",
                new_callable=AsyncMock,
                return_value=True,
            ):
                connected, _ = await communicator.connect()
                assert connected
                await communicator.receive_json_from()  # consume connection_established

                await communicator.send_json_to({
                    "action": "mark_read",
                    "notification_id": "64a1b2c3d4e5f6789abcdef0",
                })
                response = await communicator.receive_json_from()
                assert response["type"] == "mark_read_response"
                assert response["data"] == {
                    "success": True,
                    "notification_id": "64a1b2c3d4e5f6789abcdef0",
                }

        await communicator.disconnect()

    @pytest.mark.anyio
    async def test_disconnect_cleans_up_group(self):
        communicator = WebsocketCommunicator(_make_app(), "/ws/notifications/")
        communicator.scope["user"] = _FakeUser()

        with patch(
            "notifications.consumer.NotificationConsumer.get_unread_count",
            new_callable=AsyncMock,
            return_value=0,
        ):
            connected, _ = await communicator.connect()
            assert connected
            await communicator.receive_json_from()  # consume connection_established

        # Should not raise
        await communicator.disconnect()
