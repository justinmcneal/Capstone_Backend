# Notifications Production Readiness Review

Last updated: 2026-08-27

Scope: `notifications/`, `/api/notifications/`, `/ws/notifications/`, the
`notifications` and `device_tokens` MongoDB collections, template email,
Firebase Cloud Messaging (FCM), Channels/Redis broadcasting, the standalone
notification email task, notification preferences, account lifecycle
integration, cross-domain producers, persistence bootstrap, and notification-
related automated tests and documentation.

## Purpose and Status Definitions

This document records what the Notifications module currently implements, the
evidence for those claims, and the remediation required before production
approval. It distinguishes an inbox record from durable delivery: storing a
notification does not prove that email, push, or a WebSocket frame reached the
recipient.

- **Complete**: implemented and covered by proportionate automated evidence.
- **Partial**: useful behavior exists, but an important correctness, security,
  privacy, durability, scalability, or operational requirement remains.
- **Not implemented**: no production implementation was found.
- **Deployment validation**: repository implementation exists but still needs
  evidence from real MongoDB, Redis/Channels, Celery, SMTP, Firebase, HTTPS/WSS,
  monitoring, backup, and recovery environments.

The project uses PyMongo directly. Django ORM migrations are not part of the
Notifications persistence model. `mongomock`, in-memory Channels, direct view
calls, and mocked email tests do not prove real indexes, validators, query
plans, multi-worker behavior, SMTP acceptance, FCM delivery, proxy security, or
client receipt.

## Executive Summary

The Notifications module is **functional but not production-ready**. Seven REST
operations provide an owner-scoped inbox, unread counts, read mutations,
deletion, clear-all, and device-token registration. An authenticated WebSocket
provides connection state, ping/pong, owner-scoped mark-read, and real-time
broadcasts. Role-qualified ownership correctly prevents customers, officers,
and administrators with the same raw ID from sharing inbox rows or Channels
groups. Thirty-six notification types and eleven HTML/text template pairs are
present, including the temporary-password pair.

The current code does not yet provide a coherent production delivery system:

1. **FCM delivery is currently broken.** The pinned `firebase-admin==7.4.0`
   installation exposes `send_each_for_multicast` but not the invoked
   `messaging.send_multicast`. The exception is swallowed and logged, so inbox
   creation succeeds while every attempted push silently fails.
2. **Device-token ownership is unsafe.** Tokens store `user_id` without
   `user_type`, token lookup is not role-qualified, and registering an existing
   token transfers it to the current caller. There is no unregister/logout or
   account-deletion cleanup path, no strict platform/token validation, and no
   500-token FCM batching.
3. **The advertised standalone Celery email path is not operational.** Celery
   autodiscovery does not import `notifications/services/email_tasks.py`, so
   `notifications.services.email_tasks.send_email_task` is not registered in a
   normal app startup. No producer calls it. Even if imported, `EmailSender`
   converts SMTP exceptions to `False`, so `autoretry_for=(Exception,)` does not
   retry the failure.
4. **The inbox contract is now stable, while delivery durability remains
   partial.** Stage 1 separated `is_read/read_at` from delivery `status`, made
   owner mutations atomic and replay-safe, and retained legacy `status: read`
   compatibility. Most email helpers still create an `in_app` row marked
   `sent` before SMTP is attempted, so Stage 3 must complete channel delivery
   evidence.
5. **Durability is inconsistent.** Loans and Documents have their own leased,
   retryable outboxes before calling the shared sender. Assignment and account-
   security notifications are best-effort and can be permanently lost after
   the business mutation. A crash after SMTP acceptance but before outbox
   completion can resend an email on retry.
6. **Saved customer preferences are not enforced.** The Profiles module stores
   `email_loan_updates`, `email_payment_reminders`, and `email_promotions`, but
   notification/email producers do not consult them. The UI therefore exposes
   controls that do not currently control delivery.
7. **Privacy lifecycle is incomplete.** Recipient email/name, message,
   metadata, errors, and FCM tokens are plaintext. Email addresses, subjects,
   user IDs, exception details, and complete FCM tokens can enter logs.
   Customer export is limited to the latest 200 notifications without explicit
   truncation and queries by raw ID only. Account deletion does not remove or
   pseudonymize core notifications and does not deactivate device tokens.
