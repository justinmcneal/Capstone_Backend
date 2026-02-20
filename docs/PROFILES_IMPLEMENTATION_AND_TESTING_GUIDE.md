# Profiles Implementation and Testing Guide

## Scope
Profile APIs collect customer data used for loan readiness:
- Personal profile
- Business profile
- Alternative data
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

## Endpoint Reference
1. `GET /`
- Returns personal profile (creates default profile if none exists).

2. `PUT /`
- Updates personal profile.
- Key fields: `date_of_birth`, `gender`, `civil_status`, address fields, emergency contact fields.
- Response includes `profile_completed` and `completion_percentage`.

3. `GET /business/`
- Returns business profile (creates default profile if none exists).

4. `PUT /business/`
- Updates business profile.
- Key fields: `business_name`, `business_type`, `business_type_other`, `years_in_operation`, `registration_type`, `income_range`, `estimated_monthly_income`.
- Validation: if `business_type=other`, `business_type_other` is required.

5. `GET /alternative-data/`
- Returns alternative credit data (creates default record if none exists).

6. `PUT /alternative-data/`
- Updates alternative credit data.
- Key fields: education/employment, housing, existing loans, digital footprint, utility/payment behavior, community data.

7. `GET /summary/`
- Returns cross-section profile status:
  - `personal_profile`
  - `business_profile`
  - `alternative_data`
  - `documents` (counts and verification state)
  - `overall` (`profiles_complete`, `ready_for_loan`, `completion_percentage`, `missing`)
- `ready_for_loan` is based on the 3 core profile sections.

8. `GET /notifications/`
- Returns customer notification preferences.
- Defaults:
  - `email_loan_updates: true`
  - `email_payment_reminders: true`
  - `email_promotions: false`

9. `PUT /notifications/`
- Updates notification preferences.
- Body shape:
```json
{
  "preferences": {
    "email_loan_updates": true,
    "email_payment_reminders": true,
    "email_promotions": false
  }
}
```
- Unknown preference keys are rejected.
- Boolean-like values are parsed and validated.

## Allowed Choice Values
1. Personal
- `gender`: `male`, `female`, `other`, `prefer_not_to_say`
- `civil_status`: `single`, `married`, `widowed`, `separated`

2. Business
- `business_type`: `sari_sari_store`, `market_vendor`, `home_based_seller`, `food_vendor`, `transport_service`, `freelancer`, `agriculture`, `manufacturing`, `retail_trade`, `other`
- `registration_type`: `DTI`, `SEC`, `BIR`, `none`
- `income_range`: `below_10000`, `10000_20000`, `20000_30000`, `30000_50000`, `50000_100000`, `above_100000`

3. Alternative data
- `education_level`: `no_formal`, `elementary`, `high_school`, `vocational`, `college_undergraduate`, `college_graduate`, `postgraduate`
- `employment_status`: `employed`, `self_employed`, `unemployed`, `retired`, `student`
- `housing_status`: `owned`, `rented`, `living_with_family`, `company_provided`
- `existing_loan_source`: `bank`, `cooperative`, `microfinance`, `informal`, `family`, `none`
- `loan_payment_history`: `on_time`, `sometimes_late`, `often_late`, `defaulted`, `no_history`
- `ewallet_usage`: `daily`, `weekly`, `monthly`, `rarely`, `never`
- `utility_payment_history`: `on_time`, `sometimes_late`, `often_late`

## Smoke Test Sequence
1. Login as customer and set auth header.
2. `GET /summary/` to capture initial completion.
3. `PUT /` then `GET /` to confirm personal profile updates.
4. `PUT /business/` then `GET /business/`.
5. `PUT /alternative-data/` then `GET /alternative-data/`.
6. `GET /summary/` and verify `overall.profiles_complete` and `overall.ready_for_loan`.
7. `GET /notifications/`, then `PUT /notifications/`, then `GET /notifications/` to confirm persistence.

## Common Error Cases
1. `401 Unauthorized`
- Missing/invalid auth token.

2. `403 Forbidden`
- Non-customer role accessing profile endpoints.

3. `400 Bad Request`
- Invalid choice values.
- Invalid notification preference payload (`preferences` not an object or unknown keys).
