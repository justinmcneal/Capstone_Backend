# Notifications Testing Guide

Last updated: 2026-08-28

## Scope

This guide documents the **Notifications service** under `/api/notifications/` for API testing and implementation review. It covers:

- Notification inbox REST API endpoints
- WebSocket real-time delivery
- Template email and durable domain/shared Celery outbox delivery
- FCM push notifications and device-token registration
- Assignment-lifecycle event notifications
- Shared delivery reconciliation and planned operational monitoring
- Encrypted inbox persistence, bounded export/account cleanup/retention, and
  MongoDB inventory/backfill/schema validation

**Important distinction:** Email **preference settings** (`email_loan_updates`,
etc.) live under **`/api/profile/notifications/`** (Profiles module), not this
API. Notifications now enforces those settings for optional email; they do not
suppress the inbox or mandatory communications.

## Architecture Overview

Notifications combines multiple channels with explicit durable owners:

- **REST API**: fetch/manage inbox, mark read/delete, get unread counts
- **WebSocket**: real-time push of new notifications to connected clients
- **Template Email**: synchronous `EmailSender` calls, normally invoked inside
  the durable Loans/Documents or shared Notifications delivery workers
- **Shared Celery Delivery**: canonical routed tasks claim encrypted leased
  outbox records for producers that do not own a domain outbox
- **FCM Push**: installed-version multicast delivery with bounded batching and
  partial-result checkpointing through the shared asynchronous outbox
- **Assignment/Security Events**: structured, durable shared delivery intent
- **Privacy lifecycle**: encrypted sensitive inbox fields, hashed idempotency/
  event lookup material, bounded export, account erasure/pseudonymization, legal
  holds, and scheduled retention

Depending on the producer, the system can:
1. Persist an in-app record
2. Broadcast it over WebSocket to the owner
3. Send or suppress template email according to the versioned policy
4. Attempt FCM push for registered tokens and checkpoint per-token outcomes

Persistence, WebSocket publication, email acceptance, push acceptance, and
user read state are separate facts. Inbox read state is independent of channel
progress, and external providers remain at-least-once if acceptance happens
before a durable checkpoint.

## Base URL and Auth

- **Base URL:** `http://localhost:8000/api/notifications`
- **Required headers:**
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```
- **Allowed roles:** `customer`, `loan_officer`, `admin`, `super_admin`

## Related Documentation

| Document | Purpose |
|----------|---------|
| `docs/NOTIFICATIONS_PRODUCTION_READINESS_REVIEW.md` | Notifications module review, risks, and roadmap |
| `docs/LOANS_TESTING_GUIDE.md` | Loan APIs that trigger notifications |
| `docs/profiles/PROFILES_TESTING_GUIDE.md` | Notification **preferences** (`/api/profile/notifications/`) |

---

## Current Implementation and Test Baseline

The inbox and WebSocket foundations are usable locally, but Notifications is
not production-ready. Confirmed blockers and the remediation stages are tracked
in `NOTIFICATIONS_PRODUCTION_READINESS_REVIEW.md`.

Focused module command:

```bash
.venv/bin/pytest -q \
  tests/test_notifications_api.py \
  tests/test_notifications_views.py \
  tests/test_notifications_mark_read.py \
  tests/test_notification_isolation.py \
  tests/test_notifications_websocket.py \
  tests/test_websocket_notifications.py \
  tests/test_notifications_email_sender.py \
  tests/test_notifications_stage3_delivery.py \
  tests/test_notifications_stage4_privacy_persistence.py \
  tests/test_notifications_stage5_resilience_observability.py \
  tests/test_assignment_notifications.py \
  tests/test_notification_timestamps.py
```

Result after Stage 5 on 2026-08-28: **89 passed**.

Stage 1 routed contract command:

```bash
.venv/bin/pytest -q \
  tests/test_notifications_api.py \
  tests/test_notifications_views.py \
  tests/test_notifications_mark_read.py \
  tests/test_notifications_websocket.py \
  tests/test_websocket_notifications.py \
  tests/test_notification_isolation.py \
  tests/test_notification_timestamps.py \
  tests/test_notifications_stage1_contract.py \
  tests/test_ai_tool_safety_integration.py
```

Result on 2026-08-27: **78 passed**. This includes real URL routing and issued
JWT/session evidence rather than relying only on direct view calls.

Stage 2 push/token command:

```bash
.venv/bin/pytest -q tests/test_notifications_stage2_push.py
```

Result on 2026-08-27: **14 passed**. This verifies the API selected from the
installed Firebase package, batching, partial outcomes, permanent/transient
failures, encryption, role/session ownership, hostile reassignment rejection,
deduplication, expiry, unregister, logout/session revocation, and account
cleanup without contacting Firebase.

Stage 3 shared-delivery command:

```bash
.venv/bin/pytest -q tests/test_notifications_stage3_delivery.py
```

Result on 2026-08-28: **12 passed**. This verifies canonical registration and
routing, encrypted idempotent intent, broker-publication recovery, atomic and
stale leases, inbox replay repair, email policy/suppression, bounded email
retry, mandatory-event handling, partial push checkpoints, and durable
assignment/security publication.

Affected Notifications/cross-domain regression result on 2026-08-28:
**129 passed**.

Stage 4 privacy/persistence command:

```bash
.venv/bin/pytest -q \
  tests/test_notifications_stage4_privacy_persistence.py \
  tests/test_notifications_stage4_real_mongo.py
```

Local result on 2026-08-28: **8 passed and 1 opt-in real-Mongo test skipped**.
This covers encrypted core fields, digest-only lookup material, bounded export,
account cleanup and legal-hold pseudonymization, retention, sanitized email
logging, dry-run backfill, indexes/validators declarations, and task routing.

Stage 5 resilience/observability command:

```bash
.venv/bin/pytest -q \
  tests/test_notifications_stage5_resilience_observability.py
