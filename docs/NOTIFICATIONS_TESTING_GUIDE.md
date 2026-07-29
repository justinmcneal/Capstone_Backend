# Notifications Testing Guide

## Scope

This guide documents the **Notifications service** under `/api/notifications/` for API testing and implementation review. It covers:

- Notification inbox REST API endpoints
- WebSocket real-time delivery
- Email delivery via Celery async tasks
- FCM push notifications and device-token registration
- Assignment-lifecycle event notifications
- Prometheus metrics for email sends

**Important distinction:** Email **preference settings** (`email_loan_updates`, etc.) live under **`/api/profile/notifications/`** (Profiles module), not this API. This guide covers the **inbox** only.

## Architecture Overview

Notifications use multiple channels together:

- **REST API**: fetch/manage inbox, mark read/delete, get unread counts
- **WebSocket**: real-time push of new notifications to connected clients
- **Celery + Email**: async email delivery with retry and metrics
- **FCM Push**: optional mobile/desktop push via Firebase Cloud Messaging
- **Assignment Events**: structured notifications for loan-assignment lifecycle

When a notification is created, the system can:
1. Persist an in-app record
2. Broadcast it over WebSocket to the owner
3. Send an email via Celery
4. Push to FCM if the user has registered device tokens

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
| `docs/NOTIFICATIONS_METRICS.md` | Prometheus metrics deployment patterns |
| `docs/LOANS_TESTING_GUIDE.md` | Loan APIs that trigger notifications |
| `docs/PROFILES_API_TESTING_GUIDE.md` | Notification **preferences** (`/api/profile/notifications/`) |

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
| `new_application` | Loan officer | `loan` |
| `application_assigned` | Admin / new loan officer | `loan` |
| `application_reassigned` | Assigning admin | `loan` |
| `application_unassigned` | Previous loan officer | `loan` |
| `welcome` | Customer | — |
| `password_reset` | User | — |

### Channels (`channel`)

`email`, `in_app`

Default when records are created by the email sender: `email`.

### Delivery Statuses (MongoDB `status` field)

| Status | Meaning |
|--------|---------|
| `pending` | Record created; email not yet sent |
| `sent` | Email delivered successfully |
| `failed` | Email send failed (`error_message` set) |
| `read` | User marked notification as read in inbox (overwrites prior delivery status) |

### Unread Logic

A notification is **unread** when `status` is **not** `read`. Statuses `pending`, `sent`, and `failed` all count as unread until marked read.

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

---

## Automatic Trigger Map (populate inbox for testing)

Notifications are created by `notifications/services/email_sender.py` when other APIs run. Use these to generate test data:

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

Assignment event payloads and extension guidance are documented in `docs/ASSIGNMENT_NOTIFICATIONS.md`.

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
| `channel` | string | `email` or `in_app` |
| `status` | string | `pending`, `sent`, `failed`, `read` |
| `error_message` | string | Set when `status` = `failed` |
| `created_at` | datetime | Record creation time; API/WebSocket responses use an explicit UTC ISO 8601 value (for example, `2026-07-23T02:15:00Z`) |
| `sent_at` | datetime | When email was sent; API responses use an explicit UTC ISO 8601 value when present |
| `read_at` | datetime | Set when marked read via API |

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
| `unread` | boolean | (no filter) | `true`/`false`/`1`/`0`/`yes`/`no`/`on`/`off` — when `true`, only non-`read` items |
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
| `notifications[].status` | string |
| `notifications[].is_read` | boolean | `true` when `status == 'read'` |
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
| `unread_count` | int | Count where `status` is not `read` |

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
- Updates all records matching owner query where `status` is not `read`
- Sets `status` = `read` and `read_at` = current UTC timestamp

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
- Sets `status` = `read` and `read_at` = current UTC timestamp

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `notification_id` | string |
| `status` | string (`read`) |

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
- If the same token already exists, the existing record is updated
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

**Platform values:** `android`, `ios`, `web`, or custom

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

**URL:** `ws://<host>/ws/notifications/`

**Auth:** JWT token passed via query string or `sec-websocket-protocol` header.

Example:
```
ws://localhost:8000/ws/notifications/?token=<access_token>
```

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

---

## FCM Push Notifications

Device tokens are stored in MongoDB (`device_tokens` collection) and used by `notifications/services/notification_creator.py` to send push notifications via Firebase Cloud Messaging.

**Registration endpoint:** `POST /api/notifications/register-token/`

**Behavior:**
- Duplicate tokens update the existing record
- FCM `UnregisteredError` responses deactivate stale tokens automatically
- Push notifications are sent as `MulticastMessage` with title, body, and data payload

