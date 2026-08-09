"""Stage 2 profile authorization, privacy, audit, and deletion tests."""

from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from bson import ObjectId
from django.conf import settings
from django.core.management import call_command
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Customer, LoanOfficer
from accounts.services.account_lifecycle_service import AccountLifecycleService
from analytics.models import AuditLog
from profiles.models import AlternativeData, BusinessProfile, CustomerProfile
from profiles.views.profile_views import (
    OfficerCustomerProfilesListView,
    OfficerProfileView,
)


def _customer(*, active=True, account_state="active", phone=""):
    return Customer(
        first_name="Scoped",
        last_name="Customer",
        email=f"scoped-{ObjectId()}@example.com",
        password="hashed",
        phone=phone,
        verified=True,
        active=active,
        account_state=account_state,
    ).save()


def _officer():
    return LoanOfficer(
        employee_id=f"PROFILE-{str(ObjectId())[-8:]}",
        first_name="Profile",
        last_name="Officer",
        email=f"officer-{ObjectId()}@example.com",
        password="hashed",
        verified=True,
        active=True,
    ).save()


def _auth(officer):
    return AuthenticatedUser(
        customer_id=str(officer.id),
        email=officer.email,
        verified=True,
        role="loan_officer",
    )


def _assigned(officer, customer, *, status="under_review"):
    settings.MONGODB["loan_applications"].insert_one(
        {
            "customer_id": str(customer.id),
            "assigned_officer": str(officer.id),
            "status": status,
        }
    )


def _get(path, officer, query=None):
    request = APIRequestFactory().get(path, query or {}, format="json")
    force_authenticate(request, user=_auth(officer))
    return request


def _disable_framework_auth(monkeypatch, view):
    monkeypatch.setattr(view, "authentication_classes", [], raising=False)
    monkeypatch.setattr(view, "permission_classes", [], raising=False)


def test_cross_officer_profile_read_is_concealed_and_audited(monkeypatch):
    assigned_officer = _officer()
    other_officer = _officer()
    customer = _customer()
    _assigned(assigned_officer, customer)
    _disable_framework_auth(monkeypatch, OfficerProfileView)

    response = OfficerProfileView.as_view()(
        _get(f"/api/officer/profiles/{customer.id}/", other_officer),
        customer_id=customer.id,
    )

    assert response.status_code == 404
    assert response.data["message"] == "Resource not found"
    audit = AuditLog.find_by_action("profile_access_denied", limit=1)[0]
    assert audit.user_id == other_officer.id
    assert audit.resource_id == customer.id
    assert audit.details == {"reason": "outside_officer_scope"}


def test_scoped_detail_read_is_audited_and_omits_emergency_contact(monkeypatch):
    officer = _officer()
    customer = _customer()
    _assigned(officer, customer)
    CustomerProfile(
        customer_id=customer.id,
        address_line1="Review Address",
        emergency_contact_name="Private Contact",
        emergency_contact_phone="+639171234567",
    ).save()
    _disable_framework_auth(monkeypatch, OfficerProfileView)

    response = OfficerProfileView.as_view()(
        _get(f"/api/officer/profiles/{customer.id}/", officer),
        customer_id=customer.id,
    )

    assert response.status_code == 200
    personal = response.data["data"]["personal_profile"]
    assert personal["address_line1"] == "Review Address"
    assert "emergency_contact_name" not in personal
    assert "emergency_contact_phone" not in personal
    audit = AuditLog.find_by_action("profile_sensitive_read", limit=1)[0]
    assert audit.user_id == officer.id
    assert audit.resource_id == customer.id


@pytest.mark.parametrize(
    "account_state",
    ["suspended", "deactivated", "pending_deletion", "deleted"],
)
def test_inactive_customer_is_hidden_from_directory_and_detail(
    monkeypatch, account_state
):
    officer = _officer()
    customer = _customer(active=False, account_state=account_state)
    _assigned(officer, customer)
    _disable_framework_auth(monkeypatch, OfficerCustomerProfilesListView)
    _disable_framework_auth(monkeypatch, OfficerProfileView)

    directory = OfficerCustomerProfilesListView.as_view()(
        _get("/api/officer/profiles/", officer)
    )
    detail = OfficerProfileView.as_view()(
        _get(f"/api/officer/profiles/{customer.id}/", officer),
        customer_id=customer.id,
    )

    assert directory.status_code == 200
    assert directory.data["data"]["customers"] == []
    assert directory.data["data"]["total"] == 0
    assert detail.status_code == 404
    assert detail.data["message"] == "Customer not found"


