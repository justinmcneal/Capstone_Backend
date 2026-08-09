"""Stage 4 coverage for profile encryption and persistence integrity."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO

import pytest
from bson import ObjectId
from bson.decimal128 import Decimal128
from cryptography.fernet import Fernet
from django.core.management import call_command
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Customer
from config.field_encryption import (
    _build_keyring,
    _get_fernet,
    decrypt_value,
    encrypt_value,
    is_encrypted_value,
)
from profiles.models import (
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
    ProfileRevisionConflict,
)
from profiles.services.summary import get_profile_summary
from profiles.views.profile_views import (
    AlternativeDataView,
    BusinessProfileView,
    CustomerProfileView,
)


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


@pytest.mark.parametrize(
    "value",
    [42, 42.75, Decimal("42.7500"), Decimal128("42.7500")],
)
def test_numeric_encryption_round_trips_native_type(profile_encryption, value):
    encrypted = encrypt_value(value)

    assert is_encrypted_value(encrypted)
    decrypted = decrypt_value(encrypted)
    assert type(decrypted) is type(value)
    assert decrypted == value


def test_profile_financial_fields_are_ciphertext_at_rest(profile_encryption):
    customer_id = str(ObjectId())
    BusinessProfile(
        customer_id=customer_id,
        estimated_monthly_income=75_000.25,
        estimated_monthly_expenses=25_000.5,
    ).save()
    AlternativeData(
        customer_id=customer_id,
        monthly_rent=8_000.25,
        household_income=75_000.25,
        existing_loan_amount=12_000.5,
    ).save()

    business_raw = profile_encryption.MONGODB["business_profiles"].find_one(
        {"customer_id": customer_id}
    )
    alternative_raw = profile_encryption.MONGODB["alternative_data"].find_one(
        {"customer_id": customer_id}
    )
    for field in ("estimated_monthly_income", "estimated_monthly_expenses"):
        assert is_encrypted_value(business_raw[field])
    for field in ("monthly_rent", "household_income", "existing_loan_amount"):
        assert is_encrypted_value(alternative_raw[field])

    business = BusinessProfile.find_by_customer(customer_id)
    alternative = AlternativeData.find_by_customer(customer_id)
    assert business.estimated_monthly_income == 75_000.25
    assert business.estimated_monthly_expenses == 25_000.5
    assert alternative.monthly_rent == 8_000.25
    assert alternative.household_income == 75_000.25
    assert alternative.existing_loan_amount == 12_000.5


def test_encryption_backfill_supports_numeric_profile_fields(profile_encryption):
    collection = profile_encryption.MONGODB["alternative_data"]
    result = collection.insert_one(
        {
            "customer_id": str(ObjectId()),
            "household_income": 50_000.25,
            "existing_loan_amount": 10_000,
        }
    )

    output = StringIO()
    call_command("encrypt_sensitive_fields", apply=True, stdout=output)
    stored = collection.find_one({"_id": result.inserted_id})

    assert is_encrypted_value(stored["household_income"])
    assert is_encrypted_value(stored["existing_loan_amount"])
    assert "unsupported=0" in output.getvalue()
    call_command("encrypt_sensitive_fields", verify=True, stdout=StringIO())


def test_profile_summary_does_not_create_missing_profile_shells(settings):
    customer_id = str(ObjectId())

    summary = get_profile_summary(customer_id)

    assert summary["personal_profile"]["profile_revision"] == 0
    assert summary["business_profile"]["profile_revision"] == 0
    assert summary["alternative_data"]["profile_revision"] == 0
    assert settings.MONGODB["customer_profiles"].count_documents({}) == 0
    assert settings.MONGODB["business_profiles"].count_documents({}) == 0
    assert settings.MONGODB["alternative_data"].count_documents({}) == 0


def _customer():
    customer = Customer(
        first_name="Stage",
        last_name="Four",
        email=f"stage4-{ObjectId()}@example.com",
        verified=True,
    )
    customer.set_password("OldPass123!")
    return customer.save()


def _request(method, path, customer, payload=None):
    factory = APIRequestFactory()
    request = getattr(factory, method)(path, payload or {}, format="json")
    force_authenticate(
        request,
        user=AuthenticatedUser(
            customer_id=customer.id,
            email=customer.email,
            verified=True,
        ),
    )
    return request


def test_individual_profile_gets_are_side_effect_free(settings, monkeypatch):
    customer = _customer()
    endpoints = (
        (CustomerProfileView, "/api/profile/", "customer_profiles"),
        (BusinessProfileView, "/api/profile/business/", "business_profiles"),
        (
            AlternativeDataView,
            "/api/profile/alternative-data/",
            "alternative_data",
        ),
    )

    for view_class, path, collection_name in endpoints:
        monkeypatch.setattr(view_class, "authentication_classes", [])
        monkeypatch.setattr(view_class, "permission_classes", [])
        response = view_class.as_view()(_request("get", path, customer))
        assert response.status_code == 200
        assert response.data["data"]["id"] is None
        assert settings.MONGODB[collection_name].count_documents({}) == 0


def test_profile_api_returns_conflict_for_a_stale_revision(monkeypatch):
    customer = _customer()
    CustomerProfile(customer_id=customer.id).save()
    monkeypatch.setattr(CustomerProfileView, "authentication_classes", [])
    monkeypatch.setattr(CustomerProfileView, "permission_classes", [])
    monkeypatch.setattr(
        "profiles.views.profile_views.AuditLog.log_action", lambda **_kwargs: None
    )

    first = CustomerProfileView.as_view()(
        _request(
            "put",
            "/api/profile/",
            customer,
            {"gender": "female", "profile_revision": 0},
        )
    )
    stale = CustomerProfileView.as_view()(
        _request(
            "put",
            "/api/profile/",
            customer,
            {"civil_status": "single", "profile_revision": 0},
        )
    )

    assert first.status_code == 200
    assert first.data["data"]["profile_revision"] == 1
    assert stale.status_code == 409


def test_atomic_partial_updates_preserve_unrelated_concurrent_changes():
    customer_id = str(ObjectId())
    BusinessProfile(
        customer_id=customer_id,
        business_name="Original",
        business_type="market_vendor",
        income_range="20000_30000",
    ).save()
    first = BusinessProfile.find_by_customer(customer_id)
    second = BusinessProfile.find_by_customer(customer_id)

    first.update_fields({"business_name": "Updated name"})
    second.update_fields({"business_type": "food_vendor"})

    stored = BusinessProfile.find_by_customer(customer_id)
    assert stored.business_name == "Updated name"
    assert stored.business_type == "food_vendor"
    assert stored.profile_revision == 2


def test_expected_revision_rejects_stale_partial_update():
    customer_id = str(ObjectId())
    profile = CustomerProfile(customer_id=customer_id).save()

    updated = profile.update_fields({"gender": "female"}, expected_revision=0)
    with pytest.raises(ProfileRevisionConflict):
        profile.update_fields({"civil_status": "single"}, expected_revision=0)

    stored = CustomerProfile.find_by_customer(customer_id)
    assert updated.profile_revision == 1
    assert stored.gender == "female"
    assert stored.civil_status is None


def test_atomic_get_or_create_produces_one_profile_document():
    customer_id = str(ObjectId())
    CustomerProfile.create_indexes()

    with ThreadPoolExecutor(max_workers=8) as executor:
        profiles = list(
            executor.map(lambda _number: CustomerProfile.get_or_create(customer_id), range(8))
        )

    assert len({profile.id for profile in profiles}) == 1
    assert CustomerProfile.find_by_customer(customer_id).profile_revision == 0


def test_duplicate_reconciliation_is_dry_run_by_default(settings):
    customer_object_id = ObjectId()
    older = datetime.now(timezone.utc) - timedelta(days=1)
    newer = datetime.now(timezone.utc)
    for collection_name in (
        "customer_profiles",
        "business_profiles",
        "alternative_data",
    ):
        collection = settings.MONGODB[collection_name]
        collection.insert_many(
            [
                {
                    "customer_id": customer_object_id,
                    "updated_at": older,
                    "marker": "older",
                },
                {
                    "customer_id": str(customer_object_id),
                    "updated_at": newer,
                    "marker": "newer",
                },
            ]
        )

    call_command("reconcile_duplicate_profiles", stdout=StringIO())
    assert settings.MONGODB["customer_profiles"].count_documents({}) == 2

    call_command("reconcile_duplicate_profiles", apply=True, stdout=StringIO())
    for collection_name in (
        "customer_profiles",
        "business_profiles",
        "alternative_data",
    ):
        documents = list(settings.MONGODB[collection_name].find({}))
        assert len(documents) == 1
        assert documents[0]["customer_id"] == str(customer_object_id)
        assert documents[0]["marker"] == "newer"
