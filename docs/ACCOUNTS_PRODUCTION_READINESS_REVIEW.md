# Accounts Production Readiness Review

Last updated: 2026-08-04

Scope: `accounts/` plus the Django/DRF authentication settings, middleware,
MongoDB collections, Redis/Celery paths, audit logging, email delivery, consent
consumers, and domain authorization helpers used by accounts.

## Purpose and Status Definitions

This document is the source-of-truth implementation checklist for authentication,
account security, authorization, session management, consent, and privileged user
administration. It records verified behavior, production risks, and remediation
order.

- **Complete**: implemented and covered by relevant automated tests.
- **Partial**: useful implementation exists, but important behavior is missing or
  unsafe.
- **Not implemented**: no production implementation was found.
- **Blocked for production**: implemented behavior has a security, correctness,
  revocation, privacy, or durability problem that must be fixed before release.

Checklist convention:

- `[x]` with ~~strikethrough~~ means implemented and verified.
- `[ ]` means not implemented, not deployed, or still requiring validation.
- A **PARTIAL** stage contains both completed and unchecked work.

Passing unit tests alone does not make an item production-ready. The project uses
PyMongo directly, and mongomock does not reproduce every real MongoDB constraint,
atomic-update, index, TTL, concurrency, or data-type behavior.

## Executive Summary

The accounts module has strong foundations but is **not production-ready**.
Customer signup and verification, three-role authentication, password recovery,
JWT refresh membership, token blacklisting, lockouts, TOTP 2FA, admin permissions,
ABAC helpers, consent, sessions, activity tracking, email, and audit integrations
all exist. Role and resource-scope checks in the domain applications are generally
strong.

Stages 1 and 2 removed raw refresh-token persistence from new session records,
bound access and refresh JWTs to revocable session membership, added live account
state/security-version enforcement, and centralized mandatory first-password
change enforcement. Stage 3 now fails closed for cookie-backed unsafe requests
and separates cookie and response-body credential delivery. Stage 10 documentation
has been rechecked against the current views, token helpers, middleware, routes,
and account tests. The current `100/hour` authentication throttle policy is an
explicitly accepted development/deployment policy and is no longer tracked as an
unfinished implementation item. Production release remains blocked by unresolved
API token-name standardization and the validation/CI work recorded below.

Current remediation status:

- [x] **Stage 1 — Session credential safety and revocation**
- [x] **Stage 2 — Temporary-password and live account-state enforcement**
- [x] **Stage 3 — Cookie authentication and CSRF integrity**
- [x] **Stage 4 — Brute-force, OTP, and concurrency hardening**
- [x] **Stage 5 — 2FA lifecycle integrity**
- [x] **Stage 6 — Privileged administration and audit coverage**
- [x] **Stage 7 — Consent history and policy lifecycle**
- [x] **Stage 8 — Account lifecycle and recovery capabilities**
- [ ] Stage 9 — Test isolation, dependency reproducibility, and CI
- [ ] Stage 10 — API contract and documentation alignment

## Verified Complete

### API and account coverage

- Customer signup, email OTP verification, OTP resend, login, refresh, logout,
  language update, password reset, password change, 2FA, consent, session, and
  login-activity endpoints are implemented.
- Loan-officer login, logout, profile retrieval/update, temporary-password state,
  password recovery, and optional 2FA are implemented.
- Administrator login, logout, profile retrieval/update, mandatory 2FA bootstrap,
  officer management, administrator management, and permission management are
  implemented.
- The public support-contact endpoint validates input, strips HTML from email
  content, and uses centralized email delivery.
- `CustomJWTAuthentication` supports Bearer access tokens and HttpOnly access
  cookies and checks the custom access-token blacklist.

### Password and OTP foundations

- Passwords use HMAC-SHA256 with an application pepper before bcrypt hashing.
- The pepper is fail-closed outside DEBUG, and `manage.py` also requires
  `SECRET_PEPPER` before management-command execution.
- Django password validators are applied to signup, reset, and change-password
  serializers.
- Verification and reset OTPs use `secrets`, have expiration timestamps, and have
  per-account wrong-attempt counters and cooldown checks.
- OTP/reset error messages are generally normalized to reduce direct account
  enumeration.
- Unverified customer cleanup is implemented as a periodic Celery task.

