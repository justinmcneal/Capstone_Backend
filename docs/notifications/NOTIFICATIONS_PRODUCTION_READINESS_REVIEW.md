# Notifications Module Documentation and Status

Last updated: 2026-08-29

## Overview

The Notifications module provides the role-scoped inbox, unread/read state,
device-token lifecycle, Firebase Cloud Messaging (FCM), template-email helpers,
durable shared channel delivery, and authenticated real-time notification
service for MSME Pathways.

Seven REST paths expose eight HTTP method operations under
`/api/notifications/`. An authenticated Channels WebSocket is available at
`/ws/notifications/` for real-time notification and inbox-state events. The
module supports customer, loan-officer, administrator, and super-administrator
accounts; super administrators normalize to the stored `admin` owner type.

The module defines 36 notification types and supports in-app, email, and push
channels. Storing an inbox record does not prove that an email, push message, or
WebSocket frame reached the user. Durable delivery state, provider acceptance,
best-effort real-time fan-out, and user receipt are distinct concepts throughout
the implementation and this document.

This project uses PyMongo directly. Django ORM migrations are not part of the
Notifications persistence lifecycle; MongoDB inventory, backfill, indexes, and
validators are handled by module commands and the project bootstrap.

## Current Status

**Module implementation status: Complete for the reviewed repository baseline**

**Production deployment status: Ready for production-environment validation**

The REST inbox, WebSocket protocol, role-qualified ownership, durable shared
delivery, email-preference enforcement, FCM token lifecycle, encryption,
retention, account lifecycle, MongoDB tooling, metrics, dashboards, and
fail-closed release tooling are implemented and locally tested. Production
approval remains conditional on policy approval and evidence from the selected
MongoDB, Redis/Channels, Celery, SMTP, Firebase, proxy, monitoring, and recovery
topology.

| Area | Status | Summary |
| --- | --- | --- |
| REST inbox | Implemented | Eight authenticated operations provide bounded listing/counting, atomic read mutations, deletion/clear, and device registration. |
| WebSocket inbox | Implemented; deployment-gated | Authenticated connection, ping/pong, mark-read, notification/state events, live revalidation, and abuse bounds are locally covered. |
| Shared delivery | Implemented | Encrypted intent, idempotency, leases, per-channel checkpoints, retries, reconciliation, and worker-loss handling protect shared producers. |
| Loan/document delivery | Implemented in owning modules | Their domain outboxes own loan/document retry and reconciliation guarantees. |
| Email | Implemented; deployment-gated | Template rendering, mandatory/optional policy, suppression, bounded retry, and durable worker execution are available. |
| FCM push | Implemented; deployment-gated | Encrypted role/session-qualified tokens, batching, partial-result handling, invalid-token cleanup, and retry checkpoints are available. |
| Privacy lifecycle | Implemented; policy-gated | Encryption, safe lookup digests, bounded export, retention, legal holds, deletion, and held-row pseudonymization are integrated. |
| MongoDB schema/indexes | Implemented; real-Mongo proof pending | Inventory, dry-run backfill, strict validators, compound indexes, fail-closed installation, and an opt-in suite exist. |
| Observability | Implemented; deployment proof pending | Low-cardinality metrics, health, Prometheus rules/tests, a smoke config, Grafana dashboard, and release checker are present. |
| Local automated validation | Passing | Current focused Notifications suite: 90 passed on 2026-08-29. |
| Deployment validation | Pending | Real MongoDB, Redis/Channels/Celery, SMTP, Firebase, HTTPS/WSS/load, monitoring/alerts, backup, and recovery evidence remain. |

## Module Responsibilities

### Role-qualified inbox

- Persist notification content, channel/delivery compatibility state, and an
  independent authoritative `is_read/read_at` state.
- List and count only rows belonging to the authenticated `(user_type,
  user_id)` pair.
- Atomically mark one notification read and report idempotent replay.
- Mark all unread notifications in a bounded snapshot.
- Delete one eligible notification or clear a bounded owner snapshot while
  preserving legally held rows.
