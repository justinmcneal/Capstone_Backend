"""
Tests for password management endpoints.

Covers:
- Full reset flow: forgot-password → verify-reset-otp → reset-password
- Enumeration hardening (unknown email always returns 200)
- Wrong OTP rejected, same-as-old rejected
- Change-password: auth required, wrong old, same password rejected
- Change-password clears must_change_password for loan officers
"""
import os

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Customer, LoanOfficer
from accounts.utils.email_utils import EmailUtils


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _make_customer(email: str, password: str = "OldPass123!") -> Customer:
    c = Customer(
        first_name="Test",
        last_name="User",
        email=EmailUtils.normalize_email(email),
        password="",
        verified=True,
    )
    c.set_password(password)
    c.save()
    return c


def _make_officer(email: str, password: str = "OldPass123!", must_change: bool = False):
    o = LoanOfficer(
        first_name="Officer",
        last_name="Test",
        email=EmailUtils.normalize_email(email),
        password="",
        employee_id="EMP001",
        department="Loans",
        active=True,
        must_change_password=must_change,
    )
    o.set_password(password)
    o.save()
    return o


# ── Password Reset Flow ──────────────────────────────────────────────────────

@override_settings(SECURE_SSL_REDIRECT=False)
def test_forgot_password_unknown_email_always_200():
    """Enumeration hardening: unknown email must not reveal account existence."""
    client = APIClient()
    r = client.post(reverse("accounts:forgot-password"), {"email": "nobody@example.com"}, format="json")
    assert r.status_code == 200
    assert r.json()["status"] == "success"


@override_settings(SECURE_SSL_REDIRECT=False)
def test_forgot_password_full_reset_flow(monkeypatch):
    """forgot → verify OTP → reset → old pw rejected → new pw works."""
    import accounts.utils.email_utils as eu
    monkeypatch.setattr(eu.EmailUtils, "send_password_reset_email", lambda **_: None)

    client = APIClient()
    customer = _make_customer("reset-flow@example.com")

    # 1. Initiate
    r = client.post(reverse("accounts:forgot-password"), {"email": customer.email}, format="json")
    assert r.status_code == 200

    # 2. Read OTP from DB
    customer = Customer.find_one({"email": customer.email})
    otp = customer.password_reset_otp
    assert otp

    # 3. Verify OTP
    r = client.post(reverse("accounts:verify-reset-otp"), {"email": customer.email, "otp": otp}, format="json")
    assert r.status_code == 200

    # 4. Reset with new password
    new_password = "NewPass456!"
    r = client.post(
        reverse("accounts:reset-password"),
        {
            "email": customer.email,
            "otp": otp,
            "new_password": new_password,
            "confirm_password": new_password,
        },
        format="json",
    )
    assert r.status_code == 200

    # 5. Old password rejected
    r = client.post(reverse("accounts:login"), {"email": customer.email, "password": "OldPass123!"}, format="json")
    assert r.status_code == 401

    # 6. New password works
    r = client.post(reverse("accounts:login"), {"email": customer.email, "password": new_password}, format="json")
    assert r.status_code == 200


@override_settings(SECURE_SSL_REDIRECT=False)
def test_verify_reset_otp_wrong_code_rejected(monkeypatch):
    import accounts.utils.email_utils as eu
    monkeypatch.setattr(eu.EmailUtils, "send_password_reset_email", lambda **_: None)

    client = APIClient()
    customer = _make_customer("otp-wrong@example.com")
    client.post(reverse("accounts:forgot-password"), {"email": customer.email}, format="json")

    r = client.post(reverse("accounts:verify-reset-otp"), {"email": customer.email, "otp": "000000"}, format="json")
    assert r.status_code == 400


