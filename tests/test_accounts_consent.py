"""
Tests for Consent endpoints: GET status, POST record, PUT update, history, and audit.
"""
import os
import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Customer, Admin
from accounts.utils.email_utils import EmailUtils
from accounts.utils.token_utils import TokenUtils


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _make_customer(email: str = "consent-user@example.com") -> Customer:
    c = Customer(
        first_name="Consent",
        last_name="User",
        email=EmailUtils.normalize_email(email),
        password="",
        verified=True,
    )
    c.set_password("Pass123!")
    c.save()
    return c


@override_settings(SECURE_SSL_REDIRECT=False)
def test_consent_requires_auth():
    client = APIClient()
    url = reverse("accounts:consent")
    response = client.get(url)
    assert response.status_code in (401, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
def test_get_consent_returns_defaults_when_no_record():
    client = APIClient()
    customer = _make_customer("consent-defaults@example.com")
    tokens = TokenUtils.generate_tokens(user_id=customer.id, email=customer.email, role="customer")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    url = reverse("accounts:consent")
    response = client.get(url)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["data_consent"] is False
    assert data["ai_consent"] is False
    assert data["has_consent_record"] is False


@override_settings(SECURE_SSL_REDIRECT=False)
def test_post_consent_records_consent():
    client = APIClient()
    customer = _make_customer("consent-post@example.com")
    tokens = TokenUtils.generate_tokens(user_id=customer.id, email=customer.email, role="customer")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    url = reverse("accounts:consent")
    payload = {"data_consent": True, "ai_consent": True}
    response = client.post(url, payload, format="json")

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["data_consent"] is True
    assert data["ai_consent"] is True


@override_settings(SECURE_SSL_REDIRECT=False)
def test_put_consent_updates_consent_and_dispatches_task(monkeypatch):
    """Updating consent from True to False dispatches task or executes handler."""
    task_dispatched = False

    def _mock_delay(user_id):
        nonlocal task_dispatched
        task_dispatched = True

    import accounts.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod.invalidate_ai_consent_cache, "delay", _mock_delay)

    client = APIClient()
    customer = _make_customer("consent-put@example.com")
    tokens = TokenUtils.generate_tokens(user_id=customer.id, email=customer.email, role="customer")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    url = reverse("accounts:consent")
    # First set consent to True
    client.post(url, {"data_consent": True, "ai_consent": True}, format="json")

    # Now revoke ai_consent (True -> False)
    response = client.put(url, {"ai_consent": False}, format="json")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ai_consent"] is False
    assert task_dispatched is True


@override_settings(SECURE_SSL_REDIRECT=False)
def test_consent_history_and_audit():
    client = APIClient()
    customer = _make_customer("consent-hist@example.com")
    tokens = TokenUtils.generate_tokens(user_id=customer.id, email=customer.email, role="customer")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # Record initial consent
    client.post(reverse("accounts:consent"), {"data_consent": True, "ai_consent": True}, format="json")

    # Get History
    hist_url = reverse("accounts:consent-history")
    response = client.get(hist_url)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Audit requires admin
    audit_url = reverse("accounts:consent-audit")
    response = client.get(audit_url)
    assert response.status_code in (401, 403)

    # Admin access to audit
    admin = Admin(username="auditor", email="auditor@example.com", super_admin=True)
    admin.save()
    admin_tokens = TokenUtils.generate_tokens(user_id=admin.id, email=admin.email, role="admin")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_tokens['access']}")

    response = client.get(audit_url)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
