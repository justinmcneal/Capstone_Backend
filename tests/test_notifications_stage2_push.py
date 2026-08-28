"""Stage 2 FCM compatibility and device-token lifecycle evidence."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from django.urls import reverse
from firebase_admin import messaging as installed_messaging
from rest_framework.test import APIClient

from accounts.models import Customer
from accounts.utils.token_utils import TokenUtils
from config.field_encryption import _build_keyring, _get_fernet, is_encrypted_value
from notifications.models.device_token import (
    DeviceToken,
    DeviceTokenLimitExceeded,
    DeviceTokenOwnershipConflict,
)
from notifications.services import notification_creator

TOKEN_A = "fcm-token-a-1234567890abcdef"
TOKEN_B = "fcm-token-b-1234567890abcdef"
TOKEN_C = "fcm-token-c-1234567890abcdef"


def _customer():
    return Customer(
        first_name="Push",
        last_name="Customer",
        email=f"push-{ObjectId()}@example.test",
        password="hashed",
        verified=True,
        active=True,
        account_state="active",
    ).save()


def _client(customer):
    tokens = TokenUtils.generate_jwt_tokens(customer)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client, tokens


def _register(
    user_id, token, *, role="customer", session="session-1", platform="android"
):
    return DeviceToken.register(
        user_id=user_id,
        user_type=role,
        session_id=session,
        token=token,
        platform=platform,
    )


class _UnregisteredError(Exception):
    pass


class _SenderIdMismatchError(Exception):
    pass


class _QuotaError(Exception):
    pass


class _SendResponse:
    def __init__(self, *, success, exception=None):
        self.success = success
        self.exception = exception


class _BatchResponse:
    def __init__(self, responses):
        self.responses = responses
        self.success_count = sum(item.success for item in responses)
        self.failure_count = len(responses) - self.success_count


class _FakeMessaging:
    UnregisteredError = _UnregisteredError
    SenderIdMismatchError = _SenderIdMismatchError

    class Notification:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class MulticastMessage:
        def __init__(self, **kwargs):
            self.notification = kwargs["notification"]
            self.data = kwargs["data"]
            self.tokens = kwargs["tokens"]

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def send_each_for_multicast(self, message):
        self.calls.append(message)
        if self._responses:
            return self._responses.pop(0)
        return _BatchResponse([_SendResponse(success=True) for _ in message.tokens])


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


def test_pinned_firebase_exposes_the_selected_multicast_api():
    assert callable(installed_messaging.send_each_for_multicast)


def test_device_token_indexes_include_unique_fingerprint(settings):
    DeviceToken.create_indexes()
    indexes = settings.MONGODB[DeviceToken.collection_name].index_information()
    fingerprint = next(
        value for value in indexes.values() if value.get("key") == [("token_hash", 1)]
    )
    assert fingerprint["unique"] is True


def test_registration_encrypts_token_and_stores_role_session_and_fingerprint(
    settings, encrypted_fields
):
    record = _register("same-id", TOKEN_A, role="customer", session="session-a")
    raw = settings.MONGODB[DeviceToken.collection_name].find_one({"_id": record._id})

    assert raw["token"] != TOKEN_A
    assert is_encrypted_value(raw["token"])
    assert raw["token_hash"] == DeviceToken.fingerprint(TOKEN_A)
    assert raw["user_type"] == "customer"
    assert raw["session_id"] == "session-a"
    assert DeviceToken.from_dict(raw).token == TOKEN_A


def test_active_token_cannot_be_claimed_by_another_role_or_account():
    _register("same-id", TOKEN_A, role="customer")

    with pytest.raises(DeviceTokenOwnershipConflict):
        _register("same-id", TOKEN_A, role="loan_officer")
    with pytest.raises(DeviceTokenOwnershipConflict):
        _register("different-id", TOKEN_A, role="customer")


def test_inactive_token_can_be_safely_reassigned():
    _register("first", TOKEN_A)
    assert DeviceToken.deactivate_token_for_owner(
        token=TOKEN_A, user_id="first", user_type="customer"
    )

    reassigned = _register("second", TOKEN_A, session="session-2")
    assert reassigned.user_id == "second"
    assert reassigned.is_active is True


def test_same_owner_registration_refreshes_without_creating_a_duplicate(settings):
    first = _register("owner", TOKEN_A, session="session-a", platform="android")
    second = _register("owner", TOKEN_A, session="session-b", platform="ios")

    assert second._id == first._id
    assert settings.MONGODB[DeviceToken.collection_name].count_documents({}) == 1
    assert second.session_id == "session-b"
    assert second.platform == "ios"


def test_registration_validates_shape_platform_and_owner_limit(settings):
    with pytest.raises(ValueError):
        _register("owner", "short")
    with pytest.raises(ValueError):
        _register("owner", "enc::reserved-token-value")
    with pytest.raises(ValueError):
        _register("owner", TOKEN_A, platform="desktop")

    settings.NOTIFICATIONS_MAX_ACTIVE_DEVICE_TOKENS = 1
    _register("owner", TOKEN_A)
    with pytest.raises(DeviceTokenLimitExceeded):
        _register("owner", TOKEN_B)


def test_expired_and_other_role_tokens_are_excluded(settings):
    customer = _register("same-id", TOKEN_A, role="customer")
    _register("same-id", TOKEN_B, role="loan_officer")
    settings.MONGODB[DeviceToken.collection_name].update_one(
        {"_id": customer._id},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )

    assert DeviceToken.get_tokens_for_user("same-id", "customer") == []
    assert [
        item.token
        for item in DeviceToken.get_tokens_for_user("same-id", "loan_officer")
    ] == [TOKEN_B]


def test_fcm_uses_installed_api_batches_at_500_and_stringifies_data(
    monkeypatch, settings
):
    records = [
        SimpleNamespace(
            token=f"token-{index:04d}-abcdefghijklmnop", token_hash=str(index)
        )
        for index in range(501)
    ]
    fake = _FakeMessaging()
    monkeypatch.setattr(notification_creator, "messaging", fake)
    monkeypatch.setattr(
        notification_creator,
        "firebase_admin",
        SimpleNamespace(_apps={"default": object()}),
    )
    monkeypatch.setattr(
        DeviceToken,
        "get_tokens_for_user",
        classmethod(lambda cls, user_id, role: records),
    )
    monkeypatch.setattr(
        DeviceToken, "touch_hashes", classmethod(lambda cls, values: None)
    )
    monkeypatch.setattr(
        DeviceToken, "deactivate_hashes", classmethod(lambda cls, values, reason: 0)
    )
    settings.NOTIFICATIONS_FCM_BATCH_SIZE = 500

    result = notification_creator._send_push_notification(
        "owner", "customer", "Title", "Body", {"count": 2, "none": None}
    )

    assert [len(call.tokens) for call in fake.calls] == [500, 1]
    assert fake.calls[0].data == {"count": "2"}
    assert result == {"attempted": 501, "succeeded": 501, "failed": 0, "deactivated": 0}


def test_fcm_partial_failure_deactivates_only_permanent_failures(
    monkeypatch, settings, caplog
):
    records = [
        _register("owner", TOKEN_A),
        _register("owner", TOKEN_B),
        _register("owner", TOKEN_C),
    ]
    fake = _FakeMessaging(
        [
            _BatchResponse(
                [
                    _SendResponse(success=True),
                    _SendResponse(success=False, exception=_UnregisteredError()),
                    _SendResponse(success=False, exception=_QuotaError()),
                ]
            )
        ]
    )
    monkeypatch.setattr(notification_creator, "messaging", fake)
    monkeypatch.setattr(
        notification_creator,
        "firebase_admin",
        SimpleNamespace(_apps={"default": object()}),
    )

    result = notification_creator._send_push_notification(
        "owner", "customer", "Title", "Body", {"id": "notification-id"}
    )

    assert result == {"attempted": 3, "succeeded": 1, "failed": 2, "deactivated": 1}
    collection = settings.MONGODB[DeviceToken.collection_name]
    assert (
        collection.find_one({"token_hash": records[1].token_hash})["is_active"] is False
    )
    assert (
        collection.find_one({"token_hash": records[2].token_hash})["is_active"] is True
    )
    assert TOKEN_A not in caplog.text
    assert TOKEN_B not in caplog.text
    assert TOKEN_C not in caplog.text


def test_routed_registration_unregister_and_cross_owner_concealment():
    owner = _customer()
    other = _customer()
    owner_client, _ = _client(owner)
    other_client, _ = _client(other)
    url = reverse("notifications:notification-register-token")
    assert APIClient().delete(url, {"token": TOKEN_A}, format="json").status_code in {
        401,
        403,
    }

    registered = owner_client.post(
        url, {"token": TOKEN_A, "platform": "ios"}, format="json"
    )
    assert registered.status_code == 200
    assert registered.json()["data"]["platform"] == "ios"

    assert (
        other_client.delete(url, {"token": TOKEN_A}, format="json").status_code == 404
    )
    removed = owner_client.delete(url, {"token": TOKEN_A}, format="json")
    assert removed.status_code == 200
    assert removed.json()["data"]["status"] == "unregistered"


def test_customer_logout_deactivates_tokens_bound_to_that_session(settings):
    customer = _customer()
    client, tokens = _client(customer)
    url = reverse("notifications:notification-register-token")
    assert (
        client.post(
            url, {"token": TOKEN_A, "platform": "android"}, format="json"
        ).status_code
        == 200
    )

    logged_out = client.post(
        reverse("accounts:logout"),
        {"refresh_token": tokens["refresh"]},
        format="json",
    )
    assert logged_out.status_code == 200
    stored = settings.MONGODB[DeviceToken.collection_name].find_one(
        {"token_hash": DeviceToken.fingerprint(TOKEN_A)}
    )
    assert stored["is_active"] is False
    assert stored["deactivation_reason"] == "session_revoked"


def test_session_revocation_deactivates_only_that_sessions_tokens(settings):
    customer = _customer()
    first = _register(customer.id, TOKEN_A, session="session-a")
    second = _register(customer.id, TOKEN_B, session="session-b")

    TokenUtils.revoke_session(customer.id, "customer", "session-a")

    collection = settings.MONGODB[DeviceToken.collection_name]
    assert collection.find_one({"_id": first._id})["is_active"] is False
    assert collection.find_one({"_id": second._id})["is_active"] is True


def test_revoke_all_sessions_preserves_only_explicit_exception(settings):
    customer = _customer()
    first = _register(customer.id, TOKEN_A, session="session-a")
    second = _register(customer.id, TOKEN_B, session="session-b")

    TokenUtils.revoke_all_sessions(
        customer.id, "customer", except_session_id="session-b"
    )

    collection = settings.MONGODB[DeviceToken.collection_name]
    assert collection.find_one({"_id": first._id})["is_active"] is False
    assert collection.find_one({"_id": second._id})["is_active"] is True