```

Local Stage 5 result on 2026-08-28: **7 passed** across the dedicated suite and
live routed session-revocation case. It covers live-session closure,
frame and connection bounds, reconnect metadata, cross-device state events,
identifier-free backlog health, task scheduling, and monitoring assets.

Broader cross-domain selection:

```bash
.venv/bin/pytest -q tests accounts/tests \
  -k 'notification or websocket or email_template or email_tls'
```

Result after Stage 2 on 2026-08-27: **131 passed, 1,245 deselected**. The latest
full repository result after Stage 6 tooling on 2026-08-28 is **1,362 passed,
54 skipped**.

Evidence limits:

- Most REST tests call views directly and bypass `require_roles`; they verify
  query/mutation behavior but not real URL/JWT/session enforcement.
- WebSocket security tests do use ASGI routing and real issued token/session
  behavior, but use an in-memory channel layer rather than deployed Redis.
- Email tests mock rendering/transport. No SMTP message is sent.
- Stage 2 has mocked installed-API FCM and routed device-lifecycle evidence;
  live Firebase receipt remains deployment-only evidence.
- Stage 3 worker/broker, Stage 4 privacy/schema, and Stage 5 socket/monitoring
  cases are deterministic local tests. The isolated real-Mongo suite now exists
  but was not opted in; no multi-worker Redis/Celery, HTTPS/WSS, load,
  backup/restore, live monitoring/alert-delivery, or deployment probe has run.

### Stage validation map

| Stage | Primary evidence required | Current status |
| --- | --- | --- |
| Stage 1 — Contract and owner-safe inbox | Routed auth/role/owner tests, independent read/delivery state, atomic replay, bounds/throttles | Complete locally; 78 focused tests pass |
| Stage 2 — Secure working push | Installed Firebase API, role-qualified token ownership, validation, revoke/cleanup, provider batching | Complete locally; 14 focused tests pass |
| Stage 3 — Durable preference-aware delivery | Registered/routed tasks, leases/retries, broker/worker/provider recovery, preference policy | Complete locally; 12 focused tests pass |
| Stage 4 — Privacy and MongoDB correctness | Encryption/log safety, lifecycle/export, validators/indexes, inventory/backfill, real-Mongo plans | Complete locally; 8 tests pass, isolated real-Mongo execution pending |
| Stage 5 — WebSocket resilience/observability | Post-connect revocation/expiry, limits, cross-device sync, metrics/rules/dashboard/health | Complete locally; 7 focused tests pass, deployment proof pending |
| Stage 6 — Deployment validation | Real MongoDB/Redis/Celery/SMTP/FCM/HTTPS/WSS/load/recovery and release checker | Tooling complete locally; 5 release-gate tests pass and 7 real-service probes skip pending targets |

Do not turn a missing external-service test into a passing mock. Add each stage's
focused evidence with its implementation and retain opt-in gates for tests that
mutate or contact real services.

---

## Reference Values

### Notification Types (`notification_type`)

| Type | Typical Recipient | Related Entity |
|------|-------------------|----------------|
| `loan_submitted` | Customer | `loan` |
| `loan_approved` | Customer | `loan` |
| `loan_rejected` | Customer | `loan` |
| `loan_disbursed` | Customer | `loan` |
| `payment_received` | Customer | `loan` |
| `missing_documents_requested` | Customer | `loan` |
| `document_flagged` | Customer | `document` |
| `document_verified` | Customer | `document` |
| `document_pending_review` | Loan officer / reviewer | `document` |
| `new_application` | Loan officer | `loan` (helper exists; no current producer calls it) |
| `application_assigned` | Admin / new loan officer | `loan` |
| `application_reassigned` | Assigning admin | `loan` |
| `application_unassigned` | Previous loan officer | `loan` |
| `welcome` | Customer | — |
| `password_reset` | User | — |

### Channels (`channel`)

Inbox rows use `email` or `in_app`. Shared delivery records may request
`email`, `in_app`, and/or `push`.

The model default is `email`, but shared email helpers explicitly create one
`in_app` row and reuse it to track the SMTP attempt. They do not create a
separate email-channel row.

### Delivery Statuses (MongoDB `status` field)

`status` is now a backward-compatible alias for delivery state. New and
rewritten records also expose the same value as `delivery_status`; read state
is independent.

| Status | Meaning |
|--------|---------|
| `pending` | Record created; email not yet sent |
| `sent` | Email delivered successfully |
| `failed` | Email send failed (`error_message` set) |
| `unknown` | Delivery outcome is unavailable, including a loaded legacy `status: read` row |

Legacy `status: read` rows are interpreted as `is_read: true` and
`delivery_status: unknown` until Stage 4 inventory/backfill. The shared/domain
outbox is the authoritative processing record; an inbox `sent` value is not
proof that an external provider or end user received the message.

### Unread Logic

A current notification is unread when `is_read` is false. Compatibility queries
also treat a legacy `status: read` row as read. Delivery statuses `pending`,
`sent`, `failed`, and `unknown` do not decide inbox read state.

### Boolean Query Values (`unread` param)

Accepted: `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off` (case-insensitive). Omit or leave empty to disable filter.

### Related Types (`related_type` in records)

`loan`, `document` (and others as logged)

---

## Ownership and Access Rules

Who sees which notifications depends on role:

| Role | Ownership query |
|------|-----------------|
| `customer` | `user_id` = authenticated `customer_id` **AND** `user_type` = `customer` |
| `loan_officer` | `user_id` = officer ID **AND** `user_type` = `loan_officer` |
| `admin` / `super_admin` | `user_id` = admin ID **AND** `user_type` = `admin` |

Users can only mark read / list notifications they own. Accessing another user's notification ID returns `404 Not Found`.

HTTP ownership checks and WebSocket groups are role-qualified. Users from separate account collections cannot share notifications even if their raw IDs are identical. The `super_admin` authentication role is normalized to the stored `admin` notification type.

This guarantee extends to `Notification.find_by_user`, customer account export,
the AI notification-status tool, and current device-token registration,
retrieval, unregistration, and provider fan-out.

---

## Automatic Trigger Map (populate inbox for testing)

Loan and document domain services call
`notifications/services/email_sender.py` from their own delivery workers. Use
these APIs to generate test data, while checking both the domain outbox and the
core inbox record:

| Notification Type | Triggering API | Actor |
|-------------------|----------------|-------|
| `loan_submitted` | `POST /api/loans/apply/` | Customer |
| `loan_approved` | `PUT /api/loans/officer/applications/<id>/review/` (`action: approve`) | Officer |
| `loan_rejected` | `PUT /api/loans/officer/applications/<id>/review/` (`action: reject`) | Officer |
| `loan_disbursed` | `POST /api/loans/officer/applications/<id>/disburse/` | Officer |
| `payment_received` | `POST /api/loans/officer/payments/` | Officer |
| `missing_documents_requested` | `POST /api/loans/officer/applications/<id>/request-missing-documents/` | Officer |
| `application_assigned` / `application_reassigned` / `application_unassigned` | Auto/manual assign or reassign (`loans/services/assignment.py`) | System / Admin |
| `document_pending_review` | `POST /api/documents/upload/` | Customer |
| `document_verified` | `PUT /api/documents/<id>/verify/` (approve) | Officer |
| `document_flagged` | `PUT /api/documents/<id>/verify/` (reject) or `POST /api/documents/<id>/request-reupload/` | Officer |

Loans/Documents persist recoverable delivery records before their task is
published. Assignment, account-security, and notification-creator push events
use `notification_deliveries`. Optional customer email evaluates Profiles
preferences; in-app and mandatory communications remain unaffected.

---

## Stored Notification Record (MongoDB schema)

Full fields in `notifications` collection (not all exposed in list API):

| Field | Type | Description |
|-------|------|-------------|
| `_id` | ObjectId | Primary key (exposed as `id` in API) |
| `user_id` | string | Owner user ID |
| `user_type` | string | `customer`, `loan_officer`, `admin` |
| `recipient_email` | encrypted string | Email address; never exposed by inbox API |
| `recipient_name` | encrypted string | Display name; never exposed by inbox API |
| `notification_type` | string | See Reference Values |
| `subject` | encrypted string | Short subject line; transparently decrypted by the model |
| `message` | encrypted string | Body text; transparently decrypted by the model |
| `related_type` | string | `loan`, `document`, etc. |
| `related_id` | encrypted string | Linked entity ID |
| `metadata` | encrypted string | Encrypted structured event context |
| `idempotency_key` | encrypted string/null | Optional raw producer key; never queried or exposed |
| `idempotency_key_hash` | string/null | SHA-256 lookup/unique digest for idempotent replay |
| `channel` | string | `email` or `in_app` |
| `status` | string | Delivery compatibility alias: `pending`, `sent`, `failed`, `unknown` |
| `delivery_status` | string | Explicit delivery state matching `status` |
| `is_read` | boolean | Authoritative inbox read state |
| `error_message` | encrypted string | Stable non-provider failure code |
| `created_at` | datetime | Record creation time; API/WebSocket responses use an explicit UTC ISO 8601 value (for example, `2026-07-23T02:15:00Z`) |
| `sent_at` | datetime | When email was sent; API responses use an explicit UTC ISO 8601 value when present |
| `read_at` | datetime/null | Set once when marked read via API |
| `retention_expires_at` | datetime | Configured retention deadline |
| `legal_hold` | boolean | Prevents inbox deletion and scheduled retention |
| `legal_hold_reason` | encrypted string | Approved operational hold rationale |

Core sensitive fields, device-token values, and shared-delivery recipient/
payload fields use the shared field-encryption key lifecycle. User/role,
status, timestamps, channel, and digest fields remain queryable. Strict MongoDB
validators enforce the operational shape after the fail-closed schema workflow.

---

# Inbox API Endpoints

---

### 1. `GET /`

List notifications for the authenticated user (newest first).

**Request body:** none

**Query params (all optional):**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `page` | int | 1 | >= 1 |
| `page_size` | int | 20 | 1–100 |
| `unread` | boolean | (no filter) | `true`/`false`/`1`/`0`/`yes`/`no`/`on`/`off` — when `true`, only unread items |
| `channel` | string | (no filter) | `email` or `in_app` |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `notifications` | array |
| `notifications[].id` | string |
| `notifications[].notification_type` | string |
| `notifications[].subject` | string |
| `notifications[].message` | string |
| `notifications[].related_type` | string |
| `notifications[].related_id` | string |
| `notifications[].metadata` | object |
| `notifications[].channel` | string |
| `notifications[].status` | delivery-status compatibility string |
| `notifications[].delivery_status` | explicit delivery-status string |
| `notifications[].is_read` | boolean |
| `notifications[].read_at` | ISO datetime or null |
| `notifications[].created_at` | ISO datetime |
| `notifications[].sent_at` | ISO datetime |
| `unread_count` | int | Total unread for user (ignores current page filters) |
| `pagination` | object |
| `pagination.page` | int |
| `pagination.page_size` | int |
| `pagination.total_items` | int |
| `pagination.total_pages` | int |
| `pagination.has_next` | boolean |
| `pagination.has_previous` | boolean |

**Example:**
```
GET /api/notifications/?page=1&page_size=20&unread=true&channel=email
```

---

### 2. `GET /unread-count/`

Unread badge count for the authenticated user.

**Request body:** none

**Query params:** none

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `unread_count` | int | Count using independent read state with legacy compatibility |

**Example:**
```
GET /api/notifications/unread-count/
```

---

### 3. `POST /mark-all-read/`

Mark all owned unread notifications as read.

**Request body:** none

**Query params:** none

**Behavior:**
- Selects a stable owner-qualified snapshot up to
  `NOTIFICATIONS_BULK_MUTATION_LIMIT`
- Sets `is_read = true` and `read_at`; delivery status is unchanged
- Returns HTTP 409 before mutation if the inbox exceeds the synchronous bound

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `marked_count` | int | Number of records updated |

**Example:**
```
POST /api/notifications/mark-all-read/
```

---

### 4. `POST /<notification_id>/read/`

Mark a single owned notification as read.

**Path params:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `notification_id` | string | yes | Valid MongoDB ObjectId; must belong to authenticated user |

**Request body:** none

**Query params:** none

**Behavior:**
- Atomically matches the notification ID, normalized owner, and unread state
- Sets `is_read = true` and `read_at`; delivery status is unchanged
- Repeated calls succeed and return `replayed: true`

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `notification_id` | string |
| `is_read` | boolean (`true`) |
| `read_at` | ISO datetime |
| `delivery_status` | string |
| `replayed` | boolean |

**Example:**
```
POST /api/notifications/674a1b2c3d4e5f6789abcdef/read/
```

---

### 5. `DELETE /<notification_id>/`

Delete a single owned notification.

**Auth:** customer, loan_officer, admin, super_admin (ownership-scoped)

**Behavior:**
- Removes the notification record from MongoDB
- Returns `404` if the notification does not exist or is not owned by the current user
- Returns `409 NOTIFICATION_LEGAL_HOLD` when an owned row is retained by policy

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `notification_id` | string |
| `status` | string (`deleted`) |

**Example:**
```
DELETE /api/notifications/674a1b2c3d4e5f6789abcdef/
```

---

### 6. `DELETE /clear-all/`

Delete all eligible owned notifications for the current user. Legally held rows
remain and are reported in `retained_count`.

**Auth:** customer, loan_officer, admin, super_admin

**Behavior:**
- Removes all non-held records matching the owner query
- Cannot affect other users' notifications

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `deleted_count` | int | Number of records removed |
| `retained_count` | int | Number of owned rows preserved by legal hold |

**Example:**
```
DELETE /api/notifications/clear-all/
```

---

### 7. `POST /register-token/`

Register an FCM device token for push notifications.

**Auth:** customer, loan_officer, admin, super_admin

**Request body (JSON):**
```json
{
  "token": "fcm-device-token-at-least-20-characters",
  "platform": "android"
}
```

**Validation:**
- `token` is required, 20–4096 characters, and cannot contain whitespace or
  control characters
- `platform` is required and must be `android`, `ios`, or `web`
- the authenticated JWT must have a live session ID

**Behavior:**
- Stores an encrypted token plus deterministic non-reversible fingerprint
- Binds the registration to normalized user ID, role, and session
- Refreshes the same owner's registration without creating a duplicate
- Rejects an active token owned by another role/account with HTTP 409
- Applies configured active-device and expiry bounds

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `status` | string (`registered`) | Registration confirmation |
| `device_token_id` | string | Internal registration identifier; the raw token is never returned |
| `platform` | string | Normalized approved platform |

**Example:**
```bash
curl -X POST /api/notifications/register-token/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"token": "fcm-token-1234567890abcdef", "platform": "android"}'
```

### 8. `DELETE /register-token/`

Deactivate one token owned by the authenticated account.

```json
{"token": "fcm-token-1234567890abcdef"}
```

Returns `404` for a missing, inactive, or cross-owner token. Normal account
logout also deactivates all token registrations bound to the revoked session;
security-wide session revocation and account deletion deactivate every affected
registration.

---

## Complete URL Index (8 method operations)

| # | Method | URL | Roles |
|---|--------|-----|-------|
| 1 | GET | `/api/notifications/` | Customer, Officer, Admin, Super Admin |
| 2 | GET | `/api/notifications/unread-count/` | Customer, Officer, Admin, Super Admin |
| 3 | POST | `/api/notifications/mark-all-read/` | Customer, Officer, Admin, Super Admin |
| 4 | POST | `/api/notifications/<notification_id>/read/` | Customer, Officer, Admin, Super Admin |
| 5 | DELETE | `/api/notifications/<notification_id>/` | Customer, Officer, Admin, Super Admin |
| 6 | DELETE | `/api/notifications/clear-all/` | Customer, Officer, Admin, Super Admin |
| 7 | POST | `/api/notifications/register-token/` | Customer, Officer, Admin, Super Admin |
| 8 | DELETE | `/api/notifications/register-token/` | Customer, Officer, Admin, Super Admin |

---

## WebSocket Real-Time API

### Connection

**URL:** `wss://<host>/ws/notifications/` in production (`ws://` is local-development only)