- Publish owner-group state events after REST or WebSocket mutations.
- Keep REST retrieval authoritative after reconnect, missed real-time frames,
  process restart, or mobile app focus.

### Durable multi-channel delivery

- Persist shared notification intent in `notification_deliveries` before broker
  publication for producers that do not own a domain-specific outbox.
- Bind each event/recipient operation to stable idempotency material stored as a
  safe lookup digest.
- Claim work with a lease and execute through a late-acknowledged dedicated
  Celery task with worker-loss rejection.
- Track in-app, email, and push progress independently.
- Checkpoint the inbox record and successful/permanently rejected push-token
  fingerprints so retry does not resend known outcomes.
- Apply bounded attempts and backoff, then expose terminal/retryable state to
  reconciliation and monitoring.
- Reconcile stale or due deliveries without repeating the business-domain
  mutation that created the notification.

Loans and Documents retain their own durable delivery outboxes because their
delivery intent is coupled to financial/document lifecycle mutations. The
shared Notifications outbox owns assignment, account-security, and other
notification-creator channel work not protected by those domain outboxes.

### Device tokens and push

- Register or refresh Android, iOS, and web FCM tokens for the authenticated
  owner and current session.
- Encrypt token values and use non-reversible fingerprints for uniqueness and
  delivery checkpointing.
- Reject active cross-owner token claims and enforce per-account active-device
  limits.
- Validate token shape/length and platform before storage.
- Expire registrations, update last-used state, deduplicate refreshes, and
  deactivate tokens on explicit unregister, logout/session invalidation, or
  account deletion.
- Batch FCM multicast work at no more than 500 tokens.
- Process per-token success, permanent invalidation, and transient failures
  without logging raw tokens, credentials, or provider response bodies.

### Email and preference policy

- Render approved HTML/text template pairs through the canonical email sender.
- Send email asynchronously through durable domain/shared delivery workers.
- Consult Profiles-owned notification preferences before optional customer
  email delivery.
- Apply `email_loan_updates` to loan/document status updates,
  `email_payment_reminders` to reminders, and `email_promotions` to promotional
  messages.
- Keep payment receipts, staff workflow messages, and account-security notices
  mandatory.
- Record the preference decision and policy version without suppressing the
  in-app inbox record.

### Authenticated real-time delivery

- Authenticate the WebSocket through the shared JWT/session/account security
  boundary.
- Join role-qualified groups using `notifications_<role>_<id>` so identical raw
  IDs in different account domains cannot share events.
- Emit `connection_established`, `pong`, `notification`, and `inbox_state`
  frames and support only client `ping` and `mark_read` actions.
- Revalidate token expiry, live account status, forced-password state, security
  version, and session membership for every action and on a bounded timer.
- Close idle, oversized, binary, over-rate, over-connection, or security-stale
  connections with stable close codes.

### Privacy and account lifecycle

- Encrypt recipient/content, metadata, related identifiers, provider/error
  details, legal-hold reasons, raw delivery keys, and device-token values using
  the shared field-encryption lifecycle.
- Use digests/fingerprints for operational lookup and uniqueness.
- Export a bounded owner-qualified notification list with explicit total,
  returned, limit, and truncation metadata.
- Delete inbox, shared-delivery, and token data during account cleanup.
- Preserve legally held inbox evidence through pseudonymization rather than
  leaving an active customer link.
- Enforce bounded retention for inbox records, terminal delivery work, expired
  tokens, and old inactive registrations.

### Operational visibility

- Export low-cardinality REST outcomes/latency, delivery/channel outcomes,
  retries/terminal failures, backlog/oldest age, token invalidation, WebSocket
  connections/actions, active sockets, broadcasts, and collector freshness.
- Report identifier-free Notifications health through the shared health API.
- Provide Prometheus recording/alert rules, rule tests, a smoke configuration,
  and an importable Grafana dashboard under `monitoring/notifications/`.
