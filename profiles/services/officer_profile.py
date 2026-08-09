"""Read-only customer profile data exposed to loan officers."""

from typing import Any

from accounts.models import Customer
from profiles.models import AlternativeData, BusinessProfile, CustomerProfile


def _isoformat(value):
    return value.isoformat() if value else None


def _as_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _find_or_empty(model, customer_id):
    return model.find_by_customer(customer_id) or model(customer_id=customer_id)


def build_officer_customer_profile(customer: Customer) -> dict[str, Any]:
    """Build the explicitly allow-listed profile payload for officer reads.

    This function deliberately does not serialize the account model or profile
    ``to_dict`` methods, because those contain password/reset/security fields
    and the personal profile contains the customer's wallet address.
    """

    customer_id = str(customer.id)
    personal = _find_or_empty(CustomerProfile, customer_id)
    business = _find_or_empty(BusinessProfile, customer_id)
    alternative = _find_or_empty(AlternativeData, customer_id)
    mobile_number = personal.mobile_number or customer.phone or None

    return {
        "customer_id": customer_id,
        "full_name": customer.full_name,
        "email": customer.email,
        "personal_profile": {
            "first_name": customer.first_name,
            "middle_name": customer.middle_name,
            "last_name": customer.last_name,
            "mobile_number": mobile_number,
            "date_of_birth": _isoformat(personal.date_of_birth),
            "gender": personal.gender,
            "civil_status": personal.civil_status,
            "nationality": personal.nationality,
            "address_line1": personal.address_line1,
            "address_line2": personal.address_line2,
            "barangay": personal.barangay,
            "city_municipality": personal.city_municipality,
            "province": personal.province,
            "zip_code": personal.zip_code,
            "profile_completed": personal.profile_completed,
            "completion_percentage": personal.completion_percentage,
        },
        "business_profile": {
            "business_name": business.business_name,
            "business_type": business.business_type,
            "business_type_other": business.business_type_other,
            "business_description": business.business_description,
            "business_address": business.business_address,
            "business_barangay": business.business_barangay,
            "business_city": business.business_city,
            "business_province": business.business_province,
            "business_age_months": business.business_age_months,
            "is_registered": business.is_registered,
            "registration_type": business.registration_type,
            "registration_number": business.registration_number,
            "estimated_monthly_income": _as_number(
                business.estimated_monthly_income
            ),
            "income_range": business.income_range,
            "estimated_monthly_expenses": _as_number(
                business.estimated_monthly_expenses
            ),
            "number_of_employees": business.number_of_employees,
            "profile_completed": business.profile_completed,
            "completion_percentage": business.completion_percentage,
        },
        "alternative_data": {
            "education_level": alternative.education_level,
            "employment_status": alternative.employment_status,
            "years_of_experience": alternative.years_of_experience,
            "housing_status": alternative.housing_status,
            "years_at_current_address": alternative.years_at_current_address,
            "monthly_rent": _as_number(alternative.monthly_rent),
            "number_of_dependents": alternative.number_of_dependents,
            "household_income": _as_number(alternative.household_income),
            "has_existing_loans": alternative.has_existing_loans,
            "existing_loan_amount": _as_number(alternative.existing_loan_amount),
            "existing_loan_source": alternative.existing_loan_source,
            "loan_payment_history": alternative.loan_payment_history,
            "has_bank_account": alternative.has_bank_account,
            "bank_account_duration": alternative.bank_account_duration,
            "has_ewallet": alternative.has_ewallet,
            "ewallet_usage": alternative.ewallet_usage,
            "pays_utilities": alternative.pays_utilities,
            "utility_payment_history": alternative.utility_payment_history,
            "is_coop_member": alternative.is_coop_member,
            "community_involvement": alternative.community_involvement,
            "risk_score": _as_number(alternative.risk_score),
            "risk_category": alternative.risk_category,
            "score_calculated_at": _isoformat(alternative.score_calculated_at),
            "risk_score_status": alternative.risk_score_status,
            "risk_score_policy_version": alternative.risk_score_policy_version,
            "risk_score_use": alternative.risk_score_use,
            "risk_score_manual_review_required": (
                alternative.risk_score_manual_review_required
            ),
            "risk_input_revision": alternative.risk_input_revision,
            "risk_calculated_revision": alternative.risk_calculated_revision,
            "risk_score_breakdown": alternative.risk_score_breakdown,
            "risk_score_reason_codes": alternative.risk_score_reason_codes,
            "risk_score_error_code": alternative.risk_score_error_code,
            "profile_completed": alternative.profile_completed,
            "completion_percentage": alternative.completion_percentage,
        },
    }