### Token foundations

- Access and refresh lifetimes are centralized for signup, remembered, and
  non-remembered sessions.
- Refresh tokens are represented by SHA-256 hashes in `RefreshTokenEntry`.
- Customer, officer, and administrator refresh tokens require active membership
  in `RefreshTokenEntry` before rotation.
- Refresh rotation creates a new token pair and revokes the old refresh token.
- Blacklist records store token hashes and have an expiration TTL index.
- Temporary 2FA tokens are short-lived, are rejected by the normal refresh flow,
  and are blacklisted after successful use.

### 2FA foundations

- TOTP setup supports provisioning URIs, a locally generated QR data URL, and
  manual secret entry.
- Backup codes are generated with `secrets`, stored as hashes, and removed after
  successful use.
- Disabling 2FA and regenerating backup codes require password verification.
- Administrator login requires 2FA enrollment and verification; administrator
  2FA disablement is blocked.

### Authorization foundations

- Central role, administrator-permission, super-administrator, ownership, officer
  assignment, and customer-scope helpers exist in
  `accounts/utils/access_control.py`.
- Privileged domain views generally load the current officer/admin record and
  reject deactivated accounts.
- Loan, document, notification, profile, analytics, and AI views use the shared
  access-control helpers rather than trusting a client-supplied role alone.
- Administrator permissions are validated against a canonical list before they
  are persisted.

### Consent foundations

- Current data and AI consent state is stored per user and role with a unique
  compound index.
- Consent endpoints support status retrieval, initial recording, and preference
  updates.
- AI chat, qualification, and document-analysis paths check customer AI consent.
- AI consent revocation dispatches cache invalidation.
- Consent changes can be sent to the blockchain audit path, and administrators
  have a current-state consent report.

### Persistence and production settings

- Account, token, consent, active-session, and login-activity index creation is
  included in `init_db.py`.
- Email, phone, OTP, verification-token, and 2FA-secret encryption coverage exists
  for the declared sensitive string fields.
- Production startup rejects a missing or invalid `FIELD_ENCRYPTION_KEY`.
- Secure-cookie, HTTPS, HSTS, CORS, CSRF, security-header, and NoSQL payload-guard
  settings exist.

## Production Blockers and Resolved Critical Findings

### 1. Raw refresh tokens are stored and exposed

**Status: Resolved in Stage 1 (`1ff3555` plus verified operational cleanup)**

New `ActiveSession` records contain an opaque session ID and refresh-token hash,
while public serialization omits all credential/hash material. Access and refresh
JWTs share the session ID and revocation operates on durable membership. Dedicated
tests prove new MongoDB session documents and API serialization contain no raw
refresh token.

On 2026-08-02, the approved `scrub_legacy_sessions --apply` procedure invalidated
and removed `session_token` from all 91 legacy records in the configured MongoDB.
A post-operation dry run reported zero remaining records, and all 15 focused
session/security/authentication tests passed.

### 2. Temporary-password enforcement is not global

**Status: Resolved in Stage 2 (`1ff3555`)**

`CustomJWTAuthentication` now reloads live account state and enforces
`must_change_password` before every protected domain view. Only password change,
logout, and session-exit workflows are allowed, using the established HTTP 423
`password_change_required` contract. The state survives 2FA, and newly created
administrators also receive mandatory first-password-change state.

### 3. Cookie-authenticated unsafe requests can bypass custom CSRF enforcement

**Status: Resolved in Stage 3**

`CSRFSameSiteTokenMiddleware` now detects access/refresh auth cookies and requires
both the CSRF cookie and matching `X-CSRFToken` header on unsafe API requests. It
fails closed when either value is absent. Pure Bearer requests remain exempt even
if an unrelated access cookie exists; refresh/logout paths still require CSRF
when a refresh cookie can participate.

Eleven Stage 3 tests cover absent cookie/header, mismatch, valid double-submit,
Bearer exemption, refresh-cookie behavior, safe methods, cookie flags/paths,
body-only delivery, cookie-only delivery, and invalid transport selection.

### 4. Password and account-state changes do not revoke all sessions

**Status: Resolved in Stage 1–2 (`1ff3555`)**

Password reset/change and privileged-account deactivation revoke refresh
membership and active sessions. Access authentication validates session identity,
live active/deleted/verified state, and account `security_version` on every
request, immediately invalidating older access tokens.

