# Accounts Module Documentation and Status

Last updated: 2026-08-09

## Overview

The `accounts` module provides identity, authentication, authorization,
credential recovery, session management, consent, customer account lifecycle,
and privileged user administration for the platform. It supports three account
roles:

- Customer
- Loan officer
- Administrator, including super administrators

The module uses Django REST Framework views with custom JWT authentication and
stores account and security state directly in MongoDB through PyMongo. Redis is
used for shared throttling and related cache-backed controls. Celery handles
asynchronous and scheduled work such as password-reset email delivery, delivery
reconciliation, unverified-account cleanup, and scheduled account deletion.

Detailed request and response examples are maintained in
`docs/ACCOUNTS_TESTING_GUIDE.md`. This document describes the implemented module,
its current API and security status, and the validation still required before a
production deployment.

## Current Status

**Module implementation status: Complete**

**Production deployment status: Ready for production-environment validation**

All Accounts code gaps identified during the production-readiness review have
been addressed. Local automated validation is clean. Deployment approval still
depends on hosted CI, real infrastructure, browser integration, and operational
recovery checks described in **Remaining Gaps and Release Conditions**.

| Area | Status | Summary |
| --- | --- | --- |
| Customer accounts | Implemented | Signup, verification, login, language, lifecycle, export, and recovery are available. |
| Loan-officer accounts | Implemented | Login, profile maintenance, mandatory password change, optional 2FA, sessions, and logout are available. |
| Administrator accounts | Implemented | Mandatory 2FA, profile access, permissioned user management, and super-admin controls are available. |
| Password and OTP security | Implemented | Password policy, atomic OTP use, recovery controls, cooldowns, and delivery reconciliation are enforced. |
| JWT and session security | Implemented | Live account validation, refresh membership, rotation, revocation, blacklisting, and activity tracking are enforced. |
| 2FA | Implemented | TOTP enrollment, verification, replay prevention, backup codes, recovery, audit, and notifications are available. |
| Authorization | Implemented | Role checks, administrator permissions, super-admin rules, ownership, and resource-scope helpers are available. |
| Consent | Implemented | Current consent, append-only history, policy versioning, revocation, audit reporting, and AI enforcement are available. |
| Account lifecycle | Implemented | Suspension, deactivation, email change, export, deletion scheduling, anonymization, unlock, and 2FA recovery are available. |
| Field encryption | Implemented | Versioned Fernet encryption, strict production reads, previous-key support, rotation, and verification are available. |
| Local automated tests | Passing | 899 passed and 14 opt-in integration tests skipped on 2026-08-09. |
| Production environment validation | Pending | Hosted CI, real MongoDB/Redis/Celery, browser cookie/CORS, email, proxy, and recovery validation remain. |

## Module Responsibilities

### Identity and role model

Customer, loan-officer, and administrator identities use separate MongoDB
collections and role-specific login entry points. Protected requests are resolved
to a live account rather than trusting the role embedded in a JWT alone.

The global email-identity policy prevents ambiguous new identities across roles.
Legacy records with the same email in more than one role remain recoverable only
when the caller explicitly supplies the intended role.

### Authentication and credential delivery

`CustomJWTAuthentication` accepts access tokens from either a Bearer header or
the configured HttpOnly access cookie. Authentication checks all of the following
before accepting a token:

- JWT signature, expiry, purpose, and account role
- Live account state and verification requirements
- Account `security_version`
- Active refresh/session membership
- Access-token blacklist state
- Mandatory temporary-password state for protected officer operations

Clients choose one credential transport:

- `body` is the default for API and mobile clients. Successful authentication
  returns `access` and `refresh` in JSON.
- `cookie` is intended for browser clients. Tokens are removed from the JSON body
  and set in HttpOnly cookies.

Customer login, loan-officer login, email verification, refresh, and completed
2FA use the canonical body fields `access` and `refresh`. The former
loan-officer-only `access_token` and `refresh_token` response aliases are no
longer returned.

### Password security

