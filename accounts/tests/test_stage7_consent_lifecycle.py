import os

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Consent, ConsentEvent, Customer, LoanOfficer
from accounts.services.auth_service import AuthService
from accounts.services.consent_service import ConsentService
from accounts.utils.token_utils import TokenUtils


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _customer(email="stage7@example.com"):
    customer = Customer(
        first_name="Stage",
        last_name="Seven",
        email=email,
        verified=True,
    )
    customer.set_password("Pass123!")
    customer.save()
    return customer


def _customer_client(customer):
    tokens = AuthService.create_customer_tokens(customer)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


def _officer_client():
    officer = LoanOfficer(
        employee_id="STAGE7-LO",
        first_name="Stage",
        last_name="Officer",
        email="stage7-officer@example.com",
        active=True,
        must_change_password=False,
    )
    officer.set_password("OfficerPass123!")
    officer.save()
    tokens = TokenUtils.generate_tokens(
        officer.id,
        officer.email,
        role="loan_officer",
        security_version=officer.security_version,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@override_settings(
    SECURE_SSL_REDIRECT=False,
    WEBSOCKET_ENABLED=False,
    CONSENT_POLICY_VERSION="2026-08-01",
)
def test_grant_requires_the_deployed_policy_version():
    customer = _customer("policy-required@example.com")
    response = _customer_client(customer).post(
        reverse("accounts:consent"),
        {"data_consent": True, "ai_consent": True},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "CONSENT_POLICY_REQUIRED"
    assert response.json()["errors"]["current_policy"]["consent_version"] == (
        "2026-08-01"
    )
    assert ConsentEvent.latest_for_user(customer.id) is None


@override_settings(
    SECURE_SSL_REDIRECT=False,
    WEBSOCKET_ENABLED=False,
    BLOCKCHAIN_ENABLED=False,
    CONSENT_POLICY_VERSION="2026-08-01",
)
def test_local_append_only_history_is_authoritative_without_blockchain(settings):
    customer = _customer("local-history@example.com")
    client = _customer_client(customer)
    response = client.post(
        reverse("accounts:consent"),
        {
            "data_consent": True,
            "ai_consent": True,
            "consent_version": "2026-08-01",
        },
        format="json",
        REMOTE_ADDR="203.0.113.70",
    )

    assert response.status_code == 201
    assert response.json()["data"]["revision"] == 1
    event = ConsentEvent.latest_for_user(customer.id)
    assert event.action == "consent_granted"
    assert event.ip_address == "203.0.113.70"

    # The event remains authoritative even if the current-state projection is lost.
    settings.MONGODB[Consent.collection_name].delete_many({})
    assert ConsentService.check_ai_consent(customer.id) is True

    history = client.get(reverse("accounts:consent-history"))
    assert history.status_code == 200
    assert history.json()["data"]["history"][0]["event_id"] == event.event_id


@override_settings(
    SECURE_SSL_REDIRECT=False,
    WEBSOCKET_ENABLED=False,
    CONSENT_POLICY_VERSION="2026-08-01",
)
def test_consent_updates_are_single_projection_with_ordered_revisions(settings):
    customer = _customer("atomic-consent@example.com")
    client = _customer_client(customer)
    grant = {
        "data_consent": True,
        "ai_consent": True,
        "consent_version": "2026-08-01",
    }
    assert (
        client.post(reverse("accounts:consent"), grant, format="json").status_code
        == 201
    )
    assert (
        client.put(
            reverse("accounts:consent"),
            {"ai_consent": False},
            format="json",
        ).status_code
        == 200
    )

    assert settings.MONGODB[Consent.collection_name].count_documents({}) == 1
    events = ConsentEvent.find_by_user(customer.id)
    assert [event.revision for event in events] == [2, 1]
    assert events[0].action == "consent_revoked"
    assert events[0].previous_state["ai_consent"] is True


@override_settings(
    SECURE_SSL_REDIRECT=False,
    WEBSOCKET_ENABLED=False,
    CONSENT_POLICY_VERSION="2026-08-01",
)
def test_revocation_is_fail_safe_when_cache_and_blockchain_are_unavailable(
    monkeypatch,
):
    customer = _customer("fail-safe-consent@example.com")
    client = _customer_client(customer)
    assert (
        client.post(
            reverse("accounts:consent"),
            {
                "data_consent": True,
                "ai_consent": True,
                "consent_version": "2026-08-01",
            },
            format="json",
        ).status_code
        == 201
    )
    monkeypatch.setattr(
        "accounts.services.consent_service.cache.delete",
        lambda key: (_ for _ in ()).throw(ConnectionError("cache unavailable")),
    )
    monkeypatch.setattr(
        "loans.blockchain.sync.sync_consent",
        lambda **kwargs: (_ for _ in ()).throw(ConnectionError("chain unavailable")),
    )

    response = client.put(
        reverse("accounts:consent"),
        {"ai_consent": False},
        format="json",
    )

    assert response.status_code == 200
    assert ConsentService.check_ai_consent(customer.id) is False
    assert ConsentEvent.latest_for_user(customer.id).ai_consent is False


@override_settings(
    SECURE_SSL_REDIRECT=False,
    WEBSOCKET_ENABLED=False,
    CONSENT_POLICY_VERSION="2026-08-01",
)
def test_ai_requires_both_data_and_ai_consent():
    customer = _customer("combined-consent@example.com")
    ConsentService.record_consent(
        customer.id,
        "customer",
        data_consent=True,
        ai_consent=True,
        consent_version="2026-08-01",
    )
    assert ConsentService.check_ai_consent(customer.id) is True

    ConsentService.update_consent(
        customer.id,
        "customer",
        updates={"data_consent": False, "ai_consent": False},
    )
    assert ConsentService.check_ai_consent(customer.id) is False


@override_settings(
    SECURE_SSL_REDIRECT=False,
    WEBSOCKET_ENABLED=False,
    CONSENT_POLICY_VERSION="2026-09-01",
)
def test_policy_version_change_requires_reconsent(settings):
    customer = _customer("reconsent@example.com")
    settings.MONGODB[Consent.collection_name].insert_one(
        {
            "user_id": customer._id,
            "user_type": "customer",
            "data_consent": True,
            "ai_consent": True,
            "consent_version": "2026-08-01",
            "revision": 0,
        }
    )

    assert ConsentService.check_ai_consent(customer.id) is False
    status = ConsentService.get_consent_status(customer.id)
    assert status["requires_reconsent"] is True

    response = _customer_client(customer).put(
        reverse("accounts:consent"),
        {
            "data_consent": True,
            "ai_consent": True,
            "consent_version": "2026-09-01",
        },
        format="json",
    )
    assert response.status_code == 200
    assert ConsentService.check_ai_consent(customer.id) is True
    assert ConsentEvent.latest_for_user(customer.id).action == "consent_reconfirmed"


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_privileged_roles_cannot_mutate_customer_consent():
    response = _officer_client().post(
        reverse("accounts:consent"),
        {
            "data_consent": True,
            "ai_consent": True,
            "consent_version": ConsentService.current_policy()["consent_version"],
        },
        format="json",
    )
    assert response.status_code == 403


@override_settings(CONSENT_POLICY_VERSION="2026-08-01")
def test_consent_events_cannot_be_modified_through_model_api():
    customer = _customer("append-only@example.com")
    ConsentService.record_consent(
        customer.id,
        "customer",
        data_consent=True,
        ai_consent=True,
        consent_version="2026-08-01",
    )
    event = ConsentEvent.latest_for_user(customer.id)
    event.ai_consent = False

    with pytest.raises(ValueError, match="append-only"):
        event.save()
