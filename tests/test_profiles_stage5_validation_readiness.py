"""Stage 5 validation, completion-policy, and readiness coverage."""

from datetime import date, datetime, time
from decimal import Decimal
from io import StringIO

import pytest
from bson import ObjectId
from bson.decimal128 import Decimal128
from django.core.management import call_command
from django.utils import timezone

from profiles.models import (
    PROFILE_COMPLETION_POLICY_VERSION,
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
)
from profiles.serializers import (
    AlternativeDataSerializer,
    BusinessProfileSerializer,
    CustomerProfileSerializer,
)
from profiles.services.summary import get_profile_summary
from profiles.views.profile_views import _date_only_iso


def _years_ago(years):
    today = timezone.localdate()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(month=2, day=28, year=today.year - years)


def _complete_personal(customer_id):
    return CustomerProfile(
        customer_id=customer_id,
        date_of_birth=_years_ago(30),
        gender="female",
        civil_status="single",
        nationality="Filipino",
        mobile_number="+639171234567",
        address_line1="1 Rizal Street",
        barangay="Barangay 1-A",
        city_municipality="Davao City",
        province="Davao del Sur",
        zip_code="8000",
    )


def _complete_business(customer_id):
    return BusinessProfile(
        customer_id=customer_id,
        business_name="Stage Five Store",
        business_type="market_vendor",
        business_address="2 Market Road",
        business_barangay="Barangay 2",
        business_city="Davao City",
        business_province="Davao del Sur",
        business_age_months=24,
        is_registered=False,
        estimated_monthly_income=Decimal("50000.25"),
        income_range="50000_100000",
        estimated_monthly_expenses=Decimal("20000.50"),
        number_of_employees=0,
    )


def _complete_alternative(customer_id):
    return AlternativeData(
        customer_id=customer_id,
        education_level="college_graduate",
        employment_status="self_employed",
        years_of_experience=5,
        housing_status="owned",
        years_at_current_address=3,
        number_of_dependents=0,
        household_income=Decimal("50000.25"),
        has_existing_loans=False,
        has_bank_account=False,
        has_ewallet=False,
        pays_utilities=False,
        is_coop_member=False,
    )


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        (_years_ago(18), True),
        (_years_ago(100), True),
        (_years_ago(17), False),
        (_years_ago(101), False),
        (timezone.localdate(), False),
    ],
)
def test_date_of_birth_enforces_supported_customer_age(value, valid):
    serializer = CustomerProfileSerializer(data={"date_of_birth": value})

    assert serializer.is_valid() is valid
    if not valid:
        assert "date_of_birth" in serializer.errors


