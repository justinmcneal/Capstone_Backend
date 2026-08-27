# Notifications Testing Guide

Last updated: 2026-08-27

## Scope

This guide documents the **Notifications service** under `/api/notifications/` for API testing and implementation review. It covers:

- Notification inbox REST API endpoints
- WebSocket real-time delivery
- Template email and domain-owned Celery outbox delivery
- FCM push notifications and device-token registration
- Assignment-lifecycle event notifications
- Existing email-task counters and planned operational monitoring

**Important distinction:** Email **preference settings** (`email_loan_updates`, etc.) live under **`/api/profile/notifications/`** (Profiles module), not this API. This guide covers the **inbox** only.

## Architecture Overview

Notifications currently combine several channels, but they do not yet share one
complete delivery lifecycle:

- **REST API**: fetch/manage inbox, mark read/delete, get unread counts
- **WebSocket**: real-time push of new notifications to connected clients
- **Template Email**: synchronous `EmailSender` calls, normally invoked inside
  the durable Loans/Documents delivery workers
- **Standalone Celery Email**: source exists but is not registered or called in
  a normal startup; do not treat it as an active production path
- **FCM Push**: attempted synchronously after inbox creation, but currently
  broken with the pinned Firebase version
- **Assignment Events**: structured notifications for loan-assignment lifecycle

Depending on the producer, the system can:
1. Persist an in-app record
2. Broadcast it over WebSocket to the owner
3. Send template email, with durable retry only when the owning domain provides
   an outbox
4. Attempt FCM push for registered tokens

Persistence, WebSocket publication, email acceptance, push acceptance, and
user read state are separate facts even though the current `status` field
incorrectly combines some of them.

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
  tests/test_notifications_use_celery.py \
  tests/test_assignment_notifications.py \
  tests/test_notification_timestamps.py
```

Result after Stage 1 on 2026-08-27: **62 passed**.

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

Broader cross-domain selection:

```bash
.venv/bin/pytest -q tests accounts/tests \
  -k 'notification or websocket or email_template or email_tls'
```

Result after Stage 1 on 2026-08-27: **117 passed, 1,245 deselected**. The latest
full repository result on the same revision is **1,316 passed, 46 skipped**.

Evidence limits:

- Most REST tests call views directly and bypass `require_roles`; they verify
  query/mutation behavior but not real URL/JWT/session enforcement.
- WebSocket security tests do use ASGI routing and real issued token/session
  behavior, but use an in-memory channel layer rather than deployed Redis.
- Email tests mock rendering/transport. No SMTP message is sent.
- Device registration has two basic tests; no FCM send/partial-failure test
  exists.
- No Notifications-specific real-Mongo, multi-worker Redis/Celery, HTTPS/WSS,
  load, backup/restore, monitoring, or deployment probe exists yet.

### Stage validation map

| Stage | Primary evidence required | Current status |
| --- | --- | --- |
| Stage 1 — Contract and owner-safe inbox | Routed auth/role/owner tests, independent read/delivery state, atomic replay, bounds/throttles | Complete locally; 78 focused tests pass |
| Stage 2 — Secure working push | Installed Firebase API, role-qualified token ownership, validation, revoke/cleanup, provider batching | Not started; current FCM call is incompatible |
| Stage 3 — Durable preference-aware delivery | Registered/routed tasks, leases/retries, broker/worker/provider recovery, preference policy | Not started; Loans/Documents outboxes cover only their events |
| Stage 4 — Privacy and MongoDB correctness | Encryption/log safety, lifecycle/export, validators/indexes, inventory/backfill, real-Mongo plans | Not started |
| Stage 5 — WebSocket resilience/observability | Post-connect revocation/expiry, limits, cross-device sync, metrics/rules/dashboard/health | Not started |
| Stage 6 — Deployment validation | Real MongoDB/Redis/Celery/SMTP/FCM/HTTPS/WSS/load/recovery and release checker | Not started |

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

`email`, `in_app`

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
`delivery_status: unknown` until Stage 4 inventory/backfill. Most shared email
helpers still create an `in_app` row with `status: sent` before the SMTP
attempt, so `sent` is not yet durable proof of external delivery.

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

This guarantee now extends to `Notification.find_by_user`, customer account
export, and the AI notification-status tool. Device-token ownership still uses
only raw user ID and remains a Stage 2 gap.

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
published. Assignment and account-security events are best-effort and have no
equivalent recovery record. Saved Profiles email preferences are not currently
consulted by any of these paths.

---

## Stored Notification Record (MongoDB schema)

Full fields in `notifications` collection (not all exposed in list API):

| Field | Type | Description |
|-------|------|-------------|
| `_id` | ObjectId | Primary key (exposed as `id` in API) |
| `user_id` | string | Owner user ID |
| `user_type` | string | `customer`, `loan_officer`, `admin` |
| `recipient_email` | string | Email address |
| `recipient_name` | string | Display name |
| `notification_type` | string | See Reference Values |
| `subject` | string | Short subject line |
| `message` | string | Body text (often empty for email-channel records) |
| `related_type` | string | `loan`, `document`, etc. |
| `related_id` | string | Linked entity ID |
| `metadata` | object | Optional structured event context (participants, entity, audience, and occurrence time) |
| `idempotency_key` | string/null | Optional unique producer key; not exposed by the inbox API |
| `channel` | string | `email` or `in_app` |
| `status` | string | Delivery compatibility alias: `pending`, `sent`, `failed`, `unknown` |
| `delivery_status` | string | Explicit delivery state matching `status` |
| `is_read` | boolean | Authoritative inbox read state |
| `error_message` | string | Set when `status` = `failed` |
| `created_at` | datetime | Record creation time; API/WebSocket responses use an explicit UTC ISO 8601 value (for example, `2026-07-23T02:15:00Z`) |
| `sent_at` | datetime | When email was sent; API responses use an explicit UTC ISO 8601 value when present |
| `read_at` | datetime/null | Set once when marked read via API |

Recipient identity, message content, metadata, errors, and device tokens are
currently plaintext. No MongoDB validator enforces this table, the declared
type list, channel/status values, role values, or timestamp shapes.

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

Delete all owned notifications for the current user.

**Auth:** customer, loan_officer, admin, super_admin

**Behavior:**
- Removes all records matching the owner query
- Cannot affect other users' notifications

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `deleted_count` | int | Number of records removed |

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
  "token": "fcm-device-token",
  "platform": "android"
}
```