**Browser staff auth:** Open `/ws/notifications/` without a JavaScript-readable token. The browser sends the configured HttpOnly access cookie. The access cookie path must cover both `/api/` and `/ws/`; the default is `/`. The refresh cookie remains limited to `/api/auth/` and is never accepted by the WebSocket.

**Customer mobile compatibility:** The customer mobile app may continue to send its access token in the `token` query parameter or as the `access_token`-marked WebSocket subprotocol until a coordinated mobile migration removes those transports. Admin and loan-officer query/subprotocol tokens are rejected.

Mobile query example:
```
ws://localhost:8000/ws/notifications/?token=<access_token>
```

Subprotocol clients send `access_token` plus the access JWT as separate protocol values. Do not put staff tokens into browser JavaScript, URLs, local storage, logs, analytics, or error messages.

All transports use the same live authentication boundary as protected HTTP requests. The handshake validates the access-token signature and purpose, blacklist state, account role/state/verification, session membership, security version, and forced-password state. Missing or rejected credentials close with code `4001`.

### Canonical Server Frames

Every server frame has `type` and `data` at the top level:

```json
{"type":"connection_established","data":{"unread_count":3}}
{"type":"notification","data":{"id":"notification-id","subject":"Loan update"}}
{"type":"mark_read_response","data":{"success":true,"notification_id":"notification-id"}}
{"type":"pong","data":{"timestamp":"2026-08-13T10:15:30+00:00"}}
{"type":"error","data":{"code":"invalid_json","message":"Invalid JSON"}}
```

