import json
from datetime import datetime, timezone
import mongomock
import pytest
from channels.testing import WebsocketCommunicator
from django.conf import settings
from rest_framework_simplejwt.tokens import AccessToken

from config.asgi import application
from notifications.consumers import NotificationConsumer


@pytest.fixture
def mock_mongodb(monkeypatch):
    client = mongomock.MongoClient()
    monkeypatch.setattr(settings, "MONGODB", client["testdb"])
    return client["testdb"]


@pytest.fixture
def test_user():
    from accounts.authentication import AuthenticatedUser
    return AuthenticatedUser(
        customer_id="test_user_123",
        email="test@example.com",
        verified=True,
        role="customer"
    )


@pytest.fixture
def valid_token(test_user, monkeypatch):
    from datetime import timedelta

    monkeypatch.setattr(settings, "SIMPLE_JWT", {
        "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    })

    token = AccessToken()
    token["customer_id"] = test_user.customer_id
    token["email"] = test_user.email
    token["verified"] = test_user.verified
    token["role"] = test_user.role
    return str(token)


@pytest.fixture(autouse=True)
def setup_ws_settings(monkeypatch):
    monkeypatch.setattr(settings, "WEBSOCKET_ENABLED", True)


async def test_websocket_connection_with_valid_token(mock_mongodb, valid_token):
    communicator = WebsocketCommunicator(
        application,
        f"/ws/notifications/?token={valid_token}"
    )
    connected, _ = await communicator.connect()
    assert connected

    response = await communicator.receive_json_from()
    assert response["type"] == "connection_established"
    assert "unread_count" in response["data"]

    await communicator.disconnect()


async def test_websocket_rejects_invalid_token():
    communicator = WebsocketCommunicator(
        application,
        "/ws/notifications/?token=invalid_token"
    )
    connected, close_code = await communicator.connect()
    assert not connected
    assert close_code == 4001


async def test_websocket_ping_pong(mock_mongodb, valid_token):
    communicator = WebsocketCommunicator(
        application,
        f"/ws/notifications/?token={valid_token}"
    )
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to({"action": "ping"})

    response = await communicator.receive_json_from()
    assert response["type"] == "pong"
    assert "timestamp" in response

    await communicator.disconnect()


async def test_notification_broadcast(mock_mongodb, valid_token):
    from notifications.services.websocket_service import broadcast_notification_to_user

    communicator = WebsocketCommunicator(
        application,
        f"/ws/notifications/?token={valid_token}"
    )
    connected, _ = await communicator.connect()
    assert connected

    received = await communicator.receive_json_from()
    assert received["type"] == "connection_established"

    test_notification = {
        "id": "notif_123",
        "notification_type": "loan_approved",
        "subject": "Test Notification",
        "message": "This is a test",
        "channel": "in_app",
        "status": "sent",
        "is_read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    broadcast_notification_to_user("test_user_123", test_notification)

    response = await communicator.receive_json_from(timeout=2)
    assert response["type"] == "notification"
    assert response["data"]["subject"] == "Test Notification"

    await communicator.disconnect()