"""Stage 1 characterization tests for confirmed profile defects.

These assertions intentionally describe current behavior. Later remediation stages
must replace each characterization with the secure/correct target expectation.
"""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from bson import ObjectId
from cryptography.fernet import Fernet

from accounts.models import Customer
from accounts.services.account_lifecycle_service import AccountLifecycleService
from config.field_encryption import _build_keyring, _get_fernet, is_encrypted_value
from profiles.models import (
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
    ProfileRevisionConflict,
)
from profiles.serializers import BusinessProfileSerializer
from profiles.services.notification_preferences import update_preferences
from profiles.services.risk_scoring import _income_score, _loan_history_score
from profiles.services.summary import get_profile_summary
from profiles.tasks import calculate_risk_score_task


def test_summary_get_path_is_side_effect_free(settings):
    customer_id = str(ObjectId())

    summary = get_profile_summary(customer_id)

    assert summary["customer_id"] == customer_id
    assert settings.MONGODB["customer_profiles"].count_documents({}) == 0
    assert settings.MONGODB["business_profiles"].count_documents({}) == 0
    assert settings.MONGODB["alternative_data"].count_documents({}) == 0


def test_numeric_income_and_canonical_late_values_have_explicit_scores():
    numeric_income = SimpleNamespace(household_income=50_000)
    sometimes_late = SimpleNamespace(
        has_existing_loans=True, loan_payment_history="sometimes_late"
    )
    often_late = SimpleNamespace(
        has_existing_loans=True, loan_payment_history="often_late"
    )

    assert _income_score(numeric_income) == 80.0
    assert _loan_history_score(sometimes_late) == 60.0
    assert _loan_history_score(often_late) == 30.0


def test_risk_task_does_not_overwrite_a_newer_profile_update(settings, monkeypatch):
    customer_id = str(ObjectId())
    AlternativeData(
        customer_id=customer_id,
        education_level="college_graduate",
        housing_status="owned",
        household_income=50_000,
    ).save()

    def score_after_concurrent_update(_alternative):
        settings.MONGODB["alternative_data"].update_one(
            {"customer_id": customer_id},
            {
                "$set": {"housing_status": "rented"},
                "$inc": {"risk_input_revision": 1},
            },
        )
        return {"total_score": 70, "category": "low"}

    monkeypatch.setattr("profiles.tasks.calculate_risk_score", score_after_concurrent_update)
    result = calculate_risk_score_task(customer_id, 0)

    stored = settings.MONGODB["alternative_data"].find_one(
        {"customer_id": customer_id}
    )
    assert result["stale"] is True
    assert stored["housing_status"] == "rented"
    assert stored.get("risk_score") is None


def test_numeric_financial_fields_are_encrypted_and_round_trip(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = ()
    _get_fernet.cache_clear()
    _build_keyring.cache_clear()
    try:
        customer_id = str(ObjectId())
        AlternativeData(
            customer_id=customer_id,
            household_income=50_000,
            existing_loan_amount=10_000,
            existing_loan_source="bank",
        ).save()

        stored = settings.MONGODB["alternative_data"].find_one(
            {"customer_id": customer_id}
        )
        assert is_encrypted_value(stored["household_income"])
        assert is_encrypted_value(stored["existing_loan_amount"])
        assert is_encrypted_value(stored["existing_loan_source"])
        reloaded = AlternativeData.find_by_customer(customer_id)
        assert reloaded.household_income == 50_000
        assert reloaded.existing_loan_amount == 10_000
        assert reloaded.existing_loan_source == "bank"
    finally:
        _get_fernet.cache_clear()
        _build_keyring.cache_clear()


def test_account_finalization_deletes_profile_domain_data(settings):
    customer = Customer(
        first_name="Delete",
        last_name="Profile",
        email="delete-profile@example.com",
        verified=True,
        account_state="pending_deletion",
        deletion_scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    customer.set_password("OldPass123!")
    customer.save()
    CustomerProfile(
        customer_id=customer.id,
        address_line1="Sensitive Address",
        mobile_number="+639171234567",
    ).save()
    BusinessProfile(
        customer_id=customer.id,
        business_name="Sensitive Business",
        business_type="retail_store",
    ).save()
    AlternativeData(
        customer_id=customer.id,
        household_income=50_000,
    ).save()

    deleted = AccountLifecycleService.finalize_deletion(customer)

    assert deleted is not None
    assert deleted.profile_cleanup_status == "complete"
    assert CustomerProfile.find_by_customer(customer.id) is None
    assert BusinessProfile.find_by_customer(customer.id) is None
    assert AlternativeData.find_by_customer(customer.id) is None


def test_full_document_save_rejects_a_stale_business_revision():
    customer_id = str(ObjectId())
    BusinessProfile(
        customer_id=customer_id,
        business_name="Original Name",
        business_type="retail_store",
        income_range="20000_30000",
    ).save()
    first = BusinessProfile.find_by_customer(customer_id)
    second = BusinessProfile.find_by_customer(customer_id)

    first.business_name = "New Name"
    first.save()
    second.business_type = "food_vendor"
    with pytest.raises(ProfileRevisionConflict):
        second.save()

    stored = BusinessProfile.find_by_customer(customer_id)
    assert stored.business_name == "New Name"
    assert stored.business_type == "retail_store"


def test_minimal_legacy_fields_do_not_report_application_readiness():
    customer_id = str(ObjectId())
    CustomerProfile(
        customer_id=customer_id,
        date_of_birth=date(1990, 1, 1),
        gender="female",
        civil_status="single",
        address_line1="Address",
        barangay="Barangay",
        city_municipality="City",
        province="Province",
    ).save()
    BusinessProfile(
        customer_id=customer_id,
        business_type="retail_store",
        income_range="20000_30000",
    ).save()
    AlternativeData(
        customer_id=customer_id,
        education_level="college_graduate",
        housing_status="owned",
    ).save()

    summary = get_profile_summary(customer_id)

    assert summary["overall"]["profiles_complete"] is False
    assert summary["overall"]["profile_ready_for_application"] is False
    assert summary["overall"]["ready_for_loan"] is False
    assert "personal.mobile_number" in summary["overall"]["missing_field_codes"]
    assert "business.business_name" in summary["overall"]["missing_field_codes"]
    assert "alternative.employment_status" in summary["overall"]["missing_field_codes"]


def test_legacy_business_age_input_maps_to_canonical_months():
    serializer = BusinessProfileSerializer(data={"years_in_operation": 2})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {"business_age_months": 24}
    assert "years_in_operation" not in serializer.validated_data


def test_string_notification_boolean_is_rejected():
    customer = SimpleNamespace(
        id="customer-1",
        notification_preferences={"email_promotions": False},
        save=lambda: None,
    )

    with pytest.raises(TypeError, match="JSON booleans"):
        update_preferences(customer, {"email_promotions": "false"})
