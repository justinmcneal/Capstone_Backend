import os

import pyotp
import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Customer
from accounts.utils.email_utils import EmailUtils


@pytest.fixture(autouse=True)
def _ensure_secret_pepper(monkeypatch):
    pepper = os.environ.get("SECRET_PEPPER")
    if not pepper:
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


@override_settings(SECURE_SSL_REDIRECT=False)
def test_signup_otp_login_refresh_logout_smoke():
    client = APIClient()
    email = "smoke-auth@example.com"
    password = "TempPass123!"

    # 1) Signup
    signup_url = reverse("accounts:signup")
    signup_payload = {
        "first_name": "Smoke",
        "last_name": "Auth",
        "email": email,
        "password": password,
        "password_confirm": password,
    }
    response = client.post(signup_url, signup_payload, format="json")
    assert response.status_code == 201, response.content
    assert response.json()["status"] == "success"

    # 2) Read OTP from DB
    customer = Customer.find_one({"email": EmailUtils.normalize_email(email)})
    assert customer is not None
    assert customer.verified is False
    otp = customer.verification_token
    assert otp is not None
    assert len(otp) == 6

    # 3) Verify OTP
    verify_url = reverse("accounts:verify-email")
    response = client.post(
        verify_url,
        {"email": email, "otp": otp},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "success"
    assert "access" in response.json()["data"]
    assert "refresh" in response.json()["data"]

    # 4) Login with verified account
    login_url = reverse("accounts:login")
    response = client.post(
        login_url,
        {"email": email, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "success"
    login_data = response.json()["data"]
    assert "access" in login_data
    assert "refresh" in login_data
    refresh_token = login_data["refresh"]

    # 5) Refresh token
    refresh_url = reverse("accounts:refresh-token")
    response = client.post(
        refresh_url,
        {"refresh": refresh_token},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "success"
    new_tokens = response.json()["data"]
    assert "access" in new_tokens
    assert "refresh" in new_tokens
    assert new_tokens["refresh"] != refresh_token

    # 6) Logout
    logout_url = reverse("accounts:logout")
    response = client.post(
        logout_url,
        {"refresh": new_tokens["refresh"], "access": new_tokens["access"]},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "success"

    # 7) Old refresh token should be invalid now
    response = client.post(
        refresh_url,
        {"refresh": refresh_token},
        format="json",
    )
    assert response.status_code == 401


@override_settings(SECURE_SSL_REDIRECT=False)
def test_login_2fa_flow_smoke():
    client = APIClient()
    email = "smoke-2fa@example.com"
    password = "TempPass123!"
    secret = pyotp.random_base32()

    customer = Customer(
        first_name="Two",
        last_name="Factor",
        email=EmailUtils.normalize_email(email),
        password="",
        verified=True,
        two_factor_enabled=True,
        two_factor_secret=secret,
    )
    customer.set_password(password)
    customer.save()

    # 1) Login with 2FA enabled -> temp_token
    login_url = reverse("accounts:login")
    response = client.post(
        login_url,
        {"email": email, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "success"
    login_data = response.json()["data"]
    assert login_data.get("requires_2fa") is True
    temp_token = login_data["temp_token"]
    assert temp_token is not None

    # 2) Generate valid TOTP code from the stored secret
    totp = pyotp.TOTP(secret)
    code = totp.now()

    # 3) Verify 2FA -> full tokens
    verify_2fa_url = reverse("accounts:2fa-verify")
    response = client.post(
        verify_2fa_url,
        {"temp_token": temp_token, "code": code},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "success"
    twofa_data = response.json()["data"]
    assert "access" in twofa_data
    assert "refresh" in twofa_data


@override_settings(SECURE_SSL_REDIRECT=False)
def test_signup_duplicate_email_rejected():
    client = APIClient()
    email = "dup-signup@example.com"
    password = "TempPass123!"

    payload = {
        "first_name": "Dup",
        "last_name": "User",
        "email": email,
        "password": password,
        "password_confirm": password,
    }

    response = client.post(reverse("accounts:signup"), payload, format="json")
    assert response.status_code == 201

    # Second signup with same email
    response = client.post(reverse("accounts:signup"), payload, format="json")
    assert response.status_code == 400


@override_settings(SECURE_SSL_REDIRECT=False)
def test_login_locked_account_rejected():
    from datetime import datetime, timedelta, timezone

    client = APIClient()
    email = "locked-acc@example.com"
    password = "TempPass123!"

    customer = Customer(
        first_name="Locked",
        last_name="User",
        email=EmailUtils.normalize_email(email),
        password="",
        verified=True,
        locked_until=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    customer.set_password(password)
    customer.save()

    response = client.post(
        reverse("accounts:login"),
        {"email": email, "password": password},
        format="json",
    )
    assert response.status_code == 401


@override_settings(SECURE_SSL_REDIRECT=False)
def test_verify_email_wrong_otp_rejected():
    client = APIClient()
    email = "wrong-otp@example.com"
    password = "TempPass123!"

    client.post(
        reverse("accounts:signup"),
        {
            "first_name": "Wrong",
            "last_name": "OTP",
            "email": email,
            "password": password,
            "password_confirm": password,
        },
        format="json",
    )

    response = client.post(
        reverse("accounts:verify-email"),
        {"email": email, "otp": "000000"},
        format="json",
    )
    assert response.status_code == 400
