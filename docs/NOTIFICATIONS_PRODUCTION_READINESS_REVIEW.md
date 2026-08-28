# Notifications Production Readiness Review

Last updated: 2026-08-28

Scope: `notifications/`, `/api/notifications/`, `/ws/notifications/`, the
`notifications` and `device_tokens` MongoDB collections, template email,
Firebase Cloud Messaging (FCM), Channels/Redis broadcasting, the shared
notification delivery outbox, notification preferences, account lifecycle
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

The Notifications module is **functional but not production-ready**. Eight REST
method operations provide an owner-scoped inbox, unread counts, read mutations,
deletion, clear-all, and device-token registration/unregistration. An authenticated WebSocket
provides connection state, ping/pong, owner-scoped mark-read, and real-time
broadcasts. Role-qualified ownership correctly prevents customers, officers,
and administrators with the same raw ID from sharing inbox rows or Channels
groups. Thirty-six notification types and eleven HTML/text template pairs are
present, including the temporary-password pair.

The current code does not yet provide a coherent production delivery system:

1. **FCM and current device-token lifecycle are implemented locally.** Stage 2
   uses the installed `send_each_for_multicast` API, batches at no more than
   500 tokens, processes partial results, and deactivates permanently invalid
   registrations without logging credentials. Live Firebase acceptance still
   requires deployment validation.
2. **Device tokens are now protected and owner-safe.** Current registrations
   use encrypted token values, deterministic fingerprints, role-qualified
   ownership, session binding, strict token/platform validation, active-device
   limits, expiry, refresh/deduplication, explicit unregister, session/logout
   cleanup, and account-deletion cleanup. Stage 4 must inventory/backfill legacy
   rows before production index work.
3. **Stage 3 replaced the dead standalone email task with a canonical shared
   delivery path.** `notifications/tasks.py` registers routed delivery and
   reconciliation tasks with late acknowledgement, worker-loss rejection,
   leases, bounded attempts, backoff, and stable error codes. The encrypted
   shared outbox stores intent before broker publication, so a broker outage or
   stale worker lease leaves recoverable work rather than losing the event.
4. **The inbox contract and channel progress are independent.** Stage 1
   separated `is_read/read_at` from inbox delivery compatibility state. Stage 3
   adds per-channel progress to `notification_deliveries`, checkpoints the
   inbox ID and successful/permanently rejected push token fingerprints, and
   makes replay idempotent without repeating the business mutation.
5. **Required producers now have a durable owner.** Loans and Documents retain
   their domain outboxes. Assignment and account-security events use the shared
   outbox, and every notification-creator push is published through it. SMTP or
   FCM acceptance followed by a lost acknowledgement can still produce an
   at-least-once external attempt; provider acceptance is not user receipt.
6. **Saved customer email preferences are now enforced.** Loan/document update
   categories use `email_loan_updates`; payment reminders and promotions have
   explicit policy keys. Payment receipts, staff workflow mail, and security
   notices remain mandatory. Each decision records its policy version; email
   opt-out does not suppress the in-app inbox record.
7. **Privacy lifecycle is incomplete.** Device-token values are encrypted and
   token delivery logs contain only non-sensitive error types. Recipient
   email/name, message, metadata, and errors remain plaintext, while email
   addresses, subjects, user IDs, and other exception details can enter logs.
   Customer export is limited to the latest 200 notifications without explicit
   truncation. Account deletion does not remove or pseudonymize core
   notifications, although it now deactivates device tokens.
8. **Persistence and scale controls are incomplete.** Stage 1 added strict
   query parameters, a maximum offset, bounded bulk mutations, and REST/WS
   action throttles. MongoDB validators, inventory/backfill tooling,
   query-specific notification indexes and legacy inventory/backfill remain.
   Current device-token lookup, per-owner registrations, and FCM fan-out are
   bounded.
9. **WebSocket production controls are partial.** Handshake authentication,
   origin checking, and per-connection action throttling are present, but an
   already-connected socket is not
   revalidated after logout, session revocation, account suspension, security-
   version change, or access-token expiry. Message-size and connection limits
   are not defined, and REST mutations are not synchronized
   to a user's other connected devices.
10. **Operations evidence is insufficient.** The obsolete standalone task and
    its isolated counters were removed, but there are no notification
    request/delivery/backlog/push/WebSocket
    metrics, Prometheus rules, Grafana dashboard, health readiness, release
    checker, real-Mongo suite, or deployed SMTP/FCM/Redis/WSS recovery probes.
    The root README also lists two nonexistent synchronous-email counters and
    an `EMAIL_SENDER_THREADPOOL_MAX_WORKERS` setting/thread pool that the code
    does not implement.

Current local automated evidence:

- Stage 3 focused delivery selection: **12 passed** on 2026-08-28.
- Notifications and affected cross-domain regression selection: **129 passed**
  on 2026-08-28.
- Core Notifications-focused selection: **72 passed** on 2026-08-28.
- Stage 1 focused contract/security selection: **78 passed**.
- Stage 2 provider/token lifecycle selection: **14 passed**.
- Routed tests cover missing/revoked JWTs, customer/officer/admin role-qualified
  isolation, all seven REST operations, cross-owner concealment, independent
  read/delivery state, replay, strict bounds, REST throttles, and WebSocket
  action throttling.
- Broader notification/WebSocket/email-template selection: **131 passed and
  1,245 deselected**.
- Full repository: **1,340 passed and 46 opt-in integration tests skipped** on
  2026-08-28.
- Mocked FCM success, batching, partial/permanent/transient failure behavior,
  encryption, ownership, deduplication, expiry, unregister, logout/session,
  and account cleanup are covered. There is no live Firebase/SMTP test,
  real-Mongo query-plan/validator test, Redis multi-process test, or
  Notifications deployment release suite.

## Current Status

| Area | Status | Summary |
| --- | --- | --- |
| REST inbox | Complete locally | Seven routed authenticated operations have strict role-qualified ownership, independent read/delivery state, atomic replay-safe read mutation, strict query validation, bounded offset/bulk work, and dedicated throttles. |
| WebSocket inbox | Partial | Secure handshake, owner groups, ping, replay-safe mark-read, broadcasts, and per-connection action throttling exist; live-session revalidation, frame/connection limits, and cross-device state events remain. |
| Template email | Implemented locally; deployment-gated | Templates and sender helpers work inside durable domain/shared workers and enforce the recorded email policy; uncertain SMTP acceptance can still result in an at-least-once retry. |
| Shared Celery delivery | Implemented locally | Canonical registered/routed tasks, encrypted durable intent, idempotency, leases, checkpoints, bounded retry/backoff, and reconciliation cover producers without a domain outbox. |
| Loan/document delivery | Implemented in owning modules | Their domain outboxes provide leases, retries, and reconciliation; those guarantees do not cover all Notifications producers. |
| Assignment/security events | Implemented locally | Both publish durable shared-delivery intent; assignment remains in-app and security events can request in-app plus push. |
| FCM push | Implemented locally; deployment-gated | Push is asynchronous and recoverable, known successes are checkpointed, and installed-version batching, partial results, permanent-token cleanup, encrypted role/session-qualified registrations, expiry, unregister, and cleanup are covered. Live Firebase proof remains. |
| Preferences | Implemented locally | Optional customer email categories are evaluated against Profiles settings and record a versioned decision; mandatory security, staff, and receipt messages are not suppressible. |
| Privacy lifecycle | Incomplete | Device tokens are encrypted and lifecycle-bound; notification content/recipient fields, broader log safety, retention, and complete export/deletion remain. |
| MongoDB schema/indexes | Partial | Basic indexes are bootstrapped; no validator, compound query indexes, inventory/backfill, or real-Mongo proof exists. |
| Observability | Incomplete | No end-to-end channel outcomes, backlog/age gauges, rules, dashboard, readiness, or alert evidence exists. |
| Production deployment | Not ready | SMTP, Firebase, Redis/Channels, workers, HTTPS/WSS, backup/restore, monitoring, and release gates remain unproven. |

## Module Responsibilities and Boundaries

The Notifications module currently owns:

- inbox record persistence and serialization;
- role-qualified inbox REST queries and mutations;
- device-token registration and FCM dispatch;
- encrypted, leased shared delivery intent and reconciliation;
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
| `POST register-token/` | Validate and register/refresh an encrypted token for the authenticated role/session | Implemented with ownership conflict and active-device bounds |
| `DELETE register-token/` | Deactivate one token owned by the authenticated account | Implemented; cross-owner requests are concealed |

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
- Account security events create durable in-app/push intent through the shared
  delivery outbox.
- Optional customer email helpers evaluate Profiles preferences before SMTP;
  denied email is recorded as suppressed without removing in-app delivery.

### Persistence bootstrap

- `init_db.py` calls `Notification.create_indexes()`,
  `DeviceToken.create_indexes()`, and `NotificationDelivery.create_indexes()`.
- Notification idempotency keys and device tokens have unique indexes.
- These bootstrap blocks currently catch errors and continue; there is no
  Notifications validator or fail-closed release verification.

## Implemented Controls and Remaining Release Conditions

### 1. Inbox contract, authentication, and ownership

**Status: Complete locally**