8. **Persistence and scale controls are incomplete.** Stage 1 added strict
   query parameters, a maximum offset, bounded bulk mutations, and REST/WS
   action throttles. MongoDB validators, inventory/backfill tooling,
   query-specific compound indexes, device-token lookup bounds, and push
   fan-out bounds remain.
9. **WebSocket production controls are partial.** Handshake authentication,
   origin checking, and per-connection action throttling are present, but an
   already-connected socket is not
   revalidated after logout, session revocation, account suspension, security-
   version change, or access-token expiry. Message-size and connection limits
   are not defined, and REST mutations are not synchronized
   to a user's other connected devices.
10. **Operations evidence is insufficient.** Two email-task counters exist,
    but there are no notification request/delivery/backlog/push/WebSocket
    metrics, Prometheus rules, Grafana dashboard, health readiness, release
    checker, real-Mongo suite, or deployed SMTP/FCM/Redis/WSS recovery probes.
    The root README also lists two nonexistent synchronous-email counters and
    an `EMAIL_SENDER_THREADPOOL_MAX_WORKERS` setting/thread pool that the code
    does not implement.

Current Stage 1 automated evidence:

- Core Notifications-focused selection: **62 passed** on 2026-08-27.
- Stage 1 focused contract/security selection: **78 passed**.
- Routed tests cover missing/revoked JWTs, customer/officer/admin role-qualified
  isolation, all seven REST operations, cross-owner concealment, independent
  read/delivery state, replay, strict bounds, REST throttles, and WebSocket
  action throttling.
- Broader notification/WebSocket/email-template selection: **117 passed and
  1,245 deselected**.
- Full repository: **1,316 passed and 46 opt-in integration tests skipped**.
- There is no FCM send test, real SMTP test, real-Mongo query-plan/validator
  test, Redis multi-process test, or Notifications deployment release suite.

## Current Status

| Area | Status | Summary |
| --- | --- | --- |
| REST inbox | Complete locally | Seven routed authenticated operations have strict role-qualified ownership, independent read/delivery state, atomic replay-safe read mutation, strict query validation, bounded offset/bulk work, and dedicated throttles. |
| WebSocket inbox | Partial | Secure handshake, owner groups, ping, replay-safe mark-read, broadcasts, and per-connection action throttling exist; live-session revalidation, frame/connection limits, and cross-device state events remain. |
| Template email | Partial | Templates and synchronous sender helpers work and read state no longer overwrites delivery status; uncertain SMTP outcomes can still duplicate. |
| Standalone Celery email | Not operational | Task source exists but is not autodiscovered/routed/called, and returned failures bypass Celery autoretry. |
| Loan/document delivery | Implemented in owning modules | Their domain outboxes provide leases, retries, and reconciliation; those guarantees do not cover all Notifications producers. |
| Assignment/security events | Partial | Owner-scoped records and broadcasts exist, but publication is best-effort with no durable recovery. |
| FCM push | Broken | Installed Firebase API and invoked method are incompatible; device ownership and cleanup also require redesign. |
| Preferences | Stored but unenforced | Profiles persists three customer email preferences; delivery paths do not apply them. |
| Privacy lifecycle | Incomplete | Plaintext sensitive fields/tokens, unsafe logs, incomplete export, and missing account-deletion cleanup remain. |
| MongoDB schema/indexes | Partial | Basic indexes are bootstrapped; no validator, compound query indexes, inventory/backfill, or real-Mongo proof exists. |
| Observability | Incomplete | Two task counters exist, but no end-to-end channel outcomes, backlog/age gauges, rules, dashboard, readiness, or alert evidence exists. |
| Production deployment | Not ready | SMTP, Firebase, Redis/Channels, workers, HTTPS/WSS, backup/restore, monitoring, and release gates remain unproven. |

## Module Responsibilities and Boundaries

The Notifications module currently owns:

- inbox record persistence and serialization;
- role-qualified inbox REST queries and mutations;
- device-token registration and FCM dispatch;
- notification WebSocket authentication, groups, frames, and broadcasts;
- reusable email templates/sender helpers;
- assignment event formatting; and
- a local wrapper for the shared Prometheus runtime toggle.