Error codes currently include `invalid_json`, `invalid_message`, `invalid_notification_id`, and `unsupported_action`.

### Supported Actions

| Action | Direction | Description |
|--------|-----------|-------------|
| `ping` | Client → Server | Keepalive; server responds with `pong` + timestamp |
| `mark_read` | Client → Server | Mark a single notification as read over WebSocket |

### Server-Pushed Events

| Event type | Description |
|------------|-------------|
| `connection_established` | Sent on connect; includes current `unread_count` |
| `notification` | New notification broadcast to the owner's group |
| `pong` | Response to client `ping` |
| `mark_read_response` | Result of `mark_read` action |

### Ownership

WebSocket groups are role-qualified: `notifications_<user_type>_<user_id>`. This means:
- A customer and an officer with the same raw ID do **not** share a group
- `super_admin` auth role is normalized to `admin` for group naming

### Notes

- The WebSocket consumer does **not** yet support `mark_all_read`, delete, or unread-count fetch; those still require REST calls.
- Connection lifecycle is handled automatically by Django Channels.
- REST inbox and unread-count endpoints remain authoritative when real-time delivery is unavailable.
- Production must use TLS (`wss://`), exact `ALLOWED_HOSTS`/origin configuration, and a trusted reverse proxy that preserves the `Origin` and `Cookie` headers. CSRF tokens do not authenticate a WebSocket handshake; the origin validator is therefore a required browser-cookie control.
- Never enable wildcard origins or restore browser-readable JWT storage to work around a failed handshake.

