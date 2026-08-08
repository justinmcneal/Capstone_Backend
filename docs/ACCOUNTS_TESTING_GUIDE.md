# Accounts API Testing Guide

## Scope
Accounts handles authentication, OTP, password reset, consent, 2FA, loan officer auth, admin management, activity tracking, and support contact.

## Automated Setup and Stage 9 Verification

Run these commands from `Capstone_Backend`:

```powershell
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m black --check accounts
.\venv\Scripts\python.exe -m ruff check accounts
.\venv\Scripts\python.exe -m bandit --recursive accounts --exclude accounts/tests --severity-level high --confidence-level high
.\venv\Scripts\python.exe -m pip_audit --requirement requirements.lock --strict --progress-spinner off
```

Plain `pytest -q` uses `config.settings_test` automatically. It uses an
in-memory SQLite database, mongomock, an in-memory cache/channel layer, local
email delivery, and disabled blockchain integration; it must not require a
production `.env`, MongoDB, Redis, SMTP provider, or blockchain node.

The real-Mongo auth tests are opt-in because they must never use a production
database:

```powershell
$env:REAL_MONGO_TEST_URI = "mongodb://127.0.0.1:27017"
.\venv\Scripts\python.exe -m pytest -q tests/test_stage9_real_mongo.py -m real_mongo
```

The test creates a unique temporary database, verifies the actual account model
indexes, and races concurrent customer-email and session claims. Without
`REAL_MONGO_TEST_URI`, the tests skip intentionally. CI starts an isolated
MongoDB service for this job. CI installs `requirements.lock` and
`requirements-ci.lock`, runs `pip check`, then runs the full test, dependency
audit, and Bandit gates with deterministic non-production settings.

For a focused account/security run, use:

```powershell
.\venv\Scripts\python.exe -m pytest -q accounts/tests/test_csrf_transport.py accounts/tests/test_session_security.py accounts/tests/test_stage4_hardening.py accounts/tests/test_stage5_2fa_lifecycle.py accounts/tests/test_stage6_privileged_administration.py accounts/tests/test_stage7_consent_lifecycle.py accounts/tests/test_stage8_account_lifecycle.py tests/test_auth_smoke.py tests/test_accounts_password.py tests/test_accounts_sessions.py tests/test_accounts_loan_officer.py tests/test_accounts_admin.py
```

This setup is offline-safe: it uses `config.settings_test`, SQLite in memory,
mongomock, local email, in-memory cache/channel layers, eager in-memory Celery,
and disabled blockchain integration. Do not point `REAL_MONGO_TEST_URI` at a
production database. Record full-suite failures separately from account-focused
results when a local Windows temporary directory or another unrelated test
dependency is unavailable.

## Base URL and Auth
- Base URL: `http://localhost:8000/api/auth`
- Protected endpoints require:
  ```http
  Authorization: Bearer <access_token>
  Content-Type: application/json
  ```
- Customer-only endpoints require a customer token.
- Admin endpoints require admin or super-admin tokens depending on the route.
- Body token transport is the default. A client may request `token_transport:
  "cookie"` in a login/verification request or send `X-Token-Transport: cookie`.
- Cookie mode sets HttpOnly access and refresh cookies and removes token fields
  from JSON. The default access-cookie path is `/api/`; the refresh-cookie path is
  `/api/auth/`.
- Cookie clients must first call `GET /csrf-token/`, keep the `csrftoken` cookie,
  and send `X-CSRFToken` with the returned `data.csrf_token` on every unsafe API
  request that uses an auth cookie. Missing or mismatched values return `403`.
- A pure Bearer request does not need the CSRF pair. Refresh/logout still require
  the pair when a refresh cookie is present.

### Token input and response contract

- Refresh input is JSON `refresh` or `refresh_token`, otherwise the configured
  refresh cookie. `Authorization: Bearer <refresh_token>` is not a refresh input.
