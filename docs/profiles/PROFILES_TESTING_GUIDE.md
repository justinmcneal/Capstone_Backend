# Profiles API Testing Guide

Last updated: 2026-08-11

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
  - `profile_completion_policy_version`
  - `profile_missing_fields`

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
  `profile_revision`, `profile_completion_policy_version`, and
  `profile_missing_fields`
- Validation:
  - Customer age must be 18 through 100
  - Mobile number must be Philippine format (+639 or 09)
  - Emergency phone uses the same Philippine format when supplied
  - ZIP code must contain exactly four digits
  - Wallet address must be valid Ethereum format (0x + 40 hex chars)
  - Locations support Unicode letters, numbered barangays, spaces, apostrophes,
    periods, and hyphens

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
  - `profile_completion_policy_version`
  - `profile_missing_fields`

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
  - `years_in_operation` (deprecated input-only alias; converted to exact whole
    months and never returned)
  - `is_registered`
  - `registration_type` (`DTI`, `SEC`, `BIR`, `none`)
  - `registration_number`
  - `estimated_monthly_income`
  - `income_range` (`below_10000`, `10000_20000`, `20000_30000`, `30000_50000`, `50000_100000`, `above_100000`)
  - `estimated_monthly_expenses`
  - `number_of_employees`
- Optional concurrency field: `profile_revision`
- Key response field: `profile_revision`
- Response also includes completion status, percentage, policy version, and
  machine-readable missing fields.
- Validation:
  - `business_type_other` is required for `business_type=other` and cleared for
    another type.
  - Registered businesses require registration type and number; selecting false
    clears obsolete registration details.
  - Income and expenses allow at most two decimal places and reject non-finite
    values.
  - When both business-age fields are supplied, they must describe the same age.
    A legacy year value that cannot convert to a whole month is rejected.

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
  - `profile_completion_policy_version`
  - `profile_missing_fields`

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
  - `profile_completed`
  - `completion_percentage`
  - `profile_completion_policy_version`
  - `profile_missing_fields`
- Side effect: atomically advances the input revision, clears the superseded
  score, marks calculation pending, and enqueues that exact revision.
- Conditional validation requires or clears rent, loan, bank-account, e-wallet,
  and utility-history fields based on their controlling answers.

7. `GET /summary/`
- Auth: customer only
- Request fields: none
- Key response fields:
  - `customer_id`
  - `personal_profile.completed`
  - `personal_profile.completion_percentage`
  - `personal_profile.profile_revision`
  - `personal_profile.completion_policy_version`
  - `personal_profile.missing_fields`
  - `business_profile.completed`
  - `business_profile.has_business_type`
  - `business_profile.has_income_info`
  - `business_profile.profile_revision`
  - `business_profile.completion_percentage`
  - `business_profile.completion_policy_version`
  - `business_profile.missing_fields`
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
  - `alternative_data.completion_percentage`
  - `alternative_data.completion_policy_version`
  - `alternative_data.missing_fields`
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
  - `overall.ready_for_loan_deprecated`
  - `overall.profile_ready_for_application`
  - `overall.product_eligibility_evaluated`
  - `overall.completion_policy_version`
  - `overall.missing_field_codes`
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
  - Values must be actual JSON booleans; strings, numbers, `null`, arrays, and
    objects are rejected
- GET and PUT responses merge any partial stored preferences over the complete
  documented defaults.
- PUT changes only the submitted preference keys atomically and does not replace
  unrelated customer fields or simultaneous updates to other preferences.
- Successful changes are audited using the trusted-proxy client-IP policy.

10. `GET /export/`
- Auth: customer only
- Returns an allowlisted, versioned JSON export of profile, risk explanation,
  completion, notification-preference, and up to 100 risk-review records. The
  review section reports its total and whether it was truncated.
- It is generated in memory; no server-side export file is retained.
- Internal task IDs, account security, documents, loans, and AI history are
  outside this profile-only export.
- Required audit failure returns `503` without exposing the payload.

