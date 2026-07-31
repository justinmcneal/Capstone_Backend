"""
Extended 2FA tests: disable 2FA, backup code generation and consumption, and 2FA status.
"""
import os
import pyotp
import pytest
from bson import ObjectId
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Customer, Admin
from accounts.services.auth_service import AuthService
from accounts.utils.email_utils import EmailUtils
from accounts.utils.token_utils import TokenUtils


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _make_2fa_customer(email: str = "2fa-ext@example.com", password: str = "Pass123!") -> Customer:
    secret = pyotp.random_base32()
    c = Customer(
        first_name="TwoFactor",
        last_name="Ext",
        email=EmailUtils.normalize_email(email),
        password="",
        verified=True,
        two_factor_enabled=True,
        two_factor_secret=secret,
        backup_codes=["code1_hash", "code2_hash"],
    )
    c.set_password(password)
    c.save()
    return c


@override_settings(SECURE_SSL_REDIRECT=False)
def test_2fa_status_endpoint():
    client = APIClient()
    customer = _make_2fa_customer("status-2fa@example.com")
    tokens = AuthService.create_customer_tokens(customer, token_type="no_remember_me")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    url = reverse("accounts:2fa-status")
    response = client.get(url)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["two_factor_enabled"] is True
    assert data["backup_codes_remaining"] == 2


@override_settings(SECURE_SSL_REDIRECT=False)
def test_disable_2fa_success_and_wrong_password():
    client = APIClient()
    customer = _make_2fa_customer("disable-2fa@example.com", "Pass123!")
    tokens = AuthService.create_customer_tokens(customer, token_type="no_remember_me")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    url = reverse("accounts:2fa-disable")

    # Wrong password
    response = client.post(url, {"password": "WrongPassword!"}, format="json")
    assert response.status_code == 400

    # Correct password
    response = client.post(url, {"password": "Pass123!"}, format="json")
    assert response.status_code == 200

    updated = Customer.find_one({"_id": ObjectId(customer.id)})
    assert updated is not None
    assert updated.two_factor_enabled is False


@override_settings(SECURE_SSL_REDIRECT=False)
def test_admin_cannot_disable_2fa():
    """Admin accounts cannot disable 2FA (mandatory security control)."""
    client = APIClient()
    admin = Admin(
        username="admin2fa",
        email="admin2fa@example.com",
        two_factor_enabled=True,
        two_factor_secret=pyotp.random_base32(),
    )
    admin.set_password("AdminPass1!")
    admin.save()

    tokens = TokenUtils.generate_tokens(user_id=str(admin.id), email=admin.email, role="admin")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    url = reverse("accounts:2fa-disable")
    response = client.post(url, {"password": "AdminPass1!"}, format="json")
    assert response.status_code == 403
    assert response.json()["code"] == "admin_2fa_mandatory"


@override_settings(SECURE_SSL_REDIRECT=False)
def test_regenerate_backup_codes():
    client = APIClient()
    customer = _make_2fa_customer("regen-codes@example.com", "Pass123!")
    tokens = AuthService.create_customer_tokens(customer, token_type="no_remember_me")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    url = reverse("accounts:2fa-backup-codes")

    # Wrong password
    response = client.post(url, {"password": "WrongPassword!"}, format="json")
    assert response.status_code == 400

    # Correct password
    response = client.post(url, {"password": "Pass123!"}, format="json")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "backup_codes" in data
    assert len(data["backup_codes"]) == 10