- Passwords are HMAC-SHA256-peppered before bcrypt hashing.
- `SECRET_PEPPER` is mandatory outside development and is required before Django
  management commands execute.
- Django password validators are applied during signup, reset, and password
  change.
- Password changes and resets rotate security state and revoke existing sessions.
- Loan officers created with temporary passwords receive HTTP 423
  `password_change_required` on protected operations until they replace the
  temporary password.
- Recovery responses are normalized to reduce account and role enumeration.

### Email verification, OTP, and password recovery

- Email-verification and reset OTPs are generated with `secrets` and expire.
- Attempt counters and code consumption use atomic MongoDB updates.
- A valid code can be consumed only once, including under concurrent requests.
- Reset completion atomically consumes the OTP while changing the password.
- Reset issuance is limited to one message per minute and five messages per
  account per hour.
- A valid OTP is not replaced during its issuance cooldown.
- Password-reset delivery uses Celery without placing the raw OTP in the broker
  payload. The worker loads it from the encrypted account record.
- Delivery state, attempts, timestamps, next retry, and failure type are stored.
- A scheduled reconciler requeues eligible failed or abandoned deliveries.
- Prometheus counters record password-reset email success and failure.

### JWT refresh, logout, and revocation

- Access and refresh lifetimes are centralized for normal and remembered
  sessions.
- Refresh membership stores SHA-256 token hashes rather than plaintext tokens.
- Every role requires active refresh membership before refresh rotation.
- Rotation issues a new pair, revokes the old refresh token, and preserves the
  logical session ID.
- Blacklist records store hashes and use a TTL index.
- Temporary 2FA tokens cannot be used as normal refresh tokens and are consumed
  after successful verification.
- Customer, loan-officer, and administrator logout require a refresh token.
  Missing refresh credentials return HTTP 400.
- Logout and session termination fail if durable revocation cannot be confirmed;
  they do not report a false success.

Refresh-token input order is:

1. JSON `refresh` or `refresh_token`
2. The configured refresh cookie

The `Authorization` header is not a refresh-token source. It may carry the
optional access token used during logout.

### Sessions and login activity

- Active sessions contain opaque session IDs and refresh-token hashes, never raw
  credentials.
- Login and completed 2FA flows record normalized IP and device metadata.
- Successful and failed credential attempts create login-activity records.
- Authenticated requests update session activity through a bounded heartbeat,
  five minutes by default, instead of writing on every request.
- Refresh preserves the logical session, so rotation is not displayed as a new
  device.
- Customers retain intentional single-device behavior.
- Loan officers and administrators may maintain independent browser sessions.
- A user can revoke one session, all sessions, or all except the current session.
- Active sessions expire after 30 days of inactivity; login activity expires
  after 90 days.

### Two-factor authentication

- TOTP enrollment returns a provisioning URI, QR data URL, and manual secret.
- Voluntary enrollment requires current-password confirmation and expires after
  ten minutes.
- Administrator 2FA is mandatory and cannot be disabled.
- Temporary login tokens preserve remember-me and credential-transport state.
- Final verification rechecks the account's live state and security version.
- Accepted TOTP timesteps are persisted conditionally to prevent same-window
  replay.
- Backup codes are generated securely, stored as hashes, and removed atomically
  after use.
- Disabling 2FA and regenerating backup codes require password confirmation.
- Customer 2FA-loss recovery requires credential verification, OTP verification,
  and an administrator decision.
- Lifecycle changes generate security audit records and in-app notifications.

### Throttling, lockouts, and proxy handling

- Signup, login, OTP, 2FA, password reset, refresh, and contact routes have
  dedicated DRF throttles.
- Public authentication routes combine IP limits with SHA-256-hashed identifier
  or temporary-token limits where possible.
- The current development policy is intentionally `100/hour` for authentication
  throttle classes. This is an accepted test setting, not a production tuning
  recommendation.
- MongoDB `LockoutService` is the authoritative account lockout mechanism.
- Failed-login increments are atomic. The default lock is five failures for 15
  minutes; administrator login uses an explicit 30-minute lock.