**Dependencies:**
- `firebase_admin` Python package
- Firebase service account credentials in environment

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

Implemented in `notifications/services/email_tasks.py`. Counters are only registered when `prometheus-client` is installed; otherwise they no-op gracefully.

| Metric | Scope |
|--------|-------|
| `notifications_email_task_success_total` | Async Celery email sends |
| `notifications_email_task_failure_total` | Async Celery email failures |
| `notifications_email_send_success_total` | Sync email sends |
| `notifications_email_send_failure_total` | Sync email failures |

**Toggle command:**
```bash
python manage.py toggle_prometheus enable --url
python manage.py toggle_prometheus status --url
python manage.py toggle_prometheus disable --url
```

Metrics endpoint: `http://<host>:8000/metrics/` when enabled.

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

For inbox-only API testing without SMTP, records still appear in MongoDB with `status: pending` or `failed`.

---

## Smoke Test Sequences

### Inbox API

1. Authenticate as a customer and call `GET /api/notifications/`.
2. Verify empty inbox returns `notifications: []` and `unread_count: 0`.
3. Trigger a notification via another API (e.g. `POST /api/loans/apply/`).
4. Call `GET /api/notifications/` and verify the new record appears.
5. Call `GET /api/notifications/unread-count/` and note the count.
6. Call `POST /api/notifications/<id>/read/` and verify `status: read`.
7. Call `POST /api/notifications/mark-all-read/` and verify `marked_count`.
8. Call `GET /api/notifications/<id>/` and confirm the field name is `id`, not `_id`.
9. Call `DELETE /api/notifications/<id>/` and confirm deletion.
10. Call `DELETE /api/notifications/clear-all/` and confirm all records are removed.

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

1. Open WebSocket connection with valid JWT.
2. Verify `connection_established` message includes `unread_count`.
3. Send `ping` and verify `pong` response.
4. Trigger a notification event from the backend.
5. Verify `notification` message arrives over WebSocket.
6. Send `mark_read` with a valid notification ID and verify response.
7. Close connection and verify cleanup.

---

## Common Error Cases

| Code | When |
|------|------|
| `400 Bad Request` | Invalid `page` or `page_size`; invalid `unread` boolean; invalid `channel`; invalid `notification_id` format; missing FCM token |
| `401 Unauthorized` | Missing or expired JWT |
| `403 Forbidden` | Role not in allowed set |
| `404 Not Found` | Notification ID does not exist or is not owned by current user; officer account not resolved |

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
| Empty inbox | `notifications: []`, `total_items: 0`, `total_pages: 1`, `unread_count: 0` |
| `page` beyond last page | `notifications: []`, `has_next: false` |
| `page_size=100` (max) | Up to 100 items per page |
| `page_size=101` (clamped) | Treated as 100 |

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
| `loan_officer_temp_password.html` | Password setup for new officers |

Templates are rendered by `notifications/services/email_sender.py` using Django's `render_to_string`.

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
| Celery async email task | `notifications/services/email_tasks.py` |
| WebSocket broadcast service | `notifications/services/websocket_service.py` |
| Notification creator + FCM | `notifications/services/notification_creator.py` |
| Assignment triggers | `notifications/services/assignment_events.py` |
| Prometheus toggle command | `notifications/management/commands/toggle_prometheus.py` |
| Email templates | `notifications/templates/email/*.html`, `notifications/templates/email/*.txt` |

---

## Notes for API Test Automation

1. All inbox endpoints return JSON; the only mutating endpoints that accept a body are `POST /register-token/` and assignment event notifications.
2. Mark-read endpoints use **POST**, not PUT/PATCH.
3. `is_read` is derived (`status == 'read'`), not stored separately.
4. Marking read **overwrites** delivery status (`sent`/`pending`/`failed` → `read`).
5. List response includes `unread_count` even when filtering — it always reflects total unread, not filtered count.
6. Customer ownership is **strictly by `user_id`** — seed notifications with the correct `customer_id`.
7. WebSocket connections require a valid JWT in the query string or `sec-websocket-protocol` header.
8. To test email delivery end-to-end, assert on MongoDB `status: sent` and `sent_at` after async send completes.
9. Notification preferences (opt-in/opt-out) are under `/api/profile/notifications/` — separate from this inbox API.
10. Generate diverse `notification_type` values by running the full loan lifecycle (see `docs/LOANS_TESTING_GUIDE.md` smoke sequence).
11. FCM push notifications are sent asynchronously; tests should mock `firebase_admin.messaging.send_multicast` to avoid external network calls.
12. Assignment notifications do not send email or push notifications — they are in-app only with structured metadata.