Profiles owns customer notification preferences. Loans and Documents own their
durable delivery outboxes and retry policies. Accounts owns JWT/session state,
account export/deletion, and security-event production. Redis/Channels owns
real-time fan-out, Celery owns background task execution, SMTP owns email
acceptance, and Firebase owns push delivery. Production readiness requires
explicit contracts between these owners rather than assuming a successful
function call proves delivery.

## API Status

All REST routes are under `/api/notifications/` and declare
`CustomJWTAuthentication` plus `IsAuthenticated`. Allowed roles are customer,
loan officer, admin, and super admin; super admin normalizes to stored `admin`.

| Method and route | Current behavior | Status |
| --- | --- | --- |
| `GET /` | Owner-scoped page, optional unread/channel filter, total and unread count | Implemented; strict query allowlist, page-size and offset bounds |
| `GET unread-count/` | Count owner rows whose independent read state is unread | Implemented with legacy-row compatibility |
| `POST mark-all-read/` | Mark a bounded snapshot of owner unread rows read | Implemented; returns 409 when synchronous bound is exceeded |
| `POST <notification_id>/read/` | Atomic owner-scoped read mutation | Implemented; idempotent replay is explicit in REST and WS |
| `DELETE <notification_id>/` | Delete one owned row | Implemented |
| `DELETE clear-all/` | Delete a bounded snapshot of owned rows | Implemented; returns 409 when synchronous bound is exceeded |
| `POST register-token/` | Insert/update an FCM token | Present but unsafe until token ownership/validation is fixed |

WebSocket route: `GET /ws/notifications/` upgrades through
`AllowedHostsOriginValidator` and `JWTAuthMiddleware`.

| Frame/action | Current behavior | Status |
| --- | --- | --- |
| `connection_established` | Returns unread count after joining owner group | Implemented |
| client `ping` / server `pong` | Liveness timestamp | Implemented with per-connection action rate limit |
| client `mark_read` | Atomic owner-qualified update and response | Implemented; idempotent replay reports success plus `replayed: true` |
| server `notification` | Best-effort owner-group broadcast | Implemented; inbox REST is recovery source |
| mark-all/delete/unread refresh | REST only | Acceptable baseline if clients use REST; cross-device synchronization remains a gap |

## Verified Implemented Foundations

### Authentication and ownership

- HTTP queries require both normalized `user_id` and `user_type`.
- WebSocket groups use `notifications_<role>_<id>` and are role-qualified.
- Staff WebSockets accept the HttpOnly access cookie and reject staff query or
  subprotocol tokens.
- Customer query/subprotocol access tokens remain temporarily supported for
  the mobile client.
- The handshake uses the shared JWT boundary for token purpose/signature,
  blacklist, live account, session, security version, and forced-password
  enforcement.
- Missing or rejected credentials close with code `4001`.
- `AllowedHostsOriginValidator` protects browser cookie handshakes.

### Inbox contract

- Read state is stored in `is_read/read_at`; `status` and `delivery_status`
  preserve `pending/sent/failed/unknown` delivery evidence. Legacy
  `status: read` rows remain readable during later backfill work.
- List queries accept only `page`, `page_size`, `unread`, and `channel`;
  page size is strictly 1–100 and deep offsets are rejected.
- Mark-one is atomic, owner-qualified, and replay-consistent across REST/WS.
- Mark-all and clear-all operate only within the configured synchronous bound.
- Read, write, token-registration, and WebSocket actions have separate limits.
- Out-of-scope notification IDs return 404.
- MongoDB datetimes serialize with an explicit UTC designator.
- API/WebSocket payloads omit recipient email, recipient name, idempotency key,
  and stored error text.
- Single delete and role-qualified bulk mutations are implemented.

### Cross-domain production

- Loan submission/review/disbursement/payment and document review outcomes use
  shared sender helpers.
- Loans and Documents persist their delivery intent before broker publication,
  claim work with leases, retry failures, and reconcile due records.
- Assignment events create per-audience structured metadata, deduplicate a
  recipient within one publication, and can use transition-based idempotency
  keys.
- Account security events can create in-app notifications, but remain
  best-effort.

### Persistence bootstrap

- `init_db.py` calls `Notification.create_indexes()` and
  `DeviceToken.create_indexes()`.