- Successful authentication resets lockout state, and authorized administrators
  can unlock customer accounts.
- django-axes observes customer login attempts but does not impose a second
  lockout policy.
- `TRUSTED_PROXY_COUNT` defaults to zero. Forwarded client IP headers are ignored
  until an exact trusted proxy depth is configured.
- Production configuration requires a shared Redis cache so throttles and
  cache-backed security state behave consistently across workers.

### Authorization and privileged administration

The shared access-control utilities provide:

- Account-role checks
- Administrator permission checks
- Super-administrator checks
- Customer ownership checks
- Loan-officer assignment and customer-scope checks

Administrator permissions are validated against the canonical permission list.
The Accounts API supports permissioned customer and loan-officer management and
super-admin-only administrator management.

Privileged changes use allowlisted before/after audit data and conditional
`_id` plus `updated_at` writes. Stale edits return HTTP 409 `stale_update` rather
than overwriting a concurrent change. The system prevents self-demotion or
self-deactivation by a super administrator and serializes mutations that could
remove the last active super administrator. Loan-officer deactivation is blocked
while active work remains assigned; successful deactivation rotates security
state and revokes all sessions.

### Consent and policy lifecycle

- Consent is customer-owned.
- The `consents` collection provides the current state.
- The append-only `consent_events` collection is authoritative history.
- Events include a stable ID, revision, before/after state, policy identifier,
  policy version, content digest, timestamp, and request IP.
- A policy version or content change requires renewed consent.
- AI features fail closed unless current-version data and AI consent are active.
- Revocation is immediately authoritative and does not depend on Redis, Celery,
  or blockchain availability.
- Blockchain dispatch is a best-effort secondary audit mirror after the local
  event is durable.
- Administrators can retrieve a current-state consent report.

### Customer lifecycle and recovery

- Customers can request and confirm a verified email change.
- Customers can export account, consent, session, login-activity, audit, and
  notification data owned by the Accounts domain.
- Customers can request deletion, which enters `pending_deletion`, schedules the
  retention deadline, and revokes sessions.
- A deletion request can be cancelled with valid credentials before finalization.
- Authorized administrators can suspend, deactivate, restore, unlock, and finalize
  customer account deletion.
- Finalization anonymizes Accounts-owned customer identity fields.
- Security-sensitive state changes rotate `security_version`, revoke sessions,
  and generate security events.

Cross-domain customer data is not owned entirely by this module. Profile,
document, loan, blockchain, and other retention behavior must be coordinated by
their respective domain policies. In particular, profile-data deletion and
anonymization remain tracked in the Profiles production-readiness review.

### Audit, notifications, and email

- Password, 2FA, session, recovery, account-state, and privileged administration
  changes generate security or audit records.
- Sensitive audit details use allowlists and do not store passwords, tokens,
  OTPs, or complete submitted account payloads.
- Security events can produce in-app notifications.
- Support-contact input is validated and HTML is stripped before email delivery.
- Unverified customer cleanup and scheduled deletion finalization are available
  as periodic Celery tasks.

### Field encryption and key lifecycle

Account-model-declared sensitive fields—including phone numbers, OTPs,
verification values, and 2FA secrets—use versioned Fernet ciphertext.

- Production startup rejects a missing or invalid primary/previous key.
- Strict decryption is enabled by default outside development.
- New ciphertext contains a non-secret key identifier.
- Previous keys allow existing values to remain readable during rotation.
- New writes always use the primary key.
- Corrupt or unavailable-key ciphertext raises `FieldDecryptionError` in strict
  mode instead of being returned as application data.
- `encrypt_sensitive_fields` derives its collection/field map from model
  declarations, is dry-run by default, requires `--apply` for writes, supports
  `--rotate`, and provides `--verify`.

The supported rotation procedure is:

1. Configure the new primary key and retain the former key in
   `FIELD_ENCRYPTION_PREVIOUS_KEYS`.
2. Review `encrypt_sensitive_fields --rotate` dry-run results.
3. Run `encrypt_sensitive_fields --rotate --apply` through the approved
   state-changing operations process.
