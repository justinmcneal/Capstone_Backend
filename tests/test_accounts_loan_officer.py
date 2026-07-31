"""
Tests for Loan Officer endpoints: login, logout, profile, and must_change_password enforcement.
"""
import os
import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import LoanOfficer
from accounts.utils.email_utils import EmailUtils


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _make_officer(email: str, password: str = "Pass123!", active: bool = True, must_change: bool = False) -> LoanOfficer:
    o = LoanOfficer(
        first_name="Officer",
        last_name="One",
        email=EmailUtils.normalize_email(email),
        password="",
        employee_id="EMP100",
        department="Loans",
        active=active,
        must_change_password=must_change,
    )
    o.set_password(password)
    o.save()
    return o


@override_settings(SECURE_SSL_REDIRECT=False)
def test_loan_officer_login_success():
    client = APIClient()
    officer = _make_officer("lo-login@example.com", "Pass123!")

    url = reverse("accounts:loan-officer-login")
    response = client.post(url, {"email": officer.email, "password": "Pass123!"}, format="json")

    assert response.status_code == 200
    data = response.json()["data"]
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == officer.email
    assert data["must_change_password"] is False


@override_settings(SECURE_SSL_REDIRECT=False)
def test_loan_officer_login_wrong_password():
    client = APIClient()
    officer = _make_officer("lo-wrong-pw@example.com", "Pass123!")

    url = reverse("accounts:loan-officer-login")
    response = client.post(url, {"email": officer.email, "password": "WrongPassword!"}, format="json")

    assert response.status_code == 401


@override_settings(SECURE_SSL_REDIRECT=False)
def test_loan_officer_login_inactive_account():
    client = APIClient()
    officer = _make_officer("lo-inactive@example.com", "Pass123!", active=False)

    url = reverse("accounts:loan-officer-login")
    response = client.post(url, {"email": officer.email, "password": "Pass123!"}, format="json")

    assert response.status_code == 401


@override_settings(SECURE_SSL_REDIRECT=False)
def test_loan_officer_profile_requires_auth():
    client = APIClient()
    url = reverse("accounts:loan-officer-me")
    response = client.get(url)
    assert response.status_code in (401, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
def test_loan_officer_must_change_password_blocks_profile():
    client = APIClient()
    officer = _make_officer("lo-blocked@example.com", "InitialPass1!", must_change=True)

    login_url = reverse("accounts:loan-officer-login")
    login_resp = client.post(login_url, {"email": officer.email, "password": "InitialPass1!"}, format="json")
    access_token = login_resp.json()["data"]["access_token"]

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    url = reverse("accounts:loan-officer-me")
    response = client.get(url)

    # Must be blocked with 423 Locked
    assert response.status_code == 423
    assert "must change your password" in response.json()["detail"].lower()


@override_settings(SECURE_SSL_REDIRECT=False)
def test_loan_officer_logout():
    client = APIClient()
    officer = _make_officer("lo-logout@example.com", "Pass123!")

    login_url = reverse("accounts:loan-officer-login")
    login_resp = client.post(login_url, {"email": officer.email, "password": "Pass123!"}, format="json")
    refresh_token = login_resp.json()["data"]["refresh_token"]

    logout_url = reverse("accounts:loan-officer-logout")
    response = client.post(logout_url, {"refresh_token": refresh_token}, format="json")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