def test_personal_identity_fields_normalize_and_accept_real_location_shapes():
    serializer = CustomerProfileSerializer(
        data={
            "mobile_number": "0917 123 4567",
            "emergency_contact_phone": "0918-765-4321",
            "zip_code": "8000",
            "barangay": "Barangay 1-A",
            "city_municipality": "City of Mati",
            "province": "Davao Oriental",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["mobile_number"] == "+639171234567"
    assert serializer.validated_data["emergency_contact_phone"] == "+639187654321"


@pytest.mark.parametrize(
    "payload",
    [
        {"emergency_contact_phone": "12345"},
        {"zip_code": "80A0"},
        {"zip_code": "800"},
        {"barangay": "_invalid"},
    ],
)
def test_personal_identity_rejects_invalid_contact_or_location(payload):
    serializer = CustomerProfileSerializer(data=payload)
    assert not serializer.is_valid()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1.001"])
def test_monetary_fields_reject_nonfinite_or_overprecision(value):
    serializer = AlternativeDataSerializer(data={"household_income": value})
    assert not serializer.is_valid()
    assert "household_income" in serializer.errors


def test_decimal_money_uses_decimal128_without_an_encryption_key(settings):
    settings.FIELD_ENCRYPTION_KEY = ""
    customer_id = str(ObjectId())
    serializer = BusinessProfileSerializer(
        data={
            "estimated_monthly_income": "50000.25",
            "estimated_monthly_expenses": "12345.67",
        }
    )
    assert serializer.is_valid(), serializer.errors
    BusinessProfile(customer_id=customer_id, **serializer.validated_data).save()

    raw = settings.MONGODB["business_profiles"].find_one(
        {"customer_id": customer_id}
    )
    loaded = BusinessProfile.find_by_customer(customer_id)
    assert isinstance(raw["estimated_monthly_income"], Decimal128)
    assert loaded.estimated_monthly_income == Decimal("50000.25")
    assert loaded.estimated_monthly_expenses == Decimal("12345.67")


def test_business_registration_rules_use_existing_partial_update_state():
    profile = BusinessProfile(
        customer_id=str(ObjectId()),
        is_registered=True,
        registration_type="DTI",
        registration_number="DTI-123",
    )
    valid_partial = BusinessProfileSerializer(
        instance=profile,
        data={"business_name": "Updated"},
        partial=True,
    )
    assert valid_partial.is_valid(), valid_partial.errors

    invalid = BusinessProfileSerializer(
        instance=BusinessProfile(customer_id="new"),
        data={"is_registered": True},
        partial=True,
    )
    assert not invalid.is_valid()
    assert "registration_type" in invalid.errors

    clear = BusinessProfileSerializer(
        instance=profile,
        data={"is_registered": False},
        partial=True,
    )
    assert clear.is_valid(), clear.errors
    assert clear.validated_data["registration_type"] is None
    assert clear.validated_data["registration_number"] == ""


@pytest.mark.parametrize(
    ("payload", "error_field"),
    [
        ({"housing_status": "rented"}, "monthly_rent"),
        ({"has_existing_loans": True}, "existing_loan_amount"),
        ({"has_bank_account": True}, "bank_account_duration"),
        ({"has_ewallet": True}, "ewallet_usage"),
        ({"pays_utilities": True}, "utility_payment_history"),
    ],
)
def test_alternative_conditional_fields_are_required(payload, error_field):
    serializer = AlternativeDataSerializer(
        instance=AlternativeData(customer_id="new"),
        data=payload,
        partial=True,
    )
    assert not serializer.is_valid()
    assert error_field in serializer.errors


def test_alternative_false_controllers_clear_stale_dependents():
    profile = AlternativeData(
        customer_id="customer",
        housing_status="rented",
        monthly_rent=Decimal("8000.00"),
        has_existing_loans=True,
        existing_loan_amount=Decimal("10000.00"),
        existing_loan_source="bank",
        loan_payment_history="on_time",
        has_bank_account=True,
        bank_account_duration=2,
        has_ewallet=True,
        ewallet_usage="daily",
        pays_utilities=True,
        utility_payment_history="on_time",
    )
    serializer = AlternativeDataSerializer(
        instance=profile,
        data={
            "housing_status": "owned",
            "has_existing_loans": False,
            "has_bank_account": False,
            "has_ewallet": False,
            "pays_utilities": False,
        },
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    for field in (
        "monthly_rent",
        "existing_loan_amount",
        "existing_loan_source",
        "loan_payment_history",
        "bank_account_duration",
        "ewallet_usage",
        "utility_payment_history",
    ):
        assert serializer.validated_data[field] is None


def test_completion_policy_counts_false_and_zero_as_answered_values():
    customer_id = str(ObjectId())
    personal = _complete_personal(customer_id).save()
    business = _complete_business(customer_id).save()
    alternative = _complete_alternative(customer_id).save()

    assert personal.profile_completed is True
    assert business.profile_completed is True
    assert alternative.profile_completed is True
    assert business.number_of_employees == 0
    assert alternative.number_of_dependents == 0
    assert alternative.has_existing_loans is False
    assert personal.profile_missing_fields == []


def test_completion_transition_returns_versioned_machine_readable_gaps():
    customer_id = str(ObjectId())
    profile = _complete_personal(customer_id).save()
    assert profile.profile_completed is True

    profile = profile.update_fields({"mobile_number": ""})
    assert profile.profile_completed is False
    assert profile.profile_completion_policy_version == PROFILE_COMPLETION_POLICY_VERSION
    assert profile.profile_missing_fields == ["personal.mobile_number"]

    profile = profile.update_fields({"mobile_number": "+639171234567"})
    assert profile.profile_completed is True
    assert profile.profile_missing_fields == []


def test_summary_separates_profile_readiness_from_documents_and_eligibility():
    customer_id = str(ObjectId())
    _complete_personal(customer_id).save()
    _complete_business(customer_id).save()
    _complete_alternative(customer_id).save()

    summary = get_profile_summary(customer_id)

    assert summary["overall"]["profiles_complete"] is True
    assert summary["overall"]["profile_ready_for_application"] is True
    assert summary["overall"]["ready_for_loan"] is True
    assert summary["overall"]["ready_for_loan_deprecated"] is True
    assert summary["overall"]["product_eligibility_evaluated"] is False
    assert summary["overall"]["completion_policy_version"] == (
        PROFILE_COMPLETION_POLICY_VERSION
    )
    assert summary["overall"]["missing_field_codes"] == []
    assert summary["documents"]["has_documents"] is False
    assert summary["documents"]["all_approved"] is False


def test_datetime_birth_date_is_exposed_as_date_only():
    profile = _complete_personal(str(ObjectId()))
    profile.date_of_birth = datetime.combine(date(1990, 1, 2), time.min)
    profile.save()

    loaded = CustomerProfile.find_by_customer(profile.customer_id)
    assert loaded.date_of_birth.isoformat() == "1990-01-02T00:00:00"
    assert _date_only_iso(loaded.date_of_birth) == "1990-01-02"


def test_completion_reconciliation_is_dry_run_by_default(settings):
    customer_id = str(ObjectId())
    profile = _complete_personal(customer_id).save()
    settings.MONGODB["customer_profiles"].update_one(
        {"_id": profile._id},
        {
            "$set": {
                "profile_completed": False,
                "completion_percentage": 10,
                "profile_completion_policy_version": "legacy",
                "profile_missing_fields": ["legacy.field"],
            }
        },
    )

    call_command("recalculate_profile_completion", stdout=StringIO())
    raw = settings.MONGODB["customer_profiles"].find_one({"_id": profile._id})
    assert raw["profile_completion_policy_version"] == "legacy"

    call_command("recalculate_profile_completion", apply=True, stdout=StringIO())
    raw = settings.MONGODB["customer_profiles"].find_one({"_id": profile._id})
    assert raw["profile_completed"] is True
    assert raw["completion_percentage"] == 100
    assert raw["profile_completion_policy_version"] == (
        PROFILE_COMPLETION_POLICY_VERSION
    )
    assert raw["profile_missing_fields"] == []