11. `GET /history/`
- Auth: customer only
- Query fields: `page`, `page_size` (maximum 100)
- Returns metadata-only events: action, section, changed field names, revision,
  status, and timestamp. It omits values, IP addresses, and security information.

12. `GET|POST /risk-reviews/`
- Auth: customer only
- GET lists the customer's requests with pagination.
- POST accepts `reason` (`incorrect_profile_data`, `unexpected_score`,
  `missing_context`, or `other`), optional `description`, and optional current
  `risk_calculated_revision` precondition.
- It requires a completed current score. Only one request may exist for a
  customer/scoring revision; duplicate or stale revisions return `409`.

### Officer Endpoints

13. `GET /api/officer/profiles/`
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

14. `GET /api/officer/profiles/<customer_id>/`
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

15. `GET /api/officer/profile-risk-reviews/`
- Auth: active loan officer only
- Query fields: `page`, `page_size`, and optional `status`
- Returns requests only for customers in the officer's existing scope. Queue
  access requires an audit and fails closed with `503`.

16. `PUT /api/officer/profile-risk-reviews/<review_id>/`
- Auth: active, in-scope loan officer only
- Request fields: `status` (`in_review`, `resolved`, or `rejected`),
  `resolution_note`, and `review_revision`
- Terminal status requires a resolution note. Stale revisions return `409`, and
  out-of-scope request IDs return concealed `404`.

## Smoke Test Sequence

1. Log in as a customer and set the auth header.
2. `GET /summary/` to capture initial completion.
3. `PUT /` then `GET /` to confirm personal profile updates.
4. `PUT /business/` then `GET /business/`.
5. `PUT /alternative-data/` then `GET /alternative-data/`.
6. `GET /summary/` and verify `overall.profiles_complete` and
   `overall.profile_ready_for_application`. Treat `ready_for_loan` only as the
   temporary deprecated alias.
7. `GET /notifications/`, then `PUT /notifications/`, then `GET /notifications/` to confirm persistence.
8. As a loan officer: list `/api/officer/profiles/`, then retrieve an in-scope
   customer from `/api/officer/profiles/<customer_id>/`. Confirm a customer
   assigned to another officer returns the concealed `404` response.
9. Generate `/export/`, inspect `/history/`, request review of a completed score,
   and resolve it through the scoped officer review queue.

## Common Error Cases

1. `401 Unauthorized`
- Missing or invalid auth token.

2. `403 Forbidden`
- Non-customer role accessing customer endpoints.
- Customer role accessing officer endpoint.

3. `400 Bad Request`
- Invalid choice values.
- Invalid notification preference payload.
- Conflicting business months/legacy years, or legacy years that do not convert
  to a whole month.
- `business_type_other` missing when `business_type=other`.
- Age outside 18–100, invalid emergency phone or ZIP, inconsistent conditional
  answers, non-finite money, or money with more than two decimal places.
- Invalid customer ID format for officer endpoint.

4. `404 Not Found`
- Customer not found when updating notification preferences.
- Officer requested a customer outside their assigned/shared-review scope.

5. `409 Conflict`
- A PUT supplied a `profile_revision` that is no longer current. Reload the
  profile, reconcile the user's edits, and retry with the new revision.
- A risk result or risk review revision is stale, or the current score already
  has a review request.

6. `503 Service Unavailable`
- A required officer read/queue or customer export audit could not be written.

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
- Customer profile mutations remain successful if their best-effort audit write
  fails after the profile mutation is already durable. The server records an
  operational exception instead of returning a misleading retryable `500`.
- If risk-task enqueue fails after alternative data is saved, the response
  remains successful and the persisted score state becomes `failed` for the
  reconciler to retry.

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

## Completion and Application Readiness

- Completion policy version `2026-08-09-v1` replaces the former minimal 7/2/2-
  field rules.
- `profile_ready_for_application` means all three profile sections satisfy that
  policy. It does not evaluate documents, consent, identity verification, risk-
  score approval, or a loan product's eligibility requirements.