---

## FCM Push Notifications

Device tokens are stored in MongoDB (`device_tokens` collection) and used by `notifications/services/notification_creator.py` to send push notifications via Firebase Cloud Messaging.

**Current status: implemented locally; deployment proof pending.** The project
uses the pinned package's `messaging.send_each_for_multicast`, with a maximum
configured batch size of 500. Provider acceptance is still not proof that a
device displayed the notification.

**Lifecycle endpoint:** `POST` and `DELETE /api/notifications/register-token/`

Current stored fields include `user_id`, `user_type`, `session_id`, encrypted
`token`, `token_hash`, `platform`, `is_active`, `created_at`, `updated_at`,
`last_used_at`, `expires_at`, `deactivated_at`, and `deactivation_reason`.
`token_hash` identifies a registration without decrypting or returning the raw
credential; it must never be accepted as a substitute token from a client.

Operational bounds:

| Setting | Development default | Purpose |
| --- | --- | --- |
| `NOTIFICATIONS_DEVICE_TOKEN_TTL_DAYS` | `180` | Registration refresh/expiry window |
| `NOTIFICATIONS_MAX_ACTIVE_DEVICE_TOKENS` | `20` | Per-role/account active-device bound |
| `NOTIFICATIONS_FCM_BATCH_SIZE` | `500` | Maximum tokens per Firebase multicast call |
| `NOTIFICATIONS_DEVICE_TOKEN_RATE` | `60/hour` | Registration/unregistration API throttle |

**Behavior:**
- encrypted token value and fingerprinted lookup identity
- role- and session-qualified owner queries
- safe same-owner refresh/deduplication and hostile reassignment rejection
- strict platform/token/device-count/expiry bounds
- provider batches of at most 500 with ordered partial-result processing
- `UnregisteredError` and `SenderIdMismatchError` deactivate only affected
  tokens; transient failures remain active for bounded shared-delivery retry
- no raw token or provider exception body is written to notification logs
- explicit unregister plus automatic session/logout/security/account cleanup
- push intent is persisted before asynchronous dispatch; known successful and
  permanently rejected token fingerprints are checkpointed so a later retry
  targets only unresolved registrations

**Dependencies:**
- `firebase_admin` Python package
- Firebase service account credentials in environment

The Stage 2 suite mocks the provider boundary and covers complete/partial
success, permanent/transient failures, batching, role-ID collision, hostile
reassignment, encryption, unregister/logout, and account deletion. Do not run
live FCM tests with real customer tokens; use an approved Firebase test project
during Stage 6 deployment validation.

---

## Assignment Event Notifications

`notifications/services/assignment_events.py` publishes notifications for loan-assignment lifecycle events:

| Event | Recipients |
|-------|------------|
| `application_assigned` | Admin who assigned + new assignee |
| `application_reassigned` | Admin who reassigned + new assignee + previous assignee |
| `application_unassigned` | Admin who unassigned + previous assignee |

Assignment notifications:
- Are in-app only (`channel: in_app`)
- Include structured `metadata`: event type, participants, entity, occurrence time
- Deduplicate recipients by `(user_id, user_type)`
- Persist idempotent shared-delivery intent before broker publication
- Do **not** send email or push notifications

---

## Prometheus Metrics

Stage 5 exports Notifications REST outcome/latency, durable and per-channel
delivery outcomes, terminal/retry state, backlog/oldest age, provider token
invalidations, WebSocket connections/actions/broadcasts, active-process sockets,
and collector freshness. Labels contain only bounded method, action, channel,
kind, state, and outcome values—never owner IDs, addresses, tokens, messages, or
provider bodies.

**Toggle command:**
```bash
python manage.py toggle_prometheus enable --url
python manage.py toggle_prometheus status --url
python manage.py toggle_prometheus disable --url
```

The resolved private metrics URL is printed by `--url`; follow the root
`README.md` sidecar instructions rather than assuming `/metrics/` is served by
the public application port.

Validate the repository assets locally:

```bash
promtool check rules monitoring/notifications/prometheus-rules.yml
promtool test rules monitoring/notifications/prometheus-rules.test.yml
promtool check config monitoring/notifications/prometheus-smoke.yml
```

Run Prometheus with `monitoring/notifications/prometheus-smoke.yml` after
enabling the private metrics sidecar. Import
`monitoring/notifications/grafana-dashboard.json` into the same protected
Grafana used for the other domain dashboards.

### Notifications operations runbook

1. For an old/retryable backlog, confirm the Notifications worker consumes the
   `notifications` queue and Beat is scheduling reconciliation and collection.
2. For terminal failures, inspect sanitized stable error codes, provider
   availability, preference policy, and retry exhaustion without exposing PII.
3. For missing metrics, check the private metrics sidecar, minute collector,
   Prometheus target, and Celery Beat/worker health.
4. For authorization-closure spikes, check logout/security events and possible
   stale or hostile clients; do not weaken live-session validation.