Role-qualified list, count, mark, delete, bounded clear, WebSocket group, and
WebSocket mark-read behavior is implemented and locally tested through routed
JWT/session/role cases. REST and WebSocket replay contracts are aligned, owner
matching is atomic, unknown/deep queries are rejected, and separate authenticated
throttles protect reads, writes, token registration, and socket actions.

### 2. Delivery state, idempotency, and durable processing

**Status: Complete locally; deployment validation pending**

The encrypted `notification_deliveries` outbox owns events not already covered
by Loans/Documents. It uses event/recipient idempotency, late-acknowledged routed
tasks, worker-loss rejection, atomic leases, per-channel checkpoints, bounded
attempts/backoff, stable failure codes, and periodic reconciliation. Assignment,
account-security, and notification-creator push publication persist intent before
broker dispatch. Tests cover broker publication failure, stale leases, replay,
preference suppression, email retry, and partial push retry without resending
known successes.

Deployment evidence must still cover actual broker outage, worker termination
before/after provider acceptance, and provider timeout. External SMTP/FCM calls
remain at-least-once when acceptance occurs before the checkpoint is persisted.

### 3. Device tokens and FCM

**Status: Implemented locally; deployment and legacy-data validation pending**

- [x] Use the supported installed-version Firebase API and test complete and
  partial results.
- [x] Scope tokens by user ID and role and reject active cross-owner claims.
- [x] Validate token length/shape and approved `android`/`ios`/`web` platforms.
- [x] Implement explicit unregister, session/logout and account cleanup,
  expiry, refresh, active-device bounds, and last-used maintenance.
- [x] Encrypt token values, use non-reversible fingerprints for identity, and
  include the model in field-encryption rotation/verification tooling.
- [x] Batch multicast requests at the configured maximum of 500.
- [x] Stage 3 makes push durable, asynchronous, bounded-retry, and recoverable;
  successful/permanent token outcomes are checkpointed before later retries.
- [ ] Stage 4 must inventory/backfill legacy rows and prove indexes/validators
  against isolated real MongoDB.

### 4. Preferences, privacy, and lifecycle

**Status: Partial; Stage 3 preference policy complete**

Mandatory transactional/security events are separated from configurable
loan/payment/promotional messages. Profiles preferences are enforced before
optional email delivery and the decision/version is stored. Stage 4 must add
bounded, role-qualified customer export with total/truncation metadata. On account
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

**Status: Complete locally (2026-08-27)**

- [x] Replace the incompatible Firebase API call and add
  success/partial/permanent/transient failure tests.
- [x] Add role-qualified ownership, validation, deduplication, active-device
  bounds, expiry, explicit revoke, logout/session, and account-deletion behavior.
- [x] Encrypt tokens, fingerprint lookups, sanitize provider logs, and batch
  requests to the Firebase maximum.

**Exit condition:** no caller can claim another account's token, the installed
Firebase version passes mocked contract tests, and token lifecycle is complete.

### Stage 3 — Durable, preference-aware channel delivery

**Status: Complete locally (2026-08-28)**

- [x] Register and route Notifications tasks correctly.
- [x] Add a leased/retryable notification-wide delivery model for producers not
  already protected by a domain outbox.
- [x] Make email/push asynchronous, preference/policy-aware, idempotent, and
  recoverable from broker/worker/provider uncertainty.
- [x] Route assignment, account-security, and notification-creator push intent
  through the shared outbox while preserving Loans/Documents domain outboxes.

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
- Clients must register or refresh their token after login using
  `POST register-token/`, including an approved platform. Use
  `DELETE register-token/` with the token during explicit device unregister;
  normal logout also deactivates registrations bound to that session.
- Registration may return HTTP 409 if a token is actively owned by another
  account or the account has reached its active-device limit. Clients must not
  silently substitute or transfer token ownership.
- Profiles preference toggles now control optional email only:
  `email_loan_updates` covers loan/document status updates,
  `email_payment_reminders` covers reminders, and `email_promotions` covers
  promotional mail. In-app notifications, payment receipts, staff workflow
  messages, and security notices remain enabled as mandatory communications.
- The WebSocket supports only `ping` and `mark_read`. REST fallback is an
  acceptable baseline for other actions; this narrow action set is not itself a
  blocker.

## Operational Notes

- A persisted inbox row is not proof of email/push/WebSocket delivery.
- Monitor Loans, Documents, and shared Notifications outboxes separately; each
  owns different event sources.
- A worker consuming the dedicated queue is required, for example
  `celery -A config worker -Q notifications --loglevel=info`; Celery Beat must
  run the minute reconciliation schedule. Use the deployment's approved worker
  topology rather than assuming a default-queue worker consumes this queue.
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

The review confirms the installed-version Firebase API and canonical Celery
task registration through mocked local contracts. It does not certify
SMTP/Firebase terms, deliverability, privacy policy, retention periods,
notification wording, or
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
