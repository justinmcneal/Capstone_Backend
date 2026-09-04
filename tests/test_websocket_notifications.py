from datetime import datetime, timezone

import mongomock
import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import InMemoryChannelLayer, channel_layers
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.http import HttpResponse
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import Admin, Customer, LoanOfficer
from accounts.utils.auth_cookies import set_auth_cookies
from accounts.utils.token_utils import TokenUtils
from config.asgi import application


@pytest.fixture
def mock_mongodb(monkeypatch):
    client = mongomock.MongoClient()
    monkeypatch.setattr(settings, "MONGODB", client["testdb"])
    return client["testdb"]


@pytest.fixture
def mobile_session(mock_mongodb):
    customer = Customer(
        first_name="Mobile",
        last_name="Customer",
        email="mobile@example.com",
        password="test-password-hash",
        verified=True,
    )
    customer.save()
    return customer, TokenUtils.generate_jwt_tokens(customer)


@pytest.fixture
def staff_session(mock_mongodb):
    admin = Admin(
        username="socket-admin",
        email="socket-admin@example.com",
        active=True,
        security_version=1,
        must_change_password=False,
    )
    admin.save()
    return admin, TokenUtils.generate_tokens(
        user_id=admin.id,
        email=admin.email,
        role="admin",
        security_version=admin.security_version,
        token_transport="cookie",
    )


@pytest.fixture(autouse=True)
def setup_ws_settings(monkeypatch):
    monkeypatch.setattr(settings, "WEBSOCKET_ENABLED", True)
    previous_layer = channel_layers.backends.get("default")
    channel_layers.set("default", InMemoryChannelLayer())
    yield
    if previous_layer is None:
        channel_layers.backends.pop("default", None)
    else:
        channel_layers.set("default", previous_layer)


def _cookie_headers(access_token):
    cookie_name = settings.AUTH_ACCESS_COOKIE_NAME
    return [(b"cookie", f"{cookie_name}={access_token}".encode("ascii"))]


def test_mobile_query_token_connection_remains_supported(mobile_session):
    _, tokens = mobile_session

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            f"/ws/notifications/?token={tokens['access']}",
        )
        connected, _ = await communicator.connect()
        assert connected

        response = await communicator.receive_json_from()
        assert response["type"] == "connection_established"
        assert "unread_count" in response["data"]

        await communicator.disconnect()

    async_to_sync(exercise)()


def test_mobile_subprotocol_token_connection_remains_supported(mobile_session):
    _, tokens = mobile_session

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            subprotocols=["access_token", tokens["access"]],
        )
        connected, _ = await communicator.connect()
        assert connected

        response = await communicator.receive_json_from()
        assert response["type"] == "connection_established"
        await communicator.disconnect()

    async_to_sync(exercise)()


def test_staff_cookie_connection_uses_live_session(staff_session):
    _, tokens = staff_session

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=_cookie_headers(tokens["access"]),
        )
        connected, _ = await communicator.connect()
        assert connected

        response = await communicator.receive_json_from()
        assert response == {
            "type": "connection_established",
            "data": {
                "unread_count": 0,
                "sync_required": True,
                "contract_version": 2,
            },
        }
        await communicator.disconnect()

    async_to_sync(exercise)()


def test_connected_socket_closes_after_session_revocation(staff_session):
    admin, tokens = staff_session
    session_id = str(AccessToken(tokens["access"])["session_id"])

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=_cookie_headers(tokens["access"]),
        )
        connected, _ = await communicator.connect()
        assert connected
        await communicator.receive_json_from()

        await sync_to_async(TokenUtils.revoke_session)(
            admin.id,
            "admin",
            session_id,
        )
        await communicator.send_json_to({"action": "ping"})
        assert await communicator.receive_output() == {
            "type": "websocket.close",
            "code": 4002,
        }
        await communicator.disconnect()

    async_to_sync(exercise)()


def test_staff_query_token_is_rejected(staff_session):
    _, tokens = staff_session

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            f"/ws/notifications/?token={tokens['access']}",
        )
        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4001

    async_to_sync(exercise)()


def test_websocket_rejects_missing_credentials():
    async def exercise():
        communicator = WebsocketCommunicator(application, "/ws/notifications/")
        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4001

    async_to_sync(exercise)()


def test_websocket_rejects_invalid_token():
    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/?token=invalid_token",
        )
        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4001

    async_to_sync(exercise)()


def test_websocket_rejects_refresh_token_in_cookie(staff_session):
    _, tokens = staff_session

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=_cookie_headers(tokens["refresh"]),
        )
        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4001

    async_to_sync(exercise)()


def test_websocket_rejects_revoked_staff_session(staff_session):
    admin, tokens = staff_session
    session_id = AccessToken(tokens["access"])["session_id"]
    TokenUtils.revoke_session(admin.id, "admin", session_id)

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=_cookie_headers(tokens["access"]),
        )
        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4001

    async_to_sync(exercise)()


