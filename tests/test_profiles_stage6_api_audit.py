"""Stage 6 API consistency, preferences, and mutation-audit coverage."""

from decimal import Decimal

import pytest
from bson import ObjectId
from django.conf import settings
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Customer
from analytics.models import AuditLog
from profiles.models import AlternativeData, BusinessProfile, CustomerProfile
from profiles.serializers import (
    BusinessProfileSerializer,
    NotificationPreferencesUpdateSerializer,
)
from profiles.services.notification_preferences import (
    DEFAULT_PREFERENCES,
    get_preferences,
    update_preferences,
)
from profiles.views.profile_views import (
    AlternativeDataView,
    BusinessProfileView,
    CustomerProfileView,
    NotificationPreferencesView,
)
from scripts.backfill_business_age_months import main as reconcile_business_age


def _customer():
    return Customer(
        first_name="Stage",
        last_name="Six",
        email=f"profile-stage6-{ObjectId()}@example.com",
        password="hashed",
        verified=True,
    ).save()


def _auth(customer):
    return AuthenticatedUser(
        customer_id=str(customer.id),
        email=customer.email,
        verified=True,
        role="customer",
    )


def _request(method, path, customer, payload=None, **meta):
    factory = APIRequestFactory()
    request = getattr(factory, method)(path, payload or {}, format="json", **meta)
    force_authenticate(request, user=_auth(customer))
    return request


def _disable_auth(monkeypatch, view):
    monkeypatch.setattr(view, "authentication_classes", [], raising=False)
    monkeypatch.setattr(view, "permission_classes", [], raising=False)


def test_legacy_business_years_convert_to_canonical_months():
    serializer = BusinessProfileSerializer(data={"years_in_operation": "1.5"})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {"business_age_months": 18}


