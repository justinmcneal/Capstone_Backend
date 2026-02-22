# Accounts Directory Production Readiness Review

Date: 2026-02-20  
Scope: Static code review of `accounts/` and related auth/security settings (`config/`).

## Executive Summary
The `accounts/` module has strong foundations (peppered password hashing, lockouts, RBAC/ABAC helpers, 2FA support, token blacklisting), but it is **not yet production-ready** due to refresh/session-control gaps, deactivated-account refresh risk, and fail-open encryption configuration.

## High Priority Findings
1. Refresh membership is not enforced for customer refresh.
- Token history is written for customers (`accounts/utils/token_utils.py:37`, `accounts/utils/token_utils.py:56`) but not checked in refresh flow (`accounts/views/auth_views.py:390`).
- `is_refresh_token_valid()` exists but is unused (`accounts/utils/token_utils.py:195`).
- Risk: previously issued refresh tokens can remain usable until expiry.

2. Deactivated admin/loan-officer accounts can still refresh.
- Refresh path loads admin/officer but does not enforce `active` before issuing new tokens (`accounts/views/auth_views.py:437`, `accounts/views/auth_views.py:461`).
- Non-customer token path does not persist refresh-token entries (`accounts/utils/token_utils.py:70`).
- Risk: deactivated privileged users can continue rotating sessions.

3. Field encryption is fail-open when key is missing.
- Encryption helper returns plaintext when `FIELD_ENCRYPTION_KEY` is absent (`config/field_encryption.py:13`, `config/field_encryption.py:39`).
- Production settings do not hard-fail on missing key (`config/settings.py:115`).
- Risk: sensitive values may be stored unencrypted.

4. Index creation is optional/manual and incomplete in bootstrap script.
- Script states indexing is optional (`init_db.py:3`) and only creates indexes for subset of models (`init_db.py:16`).
- Admin/officer/consent indexes are defined but not auto-applied (`accounts/models/admin.py:193`, `accounts/models/loan_officer.py:178`, `accounts/models/consent.py:130`).
- Risk: uniqueness/TTL expectations may not be enforced consistently.

## Medium Priority Findings
1. Account enumeration signals exist. (DONE)
- Non-existent account responses are explicit in reset/OTP paths (`accounts/services/password_service.py:41`, `accounts/views/password_views.py:38`, `accounts/views/auth_views.py:301`, `accounts/views/auth_views.py:362`).

2. Admin and loan-officer login endpoints have no DRF throttle classes. (DONE)
- Customer login throttle is present (`accounts/views/auth_views.py:138`).
- Admin/loan-officer login throttles are now implemented (`accounts/views/admin_views.py:138`, `accounts/views/loan_officer_views.py:76`).
- Dedicated throttle classes were added (`accounts/utils/throttles.py:14`, `accounts/utils/throttles.py:19`).

3. Password-reset OTP attempt controls are incomplete. (DONE)
- Models include reset-attempt fields (`accounts/models/customer.py:53`, `accounts/models/admin.py:71`, `accounts/models/loan_officer.py:65`).
- Per-account cooldown/attempt enforcement is now applied in verify/reset flows (`accounts/services/password_service.py:79`, `accounts/services/password_service.py:108`, `accounts/services/password_service.py:127`, `accounts/services/password_service.py:140`, `accounts/services/password_service.py:159`).

4. 2FA temp tokens are not consumed after successful verification. (DONE)
- Temp token replay is now blocked via blacklist check before verification and revocation on successful use (`accounts/views/two_factor_views.py:148`, `accounts/views/two_factor_views.py:221`).

5. `accounts` consent mixin checks consent after handler dispatch. (DONE)
- Consent is now enforced after DRF `initial()` and before handler execution in the mixin dispatch path (`accounts/views/consent_views.py:257`, `accounts/views/consent_views.py:266`, `accounts/views/consent_views.py:268`).
- Note: AI assistant app appears to use a different consent mixin (`ai_assistant/views/chat_views.py:21`), so impact depends on usage.

## Current Strengths
1. Password hashing uses pepper + bcrypt with fail-closed pepper requirement.
- `accounts/utils/pepper_utils.py:41`

2. Account lockout protections are implemented across customer/officer/admin login flows.
- `accounts/views/auth_views.py:157`
- `accounts/views/loan_officer_views.py:124`
- `accounts/views/admin_views.py:194`

3. Admin 2FA posture is strong.
- Mandatory 2FA bootstrap on login when not enrolled (`accounts/views/admin_views.py:243`)
- Admin 2FA disable blocked (`accounts/views/two_factor_views.py:325`)

4. Token blacklist uses hashed storage and TTL index support.
- `accounts/utils/token_utils.py:153`
- `accounts/models/tokens.py:79`

5. Security middleware coverage includes CSRF check, NoSQL payload guard, and secure headers.
- `config/middleware.py:83`
- `config/middleware.py:135`
- `config/middleware.py:7`

6. Centralized RBAC/ABAC utilities exist for privilege and scope checks.
- `accounts/utils/access_control.py:169`
- `accounts/utils/access_control.py:221`

## Production Readiness Checklist
- [ ] Enforce refresh-token membership during refresh for customers.
- [ ] Enforce `active` checks for admin/loan-officer on refresh and token issue.
- [ ] Persist non-customer refresh sessions or introduce equivalent revocation/session controls.
- [ ] Fail startup in production when `FIELD_ENCRYPTION_KEY` is missing/invalid.
- [ ] Ensure index bootstrap is mandatory in deploy pipeline for all account-related models.
- [ ] Normalize auth/reset/OTP failure messaging to prevent enumeration.
- [ ] Add throttles to admin/loan-officer refresh endpoints.
- [x] Add per-account password-reset OTP cooldown and attempt limits.
- [x] Make 2FA temp tokens one-time-use.
- [ ] Add automated tests for `accounts` auth/security flows.

## Recommended Implementation Order
1. Refresh/session control fixes (customer + privileged roles).
2. Encryption key enforcement in production.
3. Index bootstrap reliability.
4. Enumeration-safe response normalization.
5. Throttling and reset-OTP hardening.
6. 2FA temp-token one-time consumption.
7. Automated security regression tests.

## Notes
- This review is code-level only (no live environment penetration testing).
- Syntax sanity check passed for `accounts/` (`python -m compileall accounts`).