def test_websocket_rejects_blacklisted_staff_access_token(staff_session):
    _, tokens = staff_session
    assert TokenUtils.blacklist_token(tokens["access"], token_type="access")

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=_cookie_headers(tokens["access"]),
        )
        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4001

    async_to_sync(exercise)()


def test_websocket_rejects_stale_staff_security_version(staff_session, mock_mongodb):
    admin, tokens = staff_session
    mock_mongodb[Admin.collection_name].update_one(
        {"_id": admin._id},
        {"$set": {"security_version": admin.security_version + 1}},
    )

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=_cookie_headers(tokens["access"]),
        )
        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4001

    async_to_sync(exercise)()


def test_websocket_rejects_inactive_staff_account(staff_session, mock_mongodb):
    admin, tokens = staff_session
    mock_mongodb[Admin.collection_name].update_one(
        {"_id": admin._id},
        {"$set": {"active": False}},
    )

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=_cookie_headers(tokens["access"]),
        )
        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4001

    async_to_sync(exercise)()


def test_websocket_rejects_staff_pending_forced_password_change(
    staff_session, mock_mongodb
):
    admin, tokens = staff_session
    mock_mongodb[Admin.collection_name].update_one(
        {"_id": admin._id},
        {"$set": {"must_change_password": True}},
    )

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=_cookie_headers(tokens["access"]),
        )
        connected, close_code = await communicator.connect()
        assert not connected
        assert close_code == 4001

    async_to_sync(exercise)()


def test_websocket_ping_pong(mobile_session):
    _, tokens = mobile_session

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            f"/ws/notifications/?token={tokens['access']}",
        )
        connected, _ = await communicator.connect()
        assert connected

        connected_message = await communicator.receive_json_from()
        assert connected_message["type"] == "connection_established"

        await communicator.send_json_to({"action": "ping"})

        response = await communicator.receive_json_from()
        assert response["type"] == "pong"
        assert "timestamp" in response["data"]

        await communicator.disconnect()

    async_to_sync(exercise)()


def test_notification_broadcast(mobile_session):
    from notifications.services.websocket_service import broadcast_notification_to_user

    customer, tokens = mobile_session

    async def exercise():
        communicator = WebsocketCommunicator(
            application,
            f"/ws/notifications/?token={tokens['access']}",
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

        await sync_to_async(broadcast_notification_to_user)(
            customer.id, "customer", test_notification
        )

        response = await communicator.receive_json_from(timeout=2)
        assert response["type"] == "notification"
        assert response["data"]["subject"] == "Test Notification"

        await communicator.disconnect()

    async_to_sync(exercise)()


def test_same_id_staff_websocket_groups_remain_role_isolated(mock_mongodb):
    from notifications.services.websocket_service import broadcast_notification_to_user

    admin = Admin(
        username="shared-admin",
        email="shared-admin@example.com",
        active=True,
    ).save()
    shared_id = admin._id
    officer = LoanOfficer(
        _id=shared_id,
        first_name="Shared",
        last_name="Officer",
        email="shared-officer@example.com",
        employee_id="SHARED-WS-1",
        active=True,
        must_change_password=False,
    )
    mock_mongodb[LoanOfficer.collection_name].insert_one(officer.to_dict())
    admin_tokens = TokenUtils.generate_tokens(
        user_id=admin.id,
        email=admin.email,
        role="admin",
        token_transport="cookie",
    )
    officer_tokens = TokenUtils.generate_tokens(
        user_id=officer.id,
        email=officer.email,
        role="loan_officer",
        token_transport="cookie",
    )

    async def exercise():
        admin_socket = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=_cookie_headers(admin_tokens["access"]),
        )
        officer_socket = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=_cookie_headers(officer_tokens["access"]),
        )
        admin_connected, _ = await admin_socket.connect()
        officer_connected, _ = await officer_socket.connect()
        assert admin_connected and officer_connected
        await admin_socket.receive_json_from()
        await officer_socket.receive_json_from()

        await sync_to_async(broadcast_notification_to_user)(
            str(shared_id),
            "admin",
            {"id": "admin-only", "subject": "Admin only"},
        )

        response = await admin_socket.receive_json_from(timeout=2)
        assert response["data"]["subject"] == "Admin only"
        assert await officer_socket.receive_nothing(timeout=0.05)
        await admin_socket.disconnect()
        await officer_socket.disconnect()

    async_to_sync(exercise)()


def test_auth_access_cookie_path_covers_api_and_websocket(staff_session):
    _, tokens = staff_session
    response = HttpResponse()

    set_auth_cookies(response, tokens["access"], tokens["refresh"])

    access_cookie = response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]
    refresh_cookie = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
    assert access_cookie["path"] == "/"
    assert refresh_cookie["path"] == "/api/auth/"