def test_matching_business_age_fields_are_accepted_and_alias_is_removed():
    serializer = BusinessProfileSerializer(
        data={"years_in_operation": 2, "business_age_months": 24}
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {"business_age_months": 24}


@pytest.mark.parametrize(
    "payload",
    [
        {"years_in_operation": 2, "business_age_months": 25},
        {"years_in_operation": "0.01"},
    ],
)
def test_ambiguous_business_age_inputs_are_rejected(payload):
    serializer = BusinessProfileSerializer(data=payload)

    assert not serializer.is_valid()
    assert "years_in_operation" in serializer.errors


def test_business_put_persists_legacy_years_as_canonical_months(monkeypatch):
    customer = _customer()
    _disable_auth(monkeypatch, BusinessProfileView)

    response = BusinessProfileView.as_view()(
        _request(
            "put",
            "/api/profile/business/",
            customer,
            {"years_in_operation": 2},
        )
    )

    assert response.status_code == 200
    stored = BusinessProfile.find_by_customer(customer.id)
    assert stored.business_age_months == 24
    raw = settings.MONGODB["business_profiles"].find_one({"_id": stored._id})
    assert "years_in_operation" not in raw


def test_business_age_reconciliation_is_dry_run_by_default_and_revision_guarded():
    collection = settings.MONGODB[BusinessProfile.collection_name]
    document_id = collection.insert_one(
        {
            "customer_id": str(ObjectId()),
            "years_in_operation": 1.5,
            "profile_revision": 4,
        }
    ).inserted_id

    dry_run = reconcile_business_age()
    assert dry_run == {"found": 1, "eligible": 1, "updated": 0}
    assert "business_age_months" not in collection.find_one({"_id": document_id})

    applied = reconcile_business_age(apply=True)
    stored = collection.find_one({"_id": document_id})
    assert applied == {"found": 1, "eligible": 1, "updated": 1}
    assert stored["business_age_months"] == 18
    assert stored["profile_revision"] == 5


def test_business_get_uses_the_documented_canonical_schema(monkeypatch):
    customer = _customer()
    BusinessProfile(
        customer_id=customer.id,
        business_name="Canonical Store",
        estimated_monthly_income=Decimal("1000.00"),
    ).save()
    _disable_auth(monkeypatch, BusinessProfileView)

    response = BusinessProfileView.as_view()(
        _request("get", "/api/profile/business/", customer)
    )

    assert response.status_code == 200
    assert set(response.data["data"]) == {
        "id",
        "customer_id",
        "business_name",
        "business_type",
        "business_type_other",
        "business_description",
        "business_address",
        "business_barangay",
        "business_city",
        "business_province",
        "business_age_months",
        "is_registered",
        "registration_type",
        "registration_number",
        "estimated_monthly_income",
        "income_range",
        "estimated_monthly_expenses",
        "number_of_employees",
        "profile_revision",
        "profile_completed",
        "completion_percentage",
        "profile_completion_policy_version",
        "profile_missing_fields",
    }
    assert "years_in_operation" not in response.data["data"]


def test_alternative_get_uses_the_documented_canonical_schema(monkeypatch):
    customer = _customer()
    AlternativeData(customer_id=customer.id).save()
    _disable_auth(monkeypatch, AlternativeDataView)

    response = AlternativeDataView.as_view()(
        _request("get", "/api/profile/alternative-data/", customer)
    )

    assert response.status_code == 200
    assert set(response.data["data"]) == {
        "id",
        "customer_id",
        "education_level",
        "employment_status",
        "years_of_experience",
        "housing_status",
        "years_at_current_address",
        "monthly_rent",
        "number_of_dependents",
        "household_income",
        "has_existing_loans",
        "existing_loan_amount",
        "existing_loan_source",
        "loan_payment_history",
        "has_bank_account",
        "bank_account_duration",
        "has_ewallet",
        "ewallet_usage",
        "pays_utilities",
        "utility_payment_history",
        "is_coop_member",
        "community_involvement",
        "risk_score",
        "risk_category",
        "score_calculated_at",
        "risk_score_status",
        "risk_score_policy_version",
        "risk_score_use",
        "risk_score_manual_review_required",
        "risk_input_revision",
        "risk_calculated_revision",
        "risk_score_breakdown",
        "risk_score_reason_codes",
        "risk_score_error_code",
        "risk_score_requested_at",
        "risk_score_failed_at",
        "profile_revision",
        "profile_completed",
        "completion_percentage",
        "profile_completion_policy_version",
        "profile_missing_fields",
    }


def test_partial_stored_preferences_merge_with_defaults():
    customer = _customer()
    customer.notification_preferences = {"email_promotions": True}

    assert get_preferences(customer) == {
        **DEFAULT_PREFERENCES,
        "email_promotions": True,
    }


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}])
def test_notification_preferences_require_actual_json_booleans(value):
    serializer = NotificationPreferencesUpdateSerializer(
        data={"preferences": {"email_promotions": value}}
    )

    assert not serializer.is_valid()
    assert "email_promotions" in serializer.errors["preferences"]


def test_notification_serializer_rejects_missing_object_and_unknown_keys():
    missing = NotificationPreferencesUpdateSerializer(data={})
    wrong_shape = NotificationPreferencesUpdateSerializer(
        data={"preferences": "false"}
    )
    unknown = NotificationPreferencesUpdateSerializer(
        data={"preferences": {"sms_promotions": True}}
    )

    assert not missing.is_valid()
    assert not wrong_shape.is_valid()
    assert not unknown.is_valid()


def test_atomic_partial_preferences_preserve_concurrent_account_and_pref_changes():
    customer = _customer()
    first_snapshot = Customer.find_one({"_id": customer._id})
    second_snapshot = Customer.find_one({"_id": customer._id})
    collection = settings.MONGODB[Customer.collection_name]
    collection.update_one({"_id": customer._id}, {"$set": {"last_name": "Concurrent"}})

    update_preferences(first_snapshot, {"email_promotions": True})
    update_preferences(second_snapshot, {"email_payment_reminders": False})

    stored = collection.find_one({"_id": customer._id})
    assert stored["last_name"] == "Concurrent"
    assert stored["notification_preferences"]["email_promotions"] is True
    assert stored["notification_preferences"]["email_payment_reminders"] is False