5. REST is authoritative after Redis/WebSocket disruption. Clients refresh the
   list and unread count on every connection with `sync_required: true`.

---

## Email Configuration

Set in `.env` to test actual email delivery (optional for inbox API tests — records are created even if email fails):

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=your-email@gmail.com
```

For inbox-only API testing without SMTP, helpers persist/broadcast the inbox row
before the SMTP attempt and then normally change it to `failed`. Do not infer
email delivery from the existence of that row. Loans/Documents retry through
their own outboxes; assignment/security in-app events do not use SMTP.

The canonical tasks are `notifications.deliver` and
`notifications.reconcile_deliveries`. Run a worker that consumes the dedicated
queue during local integration testing:

```bash
celery -A config worker -Q notifications --loglevel=info
celery -A config beat --loglevel=info
```

The first command consumes delivery work; Beat publishes due reconciliation
once per minute. Use synthetic recipients/providers for integration tests.

---

## Smoke Test Sequences

### Inbox API

1. Authenticate as a customer and call `GET /api/notifications/`.
2. Verify empty inbox returns `notifications: []` and `unread_count: 0`.
3. Trigger a notification via another API (e.g. `POST /api/loans/apply/`).
4. Call `GET /api/notifications/` and verify the new record appears.
5. Call `GET /api/notifications/unread-count/` and note the count.
6. Call `POST /api/notifications/<id>/read/` and verify `is_read: true`, an
   unchanged `delivery_status`, and `replayed: false`; repeat and verify
   `replayed: true`.
7. Call `POST /api/notifications/mark-all-read/` and verify `marked_count`.
8. Confirm list/WebSocket payloads use `id`, not `_id`; no single-detail GET
   endpoint exists.
9. Call `DELETE /api/notifications/<id>/` and confirm deletion.
10. Call `DELETE /api/notifications/clear-all/` only with disposable test data
    and confirm role-qualified deletion.
11. Repeat with customer/officer/admin records that deliberately share one raw
    ID and prove isolation.

### Officer Inbox

1. Admin assigns loan to Officer A.
2. Officer A: `GET /api/notifications/` should include `application_assigned`.
3. Officer B: `GET /api/notifications/` should **not** include Officer A's notification.

### Filter Combinations

```
GET /api/notifications/?page=2&page_size=10
GET /api/notifications/?unread=false
GET /api/notifications/?unread=true&channel=email
GET /api/notifications/unread-count/
```

### WebSocket Smoke Test

1. For staff Web, log in with cookie transport and open `/ws/notifications/` without a token in JavaScript or the URL. For customer mobile compatibility, use a valid access query/subprotocol token.
2. Verify `connection_established` message includes `unread_count`.
3. Send `ping` and verify `pong.data.timestamp`.
4. Trigger a notification event from the backend.
5. Verify `notification` message arrives over WebSocket.
6. Send `mark_read` with a valid notification ID and verify `mark_read_response.data`.
7. Close connection and verify cleanup.
8. Verify missing, refresh, revoked, stale-security-version, inactive, and forced-password credentials close with `4001`.
9. Verify accounts with the same raw ID but different roles do not share events or mutations.
10. Revoke/logout the session after connection and record the current gap: the
    socket remains active because post-connect authorization is not revalidated.

---

## Common Error Cases

| Code | When |
|------|------|
| `400 Bad Request` | Unknown list query parameter; invalid `page` or `page_size`; deep offset; invalid `unread`/`channel`/ID; missing FCM token |
| `401 Unauthorized` | Missing or expired JWT |
| `403 Forbidden` | Role not in allowed set |
| `404 Not Found` | Notification ID does not exist or is not owned by current user; officer account not resolved |
| `409 Conflict` | Mark-all or clear-all exceeds the configured synchronous mutation bound; concurrent read-state conflict |
| `429 Too Many Requests` | Dedicated REST throttle exceeded |

Standard error shape:
```json
{
  "status": "error",
  "message": "...",
  "errors": { }
}
```

Standard success shape:
```json
{
  "status": "success",
  "message": "...",
  "data": { }
}
```

---

## Pagination Edge Cases

| Scenario | Expected |
|----------|----------|
| Empty inbox | `notifications: []`, `total_items: 0`, `total_pages: 0`, `unread_count: 0` |
| `page` beyond last page | `notifications: []`, `has_next: false` |
| `page_size=100` (max) | Up to 100 items per page |
| `page_size=101` | HTTP 400; values are rejected, not clamped |
| offset above `NOTIFICATIONS_MAX_OFFSET` | HTTP 400 |

Offset pagination is retained for compatibility but bounded by
`NOTIFICATIONS_MAX_OFFSET`. Clients should not attempt to page beyond it.

---

## Email Templates

Template files live in `notifications/templates/email/`:

| Template | Notification Type |
|----------|-----------------|
| `loan_submitted.html` / `.txt` | `loan_submitted` |
| `loan_approved.html` / `.txt` | `loan_approved` |
| `loan_rejected.html` / `.txt` | `loan_rejected` |
| `loan_disbursed.html` / `.txt` | `loan_disbursed` |
| `payment_received.html` / `.txt` | `payment_received` |
| `document_approved.html` / `.txt` | `document_verified` |
| `document_flagged.html` / `.txt` | `document_flagged` |
| `document_pending_review.html` / `.txt` | `document_pending_review` |
| `missing_documents_requested.html` / `.txt` | `missing_documents_requested` |
| `new_application.html` / `.txt` | `new_application` |
| `loan_officer_temp_password.html` / `.txt` | Password setup for new officers |

Templates are rendered by `notifications/services/email_sender.py` using Django's `render_to_string`.

---

## Stage 4 Inventory and Schema Commands

Run these only after confirming the intended MongoDB target. The first command
and every command without `--apply` are read-only:

```bash
python manage.py notification_data_inventory --limit 10000
python manage.py backfill_notification_data
python manage.py backfill_notification_data --apply
python manage.py encrypt_sensitive_fields
python manage.py encrypt_sensitive_fields --apply
python manage.py encrypt_sensitive_fields --verify
python manage.py install_notification_schema
python manage.py install_notification_schema --apply
```

Review and back up the target before each applied operation. Backfill repairs
safe deterministic legacy fields with conditional updates; encryption handles
plaintext/old-key fields separately. Schema installation refuses to drop the
obsolete raw-idempotency index or create indexes/validators while any inventory
blocker remains or the bounded inventory is incomplete. Raise `--limit` only
after reviewing the target size and query cost.

Opt-in isolated real-Mongo proof:

```bash
RUN_NOTIFICATIONS_STAGE4_REAL_MONGO_TESTS=1 \
REAL_MONGO_TEST_URI='<isolated MongoDB URI>' \
.venv/bin/pytest -q tests/test_notifications_stage4_real_mongo.py
```

The fixture creates and drops only its uniquely named `_isolated` database.
Do not point it at production.

## Stage 6 Release Gate and Deployment Probes

The final gate is read-only and intentionally fails in development or whenever
evidence is missing:

```bash
.venv/bin/python manage.py notifications_release_check
.venv/bin/python manage.py notifications_release_check --json
```

It checks production-safe runtime configuration, encrypted strict mode,
Redis-backed Channels/Celery, recoverable task routing, monitoring assets,
secure proxy/cookies/hosts/CORS, SMTP configuration, MongoDB connectivity,
required indexes and validators, bounded complete/clean inventory,
Notifications health, and explicit reviewed evidence flags. A `True` flag
records evidence; it does not perform or replace the corresponding test.

Local Stage 6 tooling evidence:

```bash
.venv/bin/pytest -q \
  tests/test_notifications_stage6_release_validation.py \
  tests/test_notifications_stage6_deployment_integrations.py