- Notification idempotency keys and device tokens have unique indexes.
- These bootstrap blocks currently catch errors and continue; there is no
  Notifications validator or fail-closed release verification.

## Implemented Controls and Remaining Release Conditions

### 1. Inbox contract, authentication, and ownership

**Status: Partial**

Role-qualified list, count, mark, delete, clear, WebSocket group, and
WebSocket mark-read behavior is implemented and locally tested. Remaining work:

- add request-level JWT/session/role tests through actual REST URL routing;
- make REST and WebSocket read replays share one idempotent result contract;
- perform owner matching in the atomic update itself;
- reject unknown query parameters and define a maximum page/offset;
- add a dedicated authenticated throttle for reads, writes, token registration,
  and WebSocket actions; and
- decide whether clear-all is acceptable or should become a bounded/soft-delete
  operation.

### 2. Delivery state, idempotency, and durable processing

**Status: Incomplete**

The inbox read state must be separated from channel-delivery attempts. Introduce
an explicit event plus per-channel delivery records, or equivalent independent
fields, so email/push delivery cannot overwrite read state. Register tasks in a
canonical `notifications/tasks.py`, route them to a dedicated queue, use late
acknowledgement, worker-loss rejection, bounded retries, leases/checkpoints, and
stable non-sensitive failure codes. Apply durable intent-before-side-effect
semantics to assignment and required security notifications.

Release evidence must cover broker outage, worker death before/after provider
acceptance, retry/replay, duplicate event publication, provider timeout, and
reconciliation without repeating the business mutation.

### 3. Device tokens and FCM

**Status: Production blocker**

- replace the removed Firebase call with the supported pinned-version API and
  test partial-success response handling;
- scope tokens by both user ID and user type and prevent unauthorized token
  reassignment;
- add bounded token/platform validation and approved platform values;
- add unregister-current-token, logout/session cleanup, stale-token expiry,
  account-deletion cleanup, and last-used maintenance;
- encrypt or otherwise protect tokens as bearer-like delivery credentials;
- batch multicast requests to Firebase's provider limit; and
- make push asynchronous, retryable, preference-aware, observable, and safe
  under partial failure.

### 4. Preferences, privacy, and lifecycle

**Status: Production blocker**

Define mandatory transactional/security events separately from configurable
loan/payment/promotional messages. Enforce Profiles preferences at durable
delivery creation time and record the policy/version used. Add bounded,
role-qualified customer export with total/truncation metadata. On account
deletion, delete or approvedly pseudonymize notification records and deactivate
tokens. Classify and protect recipient identity, content, metadata, provider
errors, and tokens with the shared encryption/key-rotation lifecycle. Sanitize
logs so they do not contain email addresses, full device tokens, free-form
subjects/messages, customer/loan details, or provider exception bodies.

An authorized privacy/product decision is still required for retention,
mandatory security notices, preference defaults, and which event types may be
deleted by the user.

### 5. MongoDB scalability and schema integrity

**Status: Incomplete**

Add strict validators for notification/event/channel/read/delivery shapes and
device-token ownership/platform/state. Add inventory and dry-run-first backfill
for legacy user types, status separation, missing metadata, duplicate tokens,
plaintext/old-key fields, and invalid timestamps. Replace single-field indexes
with query-specific compounds for owner/type/date pages, owner/read counts,
channel filters, retention/reconciliation, and role-qualified active tokens.
Keep the Stage 1 inbox bounds under load evidence and add bounds for export,
token fan-out, and recovery jobs.

Release evidence must include isolated real-Mongo invalid-write, unique-key,
atomic ownership, inventory/backfill, and `explain()` tests with representative
cardinality.

### 6. WebSocket lifecycle and client consistency

**Status: Partial**

The connection handshake is well protected, but security must remain current
after connection. Close or revalidate sockets on token expiry, logout/session
revocation, password/security-version changes, forced-password state, account
suspension/deactivation, and account deletion. Define message-size, action-rate,
connection-count, idle/heartbeat, backpressure, and Redis outage behavior.
Broadcast read/delete/count changes to the owner's other devices or document a
client reconciliation contract using REST on reconnect/focus.