### 5. Logout can report success without confirmed revocation

**Status: Resolved in Stage 1 (`1ff3555`)**

Blacklist insertion and session termination are idempotent, individual blacklist
results are checked, and logout revokes durable refresh membership by session ID.
Failed blacklist persistence returns an error rather than silently reporting a
successful revocation.

## Partial Implementations

### Authentication throttling and lockouts

**Status: Complete for the accepted policy**

Dedicated DRF throttle classes are attached to signup, customer/officer/admin
login, OTP verification/resend, 2FA, password reset, refresh, and support contact.
Public authentication paths combine IP limits with normalized, SHA-256-hashed
identifier or temporary-token limits where a stable request subject exists.

All authentication throttle classes intentionally remain at `100/hour`. This is
an accepted project policy for the current development and initial deployment
configuration, not an unimplemented placeholder. Lower environment-specific
values, exponential cooldowns, and alerting thresholds remain optional operational
tuning rather than completion blockers.

MongoDB `LockoutService` is authoritative for customer, loan-officer, and
administrator account lockouts. Failed-attempt increments are atomic, the default
policy locks after five failures for 15 minutes, administrators use an explicit
30-minute lock, successful authentication resets state, and administrator unlock
is supported. django-axes remains an observer for customer-login events and does
not impose a second lockout because `AXES_LOCK_OUT_AT_FAILURE=False`.

`TRUSTED_PROXY_COUNT` defaults to zero, so client-supplied forwarding headers are
ignored unless an exact trusted proxy depth is configured. Invalid or negative
proxy counts now fail settings validation. Production (`DEBUG=False`) also fails
closed unless shared Redis caching is enabled and an explicit `REDIS_URL` is
configured, preventing per-worker throttle and axes state. The cache does not
assume that an arbitrary Celery broker URL is Redis-compatible.

Regression tests pin the accepted rate, compound endpoint throttle wiring,
authoritative MongoDB lockout policy, untrusted-forwarding behavior, and configured
trusted-proxy depth.

### Atomic attempt and one-time-code enforcement

**Status: Partial / concurrency hardening required**

Login, OTP, reset, and backup-code state changes now use conditional MongoDB
updates with `$inc`, `$set`, and `$pull`. Accepted TOTP timesteps are also stored
through a conditional update, preventing same-window replay.

Remaining work:

- Add real-Mongo concurrency tests; mongomock does not prove these semantics.

### Password-reset issuance controls

**Status: Complete for request-abuse controls / delivery durability remains a
maintainability gap**

Wrong reset-OTP attempts and cooldowns are implemented. Reset initiation enforces
one message per minute and five messages per account per hour without replacing a
still-valid OTP during the cooldown. Public responses remain generic, and reset
completion records a security event.

Moving security email delivery to a durable outbox/task and adding provider-level
delivery metrics remain cross-cutting email reliability improvements, not missing
password-reset issuance controls.

### 2FA lifecycle

**Status: Complete**

Voluntary enrollment now requires password confirmation and expires after ten
minutes. Temporary tokens preserve session type and transport, final verification
rechecks live account/security state, and successful login records consistent
session and activity metadata. Backup codes and TOTP timesteps are consumed
atomically, while every 2FA lifecycle change produces an audit record and in-app
security notification.

### Session and activity tracking

**Status: Partial / session-policy and activity semantics remain**

Customer non-2FA login creates `LoginActivity` and `ActiveSession`. New session
records store an opaque `session_id` and a refresh-token hash; public session
serialization omits credential material. Refresh rotates the refresh membership
and logout deactivates the matching session.

Coverage is inconsistent:

- Email-verification token issuance does not create a session record.
- New token issuance invalidates refresh membership but does not consistently
  deactivate old `ActiveSession` rows.
- `last_active` is not updated during normal authenticated use.
- The token layer describes single-device enforcement while the API exposes a
  multi-session device-management interface.

The product must choose and document one policy:

- **Single device**: keep one authoritative session and simplify the UI/model.
- **Multiple devices**: retain independent refresh memberships and revoke by
  stable session ID.

### Consent history and revocation

**Status: Implemented**

