"""Stage 7 customer export, history, review workflow, and operations coverage."""

from decimal import Decimal

import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Customer, LoanOfficer
from analytics.models import AuditLog
from config.field_encryption import (
    _build_keyring,
    _get_fernet,
    decrypt_value,
    is_encrypted_value,
)
from profiles.models import AlternativeData, CustomerProfile, RiskReviewRequest
from profiles.services.lifecycle import delete_customer_profile_data
from profiles.tasks import (
    collect_profile_operational_metrics_task,
    reconcile_profile_audit_failures_task,
)
from profiles.views.profile_views import (
    CustomerProfileView,
    OfficerRiskReviewDetailView,
    OfficerRiskReviewListView,
    ProfileExportView,
    ProfileHistoryView,
    RiskReviewRequestView,
)


def _customer():
    return Customer(
        first_name="Stage",
        last_name="Seven",
        email=f"profile-stage7-{ObjectId()}@example.com",
        password="hashed",
        verified=True,
    ).save()


@pytest.fixture
def profile_encryption(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = ()
    settings.FIELD_ENCRYPTION_STRICT_DECRYPTION = True
    _get_fernet.cache_clear()
    _build_keyring.cache_clear()
    yield settings
    _get_fernet.cache_clear()
    _build_keyring.cache_clear()


def _officer():
    return LoanOfficer(
        employee_id=f"STAGE7-{str(ObjectId())[-8:]}",
        first_name="Review",
        last_name="Officer",
        email=f"review-officer-{ObjectId()}@example.com",
        password="hashed",
        verified=True,
        active=True,
    ).save()


def _auth(actor, role):
    return AuthenticatedUser(
        customer_id=str(actor.id),
        email=actor.email,
        verified=True,
        role=role,
    )


def _request(method, path, actor, role, payload=None, query=None):
    factory = APIRequestFactory()
    if method == "get":
        request = factory.get(path, query or {}, format="json")
    else:
        request = getattr(factory, method)(path, payload or {}, format="json")
    force_authenticate(request, user=_auth(actor, role))
    return request


def _disable_auth(monkeypatch, *views):
    for view in views:
        monkeypatch.setattr(view, "authentication_classes", [], raising=False)
        monkeypatch.setattr(view, "permission_classes", [], raising=False)


def _completed_alternative(customer):
    return AlternativeData(
        customer_id=customer.id,
        household_income=Decimal("50000.00"),
        risk_score=72,
        risk_category="low",
        risk_score_status="complete",
        risk_score_policy_version="2026-08-09-v1",
        risk_input_revision=3,
        risk_calculated_revision=3,
        risk_score_reason_codes=["income_mid"],
    ).save()


def _assign(officer, customer):
    from django.conf import settings

    settings.MONGODB["loan_applications"].insert_one(
        {
            "customer_id": str(customer.id),
            "assigned_officer": str(officer.id),
            "status": "under_review",
        }
    )


def test_profile_export_is_allowlisted_ephemeral_and_audited(monkeypatch):
    customer = _customer()
    CustomerProfile(
        customer_id=customer.id,
        mobile_number="+639171234567",
        address_line1="1 Export Street",
    ).save()
    alternative = _completed_alternative(customer)
    from django.conf import settings

    settings.MONGODB[AlternativeData.collection_name].update_one(
        {"_id": alternative._id}, {"$set": {"risk_score_task_id": "internal-task"}}
    )
    _disable_auth(monkeypatch, ProfileExportView)

    response = ProfileExportView.as_view()(
        _request("get", "/api/profile/export/", customer, "customer")
    )

    assert response.status_code == 200
    export = response.data["data"]
    assert export["scope"] == "profiles_only"
    assert export["retention"]["server_copy_created"] is False
    assert export["personal_profile"]["data"]["mobile_number"] == "+639171234567"
    assert "risk_score_task_id" not in export["alternative_data"]["data"]
    assert AuditLog.find_by_action("profile_exported", limit=1)


def test_profile_export_fails_closed_and_queues_failed_audit(monkeypatch, settings):
    customer = _customer()
    _disable_auth(monkeypatch, ProfileExportView)

    def unavailable(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditLog, "log_action", unavailable)
    response = ProfileExportView.as_view()(
        _request("get", "/api/profile/export/", customer, "customer")
    )

    assert response.status_code == 503
    queued = settings.MONGODB["audit_write_failures"].find_one(
        {"domain": "profiles", "action": "profile_exported"}
    )
    assert queued is not None
    assert "personal_profile" not in decrypt_value(queued["payload_encrypted"])


def test_history_exposes_change_metadata_but_not_values_or_ip(monkeypatch):
    customer = _customer()
    CustomerProfile(customer_id=customer.id).save()
    _disable_auth(monkeypatch, CustomerProfileView, ProfileHistoryView)

    update = CustomerProfileView.as_view()(
        _request(
            "put",
            "/api/profile/",
            customer,
            "customer",
            {"gender": "female", "civil_status": "single"},
        )
    )
    history = ProfileHistoryView.as_view()(
        _request("get", "/api/profile/history/", customer, "customer")
    )

    assert update.status_code == 200
    assert history.status_code == 200
    event = history.data["data"]["history"][0]
    assert event["changed_fields"] == ["civil_status", "gender"]
    assert "female" not in str(event)
    assert "ip_address" not in event


def test_customer_can_request_one_review_per_completed_score(monkeypatch):
    customer = _customer()
    _completed_alternative(customer)
    RiskReviewRequest.create_indexes()
    _disable_auth(monkeypatch, RiskReviewRequestView)
    payload = {
        "reason": "unexpected_score",
        "description": "Please review the displayed result.",
        "risk_calculated_revision": 3,
    }

    created = RiskReviewRequestView.as_view()(
        _request(
            "post", "/api/profile/risk-reviews/", customer, "customer", payload
        )
    )
    duplicate = RiskReviewRequestView.as_view()(
        _request(
            "post", "/api/profile/risk-reviews/", customer, "customer", payload
        )
    )

    assert created.status_code == 201
    assert created.data["data"]["review"]["status"] == "pending"
    assert duplicate.status_code == 409
    assert AuditLog.find_by_action("risk_review_requested", limit=1)


def test_risk_review_requires_current_completed_result(monkeypatch):
    customer = _customer()
    AlternativeData(
        customer_id=customer.id,
        risk_score_status="pending",
        risk_input_revision=2,
    ).save()
    _disable_auth(monkeypatch, RiskReviewRequestView)

    response = RiskReviewRequestView.as_view()(
        _request(
            "post",
            "/api/profile/risk-reviews/",
            customer,
            "customer",
            {"reason": "missing_context"},
        )
    )

    assert response.status_code == 400


def test_risk_review_free_text_is_encrypted_at_rest(profile_encryption):
    customer = _customer()
    review = RiskReviewRequest.create_for_score(
        _completed_alternative(customer),
        reason="other",
        description="Sensitive correction context",
    )

    raw = profile_encryption.MONGODB[RiskReviewRequest.collection_name].find_one(
        {"_id": review._id}
    )
    loaded = RiskReviewRequest.find_by_id(review.id)
    assert is_encrypted_value(raw["description"])
    assert loaded.description == "Sensitive correction context"


def test_scoped_officer_can_list_and_resolve_review(monkeypatch):
    customer = _customer()
    officer = _officer()
    _assign(officer, customer)
    alternative = _completed_alternative(customer)
    RiskReviewRequest.create_indexes()
    review = RiskReviewRequest.create_for_score(
        alternative,
        reason="incorrect_profile_data",
        description="Income information was corrected.",
    )
    _disable_auth(
        monkeypatch,
        OfficerRiskReviewListView,
        OfficerRiskReviewDetailView,
    )

    listing = OfficerRiskReviewListView.as_view()(
        _request(
            "get", "/api/officer/profile-risk-reviews/", officer, "loan_officer"
        )
    )
    resolved = OfficerRiskReviewDetailView.as_view()(
        _request(
            "put",
            f"/api/officer/profile-risk-reviews/{review.id}/",
            officer,
            "loan_officer",
            {
                "status": "resolved",
                "resolution_note": "Reviewed corrected customer data.",
                "review_revision": 0,
            },
        ),
        review_id=review.id,
    )
    stale = OfficerRiskReviewDetailView.as_view()(
        _request(
            "put",
            f"/api/officer/profile-risk-reviews/{review.id}/",
            officer,
            "loan_officer",
            {
                "status": "resolved",
                "resolution_note": "Duplicate stale transition.",
                "review_revision": 0,
            },
        ),
        review_id=review.id,
    )

    assert listing.status_code == 200
    assert listing.data["data"]["total"] == 1
    assert resolved.status_code == 200
    assert resolved.data["data"]["review"]["status"] == "resolved"
    assert resolved.data["data"]["review"]["review_revision"] == 1
    assert stale.status_code == 409


def test_out_of_scope_review_is_concealed_from_officer(monkeypatch):
    customer = _customer()
    assigned_officer = _officer()
    other_officer = _officer()
    _assign(assigned_officer, customer)
    review = RiskReviewRequest.create_for_score(
        _completed_alternative(customer),
        reason="other",
        description="Manual review requested.",
    )
    _disable_auth(monkeypatch, OfficerRiskReviewDetailView)

    response = OfficerRiskReviewDetailView.as_view()(
        _request(
            "put",
            f"/api/officer/profile-risk-reviews/{review.id}/",
            other_officer,
            "loan_officer",
            {
                "status": "in_review",
                "resolution_note": "",
                "review_revision": 0,
            },
        ),
        review_id=review.id,
    )

    assert response.status_code == 404
    assert RiskReviewRequest.find_by_id(review.id).status == "pending"


def test_risk_reviews_follow_profile_account_deletion_policy(settings):
    customer = _customer()
    review = RiskReviewRequest.create_for_score(
        _completed_alternative(customer),
        reason="other",
        description="Delete with profile lifecycle.",
    )
    settings.MONGODB["audit_write_failures"].insert_many(
        [
            {
                "domain": "profiles",
                "resolved_at": None,
                "payload": {"user_id": customer.id},
            },
            {
                "domain": "profiles",
                "resolved_at": None,
                "payload": {"details": {"customer_id": customer.id}},
            },
            {
                "domain": "accounts",
                "resolved_at": None,
                "payload": {"user_id": customer.id},
            },
        ]
    )

    deleted = delete_customer_profile_data(settings.MONGODB, customer.id)

    assert deleted[RiskReviewRequest.collection_name] == 1
    assert deleted["profile_audit_write_failures"] == 2
    assert RiskReviewRequest.find_by_id(review.id) is None
    assert settings.MONGODB["audit_write_failures"].count_documents({}) == 1


def test_failed_profile_audit_can_be_reconciled(monkeypatch, settings):
    customer = _customer()
    _disable_auth(monkeypatch, CustomerProfileView)
    original = AuditLog.log_action

    def unavailable(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditLog, "log_action", unavailable)
    response = CustomerProfileView.as_view()(
        _request("put", "/api/profile/", customer, "customer", {"gender": "female"})
    )
    assert response.status_code == 200
    queued = settings.MONGODB["audit_write_failures"].find_one(
        {"domain": "profiles", "action": "profile_created"}
    )
    assert queued is not None

    monkeypatch.setattr(AuditLog, "log_action", original)
    assert reconcile_profile_audit_failures_task.run() == 1
    resolved = settings.MONGODB["audit_write_failures"].find_one(
        {"_id": queued["_id"]}
    )
    assert resolved["resolved_at"] is not None
    assert "payload_encrypted" not in resolved
    assert AuditLog.find_by_action("profile_created", limit=1)


def test_operational_inventory_reports_duplicates_plaintext_and_backlogs(settings):
    customer_id = str(ObjectId())
    settings.MONGODB[CustomerProfile.collection_name].insert_many(
        [
            {"customer_id": customer_id, "mobile_number": "09171234567"},
            {"customer_id": customer_id, "mobile_number": "09181234567"},
        ]
    )
    settings.MONGODB["audit_write_failures"].insert_one(
        {"domain": "profiles", "resolved_at": None}
    )
    settings.MONGODB[RiskReviewRequest.collection_name].insert_one(
        {"customer_id": customer_id, "status": "pending"}
    )

    result = collect_profile_operational_metrics_task.run()

    assert result["duplicates"][CustomerProfile.collection_name] == 1
    assert result["unprotected_fields"][CustomerProfile.collection_name] == 2
    assert result["audit_backlog"] == 1
    assert result["review_backlog"]["pending"] == 1