**Validation:**
- `token` is required and non-empty
- `platform` defaults to `unknown` if omitted

**Behavior:**
- If the same token already exists, the existing record is reassigned to the
  current caller; this is a known ownership vulnerability, not an approved
  production behavior
- New tokens are inserted with `is_active: true`

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `status` | string (`registered`) | Registration confirmation |

**Example:**
```bash
curl -X POST /api/notifications/register-token/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"token": "fcm-token-123", "platform": "android"}'
```

**Current platform values:** any caller-supplied value is accepted. Stage 2
must restrict this to approved values such as `android`, `ios`, and `web`, add
token length/format bounds, role-qualified ownership, and unregister/logout
support.

---

## Complete URL Index (7 endpoints)

| # | Method | URL | Roles |
|---|--------|-----|-------|
| 1 | GET | `/api/notifications/` | Customer, Officer, Admin, Super Admin |
| 2 | GET | `/api/notifications/unread-count/` | Customer, Officer, Admin, Super Admin |
| 3 | POST | `/api/notifications/mark-all-read/` | Customer, Officer, Admin, Super Admin |
| 4 | POST | `/api/notifications/<notification_id>/read/` | Customer, Officer, Admin, Super Admin |
| 5 | DELETE | `/api/notifications/<notification_id>/` | Customer, Officer, Admin, Super Admin |
| 6 | DELETE | `/api/notifications/clear-all/` | Customer, Officer, Admin, Super Admin |
| 7 | POST | `/api/notifications/register-token/` | Customer, Officer, Admin, Super Admin |

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

**Current status: broken and not production-safe.** The project pins
`firebase-admin==7.4.0`, which provides
`messaging.send_each_for_multicast`; the implementation calls the absent
`messaging.send_multicast`. The broad exception handler logs the failure and
allows inbox creation to continue, so an API success does not indicate that a
push was sent.

**Registration endpoint:** `POST /api/notifications/register-token/`

**Behavior:**
- Duplicate tokens currently update and may transfer the token to a different
  caller
- token queries use raw `user_id` without `user_type`
- intended `UnregisteredError` handling would deactivate stale tokens, but the
  incompatible send call prevents provider responses from being processed
- push is attempted synchronously during notification creation, not
  asynchronously
- all active tokens are loaded and submitted in one request without the
  provider's multicast batch bound

**Dependencies:**
- `firebase_admin` Python package
- Firebase service account credentials in environment

Stage 2 tests must mock the API present in the pinned package and cover complete
success, partial success, unregistered tokens, transient errors, batching,
role-ID collision, hostile token reassignment, unregister/logout, and account
deletion. Do not run live FCM tests with real customer tokens.

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
- Do **not** send email or push notifications

---

## Prometheus Metrics

Two counters are declared in `notifications/services/email_tasks.py`. Counters
are only registered when `prometheus-client` is installed; otherwise they no-op
gracefully.

| Metric | Scope |
|--------|-------|
| `notifications_email_task_success_total` | Async Celery email sends |
| `notifications_email_task_failure_total` | Async Celery email failures |

There are no `notifications_email_send_success_total` or
`notifications_email_send_failure_total` counters in the current sender. The
standalone email task is not imported by Celery autodiscovery, is not called by
producers, and converts SMTP failures to `False` rather than raising for
autoretry. Therefore even the two declared counters do not represent the active
domain delivery paths and are insufficient production monitoring.