The append-only `consent_events` collection is now authoritative. Each decision
has a stable event ID, per-customer revision, before state, resulting state,
policy identifier/version/content digest, timestamp, and request IP. The
`consents` collection is maintained as an atomic current-state projection, while
history remains available when blockchain synchronization is disabled or fails.

Consent ownership is explicitly customer-only. Grant requests must identify the
currently deployed policy (`2026-08-01`); a version or content change can update
the configured policy manifest and immediately requires re-consent. AI entry
points fail closed unless both data and AI consent are active under that current
version. Revocation is authoritative immediately and does not depend on Redis or
Celery cache invalidation. Blockchain dispatch remains a best-effort secondary
audit mirror after the local event is durable.

### Privileged administration and auditing

**Status: Implemented**

Administrator creation, profile/deactivation, privilege, and super-admin changes
now create dedicated audit entries with allowlisted before/after state. Officer
updates and deactivation have the same audit treatment. Password changes, 2FA
changes, and session termination create account-security audit records and
in-app notifications.

Super administrators cannot demote or deactivate themselves. Mutations that can
remove another active super administrator are serialized through a short MongoDB
lease and verify that another active super administrator remains. Admin/officer
updates use a conditional `_id` + `updated_at` MongoDB update, so a concurrent
write returns `409 stale_update` rather than being overwritten.

Officer deactivation increments the security version and revokes every session.
It fails with `409 active_officer_workload` while submitted, under-review,
approved, or disbursed applications remain assigned; those applications must be
reassigned through the existing loan workflow before deactivation.

### Field encryption and key lifecycle

**Status: Partial**

Production startup correctly requires a valid field-encryption key. DEBUG mode
allows plaintext pass-through by design. Additional production-hardening work is
still needed:

- Legacy `session_token` input is converted to a hash for compatibility, but
  legacy-record cleanup and the long-term session metadata retention policy still
  require operational validation.
- Session IP/device information, consent IPs, and activity metadata remain
  plaintext operational data and require an explicit retention/access policy.
- Invalid encrypted values are returned unchanged rather than raising a clear
  corruption/key-mismatch signal.
- No key-version or key-rotation design is present.
- The encryption migration command does not by itself provide online key
  rotation, rollback, or rotation verification.

## Stage 8 Implementation Status

### Customer lifecycle administration

**Status: Implemented and covered by focused regression tests**

- `manage_users` now protects customer list/detail/state, lockout-unlock,
  retention-finalization, and 2FA-recovery administration endpoints. Mutations
  write audit records and security notifications.
- Customer state transitions are persisted as active, suspended, or deactivated,
  increment security version on change, revoke sessions, and reset lockout state
  when an account is restored.
- Email changes require the current password, deliver an OTP to the new address,
  consume it atomically, enforce the global availability policy, and revoke
  existing sessions after confirmation.
- Customer export includes account, consent, session, login-activity, audit, and
  in-app notification records without credential hashes.
- Deletion uses a pending-deletion state, configurable retention period,
  credentialed cancellation, scheduled finalization, anonymization, and session
  revocation. Admin finalization cannot bypass the retention date.

### Recovery and security operations

**Status: Implemented and covered by focused regression tests**

- 2FA-loss recovery requires the account password, a short-lived email OTP,
  per-account issuance/attempt limits, and an explicit administrator decision.
- Existing session management supports single-session, revoke-all, and
  revoke-all-except-current operations.
- Security events cover new-device sign-in, password changes/resets, email
  changes, 2FA changes, customer lifecycle changes, privilege changes, and
  session termination. Notifications remain best-effort secondary delivery.
- A central authentication-risk or suspicious-session scoring service remains
  outside Stage 8.

### Global identity policy

**Status: Implemented with an explicit-role fallback for legacy ambiguity**

Customer, officer, and administrator accounts live in separate collections.
Normal account creation and verified email changes reject an email already used
by another role. If legacy data still contains the same email in more than one
collection, password recovery requires an explicit role and never selects a
role by search order.

MongoDB unique email indexes are case-sensitive by default. Application-level
normalization handles normal writes, but legacy/import/script writes can still
produce case variants unless normalized storage or index collation is enforced.

## API Contract and Documentation Status

### Refresh and logout token transport

The verified refresh-token input order is:

1. JSON `refresh` or `refresh_token`.
2. The configured refresh cookie (`refresh_token` by default).

The refresh view does not read a refresh token from the `Authorization` header.
The header is an access-token source for protected requests and for the optional
access token used by logout. Customer logout requires a refresh token from JSON
or the refresh cookie and accepts an optional access token from JSON `access`, the
Bearer header, or the access cookie. Loan-officer and administrator logout use
the same sources but currently do not reject a request when both tokens are absent;
clients should still send the refresh token so revocation is real and auditable.

### Token delivery and cookie-CSRF behavior

Credential delivery is selected with JSON `token_transport` or the
`X-Token-Transport` header:

- `body` is the default for explicit API clients. Tokens remain in JSON and auth
  cookies are not set.
- `cookie` is for browser clients. Tokens are removed from JSON and delivered in
  HttpOnly access and refresh cookies.
- The access cookie defaults to `/api/`; the refresh cookie defaults to
  `/api/auth/`. `AUTH_ACCESS_COOKIE_PATH` and `AUTH_REFRESH_COOKIE_PATH` may
  override these paths.
- `AUTH_COOKIE_SECURE` must be enabled outside local development. SameSite defaults
  to `Lax`; a cross-site deployment needs reviewed `None` + Secure, credentialed
  CORS, trusted CSRF origins, and HTTPS settings.

Before using cookie authentication, call `GET /api/auth/csrf-token/`. The response
returns `data.csrf_token` and sets the `csrftoken` cookie. For every unsafe API
request authenticated by an access or refresh cookie, send the same value in
`X-CSRFToken`. Missing or mismatched values return `403`. A pure Bearer request
does not need this CSRF pair, except refresh/logout paths remain CSRF-protected
when a refresh cookie is present.

### Token response field names

The implementation is not fully standardized yet:

- Customer login, email verification, refresh, and 2FA completion use
  `access` and `refresh` in body mode.
- Loan-officer login uses `access_token` and `refresh_token` in body mode.
- Admin login always starts or continues 2FA; admin 2FA completion uses `access`
  and `refresh`.
- Cookie mode removes all four token fields from JSON.

The underlying token helper consistently returns `access` and `refresh`, but
changing the loan-officer public aliases requires coordinated client changes.
This remains an open Stage 10 contract item rather than being falsely marked
complete by documentation alone.

### Endpoint roles and profile updates

- `PUT /api/auth/loan-officer/me/` is implemented. Only a loan officer may update
  `first_name`, `last_name`, and `phone`; department and employee ID are returned
  as read-only profile data. `must_change_password` blocks this protected view
  with HTTP 423 until `POST /api/auth/change-password/` succeeds.
- `PUT /api/auth/admin/me/` is implemented. An authenticated administrator,
  including a super administrator, may update `first_name` and `last_name` only.
  Username, email, permissions, and super-admin state use separate rules.
- `POST /api/auth/change-password/` accepts authenticated customer, loan officer,
  and administrator accounts. Password reset remains public and uses the optional
  explicit `role` when legacy email ambiguity exists.
- 2FA setup, confirmation, status, and backup-code regeneration are authenticated
  account operations for supported account types; administrator 2FA cannot be
  disabled. Administrator first-login setup is completed through the admin login
  and 2FA verification flow.
- Consent, language, email-change, export, deletion, and recovery self-service
  routes are customer-only where their views explicitly require a customer.
  Active-session and login-activity views currently accept any authenticated role.

## Scalability and Maintainability Gaps

- `accounts/views/admin_views.py` is a very large multi-responsibility module.
- Authentication, active-state, session, lockout, and audit behavior is duplicated
  across customer, officer, administrator, and 2FA login paths.
- `BaseAuthView` exists but the main authentication views generally do not use it.
- Some model saves replace broad document state, increasing lost-update risk under
  concurrent requests.
- Sensitive email delivery is synchronous and lacks a durable outbox/retry status.
- Import-time MongoDB client creation makes test startup depend on external DNS or
  network state unless `MONGODB_URI` is overridden before settings import.
- Dependency lower bounds without an upper bound or lock file allow major
  framework/tool-version drift. The reviewed environment installed Django 6 even
  though the project header and architecture target Django 4.2.