def test_unassigned_submitted_customer_is_in_shared_review_scope(monkeypatch):
    officer = _officer()
    customer = _customer()
    settings.MONGODB["loan_applications"].insert_one(
        {
            "customer_id": customer.id,
            "assigned_officer": None,
            "status": "submitted",
        }
    )
    _disable_framework_auth(monkeypatch, OfficerCustomerProfilesListView)
    _disable_framework_auth(monkeypatch, OfficerProfileView)

    directory = OfficerCustomerProfilesListView.as_view()(
        _get("/api/officer/profiles/", officer)
    )
    detail = OfficerProfileView.as_view()(
        _get(f"/api/officer/profiles/{customer.id}/", officer),
        customer_id=customer.id,
    )

    assert directory.status_code == 200
    assert directory.data["data"]["customers"][0]["customer_id"] == customer.id
    assert detail.status_code == 200


def test_directory_does_not_search_or_return_phone_values(monkeypatch):
    officer = _officer()
    customer = _customer(phone="+639171112222")
    _assigned(officer, customer)
    _disable_framework_auth(monkeypatch, OfficerCustomerProfilesListView)

    response = OfficerCustomerProfilesListView.as_view()(
        _get(
            "/api/officer/profiles/",
            officer,
            query={"search": "+639171112222"},
        )
    )

    assert response.status_code == 200
    assert response.data["data"]["customers"] == []
    assert response.data["data"]["total"] == 0
    audit = AuditLog.find_by_action("profile_directory_viewed", limit=1)[0]
    assert audit.details["search_applied"] is True
    assert "+639171112222" not in str(audit.details)


def test_sensitive_profile_read_fails_closed_when_audit_cannot_be_written(
    monkeypatch,
):
    officer = _officer()
    customer = _customer()
    _assigned(officer, customer)
    _disable_framework_auth(monkeypatch, OfficerProfileView)

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditLog, "log_action", fail_audit)
    response = OfficerProfileView.as_view()(
        _get(f"/api/officer/profiles/{customer.id}/", officer),
        customer_id=customer.id,
    )

    assert response.status_code == 503
    assert "required profile access audit" in response.data["message"]


def test_profile_cleanup_is_retryable_after_interruption(monkeypatch):
    customer = Customer(
        first_name="Delete",
        last_name="Retry",
        email=f"delete-{ObjectId()}@example.com",
        verified=True,
        active=False,
        account_state="pending_deletion",
        deletion_scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    customer.set_password("OldPass123!")
    customer.save()
    CustomerProfile(customer_id=customer.id, address_line1="Sensitive").save()
    BusinessProfile(customer_id=customer.id, business_name="Sensitive").save()
    AlternativeData(customer_id=customer.id, household_income=50_000).save()

    from profiles.services import lifecycle

    real_cleanup = lifecycle.delete_customer_profile_data

    def interrupted_cleanup(db, customer_id):
        raise RuntimeError("temporary database failure")

    monkeypatch.setattr(lifecycle, "delete_customer_profile_data", interrupted_cleanup)
    with pytest.raises(RuntimeError, match="temporary database failure"):
        AccountLifecycleService.finalize_deletion(customer)

    pending_cleanup = Customer.find_one({"_id": customer._id})
    assert pending_cleanup.account_state == "deleted"
    assert pending_cleanup.profile_cleanup_status == "pending"
    assert pending_cleanup.profile_cleanup_attempts == 1
    assert pending_cleanup.profile_cleanup_last_error == "RuntimeError"
    assert CustomerProfile.find_by_customer(customer.id) is not None

    monkeypatch.setattr(lifecycle, "delete_customer_profile_data", real_cleanup)
    completed = AccountLifecycleService.finalize_deletion(pending_cleanup)

    assert completed.profile_cleanup_status == "complete"
    assert completed.profile_cleanup_attempts == 2
    assert completed.profile_cleanup_last_error == ""
    assert sum(completed.profile_cleanup_counts.values()) == 3
    assert CustomerProfile.find_by_customer(customer.id) is None
    assert BusinessProfile.find_by_customer(customer.id) is None
    assert AlternativeData.find_by_customer(customer.id) is None


def test_deleted_profile_cleanup_command_is_dry_run_by_default():
    customer = _customer(active=False, account_state="deleted")
    CustomerProfile(customer_id=customer.id, address_line1="Legacy PII").save()
    BusinessProfile(customer_id=customer.id, business_name="Legacy Business").save()
    AlternativeData(customer_id=customer.id, household_income=50_000).save()

    dry_output = StringIO()
    call_command("cleanup_deleted_customer_profiles", stdout=dry_output)

    assert "Dry run: 3 profile record(s)" in dry_output.getvalue()
    assert CustomerProfile.find_by_customer(customer.id) is not None

    apply_output = StringIO()
    call_command(
        "cleanup_deleted_customer_profiles",
        apply=True,
        stdout=apply_output,
    )

    assert "Deleted 3 profile record(s)" in apply_output.getvalue()
    assert CustomerProfile.find_by_customer(customer.id) is None
    assert BusinessProfile.find_by_customer(customer.id) is None
    assert AlternativeData.find_by_customer(customer.id) is None
    refreshed = Customer.find_one({"_id": customer._id})
    assert refreshed.profile_cleanup_status == "complete"