```

Current local result: **5 passed and 7 opt-in deployment probes skipped**.

Run real-service probes only with synthetic accounts/recipients/tokens and an
approved target. Each probe has its own explicit opt-in boundary:

```bash
RUN_NOTIFICATIONS_REDIS_DEPLOYMENT_TESTS=1 \
NOTIFICATIONS_DEPLOYMENT_REDIS_URL='<redis URL>' \
.venv/bin/pytest -q tests/test_notifications_stage6_deployment_integrations.py::test_two_processes_share_deployment_redis_state

RUN_NOTIFICATIONS_CELERY_DEPLOYMENT_TESTS=1 \
.venv/bin/pytest -q tests/test_notifications_stage6_deployment_integrations.py::test_multiple_workers_consume_notifications_queue

RUN_NOTIFICATIONS_HTTPS_DEPLOYMENT_TESTS=1 \
NOTIFICATIONS_DEPLOYMENT_INBOX_URL='https://<host>/api/notifications/' \
NOTIFICATIONS_DEPLOYMENT_ACCESS_TOKEN='<synthetic customer token>' \
.venv/bin/pytest -q tests/test_notifications_stage6_deployment_integrations.py::test_authenticated_inbox_contract_and_read_load_through_https

RUN_NOTIFICATIONS_WSS_DEPLOYMENT_TESTS=1 \
NOTIFICATIONS_DEPLOYMENT_WSS_URL='wss://<host>/ws/notifications/' \
NOTIFICATIONS_DEPLOYMENT_ACCESS_TOKEN='<synthetic customer token>' \
.venv/bin/pytest -q tests/test_notifications_stage6_deployment_integrations.py::test_authenticated_wss_connect_ping_and_disconnect

RUN_NOTIFICATIONS_METRICS_DEPLOYMENT_TESTS=1 \
NOTIFICATIONS_DEPLOYMENT_METRICS_URL='<private metrics URL>' \
.venv/bin/pytest -q tests/test_notifications_stage6_deployment_integrations.py::test_deployed_metrics_expose_notifications_families
```

The SMTP and Firebase probes perform a real external send. Run them only after
explicit approval with a controlled recipient/token:

```bash
RUN_NOTIFICATIONS_SMTP_DEPLOYMENT_TESTS=1 \
NOTIFICATIONS_DEPLOYMENT_SMTP_RECIPIENT='<synthetic inbox>' \
.venv/bin/pytest -q tests/test_notifications_stage6_deployment_integrations.py::test_approved_synthetic_smtp_delivery

