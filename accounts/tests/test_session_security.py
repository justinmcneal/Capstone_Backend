import os
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.authentication import CustomJWTAuthentication
from accounts.models import Customer, LoanOfficer, RefreshTokenEntry
from accounts.models.activity import ActiveSession
from accounts.services.password_service import PasswordService
from accounts.utils.token_utils import TokenUtils


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _customer(email="security@example.com"):
    customer = Customer(
        first_name="Security",
        last_name="User",
        email=email,
        verified=True,
    )
    customer.set_password("OldPass123!")
    customer.save()
    return customer


def _officer(email="officer-security@example.com", must_change_password=True):
    officer = LoanOfficer(
        employee_id="LO-SEC-001",
        first_name="Security",
        last_name="Officer",
        email=email,
        verified=True,
        active=True,
        must_change_password=must_change_password,
    )
    officer.set_password("OldPass123!")
    officer.save()
    return officer


def _request(access_token, url_name="active-sessions"):
    request = APIRequestFactory().get(
        "/api/protected/", HTTP_AUTHORIZATION=f"Bearer {access_token}"
    )
    request.resolver_match = SimpleNamespace(url_name=url_name)
    return request


def test_session_records_never_store_or_serialize_raw_refresh_tokens(settings):
    customer = _customer()
    tokens = TokenUtils.generate_jwt_tokens(customer)
    refresh = RefreshToken(tokens["refresh"])
    access = AccessToken(tokens["access"])

    assert refresh["session_id"] == access["session_id"]
    assert refresh["security_version"] == customer.security_version

    stored = settings.MONGODB[ActiveSession.collection_name].find_one(
        {"session_id": refresh["session_id"]}
    )
    assert stored is not None
    assert "session_token" not in stored
    assert stored["refresh_token_hash"] != tokens["refresh"]

    session = ActiveSession.from_dict(stored)
    public_data = session.to_dict()
    assert "session_token" not in public_data
    assert "refresh_token_hash" not in public_data


def test_revoked_membership_immediately_invalidates_access_token():
    customer = _customer("revoke@example.com")
    tokens = TokenUtils.generate_jwt_tokens(customer)
    session_id = AccessToken(tokens["access"])["session_id"]
    authentication = CustomJWTAuthentication()

    assert authentication.authenticate(_request(tokens["access"])) is not None
    TokenUtils.revoke_session(customer.id, "customer", session_id)

    with pytest.raises(AuthenticationFailed):
        authentication.authenticate(_request(tokens["access"]))


def test_temporary_password_is_blocked_centrally_for_domain_requests():
    officer = _officer()
    tokens = TokenUtils.generate_tokens(
        officer.id,
        officer.email,
        role="loan_officer",
        security_version=officer.security_version,
        must_change_password=True,
    )

    with pytest.raises(PermissionDenied) as exc_info:
        CustomJWTAuthentication().authenticate(
            _request(tokens["access"], url_name="loan-application-list")
        )

    assert exc_info.value.status_code == 423
    assert exc_info.value.get_codes() == "password_change_required"


def test_password_change_rotates_security_version_and_revokes_sessions():
    customer = _customer("password-version@example.com")
    tokens = TokenUtils.generate_jwt_tokens(customer)
    old_version = customer.security_version

    success, _ = PasswordService.change_password(customer, "OldPass123!", "NewPass456!")

    assert success is True
    assert customer.security_version == old_version + 1
    assert not RefreshTokenEntry.find_one(
        {"token_hash": TokenUtils._hash_token(tokens["refresh"]), "is_active": True}
    )
    with pytest.raises(AuthenticationFailed):
        CustomJWTAuthentication().authenticate(_request(tokens["access"]))


def test_inactive_account_is_rejected_for_every_access_token():
    officer = _officer("inactive@example.com", must_change_password=False)
    tokens = TokenUtils.generate_tokens(
        officer.id,
        officer.email,
        role="loan_officer",
        security_version=officer.security_version,
    )
    officer.active = False
    officer.save()

    with pytest.raises(AuthenticationFailed, match="inactive"):
        CustomJWTAuthentication().authenticate(_request(tokens["access"]))


def test_legacy_session_scrubber_is_dry_run_by_default(settings):
    collection = settings.MONGODB[ActiveSession.collection_name]
    collection.insert_one(
        {"user_id": "legacy", "session_token": "plaintext", "is_active": True}
    )

    call_command("scrub_legacy_sessions", verbosity=0)
    assert collection.find_one({"user_id": "legacy"})["session_token"] == "plaintext"

    call_command("scrub_legacy_sessions", apply=True, verbosity=0)
    scrubbed = collection.find_one({"user_id": "legacy"})
    assert "session_token" not in scrubbed
    assert scrubbed["is_active"] is False
    assert scrubbed["legacy_invalidated_at"] is not None