- `ready_for_loan` currently returns the same boolean only for compatibility and
  is marked deprecated in the response.
- False boolean answers and numeric zero values count as answered. Missing values
  are returned as stable field codes rather than inferred from display text.

### Required personal fields

- `date_of_birth`
- `gender`
- `civil_status`
- `nationality`
- `mobile_number`
- `address_line1`
- `barangay`
- `city_municipality`
- `province`
- `zip_code`

Address line 2, emergency-contact fields, and wallet address are optional for
completion. Supplied optional values must still pass validation.

### Required business fields

- `business_name`
- `business_type`
- `business_address`
- `business_barangay`
- `business_city`
- `business_province`
- `business_age_months`
- `is_registered`
- `estimated_monthly_income`
- `income_range`
- `estimated_monthly_expenses`
- `number_of_employees`

`business_type=other` additionally requires `business_type_other`.
`is_registered=true` additionally requires `registration_type` and
`registration_number`.

### Required alternative-data fields

- `education_level`
- `employment_status`
- `years_of_experience`
- `housing_status`
- `years_at_current_address`
- `number_of_dependents`
- `household_income`
- `has_existing_loans`
- `has_bank_account`
- `has_ewallet`
- `pays_utilities`
- `is_coop_member`

Conditional requirements:

- rented housing requires `monthly_rent`;
- existing loans require positive `existing_loan_amount`, a non-`none`
  `existing_loan_source`, and `loan_payment_history`;
- a bank account requires `bank_account_duration`;
- an e-wallet requires `ewallet_usage`; and
- utility payment requires `utility_payment_history`.

Selecting false/non-applicable controllers clears obsolete dependent values.

Inventory legacy stored completion metadata without writing:

```bash
python manage.py recalculate_profile_completion
```

After backup review and staging validation, persist the current policy result:

```bash
python manage.py recalculate_profile_completion --apply
```

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
- `profiles.reconcile_audit_failures` runs every minute to replay safe queued
  audit payloads and removes payloads after successful reconciliation.
- `profiles.collect_operational_metrics` runs every 15 minutes and publishes
  duplicate, declared-encryption, audit, risk, and review backlog gauges.
- A score is current only when status is `complete`, calculated revision equals
  input revision, and its policy version is current.
- Policy `2026-08-09-v1` is `informational_only` and requires manual review. It
  must not be treated as approval, pricing, a limit, eligibility, or an adverse
  decision.

### Risk policy dimensions

| Dimension | Weight | Main signals |
| --- | ---: | --- |
| Financial stability | 25% | Numeric household income and existing-loan payment history. |
| Payment behavior | 20% | Loan and utility payment histories. |
| Social capital | 15% | Cooperative membership and community involvement. |
| Housing stability | 25% | Housing status, address duration, and rent burden. |
| Digital footprint | 15% | Bank/e-wallet access, duration, and usage. |

The result is bounded to 0–100: at least 70 is `low`, 40–69.99 is `medium`,
and below 40 is `high`. Tests must verify canonical serializer values, boundary
scores, policy version, revisions, non-sensitive reason codes, stale-task
rejection, idempotency, and the manual-review-only intended-use fields.

Any proposal to use the score for approval, rejection, pricing, limits,
prioritization, eligibility, or adverse action requires a new policy version,
representative calibration/fairness evidence, legal/product approval, client
review, and controlled recalculation.

## Operational Metrics and Alerts

| Metric | Expected use |
| --- | --- |
| `profiles_audit_write_failures_total{action}` | Detect initial audit-write failures. |
| `profiles_operations_total{operation,outcome}` | Track exports, history, reviews, reconciliation, and denied access. |
| `profiles_risk_score_events_total{outcome}` | Track completed, failed, stale, and enqueue-failed scoring. |
| `profiles_risk_score_backlog{status}` | Detect failed or abandoned score work. |
| `profiles_duplicate_records{collection}` | Detect duplicate profile records. |
| `profiles_unprotected_sensitive_fields{collection}` | Detect populated declared fields outside the encryption envelope. |
| `profiles_audit_failure_backlog` | Detect unresolved audit replay work. |
| `profiles_risk_review_backlog{status}` | Track pending and in-review correction requests. |

