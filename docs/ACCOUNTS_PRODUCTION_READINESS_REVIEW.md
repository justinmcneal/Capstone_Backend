# Accounts Directory Production Readiness Review

Date: 2026-07-26  
Scope: Static code review of `accounts/` and related auth/security settings (`config/`).

## Executive Summary

The `accounts/` module has strong foundations (peppered password hashing, lockouts, RBAC/ABAC helpers, 2FA support, token blacklisting). Most items from the 2026-02-20 review have been addressed. Remaining gaps are minor: index bootstrap is missing activity/session models, and field-encryption remains fail-open in DEBUG mode.

## High Priority Findings

1. Refresh membership is enforced for customer refresh.
- `TokenUtils.is_refresh_token_valid()` is called during refresh for customer tokens (`accounts/views/auth_views.py:624`).
- Risk: previously issued refresh tokens can remain usable until expiry. **Status: MITIGATED.**

2. Deactivated admin/loan-officer accounts cannot refresh.
- Refresh path loads admin/officer and enforces `active` before issuing new tokens (`accounts/views/auth_views.py:682`).
- Non-customer token path persists refresh-token entries via `TokenUtils.generate_tokens()` (`accounts/utils/token_utils.py:172`).
- Risk: deactivated privileged users can continue rotating sessions. **Status: MITIGATED.**

3. Field encryption is fail-open when key is missing in DEBUG mode.
- Encryption helper returns plaintext when `FIELD_ENCRYPTION_KEY` is absent (`config/field_encryption.py:13`).
- Production settings hard-fail when key is missing/invalid (`config/settings.py:142`).
- Risk: sensitive values may be stored unencrypted in development. **Status: PARTIAL — production-safe, development still permissive.**

4. Index creation is mostly complete but excludes activity/session models.
- `init_db.py` creates indexes for Customer, BlacklistedToken, RefreshTokenEntry, LoanOfficer, Admin, Consent, and profile models.
- `ActiveSession` and `LoginActivity` define `create_indexes()` (`accounts/models/activity.py:92`, `accounts/models/activity.py:166`) but are not invoked in `init_db.py`.
- Risk: session/activity query performance and uniqueness expectations may not be enforced consistently. **Status: MINOR GAP.**

## Medium Priority Findings

1. Account enumeration signals are normalized. (DONE)
- Non-existent account responses use generic messaging in reset/OTP paths (`accounts/services/password_service.py:12`, `accounts/views/password_views.py:38`, `accounts/views/auth_views.py:42`, `accounts/views/loan_officer_views.py:24`, `accounts/views/admin_views.py:39`).

2. Admin and loan-officer login endpoints have DRF throttle classes. (DONE)
- Customer login throttle is present (`accounts/views/auth_views.py:231`).
- Admin/loan-officer login throttles are implemented (`accounts/views/admin_views.py:152`, `accounts/views/loan_officer_views.py:77`).
- Dedicated throttle classes exist (`accounts/utils/throttles.py:14`, `accounts/utils/throttles.py:19`).

3. Password-reset OTP attempt controls are implemented. (DONE)
- Models include reset-attempt fields (`accounts/models/customer.py:53`, `accounts/models/admin.py:71`, `accounts/models/loan_officer.py:65`).
- Per-account cooldown/attempt enforcement is applied in verify/reset flows (`accounts/services/password_service.py:95`, `accounts/services/password_service.py:126`, `accounts/services/password_service.py:142`).

4. 2FA temp tokens are one-time-use. (DONE)
- Temp token replay is blocked via blacklist check before verification and revocation on successful use (`accounts/views/two_factor_views.py:166`, `accounts/views/two_factor_views.py:241`).

5. Consent mixin checks consent after DRF auth but before handler dispatch. (DONE)
- Consent is enforced after `initial()` and before handler execution (`accounts/views/consent_views.py:430`).

## Current Strengths

1. Password hashing uses pepper + bcrypt with fail-closed pepper requirement.
- `accounts/utils/pepper_utils.py:41`
- `manage.py` fails fast if `SECRET_PEPPER` is missing.

2. Account lockout protections are implemented across customer/officer/admin login flows.
- `accounts/views/auth_views.py:252`
- `accounts/views/loan_officer_views.py:124`
- `accounts/views/admin_views.py:194`

3. Admin 2FA posture is strong.
- Mandatory 2FA bootstrap on login when not enrolled (`accounts/views/admin_views.py:243`)
- Admin 2FA disable blocked (`accounts/views/two_factor_views.py:325`)

4. Token blacklist uses hashed storage and TTL index support.
- `accounts/utils/token_utils.py:217`
- `accounts/models/tokens.py:76`

5. Security middleware coverage includes CSRF check, NoSQL payload guard, and secure headers.
- `config/middleware.py:7`
- `config/middleware.py:83`
- `config/middleware.py:135`

6. Centralized RBAC/ABAC utilities exist for privilege and scope checks.
- `accounts/utils/access_control.py:169`
- `accounts/utils/access_control.py:221`

## Implementation Gaps Since Last Review

The following items were added or improved after the 2026-02-20 review:

- Type annotations added to `accounts/utils/token_utils.py`, `accounts/utils/email_utils.py`, and `accounts/services/otp_service.py` public methods.
- `__repr__` helpers added to all account models (`Customer`, `Admin`, `LoanOfficer`, `BlacklistedToken`, `RefreshTokenEntry`).
- Auth smoke tests added (`tests/test_auth_smoke.py`) covering signup → OTP → login → refresh → logout and 2FA flow.
- CI lint workflow added (`.github/workflows/lint.yml`) running `black --check accounts` and `ruff check accounts`.
- `manage.py` startup check added for `SECRET_PEPPER`.
- Code formatting standardized via `black accounts`.
- RUF012 mutable class attributes converted to immutable tuples in view classes.

## Production Readiness Checklist

- [x] Enforce refresh-token membership during refresh for customers.
- [x] Enforce `active` checks for admin/loan-officer on refresh and token issue.
- [x] Persist non-customer refresh sessions or introduce equivalent revocation/session controls.
- [x] Fail startup in production when `FIELD_ENCRYPTION_KEY` is missing/invalid.
- [ ] Ensure index bootstrap covers all account-related models, including activity/session collections.
- [x] Normalize auth/reset/OTP failure messaging to prevent enumeration.
- [x] Add throttles to admin/loan-officer login endpoints.
- [x] Add per-account password-reset OTP cooldown and attempt limits.
- [x] Make 2FA temp tokens one-time-use.
- [x] Add automated tests for `accounts` auth/security flows.

## Recommended Next Steps

1. Add `ActiveSession.create_indexes()` and `LoginActivity.create_indexes()` to `init_db.py`.
2. Consider making field-encryption fail-closed in all environments, or document that DEBUG mode intentionally allows plaintext.
3. Resolve remaining `ruff check accounts` warnings to reach zero lint issues.

## Notes

- This review is code-level only (no live environment penetration testing).
- Syntax sanity check passed for `accounts/` (`python -m compileall accounts`).