- Provide bounded scheduled collection and a read-only fail-closed deployment
  release check.

## API Status

All REST endpoints use `CustomJWTAuthentication`, require `IsAuthenticated`,
and accept customer, loan-officer, administrator, and super-administrator roles.

### REST API

| Method and path | Status | Contract |
| --- | --- | --- |
| `GET /api/notifications/` | Implemented | Owner-scoped page with optional unread/channel filters, pagination totals, and unread count. |
| `GET /api/notifications/unread-count/` | Implemented | Counts owner rows whose independent read state is unread. |
| `POST /api/notifications/mark-all-read/` | Implemented | Marks a bounded owner snapshot read and broadcasts state. |
| `POST /api/notifications/<notification_id>/read/` | Implemented | Atomic owner-qualified mark-read with explicit replay metadata. |
| `DELETE /api/notifications/<notification_id>/` | Implemented | Deletes one owned non-held row; inaccessible rows are concealed. |
| `DELETE /api/notifications/clear-all/` | Implemented | Deletes a bounded owner snapshot and reports deleted/retained counts. |
| `POST /api/notifications/register-token/` | Implemented | Registers or refreshes an encrypted token for the authenticated owner/session. |
| `DELETE /api/notifications/register-token/` | Implemented | Deactivates the caller-owned matching token. |

List queries accept only `page`, `page_size`, `unread`, and `channel`.
`page_size` must be between 1 and 100; excessive offsets return HTTP 400 rather
than issuing an unbounded query. Mark-all and clear-all return HTTP 409 when the
configured synchronous bound would be exceeded.

Mark-read responses expose `notification_id`, `is_read`, `read_at`,
`delivery_status`, and `replayed`. The stored/public `status` field remains a
delivery-state compatibility field; clients must use `is_read` for read state.
Legacy rows using `status: read` remain readable until backfilled.

Common response behavior includes:

- HTTP 400 for invalid IDs, filters, booleans, pagination, token data, or
  unsupported platforms;
- HTTP 401 for missing, invalid, revoked, or inactive authentication;
- HTTP 403 for unsupported account roles;
- HTTP 404 for missing or cross-owner notification/token operations;
- HTTP 409 for bulk limits, concurrent read-state conflicts, legal holds,
  active cross-owner token claims, or active-device limits; and
- HTTP 429 for the dedicated read, write, or device-token throttle.

### WebSocket API

`GET /ws/notifications/` upgrades through `AllowedHostsOriginValidator` and
`JWTAuthMiddleware`.

| Frame or action | Direction | Status | Contract |
| --- | --- | --- | --- |
| `connection_established` | Server | Implemented | Includes unread count, contract version, and `sync_required: true`. |
| `ping` / `pong` | Client/server | Implemented | Liveness action/timestamp under the socket action limit. |
| `mark_read` | Client/server | Implemented | Atomic role-qualified mutation with `replayed` response. |
| `notification` | Server | Implemented | Best-effort owner-group event; REST remains the recovery source. |
| `inbox_state` | Server | Implemented | Cross-device mark-one, mark-all, delete, or clear state signal. |

Missing/rejected credentials close with `4001`; post-connect security
invalidation closes with `4002`; idle timeout with `4003`; the per-process
owner connection limit with `4004`; and binary/oversized frames with `4005`.

Staff browsers authenticate with the HttpOnly access cookie and must not send
staff tokens through a query string or subprotocol. Customer query/subprotocol
access-token support remains a temporary mobile compatibility path.

## Delivery Semantics

Inbox, channel attempt, provider acceptance, broadcast publication, and user
receipt have separate meanings:

- An inbox write proves that the backend stored a retrievable record.
- A `delivered` email/push channel state means the provider accepted the attempt
  according to its API; it does not prove that a person read it.
- WebSocket broadcast publication is best effort; clients can disconnect or
  miss frames after publication.