Migrate customer mobile away from query-string JWTs when the client can use a
safer transport; never broaden query/subprotocol support to staff browsers.

### 7. Observability and release operations

**Status: Incomplete**

Replace the two isolated task counters with low-cardinality metrics for event
creation, per-channel outcomes/latency, retries, terminal failures, pending and
oldest-age backlogs, active sockets, rejected handshakes/actions, Redis/SMTP/FCM
availability, token invalidation, and reconciliation freshness. Add tested
Prometheus rules, Grafana dashboard/provisioning, health readiness, sanitized
structured logs, and a read-only `notifications_release_check`.

Remove or correct the root README's nonexistent synchronous counters and email
thread-pool setting as part of this stage.

Deployment evidence must prove real Redis fan-out across ASGI workers, at least
two notification workers, SMTP and Firebase sandbox behavior, HTTPS/WSS proxy
headers/origins/cookies, provider and broker failure recovery, dashboard
traffic, delivered alerts, backup/restore, key rotation, incident response, and
rollback.

## Remediation Plan

These stages follow risk and technical dependencies; six stages are sufficient
for the currently identified work.

### Stage 1 — Contract and owner-safe inbox operations

**Status: Complete locally (2026-08-27)**

- [x] Separate read state from delivery status in the public and stored contract.
- [x] Preserve compatible reads for legacy records whose `status` is `read`.
- [x] Make owner-scoped mutations atomic and replay-consistent.
- [x] Bound/validate queries and bulk operations and add notification throttles.
- [x] Correct the shadowed `register-token/` URL discovered by routed tests.
- [x] Add routed JWT/session/role/ownership tests for all seven REST operations.

**Exit condition:** every inbox operation has a stable, role-qualified,
bounded, request-level-tested contract and cannot corrupt delivery evidence.

### Stage 2 — Secure and working push notifications

**Status: Not started**

- Replace the incompatible Firebase API call and add success/partial/failure
  tests.
- Redesign role-qualified token ownership, validation, deduplication, revoke,
  expiry, logout, and account-deletion behavior.
- Protect tokens and batch provider requests.

**Exit condition:** no caller can claim another account's token, the installed
Firebase version passes mocked contract tests, and token lifecycle is complete.

### Stage 3 — Durable, preference-aware channel delivery

**Status: Not started**

- Register and route Notifications tasks correctly.
- Add a leased/retryable notification-wide delivery model for producers not
  already protected by a domain outbox.
- Make email/push asynchronous, preference/policy-aware, idempotent, and
  recoverable from broker/worker/provider uncertainty.

**Exit condition:** required notification intent survives process/broker loss,
preferences are enforced, and retry never repeats the underlying business
mutation.

### Stage 4 — Privacy lifecycle and MongoDB correctness

**Status: Not started**

- Encrypt/minimize sensitive notification/token fields and sanitize logs.
- Implement bounded export, retention, deletion/pseudonymization, token cleanup,
  inventory, backfill, and key rotation.
- Add strict validators and query-specific compound indexes.
- Add isolated real-Mongo validator, uniqueness, atomicity, and query-plan
  tests.

**Exit condition:** legacy/current data has a reviewed lifecycle, invalid writes
fail, critical queries use approved indexes, and account deletion leaves no
active delivery credential.

### Stage 5 — WebSocket resilience and observability

**Status: Not started**

- Enforce post-connect security lifecycle and connection/action limits.
- Add cross-device state synchronization and reconnect reconciliation.
- Add end-to-end channel/backlog/security metrics, health, alerts, dashboard,
  and operator runbooks.

**Exit condition:** operators and clients can detect/recover missed real-time
events without privacy leakage, and revoked users cannot retain live sockets.

### Stage 6 — Real-environment release validation

**Status: Not started**

- Add a fail-closed read-only release checker and opt-in deployment probes.
- Prove MongoDB indexes/validators, Redis multi-worker fan-out, Celery recovery,
  SMTP/Firebase sandbox outcomes, HTTPS/WSS proxy behavior, load, metrics,
  dashboard, and alert delivery.
- Rehearse backup/restore, key rotation, provider/broker outage, incident
  response, and rollback.
- Run the full suite and customer/staff end-to-end notification smoke flows.

**Exit condition:** every applicable release check passes in the selected
topology and all approved policy/evidence records are retained.

