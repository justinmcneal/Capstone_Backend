import os
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Admin, Customer
from accounts.models.activity import ActiveSession, LoginActivity
from accounts.services.auth_service import AuthService
from accounts.services.two_factor_service import TwoFactorService
from analytics.models import AuditLog
from notifications.models.notification import Notification


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _customer(
    email="stage5@example.com",
    password="Pass123!",
    *,
    two_factor_enabled=False,
):
    secret = pyotp.random_base32() if two_factor_enabled else None
    customer = Customer(
        first_name="Stage",
        last_name="Five",
        email=email,
        verified=True,
        two_factor_enabled=two_factor_enabled,
        two_factor_secret=secret,
    )
    customer.set_password(password)
    customer.save()
    return customer


def _authenticated_client(customer):
    tokens = AuthService.create_customer_tokens(customer, token_type="no_remember_me")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_admin_bootstrap_remains_bound_to_password_verified_login():
    admin = Admin(
        username="stage5-admin",
        email="stage5-admin@example.com",
        first_name="Stage",
        last_name="Admin",
        active=True,
        two_factor_enabled=False,
    )
    admin.set_password("AdminPass123!")
    admin.save()
    client = APIClient()

    login = client.post(
        reverse("accounts:admin-login"),
        {"username": admin.username, "password": "AdminPass123!"},
        format="json",
        REMOTE_ADDR="203.0.113.30",
    )
    assert login.status_code == 200
    login_data = login.json()["data"]
    assert login_data["requires_2fa_setup"] is True

    verify = client.post(
        reverse("accounts:2fa-verify"),
        {
            "temp_token": login_data["temp_token"],
            "code": pyotp.TOTP(login_data["manual_entry_key"]).now(),
        },
        format="json",
        REMOTE_ADDR="203.0.113.30",
    )
    assert verify.status_code == 200
    assert len(verify.json()["data"]["backup_codes"]) == 10
    assert ActiveSession.find_one({"user_id": admin.id, "role": "admin"}) is not None


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_voluntary_setup_requires_current_password_and_records_events():
    customer = _customer("setup-stage5@example.com")
    client = _authenticated_client(customer)
    setup_url = reverse("accounts:2fa-setup")

    assert client.post(setup_url, {}, format="json").status_code == 400
    assert (
        client.post(setup_url, {"password": "WrongPass!"}, format="json").status_code
        == 400
    )

    setup_response = client.post(setup_url, {"password": "Pass123!"}, format="json")
    assert setup_response.status_code == 200
    secret = setup_response.json()["data"]["manual_entry_key"]

    confirm_response = client.post(
        reverse("accounts:2fa-confirm"),
        {"code": pyotp.TOTP(secret).now()},
        format="json",
    )
    assert confirm_response.status_code == 200

    audit_actions = {
        entry.action for entry in AuditLog.find_by_user(customer.id, limit=20)
    }
    notification_types = {
        entry.notification_type for entry in Notification.find_by_user(customer.id)
    }
    assert {
        "two_factor_setup_started",
        "two_factor_enabled",
    }.issubset(audit_actions)
    assert {
        "two_factor_setup_started",
        "two_factor_enabled",
    }.issubset(notification_types)


def test_pending_setup_expires_before_confirmation():
    customer = _customer("expired-setup@example.com")
    setup = TwoFactorService.setup_2fa(customer, password="Pass123!")
    assert setup is not None
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    customer.two_factor_setup_expires_at = expired_at
    customer.save()

    success, backup_codes = TwoFactorService.confirm_2fa_setup(
        customer, pyotp.TOTP(setup["secret"]).now()
    )
    assert success is False
    assert backup_codes is None