4. Run `encrypt_sensitive_fields --verify`.
5. Keep both keys if verification or concurrency conflicts remain. Remove the
   former key only after verification, backup review, and the rollback window.

## API Status

All 48 registered Accounts URL patterns are implemented. The API base path is
`/api/auth/`.

### Public authentication and support

| Method and route | Access | Status | Purpose |
| --- | --- | --- | --- |
| `GET /csrf-token/` | Public | Implemented | Issues the CSRF value required by cookie-mode clients. |
| `POST /signup/` | Public | Implemented | Creates an unverified customer account. |
| `POST /verify-email/` | Public | Implemented | Atomically verifies email and completes initial authentication. |
| `POST /resend-otp/` | Public | Implemented | Reissues verification OTP subject to cooldown and throttling. |
| `POST /login/` | Public | Implemented | Customer password login and optional 2FA challenge. |
| `POST /loan-officer/login/` | Public | Implemented | Loan-officer login, temporary-password state, and optional 2FA. |
| `POST /admin/login/` | Public | Implemented | Administrator login with mandatory 2FA setup or challenge. |
| `POST /refresh-token/` | Refresh credential | Implemented | Rotates an active refresh credential and preserves the session. |
| `POST /forgot-password/` | Public | Implemented | Starts generic, role-aware password recovery. |
| `POST /verify-reset-otp/` | Public | Implemented | Verifies the active recovery code. |
| `POST /reset-password/` | Public | Implemented | Atomically consumes the code, changes the password, and revokes sessions. |
| `POST /contact/` | Public | Implemented | Validates and sends a support-contact message. |

### Authenticated account and security operations

| Method and route | Access | Status | Purpose |
| --- | --- | --- | --- |
| `POST /logout/` | Customer refresh credential | Implemented | Revokes customer refresh/session membership. |
| `POST /loan-officer/logout/` | Officer refresh credential | Implemented | Revokes loan-officer refresh/session membership. |
| `POST /admin/logout/` | Admin refresh credential | Implemented | Revokes administrator refresh/session membership. |
| `POST /change-password/` | Any authenticated role | Implemented | Changes password and revokes existing sessions. |
| `POST /2fa/setup/` | Any authenticated role | Implemented | Starts password-confirmed TOTP enrollment. |
| `POST /2fa/confirm/` | Any authenticated role | Implemented | Confirms enrollment and returns backup codes. |
| `POST /2fa/verify/` | Temporary 2FA credential | Implemented | Completes login with TOTP or a backup code. |
| `POST /2fa/disable/` | Customer or officer | Implemented | Disables 2FA after password confirmation; admins are denied. |
| `POST /2fa/backup-codes/` | Any authenticated role | Implemented | Regenerates backup codes after password confirmation. |
| `GET /2fa/status/` | Any authenticated role | Implemented | Returns enrollment and backup-code status. |
| `GET, DELETE /sessions/` | Any authenticated role | Implemented | Lists and revokes active sessions. |
| `GET /login-activity/` | Any authenticated role | Implemented | Returns the latest 20 login-activity records. |

### Customer self-service

| Method and route | Status | Purpose |
| --- | --- | --- |
| `GET, POST, PUT /consent/` | Implemented | Reads, records, or changes current consent. |
| `GET /consent/history/` | Implemented | Returns append-only customer consent history. |
| `PATCH /language/` | Implemented | Updates `en` or `tl` language preference. |
| `POST /email-change/request/` | Implemented | Verifies password and sends an OTP to the proposed address. |
| `POST /email-change/confirm/` | Implemented | Confirms the address and revokes old sessions. |
| `GET /account/export/` | Implemented | Returns Accounts-owned customer data. |
| `POST /account/deletion-request/` | Implemented | Schedules deletion and revokes sessions. |
| `POST /account/deletion-cancel/` | Implemented | Cancels a pending request with valid credentials. |
| `POST /2fa/recovery/request/` | Implemented | Starts credentialed customer 2FA-loss recovery. |
| `POST /2fa/recovery/verify/` | Implemented | Verifies recovery OTP before administrator review. |