- Security-sensitive behavior remains distributed across several services, but
  responsibility is defined: MongoDB `LockoutService` owns account lockouts,
  django-axes observes customer-login attempts, DRF/Redis owns request throttles,
  and MongoDB refresh membership/blacklists/ActiveSession own token and session
  revocation.

## Test Status and Coverage Gaps

Validation performed on 2026-08-04 used `config.settings_test` with
`MONGODB_URI` explicitly disabled. This kept account test collection isolated
from external MongoDB, Redis, SMTP, and blockchain services.

Focused account validation:

- 45 focused account/auth/security tests passed, including cookie-CSRF,
  session, 2FA, privileged-administration, lifecycle, and role-auth tests.
- The real-Mongo tests were skipped because `REAL_MONGO_TEST_URI` was not set.

Full-suite validation:

- 866 tests collected.
- 851 passed and 12 skipped.
- Two blockchain client tests errored while creating pytest temporary paths, and
  one Prometheus command test failed while creating a temporary flag file; all
  three were Windows temporary-directory permission failures outside accounts.

Current validation gaps:

- Authentication throttle values remain at the explicitly accepted `100/hour`
  policy and are covered by a regression test.
- Real-Mongo concurrency and hosted CI evidence remain pending in this run.
- Real browser cookie/CORS behavior, multi-worker rate limits, and operational
  recovery still need staging validation.
- Public token field names remain inconsistent between customer/2FA and
  loan-officer login, and officer/admin logout still accepts an empty credential
  set.
- Session `last_active` updates and the single-device versus multi-device policy
  remain product decisions.

## Remediation Plan

### Stage 1 — Session credential safety and revocation

- [x] ~~Remove refresh tokens from `ActiveSession.to_dict()` and API responses.~~
- [x] ~~Replace plaintext session tokens with session IDs/JTIs or hashes.~~
- [x] ~~Add session identity to access and refresh JWTs.~~
- [x] ~~Make session termination and logout idempotently revoke membership.~~
- [x] ~~Revoke all sessions after password reset and account deactivation.~~
- [x] ~~Add revoke-all and revoke-all-except-current workflows.~~
- [x] ~~Migrate/invalidate legacy plaintext session records through an approved
  operational procedure.~~

Implementation note (commit `1ff3555`): new sessions persist only opaque session
IDs and SHA-256 refresh-token hashes. Every protected access token is checked
against live account state, security version, and active refresh membership. The
`scrub_legacy_sessions` management command reports affected records by default.
Its approved `--apply` run scrubbed and invalidated 91 records; the verification
run reported zero remaining plaintext session records.

### Stage 2 — Temporary-password and live account-state enforcement

- [x] ~~Enforce officer `must_change_password` in the centralized authorization
  path used by every domain.~~
- [x] ~~Preserve the flag through 2FA login responses.~~
- [x] ~~Replace administrator temporary passwords with expiring invitations or
  add mandatory first-password change.~~
- [x] ~~Add account `security_version` or equivalent centralized revocation
  state.~~
- [x] ~~Enforce active/deleted/verified/security-version state for every access
  token.~~

Verification note: centralized authentication returns the established HTTP 423
`password_change_required` contract outside password/session exit workflows.
Focused account/auth validation now passes 64 tests, including the dedicated
Stage 1–3 security modules. The latest full suite reached 735 passed and 9
skipped; six failures were outside accounts (five blockchain/client tests and one
loans recent-payments test).

### Stage 3 — Cookie authentication and CSRF integrity

- [x] ~~Require CSRF cookie and header whenever an auth cookie authenticates an
  unsafe request.~~
- [x] ~~Exempt pure Bearer-token requests from cookie-CSRF state.~~
- [x] ~~Add complete CSRF transport regression tests.~~
- [x] ~~Narrow refresh-cookie path and document SameSite/secure requirements.~~
- [x] ~~Separate cookie-based browser responses from explicit-token client
  responses.~~

Implementation note: cookie transport is opt-in, while body transport remains the
default for backward-compatible non-browser clients. A cookie-mode client must
first obtain `/api/auth/csrf-token/` and send the returned value in
`X-CSRFToken` for every unsafe request. Refresh responses preserve the transport
used by the refresh request.

### Stage 4 — Brute-force, OTP, and concurrency hardening

- [x] ~~Accept and regression-test the current `100/hour` authentication throttle
  policy.~~
