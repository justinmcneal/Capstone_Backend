# Accounts API Testing Guide

## Scope
Accounts handles authentication, OTP, password reset, consent, 2FA, loan officer auth, and admin management.

## Base URL and Auth
- Base URL: `http://localhost:8000/api/auth`
- Most protected endpoints require:
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```
- Customer-only endpoints require a customer token.
- Admin endpoints require admin or super-admin tokens depending on the route.

## URL Reference

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
- Key response fields: customer `user` object, message

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
- Key response fields: message only

5. `POST /login/`
- Auth: none
- Request fields:
  - `email`
  - `password`
  - `remember_me` optional
- Key response fields:
  - If 2FA is enabled: `requires_2fa`, `temp_token`
  - Otherwise: `user`, `access`, `refresh`, `remember_me`

6. `POST /refresh-token/`
- Auth: refresh token via cookie/header
- Request fields: none required in body
- Key response fields: new `access` and `refresh` tokens

7. `POST /logout/`
- Auth: refresh token required, access token optional
- Request fields:
  - `access` optional in body
- Key response fields: logout message

8. `POST /forgot-password/`
- Auth: none
- Request fields:
  - `email`

9. `POST /verify-reset-otp/`
- Auth: none
- Request fields:
  - `email`
  - `otp`

10. `POST /reset-password/`
- Auth: none
- Request fields:
  - `email`
  - `otp`
  - `new_password`
  - `confirm_password`

11. `POST /change-password/`
- Auth: authenticated customer/loan officer
- Request fields:
  - `old_password`
  - `new_password`
  - `confirm_password`

12. `PATCH /language/`
- Auth: authenticated customer
- Request fields:
  - `language` (`en` or `tl`)
- Key response fields: updated `language`

13. `POST /2fa/setup/`
- Auth: authenticated customer or loan officer
- Request fields: none
- Key response fields: `provisioning_uri`, `manual_entry_key`, `qr_code_data_url`

14. `POST /2fa/confirm/`
- Auth: authenticated customer or loan officer
- Request fields:
  - `code`
- Key response fields: `backup_codes`

15. `POST /2fa/verify/`
- Auth: none
- Request fields:
  - `temp_token`
  - `code`
  - `use_backup` optional
- Key response fields: `user`, `access`, `refresh`

16. `POST /2fa/disable/`
- Auth: authenticated customer or loan officer
- Request fields:
  - `password`

17. `POST /2fa/backup-codes/`
- Auth: authenticated customer or loan officer
- Request fields:
  - `password`
- Key response fields: `backup_codes`

18. `GET /2fa/status/`
- Auth: authenticated customer or loan officer
- Request fields: none
- Key response fields: `two_factor_enabled`, `backup_codes_remaining`

19. `GET /consent/`
- Auth: authenticated customer
- Request fields: none
- Key response fields: `data_consent`, `ai_consent`, `consent_date`, `updated_at`, `can_access_ai`

20. `POST /consent/`
- Auth: authenticated customer
- Request fields:
  - `data_consent`
  - `ai_consent`

21. `PUT /consent/`
- Auth: authenticated customer
- Request fields:
  - `data_consent` optional
  - `ai_consent` optional

22. `POST /loan-officer/login/`
- Auth: none
- Request fields:
  - `email`
  - `password`
  - `remember_me` optional
- Key response fields: `requires_2fa` or `access_token`, `refresh_token`, `user`, `must_change_password`

23. `POST /loan-officer/logout/`
- Auth: refresh token required, access token optional
- Request fields: none required in body

24. `POST /admin/login/`
- Auth: none
- Request fields:
  - `username`
  - `password`
- Key response fields: usually `requires_2fa`, `temp_token`

25. `POST /admin/logout/`
- Auth: refresh token required, access token optional
- Request fields: none required in body

26. `GET /admin/loan-officers/`
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

27. `POST /admin/loan-officers/`
- Auth: admin with `create_loan_officer`
- Request fields:
  - `employee_id`
  - `first_name`
  - `last_name`
  - `email`
  - `phone` optional
  - `department` optional
- Key response fields: `loan_officer`, `email_sent`, temporary password message

28. `GET /admin/loan-officers/<officer_id>/`
- Auth: admin with `manage_loan_officers`
- Request fields: none

29. `PUT /admin/loan-officers/<officer_id>/`
- Auth: admin with `manage_loan_officers`
- Request fields:
  - `last_known_updated_at` optional
  - `first_name` optional
  - `last_name` optional
  - `phone` optional
  - `department` optional
  - `active` optional

30. `DELETE /admin/loan-officers/<officer_id>/`
- Auth: admin with `manage_loan_officers`
- Request fields: none

31. `GET /admin/admins/`
- Auth: super admin
- Query fields:
  - `search`
  - `active`
  - `page`
  - `page_size`
  - `sort_by`
  - `sort_order`
- Key response fields: `admins`, `total`, `page`, `page_size`, `total_pages`

32. `POST /admin/admins/`
- Auth: super admin
- Request fields:
  - `username`
  - `email`
  - `first_name`
  - `last_name`
  - `super_admin` optional
  - `permissions` optional
- Key response fields: `admin`, `temporary_password`

33. `GET /admin/admins/<admin_id>/`
- Auth: super admin
- Request fields: none

34. `PUT /admin/admins/<admin_id>/`
- Auth: super admin
- Request fields:
  - `last_known_updated_at` optional
  - `first_name` optional
  - `last_name` optional
  - `active` optional

35. `DELETE /admin/admins/<admin_id>/`
- Auth: super admin
- Request fields: none

36. `PUT /admin/admins/<admin_id>/permissions/`
- Auth: super admin
- Request fields:
  - `permissions` optional
  - `super_admin` optional

## Smoke Test Sequence
1. `GET /csrf-token/`
2. Sign up a customer with `POST /signup/`
3. Verify the email with `POST /verify-email/`
4. Log in with `POST /login/`
5. Test `GET /consent/` and `PUT /consent/`
6. Test `PATCH /language/`
7. Exercise the 2FA flow: `POST /2fa/setup/`, `POST /2fa/confirm/`, `POST /2fa/verify/`
8. Test password reset: `POST /forgot-password/`, `POST /verify-reset-otp/`, `POST /reset-password/`
9. Test `POST /refresh-token/` and `POST /logout/`
10. If you have admin credentials, test `POST /admin/login/` and the admin management routes.

## Common Errors
1. `401 Unauthorized`
- Missing or invalid auth token.

2. `403 Forbidden`
- Wrong role accessing a protected route.

3. `400 Bad Request`
- Missing required fields.
- Invalid choice values.
- Bad OTP or password confirmation mismatch.
