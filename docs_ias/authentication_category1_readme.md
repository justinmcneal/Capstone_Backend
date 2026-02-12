## Category 1 Authentication Review (accounts/urls.py)

Scope: Endpoints in `accounts/urls.py` and their linked views/services.

### Summary
1. Strong password hashing (bcrypt/Argon2): Implemented (bcrypt).
1. Secure sessions with expiry: Implemented via JWT expiry (access/refresh lifetimes).
1. Generic login errors: Implemented (no attempt-count leakage).
1. Rate limiting for logins: Partially implemented (customer only).
1. MFA available or enforced: Available, not enforced.
1. Validated tokens (JWT): Implemented (SimpleJWT + blacklist).
1. Strong password policy: Implemented for customer reset/signup/change; not uniform across admin/loan officer flows.
1. Logout invalidates session: Implemented (token blacklisting).
1. OAuth/SSO or advanced auth: Not implemented.

### Evidence (Code References)
1. Bcrypt hashing:
1. `accounts/models/customer.py`
1. `accounts/models/admin.py`
1. `accounts/models/loan_officer.py`
1. JWT auth + token expiry:
1. `config/settings.py` (SIMPLE_JWT, TOKEN_LIFETIMES)
1. `accounts/utils/token_utils.py`
1. `accounts/authentication.py`
1. Generic login errors:
1. `accounts/views/auth_views.py` (customer login returns generic invalid credentials for both unknown email and wrong password)
1. `accounts/views/admin_views.py` and `accounts/views/loan_officer_views.py` (generic "Invalid credentials")
1. Rate limiting:
1. `accounts/utils/throttles.py` (IP throttles)
1. `accounts/views/auth_views.py` + `accounts/services/auth_service.py` (30-second per-user limit)
1. MFA:
1. `accounts/views/two_factor_views.py`
1. `accounts/services/two_factor_service.py`
1. Password policy:
1. `config/settings.py` (AUTH_PASSWORD_VALIDATORS)
1. `accounts/serializers/base_serializers.py`
1. `accounts/serializers/auth_serializers.py`
1. `accounts/serializers/password_serializers.py`
1. Logout invalidation:
1. `accounts/views/auth_views.py`
1. `accounts/views/admin_views.py`
1. `accounts/views/loan_officer_views.py`
1. `accounts/utils/token_utils.py`
1. OAuth/SSO:
1. No OAuth/SSO endpoints in `accounts/urls.py`

## How To Test (Manual)

Assumptions:
1. The API is running locally at `http://localhost:8000`.
1. MongoDB is configured and reachable via `MONGODB_URI`.
1. Endpoints are under `/api/auth/` (see `config/urls.py`).

### 1) Strong Password Hashing (bcrypt)
Steps:
1. Sign up a customer:
```bash
curl -s -X POST http://localhost:8000/api/auth/signup/ \
  -H "Content-Type: application/json" \
  -d '{"first_name":"Test","last_name":"User","email":"test@example.com","password":"S3curePass!","password_confirm":"S3curePass!"}'
```
1. Inspect the stored user in MongoDB (e.g. `customer` collection) and verify `password` is a bcrypt hash (starts with `$2a$` or `$2b$`).

How to know it is correct:
1. The stored password is not plaintext and has a bcrypt prefix.
1. Login with the plaintext password succeeds.

### 2) Secure Sessions With Expiry (JWT)
Steps:
1. Login to get tokens:
```bash
curl -s -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"S3curePass!","remember_me":false}'
```
1. Decode the access token (`exp` claim) and confirm it is roughly 10 minutes ahead of issue time.

How to know it is correct:
1. Access token `exp` is short-lived (`~10 min`), refresh token `exp` is `~24h` (or `3d` if `remember_me`).
1. An expired access token is rejected by a protected endpoint with `401`.

### 3) Generic Login Errors (Implemented) Do not show attempts remaining
Steps:
1. Non-existent email:
```bash
curl -s -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"nope@example.com","password":"WrongPass123"}'
```
1. Existing email, wrong password:
```bash
curl -s -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"WrongPass123"}'
```

