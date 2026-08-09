import json
import os

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Admin, Consent, Customer, LoanOfficer
from accounts.services import AuthService
from accounts.services.account_lifecycle_service import AccountLifecycleService
from accounts.services.password_service import PasswordService
from accounts.tasks import finalize_scheduled_customer_deletions_task
from accounts.utils.email_utils import EmailUtils
from accounts.utils.token_utils import TokenUtils
from analytics.models import AuditLog


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _customer(email="stage8@example.com", *, password="Pass123!", two_factor=False):
    customer = Customer(
        first_name="Stage",
        last_name="Eight",
        email=email,
        verified=True,
        two_factor_enabled=two_factor,
        two_factor_secret="JBSWY3DPEHPK3PXP" if two_factor else None,
    )
    customer.set_password(password)
    customer.save()
    return customer


def _admin(username="stage8-admin"):
    admin = Admin(
        username=username,
        email=f"{username}@example.com",
        first_name="Stage",
        last_name="Admin",
        permissions=["manage_users"],
    )
    admin.set_password("AdminPass123!")
    admin.save()
    return admin


def _customer_client(customer):
    tokens = AuthService.create_customer_tokens(customer)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client, tokens


def _admin_client(admin):
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
def test_manage_users_state_transitions_revoke_and_restore_security_state(settings):
    customer = _customer("state-stage8@example.com")
    admin_client = _admin_client(_admin("state-stage8-admin"))

    tokens = AuthService.create_customer_tokens(customer)
    session_id = RefreshToken(tokens["refresh"])["session_id"]
    settings.MONGODB[Customer.collection_name].update_one(
        {"_id": customer._id},
        {"$set": {"failed_login_attempts": 5, "locked_until": None}},
    )

    suspended = admin_client.patch(
        reverse("accounts:admin-customer-detail", kwargs={"customer_id": customer.id}),
        {"account_state": "suspended", "reason": "Manual review"},
        format="json",
    )
    assert suspended.status_code == 200
    assert suspended.json()["data"]["account_state"] == "suspended"
    assert not TokenUtils.is_session_active(customer.id, "customer", session_id, 2)

    restored = admin_client.patch(
        reverse("accounts:admin-customer-detail", kwargs={"customer_id": customer.id}),
        {"account_state": "active", "reason": "Review completed"},
        format="json",
    )
    assert restored.status_code == 200
    refreshed = Customer.find_one({"_id": customer._id})
    assert refreshed.account_state == "active"
    assert refreshed.active is True
    assert refreshed.failed_login_attempts == 0
    assert refreshed.locked_until is None
    assert AuditLog.find_by_action("account_suspended", limit=10)


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_verified_email_change_consumes_otp_and_revokes_sessions(monkeypatch):
    customer = _customer("email-stage8@example.com")
    client, tokens = _customer_client(customer)
    sent = {}

    def fake_send(email, first_name, token):
        sent.update({"email": email, "token": token})
        return True

    monkeypatch.setattr(EmailUtils, "send_email_change_verification", fake_send)
    requested = client.post(
        reverse("accounts:email-change-request"),
        {"new_email": "new-stage8@example.com", "password": "Pass123!"},
        format="json",
    )
    assert requested.status_code == 200, requested.content
    assert sent["email"] == "new-stage8@example.com"
    assert len(sent["token"]) == 6

    confirmed = client.post(
        reverse("accounts:email-change-confirm"),
        {"otp": sent["token"]},
        format="json",
    )
    assert confirmed.status_code == 200
    refreshed = Customer.find_one({"_id": customer._id})
    assert refreshed.email == "new-stage8@example.com"
    assert not TokenUtils.is_session_active(
        customer.id,
        "customer",
        RefreshToken(tokens["refresh"])["session_id"],
        refreshed.security_version,
    )
    assert AuditLog.find_by_action("email_changed", limit=10)


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_account_export_serializes_mongodb_values():
    customer = _customer("export-stage8@example.com")
    Consent(
        user_id=customer._id,
        user_type="customer",
        data_consent=True,
        ai_consent=False,
    ).save()
    client, _tokens = _customer_client(customer)

    response = client.get(reverse("accounts:account-export"))

    assert response.status_code == 200, response.content
    payload = response.json()
    json.dumps(payload)
    assert payload["data"]["consent"]["user_id"] == str(customer._id)


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_first_new_device_login_emits_security_event():
    customer = _customer("device-stage8@example.com")
    response = APIClient().post(
        reverse("accounts:login"),
        {"email": customer.email, "password": "Pass123!"},
        format="json",
        REMOTE_ADDR="203.0.113.80",
        HTTP_USER_AGENT="Stage8-Test-Device",
    )

    assert response.status_code == 200
    assert AuditLog.find_by_action("new_device_login", limit=10)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    WEBSOCKET_ENABLED=False,
    ACCOUNT_DELETION_RETENTION_DAYS=0,
)
def test_deletion_can_be_cancelled_with_credentials_and_finalized_after_retention():
    customer = _customer("deletion-stage8@example.com")
    client, _tokens = _customer_client(customer)

    requested = client.post(
        reverse("accounts:account-deletion-request"),
        {"reason": "No longer needed"},
        format="json",
    )
    assert requested.status_code == 200
    assert requested.json()["data"]["account_state"] == "pending_deletion"

    cancelled = APIClient().post(
        reverse("accounts:account-deletion-cancel"),
        {"email": customer.email, "password": "Pass123!"},
        format="json",
    )
    assert cancelled.status_code == 200
    assert Customer.find_one({"_id": customer._id}).account_state == "active"

    refreshed = Customer.find_one({"_id": customer._id})
    deletion_client, _ = _customer_client(refreshed)
    assert (
        deletion_client.post(
            reverse("accounts:account-deletion-request"),
            {},
            format="json",
        ).status_code
        == 200
    )

    admin_client = _admin_client(_admin("deletion-stage8-admin"))
    finalized = admin_client.post(
        reverse(
            "accounts:admin-customer-deletion-finalize",
            kwargs={"customer_id": customer.id},
        ),
        {},
        format="json",
    )
    assert finalized.status_code == 200
    deleted = Customer.find_one({"_id": customer._id})
    assert deleted.account_state == "deleted"
    assert deleted.active is False
    assert deleted.password == ""
    assert deleted.email.endswith("@deleted.local")

    cleanup_status = admin_client.get(
        reverse("accounts:admin-customer-detail", kwargs={"customer_id": customer.id})
    )
    assert cleanup_status.status_code == 200
    assert cleanup_status.json()["data"]["profile_cleanup_status"] == "complete"
    assert cleanup_status.json()["data"]["profile_cleanup_attempts"] == 1
    assert cleanup_status.json()["data"]["profile_cleanup_last_error"] == ""


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_deletion_finalization_is_blocked_before_retention_period():
    customer = _customer("deletion-due-stage8@example.com")
    client, _tokens = _customer_client(customer)
    assert (
        client.post(
            reverse("accounts:account-deletion-request"),
            {},
            format="json",
        ).status_code
        == 200
    )

    admin_client = _admin_client(_admin("deletion-due-stage8-admin"))
    response = admin_client.post(
        reverse(
            "accounts:admin-customer-deletion-finalize",
            kwargs={"customer_id": customer.id},
        ),
        {},
        format="json",
    )
    assert response.status_code == 409
    assert response.json()["code"] == "deletion_not_due"


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_two_factor_recovery_requires_admin_decision_and_is_audited(monkeypatch):
    customer = _customer("recovery-stage8@example.com", two_factor=True)
    sent = {}

    def fake_send(email, first_name, token):
        sent.update({"email": email, "token": token})
        return True

    monkeypatch.setattr(EmailUtils, "send_verification_email", fake_send)
    public_client = APIClient()
    requested = public_client.post(
        reverse("accounts:2fa-recovery-request"),
        {"email": customer.email, "password": "Pass123!"},
        format="json",
    )
    assert requested.status_code == 200, requested.content
    assert requested.json()["message"]

    verified = public_client.post(
        reverse("accounts:2fa-recovery-verify"),
        {"email": customer.email, "otp": sent["token"]},
        format="json",
    )
    assert verified.status_code == 200
    assert AccountLifecycleService.is_two_factor_recovery_request_valid(
        Customer.find_one({"_id": customer._id})
    )

    admin_client = _admin_client(_admin("recovery-stage8-admin"))
    pending = admin_client.get(reverse("accounts:admin-customer-2fa-recovery-list"))
    assert pending.status_code == 200
    assert pending.json()["data"]["requests"][0]["id"] == customer.id

    decision = admin_client.post(
        reverse(
            "accounts:admin-customer-2fa-recovery-decision",
            kwargs={"customer_id": customer.id},
        ),
        {"approve": True, "reason": "Identity verified"},
        format="json",
    )
    assert decision.status_code == 200
    assert Customer.find_one({"_id": customer._id}).two_factor_enabled is False
    assert AuditLog.find_by_action("two_factor_recovery_approved", limit=10)


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_ambiguous_cross_role_email_requires_explicit_recovery_role():
    email = "ambiguous-stage8@example.com"
    _customer(email)
    officer = LoanOfficer(
        employee_id="STAGE8-LO",
        first_name="Stage",
        last_name="Officer",
        email=email,
        verified=True,
        active=True,
    )
    officer.set_password("OfficerPass123!")
    officer.save()

    assert PasswordService._find_user_by_email(email) == (None, None)
    customer, customer_type = PasswordService._find_user_by_email(email, "customer")
    assert customer is not None
    assert customer_type == "customer"


@override_settings(SECURE_SSL_REDIRECT=False, WEBSOCKET_ENABLED=False)
def test_scheduled_deletion_task_finalizes_due_accounts():
    customer = _customer("task-stage8@example.com")
    AccountLifecycleService.request_deletion(customer)
    settings_customer = Customer.find_one({"_id": customer._id})
    settings_customer.deletion_scheduled_for = AccountLifecycleService._now()
    settings_customer.save()

    result = finalize_scheduled_customer_deletions_task.run()
    assert "Finalized 1" in result
    assert Customer.find_one({"_id": customer._id}).account_state == "deleted"