### Staff profile and administration

| Method and route | Required role or permission | Status |
| --- | --- | --- |
| `GET, PUT /loan-officer/me/` | Loan officer | Implemented |
| `GET, PUT /admin/me/` | Administrator | Implemented |
| `GET /consent/audit/` | Administrator | Implemented |
| `GET, POST /admin/loan-officers/` | `create_loan_officer` | Implemented |
| `GET, PUT, DELETE /admin/loan-officers/<officer_id>/` | `manage_loan_officers` | Implemented |
| `GET /admin/customers/` | `manage_users` | Implemented |
| `GET, PATCH /admin/customers/<customer_id>/` | `manage_users` | Implemented |
| `POST /admin/customers/<customer_id>/unlock/` | `manage_users` | Implemented |
| `POST /admin/customers/<customer_id>/deletion/finalize/` | `manage_users` | Implemented |
| `GET /admin/customers/2fa-recovery/` | `manage_users` | Implemented |
| `POST /admin/customers/<customer_id>/2fa-recovery/` | `manage_users` | Implemented |
| `GET, POST /admin/admins/` | Super administrator | Implemented |
| `GET, PUT, DELETE /admin/admins/<admin_id>/` | Super administrator | Implemented |
| `PUT /admin/admins/<admin_id>/permissions/` | Super administrator | Implemented |

## Cookie, CSRF, and Browser Contract

Cookie transport is opt-in through JSON `token_transport: "cookie"` or the
`X-Token-Transport: cookie` header. Merely enabling browser credentials does not
select cookie delivery.

- The access cookie defaults to `/api/`.
- The refresh cookie defaults to `/api/auth/`.
- Cookie-authenticated unsafe requests require matching `csrftoken` and
  `X-CSRFToken` values.
- Missing or mismatched values return HTTP 403.
- Pure Bearer requests do not require the cookie-CSRF pair.
- Refresh and logout remain CSRF-protected when a refresh cookie participates.
- Production must enable secure cookies and HTTPS.
- Cross-site browser deployments require reviewed `SameSite=None`, Secure,
  credentialed CORS, and trusted CSRF origins.

## Persistence and Indexes

Account, refresh membership, blacklist, session, login activity, lockout,
password-reset delivery, consent-current-state, and consent-history data are
stored in MongoDB. Index bootstrap is wired through `init_db.py`; this project
does not use Django ORM migrations for these collections.

Declared operational indexes include:

- Unique account identity indexes
- Unique and compound consent indexes
- Refresh membership and token blacklist lookup indexes
- Blacklist expiration TTL
- Active-session 30-day inactivity TTL
- Login-activity 90-day TTL
- Password-reset delivery reconciliation indexes

The approved legacy-session scrub invalidated 91 records that could contain
plaintext refresh credentials. Its verification found no remaining plaintext
session credentials.

## Automated Validation Status

Local validation on 2026-08-09 used `config.settings_test`, mongomock, in-memory
cache/channel layers, eager Celery, local email, and disabled blockchain
integration.

- Full suite: **913 collected, 899 passed, 14 skipped**
- Focused Accounts API tests after token-contract changes: **24 passed**
- Focused Profiles suite after Stage 2: **77 passed**
- Changed Accounts view files and the new Profiles characterization module pass
  Ruff.
- The 14 skips are opt-in external/integration tests, including five real-Mongo
  tests that require an explicit `REAL_MONGO_TEST_URI` and nine blockchain
  integration tests.
- One third-party `websockets.legacy` deprecation warning remains; it is not an
  Accounts test failure.

The real-Mongo module includes concurrency and index tests and deliberately skips
unless an isolated non-production database URI is provided.

## Remaining Gaps and Release Conditions

### Required production-environment validation

These are release-evidence gaps, not missing Accounts API implementations:

- Confirm the hosted CI workflow passes from a clean dependency environment.
- Run the opt-in real-Mongo index and concurrency suite against an isolated
  MongoDB service.