def test_totp_timestep_can_only_be_consumed_once():
    customer = _customer("totp-replay@example.com", two_factor_enabled=True)
    first = Customer.find_one({"_id": customer._id})
    second = Customer.find_one({"_id": customer._id})
    code = pyotp.TOTP(customer.two_factor_secret).now()

    assert TwoFactorService.verify_and_consume_totp(first, code) is True
    assert TwoFactorService.verify_and_consume_totp(second, code) is False


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_2fa_login_preserves_remember_me_and_records_session_metadata():
    customer = _customer("remember-stage5@example.com", two_factor_enabled=True)
    client = APIClient()
    login_response = client.post(
        reverse("accounts:login"),
        {
            "email": customer.email,
            "password": "Pass123!",
            "remember_me": True,
        },
        format="json",
        HTTP_USER_AGENT="Stage5 Test Agent",
        REMOTE_ADDR="203.0.113.25",
    )
    temp_token = login_response.json()["data"]["temp_token"]

    verify_response = client.post(
        reverse("accounts:2fa-verify"),
        {
            "temp_token": temp_token,
            "code": pyotp.TOTP(customer.two_factor_secret).now(),
        },
        format="json",
        HTTP_USER_AGENT="Stage5 Test Agent",
        REMOTE_ADDR="203.0.113.25",
    )
    assert verify_response.status_code == 200
    refresh_value = verify_response.json()["data"]["refresh"]
    refresh = RefreshToken(refresh_value)
    assert refresh["session_type"] == "remember_me"

    session = ActiveSession.find_one({"session_id": refresh["session_id"]})
    assert session is not None
    assert session.ip_address == "203.0.113.25"
    assert session.device_info == "Stage5 Test Agent"

    activities = LoginActivity.find(
        {"user_id": customer.id, "status": "SUCCESS"}, limit=10
    )
    assert len(activities) == 1
    assert activities[0].ip_address == "203.0.113.25"


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_final_2fa_verification_rechecks_security_version():
    customer = _customer("state-stage5@example.com", two_factor_enabled=True)
    client = APIClient()
    login_response = client.post(
        reverse("accounts:login"),
        {"email": customer.email, "password": "Pass123!"},
        format="json",
    )
    temp_token = login_response.json()["data"]["temp_token"]
    customer.security_version += 1
    customer.save()

    response = client.post(
        reverse("accounts:2fa-verify"),
        {
            "temp_token": temp_token,
            "code": pyotp.TOTP(customer.two_factor_secret).now(),
        },
        format="json",
    )
    assert response.status_code == 401


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_backup_code_use_is_atomic_and_emits_security_event():
    customer = _customer("backup-stage5@example.com", two_factor_enabled=True)
    plain_codes, hashed_codes = TwoFactorService.generate_backup_codes(count=1)
    customer.backup_codes = hashed_codes
    customer.save()
    client = APIClient()
    login_response = client.post(
        reverse("accounts:login"),
        {"email": customer.email, "password": "Pass123!"},
        format="json",
    )

    response = client.post(
        reverse("accounts:2fa-verify"),
        {
            "temp_token": login_response.json()["data"]["temp_token"],
            "code": plain_codes[0],
            "use_backup": True,
        },
        format="json",
    )
    assert response.status_code == 200
    assert AuditLog.find_by_action("two_factor_backup_code_used", limit=10)
    assert any(
        notification.notification_type == "two_factor_backup_code_used"
        for notification in Notification.find_by_user(customer.id)
    )


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_backup_regeneration_and_disable_emit_security_events():
    customer = _customer("changes-stage5@example.com", two_factor_enabled=True)
    client = _authenticated_client(customer)

    regenerate = client.post(
        reverse("accounts:2fa-backup-codes"),
        {"password": "Pass123!"},
        format="json",
    )
    disable = client.post(
        reverse("accounts:2fa-disable"),
        {"password": "Pass123!"},
        format="json",
    )
    assert regenerate.status_code == 200
    assert disable.status_code == 200

    actions = {entry.action for entry in AuditLog.find_by_user(customer.id, limit=20)}
    assert "two_factor_backup_codes_regenerated" in actions
    assert "two_factor_disabled" in actions
