"""
Tests for ActiveSessionsView and LoginActivityView endpoints.
"""
import os
import pytest
from bson import ObjectId
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Customer
from accounts.models.activity import ActiveSession, LoginActivity
from accounts.services.auth_service import AuthService
from accounts.utils.email_utils import EmailUtils
from accounts.utils.token_utils import TokenUtils


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _make_customer(email: str = "sessions-user@example.com") -> Customer:
    c = Customer(
        first_name="Session",
        last_name="User",
        email=EmailUtils.normalize_email(email),
        password="",
        verified=True,
    )
    c.set_password("Pass123!")
    c.save()
    return c


@override_settings(SECURE_SSL_REDIRECT=False)
def test_sessions_and_activity_require_auth():
    client = APIClient()
    assert client.get(reverse("accounts:active-sessions")).status_code in (401, 403)
    assert client.get(reverse("accounts:login-activity")).status_code in (401, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
def test_get_active_sessions_and_login_activity():
    client = APIClient()
    customer = _make_customer("sess-act@example.com")
    tokens = AuthService.create_customer_tokens(customer, token_type="no_remember_me")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # Create dummy session and activity entries
    sess = ActiveSession(
        user_id=str(customer.id),
        user_type="customer",
        session_token=tokens["refresh"],
        ip_address="127.0.0.1",
        is_active=True,
    )
    sess.save()

    act = LoginActivity(
        user_id=str(customer.id),
        user_type="customer",
        action="login_success",
        ip_address="127.0.0.1",
    )
    act.save()

    # GET sessions
    response = client.get(reverse("accounts:active-sessions"))
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) >= 1

    # GET login activity
    response = client.get(reverse("accounts:login-activity"))
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) >= 1


@override_settings(SECURE_SSL_REDIRECT=False)
def test_delete_session_terminates_session():
    client = APIClient()
    customer = _make_customer("sess-del@example.com")
    tokens = AuthService.create_customer_tokens(customer, token_type="no_remember_me")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    sess = ActiveSession(
        user_id=str(customer.id),
        user_type="customer",
        session_token=tokens["refresh"],
        ip_address="127.0.0.1",
        is_active=True,
    )
    sess.save()

    url = reverse("accounts:active-sessions")
    response = client.delete(url, {"session_id": str(sess.id)}, format="json")

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify deactivated
    updated = ActiveSession.find_one({"_id": ObjectId(sess.id)})
    assert updated.is_active is False


@override_settings(SECURE_SSL_REDIRECT=False)
def test_delete_session_belonging_to_other_user_rejected():
    client = APIClient()
    user1 = _make_customer("user1@example.com")
    user2 = _make_customer("user2@example.com")

    tokens1 = AuthService.create_customer_tokens(user1, token_type="no_remember_me")
    tokens2 = AuthService.create_customer_tokens(user2, token_type="no_remember_me")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens1['access']}")

    # Session belongs to user2
    sess2 = ActiveSession(
        user_id=str(user2.id),
        user_type="customer",
        session_token=tokens2["refresh"],
        is_active=True,
    )
    sess2.save()

    url = reverse("accounts:active-sessions")
    response = client.delete(url, {"session_id": str(sess2.id)}, format="json")

    assert response.status_code == 404
