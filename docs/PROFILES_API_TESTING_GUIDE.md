# Profiles API Testing Guide

## Scope
Profiles covers customer profile data used for loan readiness:
- Personal profile
- Business profile
- Alternative credit data
- Profile summary
- Notification preferences

## Base URL and Auth
- Base URL: `http://localhost:8000/api/profile`
- Required headers:
```http
Authorization: Bearer <customer_access_token>
Content-Type: application/json
```
- Access is customer-only.

## URL Reference

1. `GET /`
- Auth: customer only
- Request fields: none
- Key response fields:
  - `id`
  - `customer_id`
  - `date_of_birth`
  - `gender`
  - `civil_status`
  - `nationality`
  - `mobile_number`
  - address fields
  - emergency contact fields
  - `wallet_address`
  - `profile_completed`
  - `completion_percentage`

2. `PUT /`
- Auth: customer only
- Request fields:
  - `date_of_birth`
  - `gender` (`male`, `female`, `other`, `prefer_not_to_say`)
  - `civil_status` (`single`, `married`, `widowed`, `separated`)
  - `nationality`
  - `mobile_number`
  - `address_line1`
  - `address_line2`
  - `barangay`
  - `city_municipality`
  - `province`
  - `zip_code`
  - `emergency_contact_name`
  - `emergency_contact_phone`
  - `emergency_contact_relationship`
  - `wallet_address`
- Key response fields: `profile_completed`, `completion_percentage`

3. `GET /business/`
- Auth: customer only
- Request fields: none
- Key response fields:
  - `id`
  - `customer_id`
  - `business_name`
  - `business_type`
  - `business_type_other`
  - `business_description`
  - `business_address`
  - `business_barangay`
  - `business_city`
  - `business_province`
  - `business_age_months` (canonical unit: months)
  - `years_in_operation` (legacy alias accepted; mapped to `business_age_months` in months)
  - `is_registered`
  - `registration_type`
  - `registration_number`
  - `estimated_monthly_income`
  - `income_range`
  - `estimated_monthly_expenses`
  - `number_of_employees`

4. `PUT /business/`
- Auth: customer only
- Request fields:
  - `business_name`
  - `business_type` (`sari_sari_store`, `market_vendor`, `home_based_seller`, `food_vendor`, `transport_service`, `freelancer`, `agriculture`, `manufacturing`, `retail_trade`, `other`)
  - `business_type_other`
  - `business_description`
  - `business_address`
  - `business_barangay`
  - `business_city`
  - `business_province`
  - `business_age_months` (canonical unit: months)
  - `years_in_operation` (legacy alias accepted; when present it's used as months-equivalent)
  
    Note: `years_in_operation` is accepted as a legacy field. The API treats it as years and converts it to `business_age_months` (months). Example: `years_in_operation: 2` → `business_age_months: 24`.
  - `is_registered`
  - `registration_type` (`DTI`, `SEC`, `BIR`, `none`)
  - `registration_number`
  - `estimated_monthly_income`
  - `income_range` (`below_10000`, `10000_20000`, `20000_30000`, `30000_50000`, `50000_100000`, `above_100000`)
  - `estimated_monthly_expenses`
  - `number_of_employees`
- Validation: `business_type_other` is required when `business_type` is `other`

5. `GET /alternative-data/`
- Auth: customer only
- Request fields: none
- Key response fields:
  - `id`
  - `customer_id`
  - `education_level`
  - `employment_status`
  - `years_of_experience`
  - `housing_status`
  - `years_at_current_address`
  - `monthly_rent`
  - `number_of_dependents`
  - `household_income`
  - `has_existing_loans`
  - `existing_loan_amount`
  - `existing_loan_source`
  - `loan_payment_history`
  - `has_bank_account`
  - `bank_account_duration`
  - `has_ewallet`
  - `ewallet_usage`
  - `pays_utilities`
  - `utility_payment_history`
  - `is_coop_member`
  - `community_involvement`
  - `risk_score`
  - `risk_category`
  - `score_calculated_at`

6. `PUT /alternative-data/`
- Auth: customer only
- Request fields:
  - `education_level` (`no_formal`, `elementary`, `high_school`, `vocational`, `college_undergraduate`, `college_graduate`, `postgraduate`)
  - `employment_status` (`employed`, `self_employed`, `unemployed`, `retired`, `student`)
  - `years_of_experience`
  - `housing_status` (`owned`, `rented`, `living_with_family`, `company_provided`)
  - `years_at_current_address`
  - `monthly_rent`
  - `number_of_dependents`
  - `household_income`
  - `has_existing_loans`
  - `existing_loan_amount`
  - `existing_loan_source` (`bank`, `cooperative`, `microfinance`, `informal`, `family`, `none`)
  - `loan_payment_history` (`on_time`, `sometimes_late`, `often_late`, `defaulted`, `no_history`)
  - `has_bank_account`
  - `bank_account_duration`
  - `has_ewallet`
  - `ewallet_usage` (`daily`, `weekly`, `monthly`, `rarely`, `never`)
  - `pays_utilities`
  - `utility_payment_history` (`on_time`, `sometimes_late`, `often_late`)
  - `is_coop_member`
  - `community_involvement`
- Key response fields: success message only

7. `GET /summary/`
- Auth: customer only
- Request fields: none
- Key response fields:
  - `customer_id`
  - `personal_profile.completed`
  - `personal_profile.completion_percentage`
  - `business_profile.completed`
  - `business_profile.has_business_type`
  - `business_profile.has_income_info`
  - `alternative_data.completed`
  - `alternative_data.has_risk_score`
  - `alternative_data.risk_category`
  - `documents.total`
  - `documents.approved`
  - `documents.pending`
  - `documents.rejected`
  - `documents.reupload_requested`
  - `documents.all_approved`
  - `documents.has_documents`
  - `overall.profiles_complete`
  - `overall.sections_complete`
  - `overall.total_sections`
  - `overall.documents_complete`
  - `overall.documents_verified`
  - `overall.ready_for_loan`
  - `overall.completion_percentage`
  - `overall.completed_section_names`
  - `overall.missing`

8. `GET /notifications/`
- Auth: customer only
- Request fields: none
- Key response fields:
  - `preferences.email_loan_updates`
  - `preferences.email_payment_reminders`
  - `preferences.email_promotions`

9. `PUT /notifications/`
- Auth: customer only
- Request fields:
```json
{
  "preferences": {
    "email_loan_updates": true,
    "email_payment_reminders": true,
    "email_promotions": false
  }
}
```
- Key response fields: `preferences`
- Validation:
  - `preferences` must be an object
  - Unknown keys are rejected
  - Boolean-like values are parsed and validated

## Smoke Test Sequence
1. Log in as a customer and set the auth header.
2. `GET /summary/` to capture initial completion.
3. `PUT /` then `GET /` to confirm personal profile updates.
4. `PUT /business/` then `GET /business/`.
5. `PUT /alternative-data/` then `GET /alternative-data/`.
6. `GET /summary/` and verify `overall.profiles_complete` and `overall.ready_for_loan`.
7. `GET /notifications/`, then `PUT /notifications/`, then `GET /notifications/` to confirm persistence.

## Common Error Cases
1. `401 Unauthorized`
- Missing or invalid auth token.

2. `403 Forbidden`
- Non-customer role accessing profile endpoints.

3. `400 Bad Request`
- Invalid choice values.
- Invalid notification preference payload.
- `business_type_other` missing when `business_type=other`.