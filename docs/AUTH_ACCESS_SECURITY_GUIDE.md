# Auth Access Security Guide

## Scope
This guide covers:
- Authentication flows for `customer`, `loan_officer`, and `admin`
- 2FA, password reset, token lifecycle, and logout
- Consent management
- Role and permission enforcement for protected APIs
- Security middleware and anti-abuse controls

## Base URL and Auth
- Base URL: `http://localhost:8000/api/auth`
- API auth uses JWT Bearer tokens.
- Browser sessions can also use HttpOnly auth cookies (`access_token`, `refresh_token` by default).

## Role Model
1. `customer`
- Self-registration.
- Accesses customer-only flows and domain APIs.

2. `loan_officer`
- Created by admins.
- Accesses officer-scoped operations.

3. `admin`
- Manages operational users and protected admin features.
- Can be `super_admin` for full admin management.

## RBAC and Permissions
Admin permission keys:
- `create_loan_officer`
- `manage_loan_officers`
- `manage_users`
- `view_analytics`
- `view_logs`
- `manage_system`

Enforcement behavior:
- Role checks are centralized in `accounts/utils/access_control.py`.
- Privileged accounts (`loan_officer`, `admin`, `super_admin`) must be active.
- `super_admin` bypasses permission lists.

## Token and Session Behavior
1. Customer tokens
- Access token: 10 minutes.
- Refresh token:
  - `remember_me=true`: 3 days.
  - Default/no remember me: 24 hours.
- Customer refresh tokens are single-device enforced (new login invalidates prior refresh entries).

2. Loan officer and admin tokens
- Access token: 15 minutes.
- Refresh token:
  - Admin: 1 day.
  - Loan officer: 1 day (or 3 days on direct login with `remember_me=true`).

3. 2FA temporary token
- Used between password verification and `POST /2fa/verify/`.
- Expires in 5 minutes.

4. Logout and revocation
- Access and refresh tokens are blacklisted on logout.
- Refresh tokens are rotated manually via `POST /refresh-token/` (old refresh is blacklisted).

## 2FA Policy
1. Setup and verification
- `POST /2fa/setup/` returns provisioning URI, manual key, and QR data URL.
- `POST /2fa/confirm/` enables 2FA and returns 10 one-time backup codes.

2. Login verification
- `POST /2fa/verify/` validates TOTP or backup code using a temporary token.

3. Admin hard requirement
- Admin login always requires 2FA.
- If not yet enabled, admin login returns setup payload and requires 2FA bootstrap.
- Admin 2FA cannot be disabled (`POST /2fa/disable/` returns `403` for admins).

## Lockout and Throttling
1. Login lockout
- Customer: 5 failed attempts -> 15-minute lock.
- Loan officer: 5 failed attempts -> 15-minute lock.
- Admin: 5 failed attempts -> 30-minute lock.

2. Additional customer login cooldown
- Customer login has a per-account 30-second attempt cooldown.

3. Endpoint throttles (IP-based)
- Sign up: `5/hour`
- Login: `10/hour`
- OTP verification: `5/hour`
- OTP resend: `3/hour`
- 2FA verify/confirm: `5/hour`
- Forgot password: `5/hour`

4. OTP constraints
- Email verification OTP expiry: 10 minutes.
- Password reset OTP expiry: 15 minutes.
- Verification OTP resend cap: 2 resends per account.

## Consent Model
Consent endpoint:
- `GET /consent/`
- `POST /consent/`
- `PUT /consent/`

Consent fields:
- `data_consent`
- `ai_consent`

AI endpoints enforce consent and return `CONSENT_REQUIRED` with action details when missing.

## Security Middleware
1. Security headers
- Adds headers such as `X-Frame-Options`, `X-Content-Type-Options`, CSP, HSTS (non-localhost), COOP/CORP/COEP.

2. CSRF same-site check for API writes
- For unsafe `/api/` methods, when CSRF cookie exists, matching CSRF header is required.

3. NoSQL injection guard
- Blocks request/query keys starting with `$` or containing `.` for API write requests.

## Endpoint Matrix
| Method | Endpoint | Access |
|---|---|---|
| `GET` | `/csrf-token/` | Public |
| `POST` | `/signup/` | Public |
| `POST` | `/verify-email/` | Public |
| `POST` | `/resend-otp/` | Public |
| `POST` | `/login/` | Public (customer) |
| `POST` | `/refresh-token/` | Public (requires refresh token) |
| `POST` | `/logout/` | Public (requires tokens) |
| `POST` | `/forgot-password/` | Public |
| `POST` | `/verify-reset-otp/` | Public |
| `POST` | `/reset-password/` | Public |
| `POST` | `/change-password/` | Authenticated |
| `POST` | `/2fa/setup/` | Authenticated |
| `POST` | `/2fa/confirm/` | Authenticated |
| `POST` | `/2fa/verify/` | Public (temp token flow) |
| `POST` | `/2fa/disable/` | Authenticated |
| `POST` | `/2fa/backup-codes/` | Authenticated |
| `GET` | `/2fa/status/` | Authenticated |
| `GET/POST/PUT` | `/consent/` | Authenticated |
| `POST` | `/loan-officer/login/` | Public |
| `POST` | `/loan-officer/logout/` | Public |
| `POST` | `/admin/login/` | Public |
| `POST` | `/admin/logout/` | Public |
| `GET/POST` | `/admin/loan-officers/` | Admin + `create_loan_officer` |
| `GET/PUT/DELETE` | `/admin/loan-officers/<officer_id>/` | Admin + `manage_loan_officers` |
| `GET/POST` | `/admin/admins/` | Super admin |
| `GET/PUT/DELETE` | `/admin/admins/<admin_id>/` | Super admin |
| `PUT` | `/admin/admins/<admin_id>/permissions/` | Super admin |

## Smoke Test Sequence
1. Customer: sign up -> verify email OTP -> login -> refresh token -> logout.
2. Customer: forgot password -> verify reset OTP -> reset password -> login with new password.
3. Customer: setup 2FA -> confirm 2FA -> login requires temp token -> verify 2FA.
4. Customer: `GET /consent/` -> `POST /consent/` -> `PUT /consent/`.
5. Loan officer: login -> if required change password -> logout.
6. Admin: login (2FA bootstrap/verify required) -> access admin user management endpoints.
7. Super admin: manage admin accounts and permissions.

## Common Error Patterns
1. `400 Bad Request`
- Validation failures, unknown preference/permission values, malformed IDs.

2. `401 Unauthorized`
- Invalid credentials, invalid/expired token, revoked token.

3. `403 Forbidden`
- Missing role/permission, deactivated account, admin 2FA-disable attempt, consent enforcement.

4. `404 Not Found`
- User/resource not found under current scope.