- If SMTP/FCM accepts a request but the worker loses its acknowledgement before
  checkpointing, a retry may repeat the external attempt. External channel
  delivery is therefore at-least-once under that uncertainty.
- Idempotency and per-channel checkpoints prevent repeat business mutations,
  duplicate inbox rows, and known completed push-token sends.
- REST refresh after connect/reconnect or app focus is the authoritative
  consistency mechanism.

## Security and Privacy Features

### Authentication, authorization, and ownership

- REST uses custom JWT authentication, active-session checks, account state,
  and role allowlisting.
- WebSocket authentication enforces token purpose/signature, blacklist, live
  account, session, security version, and forced-password state at connect and
  after connect.
- Queries, mutations, token ownership, and Channels groups use both normalized
  owner type and owner ID.
- Cross-owner notification/token operations are concealed.
- Browser cookie handshakes are protected by allowed-host/origin validation.
- Staff tokens are prohibited from JavaScript-readable WebSocket transports.

### Input, abuse, and resource bounds

- Strict query allowlists, boolean parsing, page size, maximum offset, and bulk
  mutation ceilings bound REST work.
- Separate authenticated throttles protect reads, writes, and device-token
  operations.
- WebSocket actions, message bytes/types, idle lifetime, and per-process
  connections per owner are bounded.
- FCM batches never exceed the provider's 500-token maximum.
- Delivery attempts, backoff, lease duration, export size, retention work, and
  reconciliation batches are bounded.

### Data protection and minimization

- Sensitive notification, delivery, token, error, related-resource, and hold
  fields use versioned application-level encryption.
- Device identity and idempotency uniqueness use non-reversible
  fingerprints/digests rather than raw secrets.
- API/WebSocket payloads omit recipient address/name, delivery keys, stored
  errors, provider bodies, and encrypted internal material.
- Logs record stable event type/outcome/count metadata rather than recipient
  IDs, email addresses, subject/message text, provider bodies, or raw tokens.
- Prometheus labels omit customer IDs, recipient data, messages, tokens, and
  provider response contents.

### Privacy lifecycle

- Export is bounded and explicitly reports whether results were truncated.
- Legal holds prevent single deletion and retention expiry.
- Clear-all removes eligible records while reporting the held records retained.
- Account cleanup deletes active delivery credentials and pseudonymizes held
  evidence.
- Retention policy and mandatory-versus-optional message categories are
  versioned and require deployment-owner approval.

## Persistence and Data Model

The module owns three MongoDB collections:

| Collection | Responsibility |
| --- | --- |
| `notifications` | Owner inbox content, read state, delivery compatibility state, related context, retention, and legal hold. |
| `device_tokens` | Encrypted role/session-qualified FCM registrations, fingerprints, expiry, activity, and invalidation. |
| `notification_deliveries` | Encrypted shared delivery intent, idempotency digest, lease/retry state, and per-channel checkpoints/outcomes. |

Strict JSON-schema validators cover all three collections. Compound indexes
support owner/date pages, owner/read and owner/channel filters, retention,
delivery reconciliation/history, active/session tokens, expiry, and inactive
cleanup. Notification and delivery idempotency use SHA-256 lookup digests;
device-token uniqueness uses a non-reversible fingerprint.

`init_db.py` invokes the fail-closed schema installer. Installation refuses to
change indexes or validators while bounded inventory is incomplete or detects
legacy read state, missing/invalid ownership, missing retention, plaintext,
invalid timestamps/platforms, missing token/session/expiry data, or duplicate
unique keys.

## Operational Notes

### Management commands

| Command | Purpose |
| --- | --- |
| `notification_data_inventory` | Read-only bounded inventory of inbox, shared-delivery, and token legacy/privacy/schema blockers. |
| `backfill_notification_data` | Dry-run-first conditional repair of safe deterministic legacy shapes. |
| `encrypt_sensitive_fields` | Shared inventory, encryption, rotation, and verification for declared Notifications fields. |
| `install_notification_schema` | Dry-run-first fail-closed index/validator installation after clean inventory. |
| `notifications_release_check` | Read-only, fail-closed configuration, persistence, task, health, monitoring, and evidence summary. |
| `toggle_prometheus` | Local wrapper for enabling/disabling the shared Prometheus runtime configuration. |