- [x] ~~Add per-identifier and per-token limits in addition to IP limits.~~
- [x] ~~Make login, OTP, reset, and backup-code changes atomic.~~
- [x] ~~Add password-reset issuance cooldown and email-abuse protection.~~
- [x] ~~Define trusted-proxy/IP extraction behavior.~~
- [x] ~~Reconcile custom lockouts with django-axes.~~
- [x] ~~Require explicitly configured shared Redis cache state in production.~~
- [x] ~~Regression-test compound throttle wiring and lockout authority.~~

Implementation note: auth throttles intentionally remain at the accepted
`100/hour` policy. Identifier and token cache keys are SHA-256 digests rather than
raw credentials. Password-reset issuance is limited to one message per minute and
five messages per account per hour. `TRUSTED_PROXY_COUNT` defaults to zero, and
MongoDB account lockouts are authoritative while django-axes remains an
audit/reset observer rather than imposing a second lockout duration. Production
settings require shared Redis so these cache-backed controls work consistently
across workers.

### Stage 5 — 2FA lifecycle integrity

- [x] ~~Require recent authentication/password confirmation for voluntary 2FA
  enrollment.~~
- [x] ~~Carry remember-me/session type through the temporary token.~~
- [x] ~~Recheck active/security state during final 2FA verification.~~
- [x] ~~Create consistent session/activity records after successful 2FA.~~
- [x] ~~Consume backup codes atomically and decide same-window TOTP replay policy.~~
- [x] ~~Audit and notify on every 2FA security change.~~

Implementation note: voluntary setup requires the current password and expires
after ten minutes. Administrator bootstrap remains bound to the password-verified
login request. Accepted TOTP timesteps are stored atomically and cannot be reused,
including through a second temporary login token. Successful 2FA logins now fill
the same active-session and login-activity metadata as password-only logins.
Setup, enablement, disablement, backup-code regeneration, and backup-code use
produce audit records and in-app security notifications.

### Stage 6 — Privileged administration and audit coverage

- [x] ~~Audit administrator creation, deactivation, privilege, and super-admin
  changes with old/new state.~~
- [x] ~~Audit officer deactivation, password/security changes, and session
  termination.~~
- [x] ~~Guarantee at least one active super administrator.~~
- [x] ~~Prevent unsafe self-demotion or require a controlled second-admin
  workflow.~~
- [x] ~~Make optimistic updates conditional and atomic.~~
- [x] ~~Coordinate officer deactivation with assignment/workload handling.~~

Implementation note: privileged mutations use allowlisted audit snapshots and
conditional MongoDB writes. Super-admin removal checks are serialized across
workers, and self-demotion is rejected. Officer deactivation is fail-safe: active
loan workload must first be reassigned, then deactivation rotates account
security state and revokes all sessions. Password changes and user-initiated
session termination reuse the security-event service for consistent audit and
notification behavior.

### Stage 7 — Consent history and policy lifecycle

- [x] ~~Add append-only local consent events.~~
- [x] ~~Make consent updates/upserts atomic.~~
- [x] ~~Define customer-only versus multi-role consent behavior.~~
- [x] ~~Version deployed policy content and implement re-consent.~~
- [x] ~~Make consent revocation fail-safe when cache/task infrastructure is
  down.~~
- [x] ~~Keep blockchain consent sync as a secondary audit channel.~~

Implementation note: customer consent decisions are serialized per account and
written to the append-only event stream before updating the atomic current-state
projection. The deployed policy manifest includes its repository document path
and SHA-256 digest. AI checks bypass cached grants and require current-version
data plus AI consent, so local revocation remains effective through cache, task,
or blockchain outages.

### Stage 8 — Account lifecycle and recovery capabilities

- [x] ~~Implement audited `manage_users` customer administration and unlock flows.~~
- [x] ~~Add customer suspension/deactivation state.~~
- [x] ~~Add verified email change.~~
- [x] ~~Define account deletion, anonymization, export, and retention workflows.~~
- [x] ~~Add controlled 2FA-loss recovery.~~
- [x] ~~Add security event notifications.~~
- [x] ~~Decide and enforce the global cross-role email identity policy.~~

Implementation note: the Stage 8 regression module contains nine focused tests;
the current Stage 8/security/account validation passed 45 tests using the
isolated test settings.

