"""
Tests for ContactSupportView endpoint.
"""
import os
import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


@override_settings(SECURE_SSL_REDIRECT=False)
def test_contact_support_success(monkeypatch):
    email_sent = False

    def _mock_send(**kwargs):
        nonlocal email_sent
        email_sent = True
        return True

    import accounts.views.contact_views as contact_mod
    monkeypatch.setattr(contact_mod.email_service, "send_email", _mock_send)

    client = APIClient()
    url = reverse("accounts:contact-support")
    payload = {
        "full_name": "Jane Support",
        "contact_email": "jane@example.com",
        "concern_type": "Account Access",
        "message": "I am having trouble logging into my account.",
    }

    response = client.post(url, payload, format="json")
    assert response.status_code == 201
    assert response.json()["status"] == "success"
    assert email_sent is True


@override_settings(SECURE_SSL_REDIRECT=False)
def test_contact_support_missing_required_fields():
    client = APIClient()
    url = reverse("accounts:contact-support")
    payload = {
        "full_name": "Jane Support",
        # Missing contact_email, concern_type, message
    }

    response = client.post(url, payload, format="json")
    assert response.status_code == 400
    assert response.json()["status"] == "error"