- Validate Redis-backed throttles and security state across multiple workers.
- Validate Celery delivery, retry, reconciliation, and scheduled jobs with the
  deployment broker and workers.
- Verify SMTP delivery, bounce/failure monitoring, and password-reset recovery.
- Test body and cookie token transports in real customer mobile and staff web
  clients.
- Test browser CSRF, CORS, cookie path, SameSite, Secure, HTTPS, and logout
  behavior using the deployed frontend origins.
- Validate trusted-proxy IP extraction behind the actual proxy chain.
- Rehearse field-encryption rotation, verification, rollback, backup, and key
  removal in staging.
- Exercise account suspension, password reset, session revocation, 2FA recovery,
  deletion scheduling, and operational recovery in staging.
- Confirm production MongoDB indexes and TTL behavior after the approved index
  bootstrap process.

### Cross-module release dependency

Accounts-owned deletion and anonymization are implemented, and Profiles Stage 2
now deletes personal, business, and alternative profile records with durable,
retryable cleanup state. The overall platform must still apply approved retention
or anonymization policies to Documents, Loans, blockchain records, and other
domains before account deletion can be described as system-wide erasure.

### Maintainability notes

These items are improvements rather than current Accounts production blockers:

- `accounts/views/admin_views.py` remains a large, multi-responsibility module.
- Authentication, activity, and audit orchestration still contains some
  role-specific duplication.
- `BaseAuthView` is not consistently used by the main login views.
- Some broad model saves could be replaced with narrower atomic field updates.
- Password-reset email has durable asynchronous delivery, but other sensitive
  account-email workflows do not yet have the same delivery-state model.
- Import-time MongoDB client construction requires test settings to be selected
  before base settings initialize.
- The current environment may install a newer Django major than the architecture
  target; deployment must use the reviewed lock files and supported runtime.

## Client Notes

- Customer mobile and API clients should read body-mode credentials only from
  `access` and `refresh`.
- The loan-officer web client must use `access` and `refresh`; legacy
  `access_token` and `refresh_token` login response fields were removed.
- Staff web clients must send a refresh credential on logout. An empty logout
  request now returns HTTP 400.
- Browser clients must explicitly select cookie transport, fetch a CSRF token,
  retain cookies, and send `X-CSRFToken` on unsafe cookie-authenticated requests.
- A refresh token belongs in JSON or the refresh cookie, never in the Bearer
  header.
- Customer, officer, and admin interfaces should handle immediate HTTP 401 after
  password/security/account-state revocation and HTTP 423 for an officer who must
  change a temporary password.
- Administrator interfaces must respect permission-specific routes and HTTP 409
  responses for stale updates, active officer workload, last-super-admin
  protection, and deletion timing.

## Operational Notes

- Authentication throttles intentionally remain `100/hour` during development.
  Review and change environment-specific rates before production if the accepted
  deployment policy requires stricter limits.
- `ACCOUNT_DELETION_RETENTION_DAYS` defaults to 30 days.
- Production requires shared Redis and valid field-encryption configuration.
- State-changing commands such as index bootstrap, session scrubbing, encryption
  rotation, backup, restore, and deletion finalization require the approved
  operational process, backups, dry-run review where supported, and staging
  validation.
- Do not point real-Mongo tests, cleanup jobs, or management commands at a
  production database.

## Review Boundaries

This status is based on source review and local automated validation. It is not a
live penetration test, production data audit, fairness review, or deployment
approval. No production MongoDB, Redis, Celery, email, proxy, browser, blockchain,
backup, log, uploaded-data, wallet, or credential contents were inspected.

## Related Documentation

- `docs/ACCOUNTS_TESTING_GUIDE.md` — endpoint fields, response contracts, smoke
  tests, negative cases, and revocation checks
- `.env.example` — configuration variable reference
- `docs/feats/DEPLOYMENT_AND_OPERATIONS_GUIDE.md` — deployment and operational
  procedures
- `docs/PROFILES_PRODUCTION_READINESS_REVIEW.md` — profile security, retention,
  and production-readiness work that interacts with account lifecycle