## API and Client Impact Notes

- Existing REST paths remain stable. List items now expose authoritative
  `is_read/read_at`; `status` remains a delivery-state compatibility field and
  `delivery_status` makes that meaning explicit. Clients must no longer infer
  read state from `status == "read"`.
- `page_size > 100`, unknown query parameters, and requests past the configured
  offset return HTTP 400. Oversized synchronous mark-all/clear-all operations
  return HTTP 409 instead of starting unbounded work.
- Mark-read responses expose `notification_id`, `is_read`, `read_at`,
  `delivery_status`, and `replayed`. WebSocket mark-read responses also expose
  `replayed`.
- Clients must use `pagination.total_pages == 0` for an empty inbox under the
  current contract.
- REST remains authoritative after missed WebSocket delivery. Clients should
  refresh inbox/count on reconnect and app focus until explicit synchronization
  events are implemented.
- Staff browsers must continue using HttpOnly cookie authentication. Do not put
  staff access tokens in URLs, WebSocket subprotocol lists, browser storage, or
  JavaScript.
- Customer mobile query/subprotocol compatibility is temporary and requires a
  coordinated client migration before removal.
- Device-token registration should not be treated as production-safe until
  Stage 2 is complete. Clients will need an unregister/logout call.
- Notification preferences are not currently enforced; frontends must not
  claim that toggles control delivery until Stage 3 closes that gap.
- The WebSocket supports only `ping` and `mark_read`. REST fallback is an
  acceptable baseline for other actions; this narrow action set is not itself a
  blocker.

## Operational Notes

- A persisted inbox row is not proof of email/push/WebSocket delivery.
- Loans and Documents outbox health must be monitored separately until a shared
  delivery lifecycle is implemented.
- Do not log or expose SMTP credentials, Firebase credentials, FCM tokens,
  access tokens, recipient PII, free-form messages, or provider exception bodies.
- Production WebSockets require `wss://`, exact hosts/origins, trusted proxy
  forwarding, cookie coverage for `/ws/notifications/`, and Redis available to
  every ASGI process.
- `init_db.py` is state-changing and may install notification indexes only after
  duplicate inventory, backup, and explicit target approval.
- Email/push provider acceptance is not guaranteed user receipt; define channel
  outcome terminology accordingly.

## Review Boundaries

This review inspected repository code/documentation and ran local automated
tests. It did not directly read `.env`, customer data, device-token records,
Firebase/cloud credentials, logs, backups, `dump.rdb`, or production data. It
did not initialize/mutate MongoDB, start workers, send email/push messages, or
connect to external providers.

The review confirms that the installed Firebase library lacks the method the
current code invokes and that the Celery app does not register the standalone
email task during normal startup. It does not certify SMTP/Firebase terms,
deliverability, privacy policy, retention periods, notification wording, or
on-call procedures; those require authorized product, privacy, security, and
operations review.

## Release Gate

Do not classify Notifications as production-ready until:

1. the installed-version FCM path works and device ownership/lifecycle is safe;
2. read state is independent from channel delivery state;
3. required producers have durable, preference-aware, retryable delivery;
4. sensitive fields/tokens/logs and account export/deletion/retention are fixed;
5. validators, compound indexes, inventory/backfill, and real-Mongo plans pass;
6. WebSocket post-connect authorization and abuse limits are implemented;
7. monitoring assets, health, alerts, and a release checker are implemented;
8. Redis/Celery, SMTP, FCM, HTTPS/WSS, load, backup/restore, key rotation,
   incident response, and rollback are proven in the selected topology; and
9. the final focused/full suites and customer/staff smoke flows pass.

## Related Documentation

- `docs/NOTIFICATIONS_TESTING_GUIDE.md` — current contracts, accurate test
  baseline, known gaps, and future validation commands
- `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` — JWT/session and
  account lifecycle boundary
- `docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md` — customer preference
  storage and account data integration
- `docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` — document delivery
  outbox behavior
- `docs/LOANS_PRODUCTION_READINESS_REVIEW.md` — loan delivery outbox and
  assignment producers
- `docs/ANALYTICS_PRODUCTION_READINESS_REVIEW.md` — audit/monitoring conventions