For an approved existing MongoDB target, use this order:

1. Run `notification_data_inventory --limit 10000` and increase the limit if
   any collection is incomplete.
2. Take and restore-test an encrypted backup.
3. Run `backfill_notification_data` without `--apply`; review the counts, then
   apply only with explicit authorization.
4. Run `encrypt_sensitive_fields`, apply reviewed encryption/rotation, and use
   `--verify` after completion.
5. Repeat notification inventory until complete and clean.
6. Run `install_notification_schema` without `--apply`, review blockers, then
   apply the schema only after approval.
7. Repeat inventory and verify representative query plans.

Do not run `init_db.py`, a backfill/encryption `--apply`, or schema installation
against a shared/production database without reviewed inventory, backup,
explicit target approval, and a rollback plan. Keep previous field keys until
all relevant ciphertext has been rotated and verified.

### Background tasks

| Celery task | Responsibility |
| --- | --- |
| `notifications.deliver` | Claim and execute one shared multi-channel delivery. |
| `notifications.reconcile_deliveries` | Requeue due/stale shared delivery work in bounded batches. |
| `notifications.enforce_retention` | Delete due non-held inbox rows, old terminal deliveries, and expired/inactive tokens. |
| `notifications.collect_operational_metrics` | Refresh identifier-free backlog, age, failure, and health state. |

A worker must explicitly consume the dedicated `notifications` queue, and
Celery Beat must run the reconciliation, retention, and metrics schedules.
Loans and Documents also require their own domain outbox workers/reconcilers.

### Runtime defaults

| Setting | Default | Purpose |
| --- | ---: | --- |
| `NOTIFICATIONS_MAX_OFFSET` | `10000` | Deep-pagination bound. |
| `NOTIFICATIONS_BULK_MUTATION_LIMIT` | `1000` | Synchronous mark-all/clear ceiling. |
| `NOTIFICATIONS_READ_RATE` | `600/hour` | Per-authenticated-owner read rate. |
| `NOTIFICATIONS_WRITE_RATE` | `300/hour` | Inbox mutation rate. |
| `NOTIFICATIONS_DEVICE_TOKEN_RATE` | `60/hour` | Device registration/unregistration rate. |
| `NOTIFICATIONS_DEVICE_TOKEN_TTL_DAYS` | `180` | Registration expiry. |
| `NOTIFICATIONS_MAX_ACTIVE_DEVICE_TOKENS` | `20` | Active registrations per owner. |
| `NOTIFICATIONS_FCM_BATCH_SIZE` | `500` | Maximum provider multicast batch. |
| `NOTIFICATIONS_DELIVERY_MAX_ATTEMPTS` | `5` | Shared delivery attempt ceiling. |
| `NOTIFICATIONS_DELIVERY_LEASE_SECONDS` | `300` | Shared worker lease. |
| `NOTIFICATIONS_RETENTION_DAYS` | `365` | Inbox retention. |
| `NOTIFICATIONS_DELIVERY_RETENTION_DAYS` | `90` | Terminal delivery retention. |
| `NOTIFICATIONS_INACTIVE_TOKEN_RETENTION_DAYS` | `30` | Inactive token retention. |
| `NOTIFICATIONS_WS_ACTIONS_PER_MINUTE` | `120` | Per-socket action limit. |
| `NOTIFICATIONS_WS_REVALIDATE_SECONDS` | `30` | Active security recheck interval. |
| `NOTIFICATIONS_WS_IDLE_TIMEOUT_SECONDS` | `300` | Idle connection timeout. |
| `NOTIFICATIONS_WS_MAX_MESSAGE_BYTES` | `16384` | Maximum client frame payload. |
| `NOTIFICATIONS_WS_MAX_CONNECTIONS_PER_USER` | `5` | Per-process owner connection limit. |

