# Profiles Production Readiness Review

Date: 2026-07-30  
Scope: Static code review of `profiles/` and related loan-readiness profile behavior.

## Executive Summary

The `profiles/` module provides customer personal profiles, business/MSME profiles, alternative credit data, a profile summary endpoint, and notification preferences. It uses PyMongo directly with MongoDB rather than Django ORM. Core CRUD endpoints are implemented and protected by customer-only access control. Serializer validation covers mobile numbers, wallet addresses, and location names. Profile completion and summary logic are implemented, though some rules are split between model and view. This review documents gaps and recommended next steps for production hardening.

## High Priority Findings

1. Dedicated API endpoint test file is now present.
   - `tests/test_profiles_api.py` covers the five profile endpoints with authenticated customer requests, role enforcement, and validation.

 2. Services layer extraction completed.
    - `profiles/services/summary.py` extracts profile summary readiness calculation from `ProfileSummaryView`.
    - `profiles/services/notification_preferences.py` extracts notification preferences get/update logic from `NotificationPreferencesView`.
    - `profiles/services/risk_scoring.py` implements weighted multi-factor risk scoring.
    - Views now delegate to services instead of containing completion logic inline.
    - **Status: COMPLETED.**

## Medium Priority Findings

1. Profile completion rules are now unified.
   - `CustomerProfile.calculate_completion()` checks 10 personal fields.
   - `BusinessProfile.calculate_completion()` checks `business_type` and `income_range`.
   - `AlternativeData.calculate_completion()` checks `education_level` and `housing_status`.
   - `profiles/services/summary.py` now reads `profile_completed` from each model instead of duplicating rules.
   - **Status: COMPLETED.**

2. Risk score calculation service implemented.
   - `profiles/services/risk_scoring.py` implements a weighted multi-factor rule engine:
     - financial_stability (income + existing loan history)
     - payment_behavior (loan + utility payment history)
     - social_capital (coop membership + community involvement)
     - housing_stability (ownership + years at address + rent burden)
     - digital_footprint (bank account + e-wallet usage)
   - Returns score (0-100), category (`low`/`medium`/`high`), and dimension breakdown.
   - Works without AI/LLM dependencies.
   - `profiles/tasks.py` exposes a Celery task `calculate_risk_score_task` that persists scores.
   - Triggered asynchronously after `AlternativeDataView PUT`.
   - **Status: COMPLETED.**

3. Rate limiting added to profile endpoints.
   - `ProfileRateThrottle` (500/hour user-based) added to all 6 profile views.
   - Mitigates enumeration and scraping risk.
   - **Status: COMPLETED.**

  4. Notification preferences are stored on the customer document.
    - `NotificationPreferencesView` reads/writes `notification_preferences` on the customer record.
    - Current implementation uses validated get/set helpers with a fixed key allowlist.
    - Migration to a dedicated collection is deferred; current schema is acceptable for production.
    - **Status: ACCEPTED / DEFERRED.**

 5. `AlternativeData.to_dict()` does not encrypt fields.
    - `CustomerProfile` and `BusinessProfile` call `encrypt_fields()`, but `AlternativeData.to_dict()` returns raw data.
    - `AlternativeData` contains sensitive fields such as `existing_loan_amount` and `household_income`.
    - **Status: NEEDS REVIEW.**

 6. `business_age_months` serializer rejects `0`.
    - `BusinessProfileSerializer` sets `min_value=1` on `business_age_months`, but the model accepts `None` and legacy `years_in_operation=0` would produce `0` months.
    - Risk: legitimate records with 0 months are rejected at the serializer level.
    - **Status: NEEDS REVIEW.**

 7. `ready_for_loan` logic ignores document verification.
    - `ready_for_loan = profiles_complete` does not require `documents_verified`.
    - A customer can have `ready_for_loan: True` while documents are unverified.
    - **Status: ACCEPTED / BY DESIGN.** (profiles gate readiness; document verification is enforced later in loan application)

 8. Missing model integration tests.
    - No tests for `CustomerProfile.save()`, `find_one`, `find_by_customer`, or `create_indexes` against MongoDB.
    - No tests for `BusinessProfile.save()` or `AlternativeData.save()` round-trip.
    - **Status: GAP.**

 9. Missing serializer unit tests.
    - Location name regex, mobile number normalization, Ethereum address validation are only tested through API views, not at the serializer unit level.
    - **Status: GAP.**

 10. Missing service tests.
     - `get_profile_summary()` and notification preferences service have no dedicated tests.
     - **Status: GAP.**

 11. Missing task tests.
     - `calculate_risk_score_task` Celery task is untested.
     - **Status: GAP.**

 12. Missing encryption round-trip tests.
     - `encrypt_fields`/`decrypt_fields` behavior for profile models is untested.
     - **Status: GAP.**