- Customer logout requires a refresh token from JSON or the refresh cookie. Its
  optional access token may be JSON `access`, a Bearer header, or the access cookie.
- Loan-officer and administrator logout read the same sources but currently do not
  reject missing tokens; send the refresh token to ensure session revocation.
- Customer login, email verification, refresh, and 2FA completion return
  `access` and `refresh` in body mode. Loan-officer login currently returns
  `access_token` and `refresh_token`. Cookie mode returns neither in JSON.
- Public token response names are not fully standardized yet. Do not silently
  rename fields in a client until the API and web/mobile clients are coordinated.

## URL Reference

### Customer Authentication

1. `GET /csrf-token/`
- Auth: none
- Request fields: none
- Key response fields: `csrf_token`, `same_site`

2. `POST /signup/`
- Auth: none
- Request fields:
  - `first_name`
  - `middle_name` optional
  - `last_name`
  - `email`
  - `password`
  - `password_confirm` required
  - `phone` optional
  - `language` optional (`en` or `tl`)
- Key response fields: `user`, `message`

3. `POST /verify-email/`
- Auth: none
- Request fields:
  - `email`
  - `otp`
- Key response fields: `user`, `access`, `refresh`

4. `POST /resend-otp/`
- Auth: none
- Request fields:
  - `email`
- Key response fields: `message`

5. `POST /login/`
- Auth: none
- Request fields:
  - `email`
  - `password`
  - `remember_me` optional
- Key response fields:
  - If 2FA is enabled: `requires_2fa`, `temp_token`, `message`
  - Otherwise: `user`, `access`, `refresh`, `remember_me`

6. `POST /refresh-token/`
- Auth: refresh token in JSON `refresh`/`refresh_token` or the refresh cookie
- Request body: optional JSON refresh token; no `Authorization` refresh token
- Key response fields: new `access` and `refresh` tokens

7. `POST /logout/`
- Auth: customer refresh token in JSON `refresh`/`refresh_token` or cookie; access
  token optional via JSON `access`, Bearer header, or access cookie
- Request fields:
  - `access` optional in body
- Key response fields: `message`

### Password Management

8. `POST /forgot-password/`
- Auth: none
- Request fields:
  - `email`
  - `role` optional (`customer`, `loan_officer`, `admin`)
- Key response fields: `message` only

9. `POST /verify-reset-otp/`
- Auth: none
- Request fields:
  - `email`
  - `otp`
  - `role` optional (`customer`, `loan_officer`, `admin`)
- Key response fields: `message` only

10. `POST /reset-password/`
- Auth: none
- Request fields:
  - `email`
  - `otp`
  - `new_password`
  - `confirm_password`
  - `role` optional (`customer`, `loan_officer`, `admin`)
- Key response fields: `message` only

11. `POST /change-password/`
- Auth: authenticated customer, loan officer, or administrator
- Request fields:
  - `old_password`
  - `new_password`
  - `confirm_password`
- Key response fields: `message`

### Two-Factor Authentication

12. `POST /2fa/setup/`
- Auth: authenticated customer, loan officer, or administrator
- Request fields: none
- Key response fields: `provisioning_uri`, `manual_entry_key`, `qr_code_data_url`, `message`

13. `POST /2fa/confirm/`
- Auth: authenticated customer, loan officer, or administrator
- Request fields:
  - `code`
- Key response fields: `backup_codes`, `message`

14. `POST /2fa/verify/`
- Auth: none
- Request fields:
  - `temp_token`
  - `code`
  - `use_backup` optional
- Key response fields: `user`, `access`, `refresh`

15. `POST /2fa/disable/`
- Auth: authenticated customer, loan officer, or administrator; administrator
  2FA cannot be disabled
- Request fields:
  - `password`
- Key response fields: `message`

16. `POST /2fa/backup-codes/`
- Auth: authenticated customer, loan officer, or administrator
- Request fields:
  - `password`
- Key response fields: `backup_codes`