### Stage 9 — Test isolation, dependency reproducibility, and CI

- [x] ~~Make plain `pytest -q` select an isolated test configuration before base
  settings initialize external services.~~
- [ ] Ensure CI supplies safe deterministic settings and verify it from a clean
  environment.
- [x] ~~Add real-Mongo index/concurrency tests for auth-critical operations.~~
- [x] ~~Pin supported framework/runtime versions or introduce a reviewed lock file.~~
- [x] ~~Restore `black --check accounts` compliance.~~
- [x] ~~Add dependency and static security scanning to CI.~~

Implementation note: `pytest.ini` selects `config.settings_test`, which sets safe
values before importing base settings; the root fixtures use mongomock and force
AnyIO tests onto asyncio. `requirements.lock` pins application and test
dependencies, while `requirements-ci.lock` pins Black, Ruff, Bandit, and
pip-audit. CI defines a dedicated real-Mongo service job and security gates.
The current local full run collected 866 tests and reached 851 passed and 12
skipped, but also hit two Windows temporary-directory errors and one unrelated
Prometheus temporary-file failure. The focused account/security run passed 45
tests. Real-Mongo tests intentionally skip without `REAL_MONGO_TEST_URI`; the
hosted workflow and a clean dependency environment remain pending evidence.

### Stage 10 — API contract and documentation alignment

- [x] Correct refresh/logout token transport documentation.
- [x] Document cookie-CSRF behavior and client transport modes.
- [ ] Standardize token response field names; the public loan-officer aliases
  still differ from the customer/admin/refresh contract.
- [x] Document profile update endpoints and actual role restrictions.
- [x] Expand `ACCOUNTS_TESTING_GUIDE.md` with automated setup, negative tests,
  revocation checks, and security-state transitions.
- [x] Re-run this review after stages 1-9 and update statuses from current source
  and test evidence.

## Production Readiness Checklist

### Verified foundations

- [x] ~~Pepper + bcrypt password hashing~~
- [x] ~~Production field-encryption key validation~~
- [x] ~~Customer/officer/admin login lockout foundations~~
- [x] ~~Refresh-token membership for all three roles~~
- [x] ~~Hashed blacklist and refresh membership storage~~
- [x] ~~Short-lived, one-time-use 2FA temporary tokens~~
- [x] ~~Mandatory administrator 2FA bootstrap~~
- [x] ~~Central RBAC, admin permissions, and domain ABAC helpers~~
- [x] ~~Account/token/consent/activity/session index bootstrap coverage~~
- [x] ~~Account-focused automated happy-path tests~~

### Required before production

- [x] ~~Remove plaintext refresh credentials from active sessions and responses.~~
- [x] ~~Enforce temporary-password restrictions across every officer endpoint.~~
- [x] ~~Correct cookie-authenticated CSRF enforcement.~~
- [x] ~~Revoke sessions on password reset/change, deactivation, and security
  events.~~
- [x] ~~Enforce live account/security state for every protected endpoint.~~
- [x] ~~Make logout/session revocation reliable and observable.~~
- [x] ~~Accept and verify the current authentication throttle policy.~~
- [x] ~~Complete 2FA lifecycle/session/audit behavior.~~
- [x] ~~Complete privileged administration audit and last-super-admin
  protection.~~
- [x] ~~Add authoritative local consent history and policy versioning.~~
- [x] ~~Implement required customer lifecycle and security-recovery operations.~~
- [ ] Make test startup isolated and CI reproducible; isolated account tests pass,
  but the current full local run and hosted CI still need clean evidence.
- [ ] Standardize public token response field names and close the remaining
  officer/admin logout contract gap.

## Review Limits

- This was a static code review plus local automated validation, not a live
  penetration test.
- No production MongoDB indexes, Redis state, Celery workers, email provider,
  deployed cookies/CORS, proxy configuration, or blockchain contracts were
  inspected live.
- No sensitive `.env`, media, backup, log, credential, wallet, or uploaded-data
  contents were read.
- Real browser CSRF/CORS behavior, real-Mongo concurrency, email deliverability,
  rate-limit behavior across multiple workers, key rotation, clean dependency
  reproducibility, hosted CI, and operational recovery still require staging or
  CI validation.