def test_notification_update_is_audited_with_trusted_client_ip(monkeypatch):
    customer = _customer()
    _disable_auth(monkeypatch, NotificationPreferencesView)
    monkeypatch.setattr(api_settings, "NUM_PROXIES", 1)

    response = NotificationPreferencesView.as_view()(
        _request(
            "put",
            "/api/profile/notifications/",
            customer,
            {"preferences": {"email_promotions": True}},
            REMOTE_ADDR="192.0.2.10",
            HTTP_X_FORWARDED_FOR="198.51.100.20, 203.0.113.30",
        )
    )

    assert response.status_code == 200
    audit = AuditLog.find_by_action("notification_preferences_updated", limit=1)[0]
    assert audit.ip_address == "203.0.113.30"
    assert audit.details == {"changed_keys": ["email_promotions"]}


def test_first_profile_mutation_records_creation(monkeypatch):
    customer = _customer()
    _disable_auth(monkeypatch, CustomerProfileView)

    response = CustomerProfileView.as_view()(
        _request("put", "/api/profile/", customer, {"gender": "female"})
    )

    assert response.status_code == 200
    audit = AuditLog.find_by_action("profile_created", limit=1)[0]
    assert audit.resource_type == "customer_profile"
    assert audit.details["profile_revision"] == 1


def test_business_and_alternative_mutations_record_resource_audits(monkeypatch):
    customer = _customer()
    BusinessProfile(customer_id=customer.id).save()
    AlternativeData(customer_id=customer.id).save()
    _disable_auth(monkeypatch, BusinessProfileView)
    _disable_auth(monkeypatch, AlternativeDataView)
    monkeypatch.setattr(
        "profiles.views.profile_views.enqueue_risk_score_calculation",
        lambda *args, **kwargs: True,
    )

    business_response = BusinessProfileView.as_view()(
        _request(
            "put",
            "/api/profile/business/",
            customer,
            {"business_name": "Audited Store"},
        )
    )
    alternative_response = AlternativeDataView.as_view()(
        _request(
            "put",
            "/api/profile/alternative-data/",
            customer,
            {"education_level": "college_graduate"},
        )
    )

    assert business_response.status_code == 200
    assert alternative_response.status_code == 200
    resources = {
        audit.resource_type
        for audit in AuditLog.find_by_action("profile_updated", limit=10)
    }
    assert {"business_profile", "alternative_data"} <= resources
    assert alternative_response.data["data"]["profile_completion_policy_version"]


def test_audit_failure_does_not_turn_a_durable_mutation_into_an_error(monkeypatch):
    customer = _customer()
    profile = CustomerProfile(customer_id=customer.id).save()
    _disable_auth(monkeypatch, CustomerProfileView)

    def audit_unavailable(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditLog, "log_action", audit_unavailable)
    response = CustomerProfileView.as_view()(
        _request("put", "/api/profile/", customer, {"gender": "female"})
    )

    assert response.status_code == 200
    stored = CustomerProfile.find_by_customer(customer.id)
    assert stored._id == profile._id
    assert stored.gender == "female"


def test_preference_audit_failure_keeps_successful_atomic_update(monkeypatch):
    customer = _customer()
    _disable_auth(monkeypatch, NotificationPreferencesView)

    def audit_unavailable(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditLog, "log_action", audit_unavailable)
    response = NotificationPreferencesView.as_view()(
        _request(
            "put",
            "/api/profile/notifications/",
            customer,
            {"preferences": {"email_promotions": True}},
        )
    )

    assert response.status_code == 200
    stored = Customer.find_one({"_id": customer._id})
    assert stored.notification_preferences["email_promotions"] is True