RUN_NOTIFICATIONS_FIREBASE_DEPLOYMENT_TESTS=1 \
NOTIFICATIONS_DEPLOYMENT_FCM_TOKEN='<synthetic device token>' \
.venv/bin/pytest -q tests/test_notifications_stage6_deployment_integrations.py::test_approved_synthetic_firebase_delivery
```

After each approved proof, retain its revision, target, timestamp, sanitized
output, reviewer, and rollback reference. Set only the corresponding
`NOTIFICATIONS_*_VERIFIED` flag. Run the final release checker after all
evidence is recorded.

## Required Future Integration Evidence

The following deployment evidence remains external or opt-in. Keep
state-changing cases explicitly gated.

### Routed REST security suite

Use `APIClient` with issued tokens, persisted active sessions, and live account
records. For every endpoint test unauthenticated, expired/revoked token, wrong
role, suspended/deactivated account, forced-password state, same-ID cross-role
collision, another owner's ID, malformed ID, missing ID, unknown query
parameters, bounds/throttle, and stable public errors.

### Isolated real-Mongo suite

`tests/test_notifications_stage4_real_mongo.py` now creates a uniquely named
temporary database ending in `_isolated` and removes only that database in
fixture cleanup. After explicit target approval, it proves validator rejection,
idempotency uniqueness, and the representative owner/date query plan. Extend
the deployment evidence where needed to prove:

1. all notification/device validators reject invalid shapes;
2. role-qualified token and event uniqueness under concurrency;
3. atomic read/delete/replay behavior;
4. inventory/backfill and key-rotation correctness;
5. owner/date, owner/read, owner/channel/date, retention/reconciliation, and
   active-token query plans use approved indexes; and
6. representative inbox, bulk-operation, and delivery-backlog bounds.

Never point this suite at production.

### Redis/Channels/Celery suite

Prove at least two ASGI processes share owner-group broadcasts through Redis
and at least two workers consume a dedicated notifications queue. Terminate a
worker before provider call, after provider acceptance, and before completion;
prove lease recovery, retry from durable intent, bounded attempts, no repeated
business mutation, and visible backlog/oldest-age metrics. Also test Redis and
broker outage, backpressure, and reconnect reconciliation.

### SMTP and Firebase sandbox suite

Use synthetic recipients/tokens only. Prove SMTP success, permanent refusal,
transient timeout, uncertain acceptance, template/render failure, and redacted
logging. For Firebase, prove installed-version compatibility, batching,
complete/partial success, unregistered-token cleanup, transient/permanent
errors, preference denial, role isolation, logout, and account deletion.

### HTTPS/WSS and monitoring deployment suite

Through the selected proxy, prove exact host/origin policy, secure cookies,
staff-cookie and customer-mobile transports, rejected refresh/query staff
tokens, token expiry/revocation after connection, frame/action limits, load,
Redis fan-out, metrics scrape, dashboard series, and alert firing/resolution.

## Release Test Checklist

- [x] Existing direct-view inbox behavior and role-qualified owner queries pass.
- [x] Existing ASGI WebSocket handshake/group/security tests pass locally.
- [x] Existing mocked template-email and assignment tests pass.
- [x] Stage 1 routed REST and independent read/delivery-state tests pass.
- [x] Stage 2 FCM/device-token security and lifecycle tests pass locally.
- [x] Stage 3 durable/preference-aware broker/worker/provider recovery passes
      under deterministic local tests.
- [x] Stage 4 privacy lifecycle, validator/index, inventory/backfill, and
      retention tests pass locally.
- [ ] Stage 4 isolated real-Mongo test passes against an explicitly approved
      target and reviewed inventory/backfill/schema work is complete.
- [x] Stage 5 post-connect WebSocket security, limits, synchronization,
      monitoring assets, and alert tests pass locally.
- [x] Stage 6 fail-closed release checker and opt-in probes pass local contract
      tests without contacting external services.
- [ ] Stage 6 probes and `notifications_release_check` pass in the final target.
- [ ] Final full suite and customer/officer/admin end-to-end smoke flows pass on
      the release revision.

---

## Where to Look in Code

| Area | Path |
|------|------|
| URL routing | `notifications/urls.py` |
| Inbox views | `notifications/views/notification_views.py` |
| WebSocket routing | `notifications/routing.py` |
| WebSocket consumer | `notifications/consumer.py` |
| WebSocket auth middleware | `notifications/middleware.py` |
| Ownership/query helpers | `notifications/ownership.py` |
| Notification model | `notifications/models/notification.py` |
| Device token model | `notifications/models/device_token.py` |
| Shared delivery model | `notifications/models/delivery.py` |
| Email sender + record creation | `notifications/services/email_sender.py` |
| Shared delivery service | `notifications/services/delivery.py` |
| Preference policy | `notifications/services/preference_policy.py` |
| Canonical Celery tasks | `notifications/tasks.py` |
| Privacy export/cleanup/retention | `notifications/services/lifecycle.py` |
| Validators/inventory/backfill | `notifications/services/persistence.py` |
| Inventory command | `notifications/management/commands/notification_data_inventory.py` |
| Backfill command | `notifications/management/commands/backfill_notification_data.py` |
| Fail-closed schema command | `notifications/management/commands/install_notification_schema.py` |
| WebSocket broadcast service | `notifications/services/websocket_service.py` |
| Notification creator + FCM | `notifications/services/notification_creator.py` |
| Assignment triggers | `notifications/services/assignment_events.py` |
| Prometheus toggle command | `notifications/management/commands/toggle_prometheus.py` |
| Release checker | `notifications/management/commands/notifications_release_check.py` |
| Release/health summary | `notifications/services/operations.py` |
| Email templates | `notifications/templates/email/*.html`, `notifications/templates/email/*.txt` |

---

## Notes for API Test Automation

1. All inbox endpoints return JSON. `POST` and `DELETE /register-token/` accept
   token bodies; assignment event producers also accept structured data.
2. Mark-read endpoints use **POST**, not PUT/PATCH.
3. `is_read` and `read_at` are authoritative and stored separately from
   delivery state. Legacy `status: read` rows are still interpreted safely.
4. Marking read preserves `status`/`delivery_status`; repeated mark-read calls
   succeed with `replayed: true`.
5. List response includes `unread_count` even when filtering — it always reflects total unread, not filtered count.
6. Inbox and device-token ownership are by both `user_id` and normalized
   `user_type`; seed both, and bind device tokens to a live `session_id`.
7. Staff WebSocket connections use the HttpOnly access cookie. Customer mobile query/subprotocol access tokens remain temporarily supported; rejected credentials close with `4001`.
8. `status: sent` is not end-to-end user-receipt evidence. Assert channel
   progress in the owning Loans/Documents/shared outbox independently from read
   state.
9. Notification preferences (opt-in/opt-out) are under `/api/profile/notifications/` — separate from this inbox API.
10. Generate diverse `notification_type` values by running the full loan lifecycle (see `docs/LOANS_TESTING_GUIDE.md` smoke sequence).
11. FCM is called asynchronously by shared delivery using the installed
    `send_each_for_multicast` API in bounded batches. Mock it in unit tests;
    never call live customer tokens outside an approved Firebase test project.
12. Assignment notifications do not send email or push notifications — they are in-app only with structured metadata.
13. Profiles preferences suppress only optional email. Test both allowed and
    denied loan/document updates and verify mandatory security/staff/receipt
    events remain deliverable.
14. Test that logs and public payloads never contain email addresses, FCM
    tokens, provider exception bodies, credentials, or internal idempotency
    values.
15. Raw MongoDB content fields are ciphertext when field encryption is enabled;
    load them through `Notification.from_dict()` in trusted tests.
16. A held notification returns `NOTIFICATION_LEGAL_HOLD` for single delete;
    clear-all reports held rows in `retained_count`.
17. Account export adds `notification_export` completeness metadata while
    preserving the historical `notifications` list.