Starting alert expressions must be calibrated to real traffic. During
deployment validation, verify that duplicate and unprotected-field gauges remain
zero, persistent audit/scoring backlogs alert, denied-access spikes are visible,
and review backlog thresholds match the approved operational SLA.

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
document's `customer_id` as a string. The 2026-08-09 development dry run found
zero duplicate groups and zero older duplicate documents across all three
collections. No `--apply` operation was run; staging or production must receive
its own reviewed dry run before index work.

## Deleted-Customer Profile Cleanup

Final account deletion removes records from `customer_profiles`,
`business_profiles`, `alternative_data`, and `profile_risk_reviews`, plus
unresolved Profiles audit-recovery payloads associated with the customer. Cleanup
is idempotent and records a durable completion status on the customer account so
an interrupted cleanup can be retried. Administrators with `manage_users` can
inspect cleanup status, attempts, counts, last error type, and timestamps through
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
.venv/bin/python scripts/backfill_business_age_months.py
```

The script always prints aggregate `found`, `eligible`, and `updated` counts. In
dry-run mode, `updated` remains zero.

The approved 2026-08-09 development encryption remediation was followed by
`encrypt_sensitive_fields --verify`; all populated declared fields passed with
zero unsupported values, conflicts, or failures.

This prints each document `_id` and the months value that would be written.

### Full run
After verifying the default dry run and taking backups, run the state-changing
form:

```bash
# Ensure your environment is set (DJANGO_SETTINGS_MODULE, virtualenv activated)
.venv/bin/python scripts/backfill_business_age_months.py --apply
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
- Confirm deployed-client telemetry or a coordinated mobile/web release before
  removing the alias.

## Client Compatibility Tests

Customer mobile must:

- send `business_age_months` rather than the input-only years alias;
- use `profile_ready_for_application`, policy version, and missing-field codes;
- preserve/send `profile_revision` and reload after `409`;
- send actual JSON booleans for notification preferences;
- treat risk scoring as asynchronous, informational, and manually reviewable;
- describe export as profile-only and history as metadata-only; and
- keep document approval and product eligibility separate from profile
  completion.

Loan-officer web must:

- use `/api/officer/profiles/` and its canonical detail route;
- treat inaccessible customers/reviews as concealed `404`;
- stop relying on phone search/output, wallet, account-security, or emergency
  contact fields;
- display policy/status/reason/manual-review metadata without turning the score
  into a credit decision; and
- submit the latest `review_revision` for review transitions.

Admin web has no direct Profiles API integration. Compatibility aliases may be
removed only after telemetry or coordinated releases confirm no supported
client still uses them.

## Deliberately Unsupported Features

- Profile avatars are deferred until an approved requirement defines media
  validation, moderation, storage, retention, and privacy controls.
- A bundled Philippine address-reference dataset is deferred until an
  authoritative maintained source, stable identifiers, version policy, and
  migration plan exist.
- Direct administrator profile access is unsupported; a future feature requires
  a separate permissioned and audited contract.

## Related Documentation

- `docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md` — Profiles technical
  architecture, implementation status, security, operations, clients, and
  release conditions.
- `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` — authentication,
  account lifecycle, encryption keys, and shared authorization.
- `docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` — separate document
  completion and review behavior.
- `docs/LOANS_TESTING_GUIDE.md` — downstream qualification and loan workflows.

## Validation Baseline

On 2026-08-11, `pytest -q tests/test_profiles*.py` collected and passed 164
tests. The most recent repository-wide suite passed 1,058 tests and skipped 21
explicitly gated integrations. The opt-in real-Mongo profile tests separately
cover atomic creation, concurrent profile revisions, and the unique risk-review
index; they must use an approved non-production target.