Deployment owners must approve retention, preferences, rate/capacity limits,
provider quotas, connection bounds, health thresholds, and alert thresholds.

### Monitoring and incident handling

- Import `monitoring/notifications/prometheus-rules.yml` and
  `monitoring/notifications/grafana-dashboard.json`; checked-in thresholds are
  starting points, not approved service-level objectives.
- Monitor each domain/shared outbox separately because they own different event
  sources and recovery paths.
- Diagnose delivery using durable status, channel outcomes, attempt count,
  backlog age, and collector freshness—not inbox count alone.
- On broker/provider failure, preserve delivery IDs, leases, and channel
  checkpoints; do not manually reset encrypted payloads or successful-token
  fingerprints.
- Keep metrics, SMTP, Firebase, and Redis endpoints private and keep credentials
  in the deployment secret store.
- Define provider acceptance and user receipt separately in runbooks and support
  communications.

## Client Notes

- Customer mobile, loan-officer web, and administrator web clients use the same
  owner-scoped REST contract; the backend derives role-qualified ownership.
- Use `is_read` and `read_at` as the read-state contract. Do not infer read state
  from `status`; `delivery_status` describes inbox/channel compatibility state.
- For an empty inbox, `pagination.total_pages` is `0`.
- Refresh inbox and unread count after WebSocket connect/reconnect, application
  focus, or a suspected missed event. `sync_required: true` explicitly requests
  that refresh.
- Handle WebSocket `notification` and `inbox_state` as best-effort hints, not as
  the sole source of persisted inbox truth.
- The WebSocket accepts only `ping` and `mark_read`; use REST for mark-all,
  deletion, clear-all, listing, and token lifecycle.
- Staff web clients must use the HttpOnly access cookie. Never place staff JWTs
  in URLs, subprotocols, JavaScript storage, or client logs.
- Customer mobile query/subprotocol JWT support is temporary; plan a coordinated
  migration to a safer transport before removing compatibility.
- Register/refresh a token after login with the approved platform and unregister
  it during explicit device removal. Normal logout also deactivates tokens
  bound to the session.
- Do not silently transfer a token after HTTP 409 ownership or device-limit
  errors.
- Mark-all/clear may return HTTP 409 when the synchronous limit is exceeded;
  clients should narrow the action or use the future asynchronous contract if
  one is introduced.
- Single deletion of a legally held notification returns
  `NOTIFICATION_LEGAL_HOLD`; clear-all returns both `deleted_count` and
  `retained_count`.
- Optional email preference changes do not remove in-app notifications or
  mandatory security, receipt, and staff messages.
- Account export keeps the `notifications` list and adds
  `notification_export` completeness metadata.

## Validation Evidence

Current repository evidence:

- Focused Notifications suite: **90 passed** on 2026-08-29.
- The focused command covers routed inbox behavior, owner isolation, REST and
  WebSocket state, template sender behavior, durable delivery, privacy,
  persistence declarations, resilience, observability, assignment events, and
  timestamp serialization.
- Release-tooling selection: **6 passed and 8 real-service probes skipped** on
  2026-08-29; the probes correctly remain opt-in without approved targets.
- Mocked installed-version FCM tests cover success, batching, partial results,
  permanent/transient failures, encryption, ownership, deduplication, expiry,
  unregister, logout/session revocation, and account cleanup.
- Local WebSocket tests use real ASGI routing/token/session behavior but an
  in-memory channel layer; email tests mock transport.

The opt-in isolated real-Mongo and deployment probes exist but have not been
executed against a final target. Passing mocks are not evidence of real
MongoDB, Redis, Celery, SMTP, Firebase, HTTPS/WSS, monitoring, or load behavior.

