"""Stage 4 officer event scope and dashboard metric reconciliation tests."""

import pytest
from bson import ObjectId
from cryptography.fernet import Fernet

from accounts.authentication import AuthenticatedUser
from analytics.models import AuditLog
from analytics.services.dashboard_metrics import METRIC_DEFINITION_VERSION
from analytics.views import (
    AdminDashboardView,
    CustomerDashboardView,
    OfficerAuditLogsView,
    OfficerDashboardView,
)
from config.field_encryption import _build_keyring, _get_fernet
from loans.services.audit import record_loan_audit
from tests.test_analytics_api import (
    _auth_get_request,
    _bypass_auth,
    _create_admin,
    _create_customer,
    _create_officer,
    _restore_auth,
)


def _user(account, role):
    return AuthenticatedUser(
        customer_id=str(account.id),
        email=account.email,
        verified=True,
        role=role,
    )


def _get(view, path, user, query=None):
    original_auth, original_perm = _bypass_auth(view)
    try:
        return view.as_view()(_auth_get_request(path, user, query))
    finally:
        _restore_auth(view, original_auth, original_perm)


def test_event_time_scope_does_not_transfer_history_on_reassignment(settings):
    first = _create_officer()
    second = _create_officer()
    loan_id = settings.MONGODB["loan_applications"].insert_one(
        {
            "customer_id": str(ObjectId()),
            "assigned_officer": str(first.id),
            "status": "under_review",
        }
    ).inserted_id

    event = record_loan_audit(
        action="loan_submitted",
        user_id=str(ObjectId()),
        user_type="customer",
        resource_type="loan",
        resource_id=str(loan_id),
        details={"amount": 10000, "product": "Microloan", "term": 6},
    )
    stored = settings.MONGODB["audit_logs"].find_one({"_id": event._id})
    assert stored["scope_officer_index"] == AuditLog.blind_index(str(first.id))
    assert stored["scope_policy_version"] == "event-time-assignment-v1"

    settings.MONGODB["loan_applications"].update_one(
        {"_id": loan_id}, {"$set": {"assigned_officer": str(second.id)}}
    )
    query = {"action": "loan_submitted"}
    first_response = _get(
        OfficerAuditLogsView,
        "/api/analytics/officer/audit-logs/",
        _user(first, "loan_officer"),
        query,
    )
    second_response = _get(
        OfficerAuditLogsView,
        "/api/analytics/officer/audit-logs/",
        _user(second, "loan_officer"),
        query,
    )

    assert first_response.data["data"]["total"] == 1
    assert second_response.data["data"]["total"] == 0


def test_assignment_event_scopes_to_assignee_not_admin_actor(settings):
    officer = _create_officer()
    event = record_loan_audit(
        action="loan_assigned",
        user_id=str(ObjectId()),
        user_type="admin",
        resource_type="loan",
        resource_id=str(ObjectId()),
        details={
            "assigned_officer": str(officer.id),
            "customer_id": str(ObjectId()),
            "loan_id": str(ObjectId()),
            "new_status": "under_review",
            "old_status": "submitted",
        },
    )
    raw = settings.MONGODB["audit_logs"].find_one({"_id": event._id})
    assert raw["scope_officer_index"] == AuditLog.blind_index(str(officer.id))


def test_scope_policy_fails_closed_when_incomplete_or_unknown(settings):
    with pytest.raises(ValueError, match="scope and policy"):
        AuditLog.log_action(
            action="loan_submitted",
            user_type="customer",
            scope_officer_id=str(ObjectId()),
        )
    with pytest.raises(ValueError, match="Unregistered audit officer scope"):
        AuditLog.log_action(
            action="loan_submitted",
            user_type="customer",
            scope_officer_id=str(ObjectId()),
            scope_policy_version="current-assignment-unsafe",
        )
    assert settings.MONGODB["audit_logs"].count_documents({}) == 0


def test_legacy_unscoped_customer_event_is_not_broadened_by_current_assignment(
    settings,
):
    officer = _create_officer()
    loan_id = settings.MONGODB["loan_applications"].insert_one(
        {
            "assigned_officer": str(officer.id),
            "status": "under_review",
        }
    ).inserted_id
    AuditLog.log_action(
        action="loan_submitted",
        user_id=str(ObjectId()),
        user_type="customer",
        resource_type="loan",
        resource_id=str(loan_id),
    )

    response = _get(
        OfficerAuditLogsView,
        "/api/analytics/officer/audit-logs/",
        _user(officer, "loan_officer"),
        {"action": "loan_submitted"},
    )
    assert response.data["data"]["total"] == 0


