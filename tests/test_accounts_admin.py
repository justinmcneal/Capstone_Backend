"""
Tests for Admin endpoints: login flow (including 2FA bootstrap), profile, and loan officer management.
"""
import os
import pytest
from bson import ObjectId
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Admin, LoanOfficer
from accounts.utils.email_utils import EmailUtils
from accounts.utils.token_utils import TokenUtils


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _make_admin(
    username: str = "adminuser",
    email: str = "admin@example.com",
    password: str = "AdminPass123!",
    two_factor_enabled: bool = False,
    super_admin: bool = True,
    permissions: list = None,
    active: bool = True,
) -> Admin:
    a = Admin(
        username=username,
        email=EmailUtils.normalize_email(email),
        password="",
        first_name="Admin",
        last_name="User",
        two_factor_enabled=two_factor_enabled,
        super_admin=super_admin,
        permissions=permissions or [],
        active=active,
    )
    a.set_password(password)
    a.save()
    return a


@override_settings(SECURE_SSL_REDIRECT=False)
def test_admin_login_triggers_2fa_setup_on_first_login():
    """First-time admin login (2FA not set up) requires 2FA setup."""
    client = APIClient()
    admin = _make_admin(username="firstadmin", two_factor_enabled=False)

    url = reverse("accounts:admin-login")
    response = client.post(url, {"username": admin.username, "password": "AdminPass123!"}, format="json")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data.get("requires_2fa") is True
    assert data.get("requires_2fa_setup") is True
    assert "temp_token" in data
    assert "provisioning_uri" in data


@override_settings(SECURE_SSL_REDIRECT=False)
def test_admin_login_wrong_password():
    client = APIClient()
    admin = _make_admin(username="wrongpwadmin")

    url = reverse("accounts:admin-login")
    response = client.post(url, {"username": admin.username, "password": "WrongPassword!"}, format="json")
    assert response.status_code == 401


@override_settings(SECURE_SSL_REDIRECT=False)
def test_admin_login_inactive_account():
    client = APIClient()
    admin = _make_admin(username="inactiveadmin", active=False)

    url = reverse("accounts:admin-login")
    response = client.post(url, {"username": admin.username, "password": "AdminPass123!"}, format="json")
    assert response.status_code == 401


@override_settings(SECURE_SSL_REDIRECT=False)
def test_admin_profile_requires_auth():
    client = APIClient()
    url = reverse("accounts:admin-me")
    response = client.get(url)
    assert response.status_code in (401, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
def test_admin_create_and_list_loan_officers():
    """Super admin creates a loan officer, then lists all loan officers."""
    import pyotp

    client = APIClient()
    secret = pyotp.random_base32()
    admin = _make_admin(username="superadmin", two_factor_enabled=True, super_admin=True)
    admin.two_factor_secret = secret
    admin.save()

    # Generate admin JWT tokens directly for API testing
    tokens = TokenUtils.generate_tokens(
        user_id=str(admin.id),
        email=admin.email,
        verified=True,
        role="admin",
        token_type="no_remember_me",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # Create Loan Officer
    create_url = reverse("accounts:admin-loan-officers")
    lo_payload = {
        "first_name": "New",
        "last_name": "Officer",
        "email": "new-lo@example.com",
        "employee_id": "EMP200",
        "department": "Loans",
        "phone": "09171234567",
    }
    response = client.post(create_url, lo_payload, format="json")
    assert response.status_code == 201, response.content
    assert response.json()["status"] == "success"

    # List Loan Officers
    response = client.get(create_url)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    officers = response.json()["data"]["loan_officers"]
    assert len(officers) >= 1
    assert any(o["email"] == "new-lo@example.com" for o in officers)


@override_settings(SECURE_SSL_REDIRECT=False)
def test_admin_deactivate_loan_officer():
    client = APIClient()
    admin = _make_admin(username="mgradmin", super_admin=True)

    # Create target loan officer
    officer = LoanOfficer(
        first_name="Target",
        last_name="Officer",
        email="target-lo@example.com",
        employee_id="EMP300",
        active=True,
    )
    officer.save()

    tokens = TokenUtils.generate_tokens(
        user_id=str(admin.id),
        email=admin.email,
        verified=True,
        role="admin",
        token_type="no_remember_me",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    detail_url = reverse("accounts:admin-loan-officer-detail", kwargs={"officer_id": str(officer.id)})
    response = client.delete(detail_url)

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    updated = LoanOfficer.find_one({"_id": ObjectId(officer.id)})
    assert updated is not None
    assert updated.active is False