**Toggle command:**
```bash
python manage.py toggle_prometheus enable --url
python manage.py toggle_prometheus status --url
python manage.py toggle_prometheus disable --url
```

The resolved private metrics URL is printed by `--url`; follow the root
`README.md` sidecar instructions rather than assuming `/metrics/` is served by
the public application port.

Stage 5 must add request, per-channel outcome/latency, retry, terminal failure,
backlog/oldest-age, token invalidation, WebSocket connection/rejection, and job-
freshness metrics plus tested Prometheus rules and a Grafana dashboard.

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

The standalone `send_email_task` is currently neither autodiscovered nor used.
After Stage 3, verify registration with a worker inspection test and prove that
returned/raised provider failures enter the approved retry path.

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

## Required Future Integration Evidence

The following suites do not exist yet. Implement them with the corresponding
readiness stage; keep external/state-changing cases explicitly opt-in.

### Routed REST security suite

Use `APIClient` with issued tokens, persisted active sessions, and live account
records. For every endpoint test unauthenticated, expired/revoked token, wrong
role, suspended/deactivated account, forced-password state, same-ID cross-role
collision, another owner's ID, malformed ID, missing ID, unknown query
parameters, bounds/throttle, and stable public errors.

### Isolated real-Mongo suite

Use a uniquely named temporary database ending in `_isolated` and remove only
that database in fixture cleanup. After explicit target approval, prove:

1. all notification/device validators reject invalid shapes;
2. role-qualified token and event uniqueness under concurrency;
3. atomic read/delete/replay behavior;
4. inventory/backfill and key-rotation correctness;
5. owner/date, owner/read, owner/channel/date, retention/reconciliation, and
   active-token query plans use approved indexes; and
6. representative inbox, bulk-operation, and delivery-backlog bounds.

Never point this future suite at production.

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
- [ ] Stage 2 FCM/device-token security and lifecycle tests pass.
- [ ] Stage 3 durable/preference-aware broker/worker/provider recovery passes.
- [ ] Stage 4 privacy lifecycle, validator/index, inventory/backfill, and real-
      Mongo tests pass.
- [ ] Stage 5 post-connect WebSocket security, limits, synchronization,
      monitoring assets, and alert tests pass.
- [ ] Stage 6 deployment probes and `notifications_release_check` pass.
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
| Email sender + record creation | `notifications/services/email_sender.py` |
| Unregistered standalone email-task source | `notifications/services/email_tasks.py` |
| WebSocket broadcast service | `notifications/services/websocket_service.py` |
| Notification creator + FCM | `notifications/services/notification_creator.py` |
| Assignment triggers | `notifications/services/assignment_events.py` |
| Prometheus toggle command | `notifications/management/commands/toggle_prometheus.py` |
| Email templates | `notifications/templates/email/*.html`, `notifications/templates/email/*.txt` |

---

## Notes for API Test Automation

1. All inbox endpoints return JSON; the only mutating endpoints that accept a body are `POST /register-token/` and assignment event notifications.
2. Mark-read endpoints use **POST**, not PUT/PATCH.
3. `is_read` and `read_at` are authoritative and stored separately from
   delivery state. Legacy `status: read` rows are still interpreted safely.
4. Marking read preserves `status`/`delivery_status`; repeated mark-read calls
   succeed with `replayed: true`.
5. List response includes `unread_count` even when filtering — it always reflects total unread, not filtered count.
6. Inbox ownership is by both `user_id` and normalized `user_type`; seed both.
   Separately test the remaining raw-ID-only device-token gap in Stage 2.
7. Staff WebSocket connections use the HttpOnly access cookie. Customer mobile query/subprotocol access tokens remain temporarily supported; rejected credentials close with `4001`.
8. Current `status: sent` is not reliable end-to-end email evidence because it
   can be set before SMTP. Stage 1 preserves it independently from read state;
   after Stage 3, assert channel attempt/outcome fields and domain outbox state.
9. Notification preferences (opt-in/opt-out) are under `/api/profile/notifications/` — separate from this inbox API.
10. Generate diverse `notification_type` values by running the full loan lifecycle (see `docs/LOANS_TESTING_GUIDE.md` smoke sequence).
11. FCM is currently attempted synchronously and calls an API absent from the
    pinned Firebase version. Stage 2 tests should mock
    `send_each_for_multicast`; never call live customer tokens in unit tests.
12. Assignment notifications do not send email or push notifications — they are in-app only with structured metadata.
13. Profiles notification preferences are currently unenforced. Add allow/deny
    tests for each optional category when Stage 3 implements the policy.
14. Test that logs and public payloads never contain email addresses, FCM
    tokens, provider exception bodies, credentials, or internal idempotency
    values.
