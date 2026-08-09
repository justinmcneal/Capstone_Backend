# Profiles API Testing Guide

## Scope

Profiles covers customer profile data used for loan readiness:
- Personal profile
- Business profile
- Alternative credit data
- Profile summary
- Notification preferences
- Risk score calculation
- Officer read-only access

## Base URL and Auth

- Customer base URL: `http://localhost:8000/api/profile`
- Canonical officer base URL: `http://localhost:8000/api/officer/profiles`
- Required headers:
```http
Authorization: Bearer <customer_access_token>
Content-Type: application/json
```
- Customer endpoints require customer role.
- Officer endpoints require an active loan-officer account. Administrators are
  denied unless a future, separately permissioned admin profile API is added.

## URL Reference

### Customer Endpoints

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
  - `profile_revision`

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
  - `profile_revision` (optional optimistic-concurrency precondition)
- Key response fields: `profile_completed`, `completion_percentage`,
  `profile_revision`
- Validation:
  - Mobile number must be Philippine format (+639 or 09)
  - Wallet address must be valid Ethereum format (0x + 40 hex chars)
  - Barangay/city/province must match location name regex

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
  - `profile_completed`
  - `completion_percentage`
  - `profile_revision`

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
  - `years_in_operation` (legacy alias accepted; when present it's used as years and converted to months)
  
    Note: `years_in_operation` is accepted as a legacy field. The API treats it as years and converts it to `business_age_months` (months). Example: `years_in_operation: 2` → `business_age_months: 24`.
  - `is_registered`
  - `registration_type` (`DTI`, `SEC`, `BIR`, `none`)
  - `registration_number`
  - `estimated_monthly_income`
  - `income_range` (`below_10000`, `10000_20000`, `20000_30000`, `30000_50000`, `50000_100000`, `above_100000`)
  - `estimated_monthly_expenses`
  - `number_of_employees`
- Optional concurrency field: `profile_revision`
- Key response field: `profile_revision`
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
  - `is_coop_member`
  - `community_involvement`
  - `risk_score`
  - `risk_category`
  - `score_calculated_at`
  - `risk_score_status` (`not_calculated`, `pending`, `complete`, or `failed`)
  - `risk_score_policy_version`
  - `risk_score_use` (`informational_only`)
  - `risk_score_manual_review_required`
  - `risk_input_revision`
  - `risk_calculated_revision`
  - `risk_score_breakdown`
  - `risk_score_reason_codes`
  - `risk_score_error_code`
  - `risk_score_requested_at`
  - `risk_score_failed_at`
  - `profile_completed`
  - `completion_percentage`
  - `profile_revision`

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
  - `profile_revision` (optional optimistic-concurrency precondition)
- Key response fields:
  - `risk_score_status`
  - `risk_input_revision`
  - `profile_revision`
- Side effect: atomically advances the input revision, clears the superseded
  score, marks calculation pending, and enqueues that exact revision.

7. `GET /summary/`
- Auth: customer only
- Request fields: none
- Key response fields:
  - `customer_id`
  - `personal_profile.completed`
  - `personal_profile.completion_percentage`
  - `personal_profile.profile_revision`
  - `business_profile.completed`
  - `business_profile.has_business_type`
  - `business_profile.has_income_info`
  - `business_profile.profile_revision`
  - `alternative_data.completed`
  - `alternative_data.has_risk_score`
  - `alternative_data.risk_category`
  - `alternative_data.risk_score_status`
  - `alternative_data.risk_score_policy_version`
  - `alternative_data.risk_score_use`
  - `alternative_data.risk_score_manual_review_required`
  - `alternative_data.risk_input_revision`
  - `alternative_data.risk_calculated_revision`
  - `alternative_data.profile_revision`
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

### Officer Endpoints

10. `GET /api/officer/profiles/`
- Auth: active loan officer only
- Query fields: `search`, `page`, `page_size` (maximum 100)
- Scope:
  - customers assigned to the requesting officer;
  - submitted/under-review customers that remain unassigned; and
  - eligible document-review customers from the shared access-control scope.
- Customers assigned to another officer and inactive, suspended, deactivated,
  pending-deletion, or deleted customers are excluded.
- Key response fields: `customer_id`, `full_name`, and `email` only. Phone search
  and phone output are intentionally unsupported because phone data is encrypted.

11. `GET /api/officer/profiles/<customer_id>/`
- Auth: active loan officer only
- Request fields: none
- Returns the explicitly allowlisted personal, business, and alternative-data
  profile for an in-scope customer.
- Omits account security fields, wallet address, and emergency-contact data.
- Returns `404 Resource not found` for an out-of-scope customer, whether or not
  the customer exists.
- Returns `400` for an invalid customer ID format.
- The legacy `/api/profile/officer/<customer_id>/` alias currently reaches the
  same scoped view and is pending deprecation.
- Directory access, successful sensitive reads, and denied reads require audit
  records. If the audit store is unavailable, sensitive access returns `503`.

## Smoke Test Sequence

1. Log in as a customer and set the auth header.
2. `GET /summary/` to capture initial completion.
3. `PUT /` then `GET /` to confirm personal profile updates.
4. `PUT /business/` then `GET /business/`.
5. `PUT /alternative-data/` then `GET /alternative-data/`.
6. `GET /summary/` and verify `overall.profiles_complete` and `overall.ready_for_loan`.
7. `GET /notifications/`, then `PUT /notifications/`, then `GET /notifications/` to confirm persistence.
8. As a loan officer: list `/api/officer/profiles/`, then retrieve an in-scope
   customer from `/api/officer/profiles/<customer_id>/`. Confirm a customer
   assigned to another officer returns the concealed `404` response.

## Common Error Cases

1. `401 Unauthorized`
- Missing or invalid auth token.

2. `403 Forbidden`
- Non-customer role accessing customer endpoints.
- Customer role accessing officer endpoint.

3. `400 Bad Request`
- Invalid choice values.
- Invalid notification preference payload.
- `business_type_other` missing when `business_type=other`.
- Invalid customer ID format for officer endpoint.

4. `404 Not Found`
- Customer not found when updating notification preferences.
- Officer requested a customer outside their assigned/shared-review scope.

5. `409 Conflict`
- A PUT supplied a `profile_revision` that is no longer current. Reload the
  profile, reconcile the user's edits, and retry with the new revision.

6. `503 Service Unavailable`
- A required officer profile-access audit could not be written.

## Profile Persistence and Concurrency

- Personal, business, alternative-data, and summary GET requests are
  side-effect-free. If no record exists, they return an empty representation with
  `id: null` and `profile_revision: 0` without inserting a document.
- The first PUT creates the profile through an atomic upsert. Subsequent PUTs
  update only validated submitted fields, so unrelated simultaneous edits are
  preserved.
- Every accepted PUT increments `profile_revision`. Sending the last observed
  revision enables optimistic concurrency and produces `409` for a stale edit.
  Omitting it remains supported for older clients, but clients should adopt it.
- Completion state is written only for the newest observed revision.

## Profile Field Encryption

- Declared personal contact/address, business address/registration/financial,
  and alternative rent/income/loan fields are encrypted in raw MongoDB when
  `FIELD_ENCRYPTION_KEY` is configured.
- Numeric values use a versioned BSON envelope and round-trip as their original
  `int`, `float`, Python `Decimal`, or MongoDB `Decimal128` type.
- API clients continue to send and receive ordinary numeric JSON values; the
  ciphertext format is an internal storage concern.
- Randomized encrypted fields cannot be queried or sorted by their plaintext
  value without a separate reviewed indexing design.

## Rate Limiting

- All profile endpoints are throttled at 500 requests/hour per authenticated user via `ProfileRateThrottle`.

## Background Tasks

- `calculate_risk_score_task` is triggered asynchronously after
  `PUT /alternative-data/` and calculates a weighted score from 0–100.
- A task writes score fields only when its expected `risk_input_revision` is
  still current. An older task is recorded as stale and cannot overwrite newer
  inputs or a newer score. Duplicate completed tasks are idempotent.
- Successful results include category, timestamp, policy version, calculated
  revision, non-sensitive dimension breakdown, and reason codes.
- Calculation failures are stored as `failed` with a machine-readable error code
  and are retried with backoff. If initial broker enqueue fails, the profile
  update remains saved and its failed state is visible to the client.
- `profiles.reconcile_risk_scores` runs every minute to requeue failed work and
  pending work abandoned for at least five minutes.
- A score is current only when status is `complete`, calculated revision equals
  input revision, and its policy version is current.
- Policy `2026-08-09-v1` is `informational_only` and requires manual review. It
  must not be treated as approval, pricing, a limit, eligibility, or an adverse
  decision. See `docs/PROFILES_RISK_SCORING_POLICY.md`.

## Risk-Score Recalculation

Inventory scores made under an obsolete policy without changing MongoDB:

```bash
python manage.py recalculate_profile_risk_scores
```

After backup review and staging validation, enqueue affected records under the
current policy:

```bash
python manage.py recalculate_profile_risk_scores --apply
```

Add `--all` to include every alternative-data record. The command is dry-run by
default; operational execution is intentionally not part of local unit testing.

## Duplicate Profile Reconciliation

Inventory legacy records where string and ObjectId forms identify the same
customer without changing MongoDB:

```bash
python manage.py reconcile_duplicate_profiles
```

After backup review, staging validation, and review of which newest documents
will be retained, apply reconciliation:

```bash
python manage.py reconcile_duplicate_profiles --apply
```

The applied command deletes older duplicates and canonicalizes the retained
document's `customer_id` as a string. It was not run against a development or
production database as part of Stage 4.

## Deleted-Customer Profile Cleanup

Final account deletion removes records from `customer_profiles`,
`business_profiles`, and `alternative_data`. Cleanup is idempotent and records a
durable completion status on the customer account so an interrupted cleanup can
be retried. Administrators with `manage_users` can inspect cleanup status,
attempts, counts, last error type, and timestamps through
`GET /api/auth/admin/customers/<customer_id>/`.

For profile records retained by accounts deleted before this behavior existed,
inventory the records without modifying the database:

```bash
python manage.py cleanup_deleted_customer_profiles
```

After retention approval, backup review, and staging validation, the operational
owner may run the state-changing form:

```bash
python manage.py cleanup_deleted_customer_profiles --apply
```

## Backfill: `business_age_months` from `years_in_operation`

### Purpose
Some older records use the legacy `years_in_operation` field (years). The canonical field is `business_age_months` (months). This document describes the safe migration and backfill process.

### Dry run
Preview what would be changed without modifying the DB:

```bash
./venv/bin/python scripts/backfill_business_age_months.py --dry
```

This prints each document `_id` and the months value that would be written.

### Full run
After verifying the dry run and taking backups, run the real backfill:

```bash
# Ensure your environment is set (DJANGO_SETTINGS_MODULE, virtualenv activated)
./venv/bin/python scripts/backfill_business_age_months.py
```

### Precautions
- Always take a database backup before running the full backfill.
- Run the script during a low-traffic maintenance window.
- Test the script in a staging environment first.
- Consider putting the code change behind a feature flag if your deployment supports it.

### Rollback
This backfill is additive (writes `business_age_months`). To roll back, restore from backup. If you only want to remove the written field for a small set of documents, use a manual `update_many` or targeted `update_one` undo.

### Next steps
- After backfill, monitor logs and alerts for anomalies.
- Deprecate `years_in_operation` in the API clients over a scheduled window (e.g., 2-4 weeks) and then remove alias support in a follow-up release.