def test_event_scope_and_integrity_remain_readable_during_key_rotation(settings):
    officer = _create_officer()
    old_key = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEY = old_key
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = ()
    _build_keyring.cache_clear()
    _get_fernet.cache_clear()
    event = AuditLog.log_action(
        action="loan_submitted",
        user_type="customer",
        resource_type="loan",
        resource_id=str(ObjectId()),
        scope_officer_id=str(officer.id),
        scope_policy_version="event-time-assignment-v1",
    )
    raw = settings.MONGODB["audit_logs"].find_one({"_id": event._id})

    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = (old_key,)
    _build_keyring.cache_clear()
    _get_fernet.cache_clear()
    try:
        assert AuditLog.verify_integrity_document(raw)
        response = _get(
            OfficerAuditLogsView,
            "/api/analytics/officer/audit-logs/",
            _user(officer, "loan_officer"),
            {"action": "loan_submitted"},
        )
        assert response.data["data"]["total"] == 1
    finally:
        _build_keyring.cache_clear()
        _get_fernet.cache_clear()


def test_loan_outcome_metrics_reconcile_across_dashboards(settings):
    customer = _create_customer()
    officer = _create_officer()
    product_id = settings.MONGODB["loan_products"].insert_one(
        {"name": "Growth", "active": True}
    ).inserted_id
    statuses = ["approved", "disbursed", "completed", "written_off", "rejected"]
    settings.MONGODB["loan_applications"].insert_many(
        [
            {
                "customer_id": ObjectId(str(customer.id)),
                "assigned_officer": ObjectId(str(officer.id)),
                "product_id": str(product_id),
                "status": loan_status,
            }
            for loan_status in statuses
        ]
    )

    admin = _create_admin(permissions=["view_analytics"])
    admin_data = _get(
        AdminDashboardView, "/api/analytics/admin/", _user(admin, "admin")
    ).data["data"]
    officer_data = _get(
        OfficerDashboardView,
        "/api/analytics/officer/",
        _user(officer, "loan_officer"),
    ).data["data"]
    customer_data = _get(
        CustomerDashboardView,
        "/api/analytics/customer/",
        _user(customer, "customer"),
    ).data["data"]

    for data in (admin_data, officer_data, customer_data):
        assert data["metric_definition_version"] == METRIC_DEFINITION_VERSION
        assert data["as_of"].endswith("+00:00")
    assert admin_data["loans"]["approved"] == 4
    assert admin_data["loans"]["reviewed"] == 5
    assert officer_data["my_reviews"]["total_approved"] == 4
    assert officer_data["performance"] == {
        "total_reviewed": 5,
        "approval_rate": "80.0%",
    }
    assert customer_data["applications"]["approved"] == 4
    assert customer_data["applications"]["disbursed"] == 3
    assert admin_data["products"][0]["reviewed"] == 5
    assert admin_data["products"][0]["approval_rate"] == "80.0%"


def test_document_metrics_use_current_available_canonical_status(settings):
    customer = _create_customer()
    owner = ObjectId(str(customer.id))
    settings.MONGODB["documents"].insert_many(
        [
            {
                "customer_id": owner,
                "document_type": "valid_id",
                "status": "pending",
                "verified": False,
                "storage_state": "available",
            },
            {
                "customer_id": owner,
                "document_type": "valid_id",
                "status": "approved",
                "verified": True,
                "storage_state": "available",
            },
            {
                "customer_id": owner,
                "document_type": "valid_id",
                "status": "approved",
                "verified": True,
                "storage_state": "delete_pending",
            },
            {
                "customer_id": owner,
                "document_type": "valid_id",
                "status": "approved",
                "verified": True,
                "storage_state": "available",
                "superseded_by_document_id": str(ObjectId()),
            },
        ]
    )

    data = _get(
        CustomerDashboardView,
        "/api/analytics/customer/",
        _user(customer, "customer"),
    ).data["data"]
    assert data["documents"]["total"] == 2
    assert data["documents"]["pending"] == 1
    assert data["documents"]["verified"] == 1
    assert data["profile_completion"]["valid_id_uploaded"] is True


def test_pending_valid_id_is_not_reported_as_ready(settings):
    customer = _create_customer()
    settings.MONGODB["documents"].insert_one(
        {
            "customer_id": str(customer.id),
            "document_type": "valid_id",
            "status": "pending",
            "verified": False,
            "storage_state": "available",
        }
    )
    data = _get(
        CustomerDashboardView,
        "/api/analytics/customer/",
        _user(customer, "customer"),
    ).data["data"]
    assert data["profile_completion"]["valid_id_uploaded"] is False