The latest full repository attempt on 2026-08-29 completed with **1,364 passed,
55 opt-in tests skipped, and 4 failed**. All four failures were in Documents
upload/finalization tests because the configured local ClamAV service refused
the connection. They do not indicate a Notifications regression, but the full
repository release gate must be repeated after the scanner is available.

## Remaining Gaps and Release Conditions

No known application-code stage remains for the reviewed Notifications
baseline. The following conditions remain for production certification:

1. Against a reviewed deployment copy, run a complete notification inventory,
   backfill and encryption dry runs, reconcile duplicates/blockers, take and
   restore-test an encrypted backup, apply approved changes, install validators
   and indexes, and repeat inventory.
2. Run the isolated real-Mongo suite to prove invalid-write rejection,
   uniqueness, role-qualified token ownership, atomic mutations, retention, and
   indexed query plans at representative cardinality.
3. Prove Redis Channels fan-out across multiple ASGI processes and shared
   connection/rate behavior through the selected aggregate proxy controls.
4. Prove at least two deployed Notifications workers consume the dedicated
   queue and safely recover broker outages, stale leases, worker termination,
   Beat overlap, and provider timeout before/after acceptance.
5. Validate SMTP and Firebase using approved synthetic recipients/tokens;
   exercise success, rejection, partial failure, invalid-token cleanup, retry,
   and credential isolation.
6. Test exact host/origin, cookie, HTTPS/WSS, frame, timeout, backpressure,
   reconnect, and representative load behavior through the deployed proxy.
7. Generate representative REST/WebSocket/delivery traffic, inspect Prometheus
   and Grafana series, calibrate thresholds, and prove alert delivery/recovery.
8. Obtain authorized product/privacy/security approval for retention periods,
   preference defaults, mandatory security notices, and user deletion policy.
9. Rehearse deployed backup/restore, field-key rotation, provider/broker outage,
   incident response, and rollback with named owners and retained evidence.
10. Run final customer/officer/admin inbox and channel smoke flows plus the full
    suite on the release revision, then require every check and `overall` from
    `notifications_release_check` to pass.

Until these conditions pass, the accurate status is **application-complete and
awaiting production-environment validation**, not a certified production
deployment.

## Review Boundaries

This document verifies repository implementation, API contracts, local
automated behavior, and the listed local evidence. It does not certify live
MongoDB indexes/query plans, Redis/Channels/Celery topology, SMTP deliverability,
Firebase acceptance, browser/mobile push receipt, reverse-proxy policy,
production load, monitoring delivery, secret-manager operation, backup
restorability, live customer data, or provider availability.

It does not approve provider terms, retention periods, preference defaults,
mandatory-message classifications, notification wording, marketing consent,
support procedures, on-call ownership, or service-level objectives. Those
require authorized product, privacy, legal/compliance, security, and operations
review for the deployment jurisdiction.

Accounts owns JWT/session/account lifecycle and security-event production.
Profiles owns customer notification preferences. Loans and Documents own their
domain outboxes. Analytics owns protected audit storage. Notifications owns its
inbox, token, shared-delivery, channel, and real-time contracts and must not
represent a provider API response as guaranteed human receipt.

This document describes backend behavior. Customer-mobile and staff-web
presentation, accessibility, offline handling, operating-system push behavior,
and end-to-end usability require separate client validation.

## Related Documentation

- `docs/NOTIFICATIONS_TESTING_GUIDE.md` — endpoint examples, test commands,
  WebSocket/FCM/email behavior, deployment probes, and runbook.
- `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` — JWT/session,
  account lifecycle, security events, and shared encryption contracts.
- `docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md` — customer preferences
  and account-data integration.
- `docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` — document delivery
  outbox and lifecycle behavior.
- `docs/LOANS_PRODUCTION_READINESS_REVIEW.md` — loan delivery outbox and
  assignment producers.
- `docs/analytics/ANALYTICS_PRODUCTION_READINESS_REVIEW.md` — audit and
  monitoring conventions.