17. `GET /2fa/status/`
- Auth: authenticated customer, loan officer, or administrator
- Request fields: none
- Key response fields: `two_factor_enabled`, `backup_codes_remaining`

### Consent Management

18. `GET /consent/`
- Auth: authenticated customer
- Request fields: none
- Key response fields: `data_consent`, `ai_consent`, `consent_date`, `updated_at`, `can_access_ai`, `has_consent_record`

19. `POST /consent/`
- Auth: authenticated customer
- Request fields:
  - `data_consent`
  - `ai_consent`
- Key response fields: `data_consent`, `ai_consent`, `consent_date`, `can_access_ai`

20. `PUT /consent/`
- Auth: authenticated customer
- Request fields:
  - `data_consent` optional
  - `ai_consent` optional
- Key response fields: `data_consent`, `ai_consent`, `updated_at`, `can_access_ai`

### Language

21. `PATCH /language/`
- Auth: authenticated customer
- Request fields:
  - `language` (`en` or `tl`)
- Key response fields: `language`

### Activity & Session Management

22. `GET /sessions/`
- Auth: authenticated customer, loan officer, or administrator
- Request fields: none
- Key response fields: list of active session objects

23. `DELETE /sessions/`
- Auth: authenticated customer, loan officer, or administrator
- Request fields:
  - `session_id` for one session; or
  - `revoke_all` and optional `keep_current` for bulk revocation
- Key response fields: `message`

24. `GET /login-activity/`
- Auth: authenticated customer, loan officer, or administrator
- Request fields: none
- Key response fields: list of login activity objects

### Account Lifecycle and Recovery

- `POST /email-change/request/`
  - Auth: authenticated customer
  - Request fields: `new_email`, `password`
  - Sends a verification OTP to the new address.
- `POST /email-change/confirm/`
  - Auth: authenticated customer
  - Request fields: `otp`
  - Consumes the OTP, changes the email, and revokes existing sessions.
- `GET /account/export/`
  - Auth: authenticated customer
  - Returns account, consent, session, login-activity, audit, and notification data.
- `POST /account/deletion-request/`
  - Auth: authenticated customer
  - Request fields: `reason` optional
  - Moves the account to `pending_deletion`, revokes sessions, and returns
    `deletion_scheduled_for`.
- `POST /account/deletion-cancel/`
  - Auth: none
  - Request fields: `email`, `password`
  - Credentialed cancellation is available until the retention date. The
    response is generic when the account or credentials are not eligible.
- `GET /admin/customers/`
  - Auth: admin with `manage_users`
  - Query fields: `search`, `active`, `account_state`
- `GET /admin/customers/<customer_id>/`
  - Auth: admin with `manage_users`
  - Returns customer lifecycle and deletion metadata.
- `PATCH /admin/customers/<customer_id>/`
  - Auth: admin with `manage_users`
  - Request fields: `account_state` (`active`, `suspended`, or `deactivated`),
    `reason` optional
  - State changes revoke sessions; restoring an account also clears lockout state.
- `POST /admin/customers/<customer_id>/unlock/`
  - Auth: admin with `manage_users`
  - Clears login lockout counters and records an audit/security event.
- `POST /admin/customers/<customer_id>/deletion/finalize/`
  - Auth: admin with `manage_users`
  - Request fields: `reason` optional
  - Finalization is accepted only after `deletion_scheduled_for` and anonymizes
    customer identity fields.
- `POST /2fa/recovery/request/`
  - Auth: none
  - Request fields: customer `email`, current `password`
  - Sends a generic recovery OTP when the account is eligible.
- `POST /2fa/recovery/verify/`
  - Auth: none
  - Request fields: customer `email`, `otp`
  - Verifies the OTP and queues the request for administrator review.
- `GET /admin/customers/2fa-recovery/`
  - Auth: admin with `manage_users`
  - Returns verified recovery requests awaiting a decision.