How to know it is correct:
1. For non-existent email, the response is generic (`Invalid email or password`).
1. For wrong password on an existing user, the response is also generic (`Invalid email or password`) with no attempt count shown.

### 4) Rate Limiting For Logins (Partial) admin/loan officer only use lockout

Steps:
1. Send more than 10 login requests/hour from the same IP to `/api/auth/login/`.
1. Send rapid back-to-back logins for the same user within 30 seconds.

How to know it is correct:
1. IP throttle returns `429` with a rate-limit message after 10/hour.
1. Per-user short window returns `429` with "Please try again in X seconds."
1. Note: Admin/loan officer logins do not use DRF throttles; only lockout applies there.

Validated results (Feb 12, 2026):
1. Customer `/api/auth/login/` from same IP: first 10 attempts returned `401`, 11th returned `429`.
1. Customer rapid retry for same account within 30s: second request returned `429` with `Please try again in X seconds`.
1. Admin `/api/auth/admin/login/`: no DRF throttle (`429` not observed); lockout path returned `403` after repeated failures.
1. Loan officer `/api/auth/loan-officer/login/`: no DRF throttle (`429` not observed); lockout path returned `403` after repeated failures.

Automated test:
1. `accounts/tests/test_login_rate_limiting.py`
1. Run:
```bash
python manage.py test accounts.tests.test_login_rate_limiting -v 2
```

### 5) 2FA Available (2FA)
Steps:
1. Authenticate and call setup:
```bash
curl -s -X POST http://localhost:8000/api/auth/2fa/setup/ \
  -H "Authorization: Bearer <access_token>"
```
1. Confirm setup with a valid TOTP code:
```bash
curl -s -X POST http://localhost:8000/api/auth/2fa/confirm/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"code":"123456"}'
```
1. Login again and verify the login flow requires `temp_token` and `/api/auth/2fa/verify/`.

How to know it is correct:
1. Setup returns a provisioning URI and manual key.
1. Confirm returns backup codes and `two_factor_enabled` flips to `true`.
1. Login returns `requires_2fa: true` and a temporary token.

### 6) Validated Tokens (JWT)
Steps:
1. Use `/api/auth/refresh-token/` with a valid refresh token.
1. Use an invalid or tampered token for refresh.

How to know it is correct:
1. Valid refresh returns new tokens.
1. Invalid refresh returns `401` or `400` with "Invalid or expired token."

### 7) Strong Password Policy (Implemented for signup/reset/change; forgot-password is OTP-only)
Steps:
1. Signup: submit a weak password (e.g., `123456`) to `/api/auth/signup/`, then submit a strong password.
1. Reset password: submit weak and strong `new_password` values to `/api/auth/reset-password/`.
1. Change password: submit weak and strong `new_password` values to `/api/auth/change-password/`.
1. Forgot password: call `/api/auth/forgot-password/` and confirm it only accepts `email` (no password field in this step).

How to know it is correct:
1. Weak passwords are rejected with Django validator messages (e.g., too short/common/numeric) in signup, reset, and change flows.
1. Strong passwords pass serializer validation in signup, reset, and change flows.
1. Forgot-password flow only initiates OTP; password policy is enforced later at reset/change steps.

Automated test:
1. `accounts/tests/test_password_policy.py`
1. Run:
```bash
MONGODB_URI='' .venv/bin/python manage.py test accounts.tests.test_password_policy -v 2
```

### 8) Logout Invalidates Session
Steps:
1. Login and capture access/refresh tokens.
1. Logout:
```bash
curl -s -X POST http://localhost:8000/api/auth/logout/ \
  -H "Content-Type: application/json" \
  -d '{"refresh":"<refresh_token>","access":"<access_token>"}'
```
1. Call a protected endpoint using the same access token.

How to know it is correct:
1. The protected endpoint returns `401` with "Token has been revoked."

### 9) OAuth/SSO or Advanced Auth NO OAUTH NO NEED
Steps:
1. Check `accounts/urls.py` for OAuth/SSO endpoints.

How to know it is correct:
1. There are no OAuth/SSO endpoints present, confirming this is not implemented.