## Low Priority Findings

1. Legacy `years_in_operation` is silently dropped by the serializer.
   - `BusinessProfile` model accepts and converts `years_in_operation` to `business_age_months`, but `BusinessProfileSerializer` only exposes `business_age_months`.
   - Risk: clients sending old field names get silent data loss.

2. No profile photo or document export.
   - No avatar upload or PDF/CSV export endpoints.

3. Staff/loan-officer read-only profile endpoint implemented.
   - `OfficerProfileView` at `/api/profile/officer/<customer_id>/`
   - Requires `require_officer_or_admin` role check
   - Returns same `get_profile_summary` payload as customer-facing summary
   - Read-only GET — no mutations allowed
   - **Status: COMPLETED.**

## Current Strengths

1. Strong input validation on serializers.
   - Philippine mobile number normalization (+639/09).
   - Ethereum wallet address format validation.
   - Location name regex for barangay, city, province.
   - `business_type_other` required when `business_type=other`.

2. Sensitive fields are encrypted.
   - `config.field_encryption` is applied to mobile, address, and registration fields.

3. Audit logging is integrated.
   - Profile mutations log to `analytics.models.AuditLog`.

4. Profile summary provides readiness signal.
   - Cross-section view aggregates personal, business, alternative, and documents into `ready_for_loan`.

5. Business age normalization is backward compatible.
   - Legacy `years_in_operation` inputs are converted to canonical `business_age_months`.

## Implementation Gaps Since Last Review

- No profiles production-readiness review existed prior to this document.
- `profiles/services/` was empty; now contains `summary.py`, `notification_preferences.py`, `risk_scoring.py`, and `tasks.py`.
- Ruff lint issues across `profiles/` have been fixed (23 issues resolved).
- `tests/test_profiles_api.py` was added with 21 endpoint-level tests covering GET/PUT for personal, business, alternative data, summary, notification preferences, and officer read-only access, including role enforcement and validation.
- `tests/test_profiles_risk_scoring.py` was added with 18 dimension/integration tests.
- `tests/test_ai_model_methods.py` was added with 2 `AIInteraction` model-method tests.
- In-memory pagination in analytics audit logs was replaced with DB-level `skip`/`limit` and `count_with_filters`.
- Documents reviewer notification dispatch was migrated from raw daemon thread to Celery task.
- Documents notification helpers were moved from `documents/views/document_views.py` to `documents/services/notification.py`.

## Production Readiness Checklist

- [x] Three MongoDB document models with CRUD and indexes.
- [x] Four DRF serializers with field-level validation.
- [x] Five API endpoints with JWT auth and customer-only access control.
- [x] Profile summary with completion and ready_for_loan logic.
- [x] Notification preferences GET/PUT.
- [x] Audit logging on mutations.
- [x] Field encryption for sensitive profile data.
- [x] Dedicated API endpoint tests (`tests/test_profiles_api.py`).
- [x] Ruff/lint fixes across `profiles/`.
- [x] Services layer extraction (`profiles/services/`).
- [x] Unified profile completion rules.
- [x] Risk score calculation service.
- [x] Staff/loan-officer read-only access.
- [x] Rate limiting on profile endpoints.
- [ ] Encrypt sensitive fields in `AlternativeData.to_dict()`.
- [ ] Fix `business_age_months` serializer to accept `0`.
- [ ] Add model integration tests for all three profile models.
- [ ] Add serializer unit tests.
- [ ] Add service-layer tests for summary and notification preferences.
- [ ] Add Celery task tests for `calculate_risk_score_task`.
- [ ] Add encryption/decryption round-trip tests.

## Recommended Next Steps

1. Add `encrypt_fields()` call in `AlternativeData.to_dict()` for sensitive fields.
2. Fix `BusinessProfileSerializer.business_age_months` to accept `0` by changing `min_value=1` to `min_value=0`.
3. Add model integration tests for `CustomerProfile`, `BusinessProfile`, and `AlternativeData` save/find/create_indexes.
4. Add serializer unit tests for mobile, wallet, location name validation.
5. Add service tests for `get_profile_summary()` and notification preferences.
6. Add Celery task test for `calculate_risk_score_task`.
7. Add encryption/decryption round-trip tests for profile models.
8. Encryption key management audit and index bootstrap verification are operational/deployment tasks.
9. Notification preferences schema migration to a dedicated collection, if needed, is deferred to a future phase.

## Notes

- This review is code-level only (no live environment penetration testing).
- Profile endpoints mutate state and write to MongoDB; tests should mock external I/O and assert on created records.
