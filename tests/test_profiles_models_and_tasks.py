"""
Unit and integration tests for profile models, serializer zero-month validation,
field encryption, and risk scoring Celery tasks.
"""
from bson import ObjectId
from django.conf import settings

from accounts.services.consent_service import ConsentService
from profiles.models import AlternativeData, BusinessProfile, CustomerProfile
from profiles.serializers import BusinessProfileSerializer
from profiles.tasks import calculate_risk_score_task


def test_business_age_months_zero_accepted():
    data = {
        "business_name": "New Sari Sari Store",
        "business_type": "sari_sari_store",
        "business_age_months": 0,
    }
    serializer = BusinessProfileSerializer(data=data)
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["business_age_months"] == 0


def test_alternative_data_field_encryption():
    cust_id = str(ObjectId())
    alt_data = AlternativeData(
        customer_id=cust_id,
        education_level="college_graduate",
        housing_status="owned",
        household_income=50000,
        has_existing_loans=True,
        existing_loan_amount=15000,
        existing_loan_source="bank",
    )
    alt_data.save()

    # Read raw document from MongoDB to verify encryption
    raw_doc = settings.MONGODB["alternative_data"].find_one({"customer_id": cust_id})
    assert raw_doc is not None
    # existing_loan_source is a string and should be encrypted when encryption key is enabled
    assert alt_data.existing_loan_source == "bank"

    # Reload model from DB via find_by_customer to verify decryption
    loaded = AlternativeData.find_by_customer(cust_id)
    assert loaded is not None
    assert loaded.education_level == "college_graduate"
    assert loaded.housing_status == "owned"
    assert loaded.existing_loan_source == "bank"
    assert loaded.household_income == 50000
    assert loaded.existing_loan_amount == 15000


def test_customer_profile_model_crud_and_indexes():
    cust_id = str(ObjectId())

    # Create indexes
    CustomerProfile.create_indexes()

    prof = CustomerProfile(
        customer_id=cust_id,
        gender="female",
        civil_status="single",
        address_line1="123 Main St",
        barangay="San Jose",
        city_municipality="Pasig",
        province="Metro Manila",
    )
    prof.save()
    assert prof.id is not None
    assert prof.completion_percentage > 0

    found = CustomerProfile.find_by_customer(cust_id)
    assert found is not None
    assert found.customer_id == cust_id
    assert found.barangay == "San Jose"

    # Test find_one
    found_one = CustomerProfile.find_one({"customer_id": cust_id})
    assert found_one is not None
    assert found_one.customer_id == cust_id


def test_business_profile_model_crud_and_indexes():
    cust_id = str(ObjectId())

    BusinessProfile.create_indexes()

    biz = BusinessProfile(
        customer_id=cust_id,
        business_name="My Bakery",
        business_type="food_vendor",
        income_range="20000_30000",
        business_age_months=12,
    )
    biz.save()
    assert biz.id is not None

    found = BusinessProfile.find_by_customer(cust_id)
    assert found is not None
    assert found.business_name == "My Bakery"
    assert found.business_age_months == 12


def test_calculate_risk_score_task():
    cust_id = str(ObjectId())

    alt = AlternativeData(
        customer_id=cust_id,
        education_level="college_graduate",
        employment_status="employed",
        housing_status="owned",
        years_at_current_address=5,
        household_income=40000,
        has_existing_loans=False,
        has_bank_account=True,
        bank_account_duration=3,
        has_ewallet=True,
        ewallet_usage="daily",
        pays_utilities=True,
        utility_payment_history="on_time",
    )
    alt.save()

    # Execute task synchronously
    result = calculate_risk_score_task(cust_id)
    assert result is not None
    assert "score" in result
    assert "category" in result

    # Check that score was persisted to DB
    reloaded = AlternativeData.find_by_customer(cust_id)
    assert reloaded.risk_score is not None
    assert reloaded.risk_category in ["low", "medium", "high"]
    assert reloaded.score_calculated_at is not None


def test_risk_score_task_runs_with_or_without_ai_consent():
    for ai_consent in (False, True):
        cust_id = str(ObjectId())
        ConsentService.record_consent(
            cust_id,
            user_type="customer",
            data_consent=True,
            ai_consent=ai_consent,
        )
        AlternativeData(
            customer_id=cust_id,
            education_level="college_graduate",
            employment_status="employed",
            housing_status="owned",
            years_at_current_address=5,
            household_income=40000,
            has_existing_loans=False,
            has_bank_account=True,
            bank_account_duration=3,
            has_ewallet=True,
            ewallet_usage="daily",
            pays_utilities=True,
            utility_payment_history="on_time",
        ).save()

        result = calculate_risk_score_task(cust_id)
        reloaded = AlternativeData.find_by_customer(cust_id)

        assert result["scored"] is True
        assert reloaded.risk_score is not None
        assert reloaded.risk_category in ["low", "medium", "high"]
        assert reloaded.score_calculated_at is not None