- `POST /admin/customers/<customer_id>/2fa-recovery/`
  - Auth: admin with `manage_users`
  - Request fields: `approve`, `reason` optional
  - Approval disables 2FA, revokes sessions, and records the decision.

### Loan Officer Authentication

25. `POST /loan-officer/login/`
- Auth: none
- Request fields:
  - `email`
  - `password`
  - `remember_me` optional
- Key response fields:
  - If 2FA is enabled: `requires_2fa`, `temp_token`, `must_change_password`
  - Otherwise: `access_token`, `refresh_token`, `user`, `must_change_password`

26. `POST /loan-officer/logout/`
- Auth: refresh token recommended from JSON `refresh`/`refresh_token` or cookie;
  access token may be sent by Bearer header or access cookie
- Request fields: none required in body
- Key response fields: `message`

27. `GET /loan-officer/me/`
- Auth: authenticated loan officer
- Request fields: none
- Key response fields: `id`, `email`, `first_name`, `last_name`, `full_name`, `phone`, `department`, `employee_id`, `role`, `last_login_attempt`

27a. `PUT /loan-officer/me/`
- Auth: authenticated loan officer only
- Request fields: `first_name`, `last_name`, and/or `phone` optional
- Read-only profile fields: `email`, `department`, and `employee_id`
- Key response fields: updated officer profile
- If `must_change_password` is active, protected profile access returns HTTP 423
  with `password_change_required` until `POST /change-password/` succeeds.

### Admin Authentication

28. `POST /admin/login/`
- Auth: none
- Request fields:
  - `username`
  - `password`
- Key response fields:
  - If 2FA setup required: `requires_2fa`, `requires_2fa_setup`, `temp_token`, `provisioning_uri`, `manual_entry_key`, `qr_code_data_url`
  - If 2FA is enabled: `requires_2fa`, `temp_token`

29. `POST /admin/logout/`
- Auth: refresh token recommended from JSON `refresh`/`refresh_token` or cookie;
  access token may be sent by Bearer header or access cookie
- Request fields: none required in body
- Key response fields: `message`

30. `GET /admin/me/`
- Auth: authenticated admin
- Request fields: none
- Key response fields: admin profile fields

30a. `PUT /admin/me/`
- Auth: authenticated administrator or super administrator only
- Request fields: `first_name` and/or `last_name` optional
- Read-only/profile-managed elsewhere: `username`, `email`, `permissions`, and
  `super_admin`
- Key response fields: updated admin profile

### Admin - Loan Officer Management

31. `GET /admin/loan-officers/`
- Auth: admin with `create_loan_officer`
- Query fields:
  - `search`
  - `active`
  - `department`
  - `page`
  - `page_size`
  - `sort_by`
  - `sort_order`
- Key response fields: `loan_officers`, `total`, `page`, `page_size`, `total_pages`

32. `POST /admin/loan-officers/`
- Auth: admin with `create_loan_officer`
- Request fields:
  - `employee_id` / `employeeId`
  - `first_name` / `firstName`
  - `last_name` / `lastName`
  - `email` / `emailAddress`
  - `phone` / `phone_number` / `phoneNumber` optional
  - `department` / `departmentName` optional
- Key response fields: `loan_officer`, `email_sent`, `message`

33. `GET /admin/loan-officers/<officer_id>/`
- Auth: admin with `manage_loan_officers`
- Request fields: none
- Key response fields: loan officer detail object

34. `PUT /admin/loan-officers/<officer_id>/`
- Auth: admin with `manage_loan_officers`
- Request fields:
  - `last_known_updated_at` optional
  - `first_name` optional
  - `last_name` optional
  - `phone` optional
  - `department` optional
  - `active` optional
- Key response fields: updated loan officer object

35. `DELETE /admin/loan-officers/<officer_id>/`
- Auth: admin with `manage_loan_officers`
- Request fields: none
- Key response fields: `message`

