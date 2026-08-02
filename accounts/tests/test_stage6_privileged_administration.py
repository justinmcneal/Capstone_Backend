import os
from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import Admin, LoanOfficer
from accounts.services.password_service import PasswordService
from accounts.utils.token_utils import TokenUtils
from analytics.models import AuditLog
from notifications.models.notification import Notification


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _admin(username, *, super_admin=True, active=True):
    admin = Admin(
        username=username,
        email=f"{username}@example.com",
        first_name="Stage",
        last_name="Six",
        super_admin=super_admin,
        permissions=["*"] if super_admin else ["manage_loan_officers"],
        active=active,
    )
    admin.set_password("AdminPass123!")
    admin.save()
    return admin


def _officer(employee_id="STAGE6-LO-1"):
    officer = LoanOfficer(
        employee_id=employee_id,
        email=f"{employee_id.lower()}@example.com",
        first_name="Loan",
        last_name="Officer",
        department="Loans",
        must_change_password=False,
    )
    officer.set_password("OfficerPass123!")
    officer.save()
    return officer


def _client(admin):
    tokens = TokenUtils.generate_tokens(
        user_id=admin.id,
        email=admin.email,
        role="admin",
        security_version=admin.security_version,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_super_admin_cannot_demote_self():
    actor = _admin("stage6-self")
    response = _client(actor).put(
        reverse("accounts:admin-permissions", kwargs={"admin_id": actor.id}),
        {"super_admin": False, "permissions": ["view_logs"]},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "self_demotion_not_allowed"
    refreshed = Admin.find_one({"_id": actor._id})
    assert refreshed.super_admin is True


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_super_admin_cannot_deactivate_self_through_update():
    actor = _admin("stage6-self-active")
    response = _client(actor).put(
        reverse("accounts:admin-detail", kwargs={"admin_id": actor.id}),
        {"active": False},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "self_deactivation_not_allowed"
    assert Admin.find_one({"_id": actor._id}).active is True


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_second_super_admin_can_demote_target_with_before_after_audit():
    actor = _admin("stage6-actor")
    target = _admin("stage6-target")
    response = _client(actor).put(
        reverse("accounts:admin-permissions", kwargs={"admin_id": target.id}),
        {"super_admin": False, "permissions": ["view_logs"]},
        format="json",
        REMOTE_ADDR="203.0.113.60",
    )

    assert response.status_code == 200
    refreshed = Admin.find_one({"_id": target._id})
    assert refreshed.super_admin is False
    assert refreshed.permissions == ["view_logs"]

    entries = AuditLog.find_by_action("admin_permissions_changed", limit=10)
    assert len(entries) == 1
    assert entries[0].resource_id == target.id
    assert entries[0].details["before"]["super_admin"] is True
    assert entries[0].details["after"]["super_admin"] is False
    assert entries[0].ip_address == "203.0.113.60"


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_officer_deactivation_is_blocked_until_active_workload_is_reassigned(
    settings,
):
    actor = _admin("stage6-workload")
    officer = _officer()
    settings.MONGODB["loan_applications"].insert_one(
        {
            "assigned_officer": officer.id,
            "status": "under_review",
        }
    )

    response = _client(actor).delete(
        reverse(
            "accounts:admin-loan-officer-detail",
            kwargs={"officer_id": officer.id},
        )
    )

    assert response.status_code == 409
    assert response.json()["code"] == "active_officer_workload"
    assert response.json()["errors"]["active_assignment_count"] == 1
    assert LoanOfficer.find_one({"_id": officer._id}).active is True
    assert not AuditLog.find_by_action("loan_officer_deactivated", limit=10)


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_officer_deactivation_revokes_security_state_and_is_audited():
    actor = _admin("stage6-deactivate")
    officer = _officer("STAGE6-LO-2")
    original_security_version = officer.security_version

    response = _client(actor).delete(
        reverse(
            "accounts:admin-loan-officer-detail",
            kwargs={"officer_id": officer.id},
        ),
        REMOTE_ADDR="203.0.113.61",
    )

    assert response.status_code == 200
    refreshed = LoanOfficer.find_one({"_id": officer._id})
    assert refreshed.active is False
    assert refreshed.security_version == original_security_version + 1
    entries = AuditLog.find_by_action("loan_officer_deactivated", limit=10)
    assert len(entries) == 1
    assert entries[0].details["before"] == {"active": True}
    assert entries[0].details["after"] == {"active": False}


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_stale_admin_update_cannot_overwrite_newer_state():
    actor = _admin("stage6-stale-actor")
    target = _admin("stage6-stale-target", super_admin=False)
    stale_version = target.updated_at
    target.first_name = "Newer"
    target.updated_at = target.updated_at + timedelta(seconds=1)
    target.save()

    response = _client(actor).put(
        reverse("accounts:admin-detail", kwargs={"admin_id": target.id}),
        {
            "first_name": "Overwritten",
            "last_known_updated_at": stale_version.isoformat(),
        },
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "stale_update"
    assert Admin.find_one({"_id": target._id}).first_name == "Newer"


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_officer_password_change_records_security_audit_and_notification():
    officer = _officer("STAGE6-LO-3")
    tokens = TokenUtils.generate_tokens(
        user_id=officer.id,
        email=officer.email,
        role="loan_officer",
        security_version=officer.security_version,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    response = client.post(
        reverse("accounts:change-password"),
        {
            "old_password": "OfficerPass123!",
            "new_password": "NewPass456!",
            "confirm_password": "NewPass456!",
        },
        format="json",
        REMOTE_ADDR="203.0.113.62",
    )

    assert response.status_code == 200
    entries = AuditLog.find_by_action("password_changed", limit=10)
    assert len(entries) == 1
    assert entries[0].user_id == officer.id
    assert entries[0].details == {"sessions_revoked": True}
    assert any(
        item.notification_type == "password_changed"
        for item in Notification.find_by_user(officer.id)
    )


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_single_session_termination_records_security_event():
    officer = _officer("STAGE6-LO-4")
    tokens = TokenUtils.generate_tokens(
        user_id=officer.id,
        email=officer.email,
        role="loan_officer",
        security_version=officer.security_version,
    )
    session_id = AccessToken(tokens["access"])["session_id"]
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    response = client.delete(
        reverse("accounts:active-sessions"),
        {"session_id": session_id},
        format="json",
        REMOTE_ADDR="203.0.113.63",
    )

    assert response.status_code == 200
    entries = AuditLog.find_by_action("sessions_terminated", limit=10)
    assert len(entries) == 1
    assert entries[0].user_id == officer.id
    assert entries[0].details["scope"] == "single_session"


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_officer_password_recovery_completion_records_security_event(monkeypatch):
    officer = _officer("STAGE6-LO-5")
    monkeypatch.setattr(
        "accounts.services.password_service.EmailUtils.send_password_reset_email",
        lambda **kwargs: True,
    )
    success, _ = PasswordService.initiate_password_reset(
        officer.email, "loan_officer"
    )
    assert success is True
    otp = LoanOfficer.find_one({"_id": officer._id}).password_reset_otp

    response = APIClient().post(
        reverse("accounts:reset-password"),
        {
            "email": officer.email,
            "role": "loan_officer",
            "otp": otp,
            "new_password": "Recovered456!",
            "confirm_password": "Recovered456!",
        },
        format="json",
        REMOTE_ADDR="203.0.113.64",
    )

    assert response.status_code == 200
    entries = AuditLog.find_by_action("password_reset_completed", limit=10)
    assert len(entries) == 1
    assert entries[0].user_id == officer.id
    assert any(
        item.notification_type == "password_reset_completed"
        for item in Notification.find_by_user(officer.id)
    )
