# Accounts API Testing Guide

## Scope
Accounts handles authentication, OTP, password reset, consent, 2FA, loan officer auth, admin management, activity tracking, and support contact.

## Base URL and Auth
- Base URL: `http://localhost:8000/api/auth`
- Protected endpoints require:
  ```http
  Authorization: Bearer <access_token>
  Content-Type: application/json
  ```
- Customer-only endpoints require a customer token.
- Admin endpoints require admin or super-admin tokens depending on the route.
- Some endpoints accept tokens via cookies instead of the `Authorization` header.

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
- Auth: refresh token via cookie or `Authorization: Bearer <refresh_token>`
- Request body: none required
- Key response fields: new `access` and `refresh` tokens

7. `POST /logout/`
- Auth: refresh token via cookie; access token optional via cookie or request body
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
- Auth: authenticated customer or loan officer
- Request fields:
  - `old_password`
  - `new_password`
  - `confirm_password`
- Key response fields: `message`

### Two-Factor Authentication

12. `POST /2fa/setup/`
- Auth: authenticated customer or loan officer
- Request fields: none
- Key response fields: `provisioning_uri`, `manual_entry_key`, `qr_code_data_url`, `message`

13. `POST /2fa/confirm/`
- Auth: authenticated customer or loan officer
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
- Auth: authenticated customer or loan officer
- Request fields:
  - `password`
- Key response fields: `message`

16. `POST /2fa/backup-codes/`
- Auth: authenticated customer or loan officer
- Request fields:
  - `password`
- Key response fields: `backup_codes`

17. `GET /2fa/status/`
- Auth: authenticated customer or loan officer
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
- Auth: authenticated customer
- Request fields: none
- Key response fields: list of active session objects

23. `DELETE /sessions/`
- Auth: authenticated customer
- Request fields:
  - `session_id` for one session; or
  - `revoke_all` and optional `keep_current` for bulk revocation
- Key response fields: `message`

24. `GET /login-activity/`
- Auth: authenticated customer
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
- Auth: refresh token required
- Request fields: none required in body
- Key response fields: `message`

27. `GET /loan-officer/me/`
- Auth: authenticated loan officer
- Request fields: none
- Key response fields: `id`, `email`, `first_name`, `last_name`, `full_name`, `phone`, `department`, `employee_id`, `role`, `last_login_attempt`

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
- Auth: refresh token required
- Request fields: none required in body
- Key response fields: `message`

30. `GET /admin/me/`
- Auth: authenticated admin
- Request fields: none
- Key response fields: admin profile fields

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

- Customer login returns `access` and `refresh`; loan officer login returns `access_token` and `refresh_token`.
- Refresh and logout endpoints expect the refresh token via cookie or `Authorization: Bearer` header, not in the JSON body.
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