### Admin - Admin Management

36. `GET /admin/admins/`
- Auth: super admin
- Query fields:
  - `search`
  - `active`
  - `page`
  - `page_size`
  - `sort_by`
  - `sort_order`
- Key response fields: `admins`, `total`, `page`, `page_size`, `total_pages`

37. `POST /admin/admins/`
- Auth: super admin
- Request fields:
  - `username`
  - `email`
  - `first_name`
  - `last_name`
  - `super_admin` optional
  - `permissions` optional
- Key response fields: `admin`, `temporary_password`

38. `GET /admin/admins/<admin_id>/`
- Auth: super admin
- Request fields: none
- Key response fields: admin detail object

39. `PUT /admin/admins/<admin_id>/`
- Auth: super admin
- Request fields:
  - `last_known_updated_at` optional
  - `first_name` optional
  - `last_name` optional
  - `active` optional
- Key response fields: updated admin object

40. `DELETE /admin/admins/<admin_id>/`
- Auth: super admin
- Request fields: none
- Key response fields: `message`

41. `PUT /admin/admins/<admin_id>/permissions/`
- Auth: super admin
- Request fields:
  - `permissions` optional
  - `super_admin` optional
- Key response fields: updated permissions object

### Consent Audit

42. `GET /consent/history/`
- Auth: authenticated customer
- Request fields: none
- Key response fields: list of consent history records

43. `GET /consent/audit/`
- Auth: admin
- Request fields: none
- Key response fields: admin consent audit report

### Support

44. `POST /contact/`
- Auth: none
- Request fields:
  - `full_name`
  - `contact_email`
  - `concern_type`
  - `message`
- Key response fields: `message`

## Smoke Test Sequence

1. `GET /csrf-token/`
2. Sign up a customer with `POST /signup/`
3. Verify the email with `POST /verify-email/`
4. Log in with `POST /login/`
5. Test `GET /consent/`, `POST /consent/`, and `PUT /consent/`
6. Test `PATCH /language/`
7. Exercise the 2FA flow: `POST /2fa/setup/`, `POST /2fa/confirm/`, `POST /2fa/verify/`
8. Test password reset: `POST /forgot-password/`, `POST /verify-reset-otp/`, `POST /reset-password/`
9. Test `POST /refresh-token/` and `POST /logout/`
10. Test activity endpoints: `GET /sessions/` and `GET /login-activity/`
11. Test customer lifecycle endpoints: email change, export, deletion request,
    and credentialed deletion cancellation.
12. If you have `manage_users` credentials, test customer state management,
    lockout unlock, deletion finalization after retention, and 2FA recovery review.
13. Test `POST /contact/`
14. If you have loan-officer credentials, test `POST /loan-officer/login/`, `GET /loan-officer/me/`, and `POST /loan-officer/logout/`
15. If you have super-admin credentials, test `POST /admin/login/`, `POST /admin/admins/`, and the admin management routes.

## Negative Tests

Run these checks with a disposable test account and record the HTTP status and
error code:

1. Send `token_transport: "hybrid"` to a login or verification endpoint -> `400`.
2. Send a cookie-authenticated unsafe request without `csrftoken` or
   `X-CSRFToken` -> `403 csrf_token_missing`.
3. Send a mismatched CSRF cookie/header pair -> `403 csrf_token_invalid`.
4. Send a pure Bearer request without a CSRF pair -> it is not blocked by the
   cookie-CSRF middleware.
5. Call refresh with only `Authorization: Bearer <refresh_token>` -> no refresh
   token is found; use JSON or the refresh cookie instead.
6. Call customer refresh or logout without a refresh token -> `400`.
7. Use a temporary 2FA token at refresh -> `401`.
8. Reuse the old refresh token after rotation or logout -> `401`.
9. Use a customer token on `/loan-officer/me/` or an officer token on the
   customer-only consent/lifecycle routes -> reject the request.