@override_settings(SECURE_SSL_REDIRECT=False)
def test_reset_password_same_as_old_rejected(monkeypatch):
    import accounts.utils.email_utils as eu
    monkeypatch.setattr(eu.EmailUtils, "send_password_reset_email", lambda **_: None)

    client = APIClient()
    customer = _make_customer("same-pw@example.com", password="OldPass123!")
    client.post(reverse("accounts:forgot-password"), {"email": customer.email}, format="json")

    customer = Customer.find_one({"email": customer.email})
    otp = customer.password_reset_otp

    r = client.post(
        reverse("accounts:reset-password"),
        {
            "email": customer.email,
            "otp": otp,
            "new_password": "OldPass123!",
            "confirm_password": "OldPass123!",
        },
        format="json",
    )
    assert r.status_code == 400


# ── Change Password ──────────────────────────────────────────────────────────

@override_settings(SECURE_SSL_REDIRECT=False)
def test_change_password_requires_auth():
    client = APIClient()
    r = client.post(
        reverse("accounts:change-password"),
        {"old_password": "X", "new_password": "Y", "confirm_password": "Y"},
        format="json",
    )
    assert r.status_code in (401, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
def test_change_password_wrong_old_password():
    client = APIClient()
    customer = _make_customer("change-pw@example.com", password="CorrectOld123!")

    login_resp = client.post(reverse("accounts:login"), {"email": customer.email, "password": "CorrectOld123!"}, format="json")
    access = login_resp.json()["data"]["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    r = client.post(
        reverse("accounts:change-password"),
        {"old_password": "WrongOld999!", "new_password": "NewPass456!", "confirm_password": "NewPass456!"},
        format="json",
    )
    assert r.status_code == 400


@override_settings(SECURE_SSL_REDIRECT=False)
def test_change_password_requires_old_password_when_not_mandatory():
    client = APIClient()
    customer = _make_customer("change-missing-old@example.com")

    login_resp = client.post(
        reverse("accounts:login"),
        {"email": customer.email, "password": "OldPass123!"},
        format="json",
    )
    access = login_resp.json()["data"]["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    r = client.post(
        reverse("accounts:change-password"),
        {"new_password": "NewPass456!", "confirm_password": "NewPass456!"},
        format="json",
    )
    assert r.status_code == 400
    assert "old_password" in r.json()["errors"]


@override_settings(SECURE_SSL_REDIRECT=False)
def test_change_password_same_rejected():
    client = APIClient()
    customer = _make_customer("change-same@example.com", password="SamePass123!")

    login_resp = client.post(reverse("accounts:login"), {"email": customer.email, "password": "SamePass123!"}, format="json")
    access = login_resp.json()["data"]["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    r = client.post(
        reverse("accounts:change-password"),
        {"old_password": "SamePass123!", "new_password": "SamePass123!", "confirm_password": "SamePass123!"},
        format="json",
    )
    assert r.status_code == 400


@override_settings(SECURE_SSL_REDIRECT=False)
def test_change_password_clears_must_change_flag():
    """Mandatory first-login change does not require the temporary password."""
    client = APIClient()
    officer = _make_officer("lo-mustchange@example.com", password="Initial123!", must_change=True)

    login_resp = client.post(
        reverse("accounts:loan-officer-login"),
        {"email": officer.email, "password": "Initial123!"},
        format="json",
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["data"]["must_change_password"] is True
    access = login_resp.json()["data"]["access_token"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    r = client.post(
        reverse("accounts:change-password"),
        {"new_password": "Changed456!", "confirm_password": "Changed456!"},
        format="json",
    )
    assert r.status_code == 200

    # Flag must be cleared in DB
    from bson import ObjectId
    officer = LoanOfficer.find_one({"_id": ObjectId(officer.id)})
    assert officer.must_change_password is False


@override_settings(SECURE_SSL_REDIRECT=False)
def test_mandatory_change_rejects_reusing_temporary_password():
    client = APIClient()
    officer = _make_officer(
        "lo-reuse-temp@example.com", password="Initial123!", must_change=True
    )

    login_resp = client.post(
        reverse("accounts:loan-officer-login"),
        {"email": officer.email, "password": "Initial123!"},
        format="json",
    )
    access = login_resp.json()["data"]["access_token"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    r = client.post(
        reverse("accounts:change-password"),
        {"new_password": "Initial123!", "confirm_password": "Initial123!"},
        format="json",
    )
    assert r.status_code == 400