10. Access a protected officer route while `must_change_password` is true ->
    `423 password_change_required`.
11. Attempt administrator 2FA disablement -> reject with the administrator-2FA
    mandatory error.

## Revocation Checks

For each check, use a second protected request or refresh attempt to prove that
the old credential is no longer usable:

- Refresh rotation: the new pair works, while the old refresh token returns
  `401`.
- Logout: the refresh membership is revoked and a later refresh returns `401`.
- Staff multi-session login: signing in from two browsers keeps both sessions
  active and lists both on `GET /sessions/`.
- Password change/reset: all existing sessions are revoked; old access and
  refresh credentials fail.
- Customer email confirmation, account deletion request, state change, officer
  deactivation, and approved 2FA recovery: existing sessions are revoked.
- `DELETE /sessions/` with one session, `revoke_all: true`, and
  `keep_current: true` produces the expected single-session, all-session, and
  all-except-current results. For all-except-current, the other browser must
  receive `401` while the requesting browser remains authenticated.
- A security-state change increments `security_version`; an older access token
  then fails live authentication even if its JWT expiry has not passed.

## Security-State Transitions

| Transition | Expected behavior |
| --- | --- |
| Customer `active` -> `suspended` or `deactivated` | Existing sessions are revoked; protected access and refresh fail. |
| Account `security_version` changes | Older access/refresh credentials fail live-state validation. |
| Officer `must_change_password = true` | Protected officer views return HTTP 423 until password change succeeds. |
| Password reset/change succeeds | Existing sessions are revoked and a security event is recorded. |
| Login password accepted with 2FA enabled | A short-lived `temp_token` is returned; full tokens are issued only after 2FA verification. |
| Temporary 2FA token is verified | The temporary token is consumed/blacklisted and the final token transport is preserved. |
| Customer deletion requested | State becomes `pending_deletion`, sessions are revoked, and cancellation remains credentialed until retention. |

## Common Errors

1. `401 Unauthorized`
- Missing or invalid auth token.
- Inactive account attempting to refresh or access protected routes.

2. `403 Forbidden`
- Wrong role accessing a protected route.
- Missing required permissions for admin routes.

3. `400 Bad Request`
- Missing required fields.
- Invalid choice values.
- Bad OTP or password confirmation mismatch.

4. `429 Too Many Requests`
- OTP or login rate limit exceeded. Wait for cooldown.

5. `409 Conflict`
- Customer deletion is not yet due for administrative finalization.
- A verified 2FA recovery request has expired or was already processed.

6. `500 Internal Server Error`
- Unexpected server error. Check logs for details.

## Notes

- Customer login returns `access` and `refresh`; loan officer login returns `access_token` and `refresh_token` in body mode.
- Refresh uses JSON `refresh`/`refresh_token` or the refresh cookie, not `Authorization: Bearer` for the refresh token.
- Cookie-mode login/verification requests must explicitly request `token_transport: "cookie"` or send `X-Token-Transport: cookie`; `withCredentials` alone does not select cookie delivery.
- Admin login accepts `username` and `password`. The `username` field also supports email lookup.
- Password reset accepts optional `role` (`customer`, `loan_officer`, `admin`) to target non-customer accounts.
- Admin loan-officer creation accepts multiple field name aliases (snake_case and camelCase) for frontend compatibility.
- 2FA is mandatory for admin accounts. If an admin has not enrolled in 2FA, login returns `requires_2fa_setup: true` plus QR provisioning data.
- Consent GET returns `has_consent_record` to distinguish between no record and explicit false consent.
- `remember_me` defaults to `false` on customer login and affects refresh token lifetime.
- `ACCOUNT_DELETION_RETENTION_DAYS` defaults to 30 days; scheduled finalization is
  handled by `accounts.tasks.finalize_scheduled_customer_deletions_task`.
- If legacy data contains the same email in multiple roles, password recovery
  requires the explicit `role` field and never selects a role by search order.
