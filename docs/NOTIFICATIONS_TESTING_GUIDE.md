# Notifications API Testing Guide

## Scope

This guide documents the **Notifications inbox API** under `/api/notifications/` for API testing. It covers:

- All inbox endpoints (list, unread count, mark read)
- Every query parameter and response field
- Notification record schema and status lifecycle
- Automatic email triggers that populate the inbox (tested indirectly via other APIs)

**Important distinction:** Email **preference settings** (`email_loan_updates`, etc.) live under **`/api/profile/notifications/`** (Profiles module), not this API. This guide covers the **inbox** only.

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
| `docs/NOTIFICATIONS_IMPLEMENTATION_AND_TESTING_GUIDE.md` | Shorter implementation overview (legacy) |
| `docs/NOTIFICATIONS_METRICS.md` | Prometheus email send metrics |
| `docs/LOANS_TESTING_GUIDE.md` | Loan APIs that trigger loan notifications |
| `docs/PROFILES_API_TESTING_GUIDE.md` | Notification **preferences** (`/api/profile/notifications/`) |

---

## Reference Values

### Notification Types (stored in `notification_type`)

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
| `welcome` | Customer | — |
| `password_reset` | User | — |

### Channels (`channel` filter)

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
| `customer` | Strictly `user_id` = authenticated `customer_id` (email fallback **not** used — prevents cross-account leakage on recreated accounts) |
| `loan_officer` | `user_id` = officer ID **OR** (`recipient_email` + `user_type` = `loan_officer`) |
| `admin` / `super_admin` | `user_id` = admin ID **OR** (`recipient_email` + matching `user_type`) |

Users can only mark read / list notifications they own. Accessing another user's notification ID returns `404 Not Found`.

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
| `new_application` | Auto/manual assign or reassign (`loans/services/assignment.py`) | System / Admin |
| `document_pending_review` | `POST /api/documents/upload/` | Customer |
| `document_verified` | `PUT /api/documents/<id>/verify/` (approve) | Officer |
| `document_flagged` | `PUT /api/documents/<id>/verify/` (reject) or `POST /api/documents/<id>/request-reupload/` | Officer |

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
| `channel` | string | `email` or `in_app` |
| `status` | string | `pending`, `sent`, `failed`, `read` |
| `error_message` | string | Set when `status` = `failed` |
| `created_at` | datetime | Record creation time |
| `sent_at` | datetime | When email was sent |
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

## Complete URL Index (4 endpoints)

| # | Method | URL | Roles |
|---|--------|-----|-------|
| 1 | GET | `/api/notifications/` | Customer, Officer, Admin, Super Admin |
| 2 | GET | `/api/notifications/unread-count/` | Customer, Officer, Admin, Super Admin |
| 3 | POST | `/api/notifications/mark-all-read/` | Customer, Officer, Admin, Super Admin |
| 4 | POST | `/api/notifications/<notification_id>/read/` | Customer, Officer, Admin, Super Admin |

---

## Email Configuration (for end-to-end notification testing)

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

## Smoke Test Sequence

### Prerequisites

1. Create test accounts: **customer**, **loan_officer** (with JWTs).
2. Configure email env vars (optional).

### Steps

| Step | Actor | Action | Expected |
|------|-------|--------|----------|
| 1 | Customer | `POST /api/loans/apply/` | Triggers `loan_submitted` notification record |
| 2 | Customer | `GET /api/notifications/` | 200; at least one notification in `notifications` |
| 3 | Customer | `GET /api/notifications/unread-count/` | 200; `unread_count` >= 1 |
| 4 | Customer | `GET /api/notifications/?unread=true` | Only non-read items |
| 5 | Customer | `GET /api/notifications/?channel=email` | Only email-channel items |
| 6 | Customer | `POST /api/notifications/<id>/read/` | 200; `status: read` |
| 7 | Customer | `GET /api/notifications/unread-count/` | Count decreased by 1 |
| 8 | Customer | `POST /api/notifications/mark-all-read/` | 200; `marked_count` >= 0 |
| 9 | Customer | `GET /api/notifications/unread-count/` | `unread_count` = 0 |
| 10 | Customer | `POST /api/notifications/<other_user_id>/read/` | 404 Not Found |
| 11 | Customer | `POST /api/notifications/not-an-objectid/read/` | 400 Bad Request |
| 12 | Officer | `GET /api/notifications/` after assignment | Officer sees `new_application` if assigned |

### Officer Inbox Test

1. Admin assigns loan to Officer A (`POST /api/loans/admin/applications/<id>/assign/`).
2. Officer A: `GET /api/notifications/` → should include `new_application`.
3. Officer B: `GET /api/notifications/` → should NOT include Officer A's notification.

### Filter Combination Tests

```
GET /api/notifications/?page=2&page_size=10
GET /api/notifications/?unread=false
GET /api/notifications/?unread=true&channel=email
GET /api/notifications/unread-count/
```

---

## Common Error Cases

| Code | When |
|------|------|
| `400 Bad Request` | Invalid `page` or `page_size` (non-integer or < 1); invalid `unread` boolean; invalid `channel` (not `email`/`in_app`); invalid `notification_id` format |
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

## Where to Look in Code

| Area | Path |
|------|------|
| URL routing | `notifications/urls.py` |
| Inbox views | `notifications/views/notification_views.py` |
| Notification model | `notifications/models/notification.py` |
| Email sender + record creation | `notifications/services/email_sender.py` |
| Celery email tasks | `notifications/services/email_tasks.py` |
| Assignment triggers | `loans/services/assignment.py` |
| Existing tests | `tests/test_notifications_views.py`, `tests/test_notifications_mark_read.py`, `tests/test_notifications_email_sender.py` |

---

## Notes for API Test Automation

1. All inbox endpoints have **no request bodies** — only query params on `GET /`.
2. Mark-read endpoints use **POST**, not PUT/PATCH.
3. Customer ownership is **strictly by `user_id`** — seed notifications with the correct `customer_id`.
4. `is_read` is derived (`status == 'read'`), not stored separately.
5. Marking read **overwrites** delivery status (`sent`/`pending`/`failed` → `read`).
6. List response includes `unread_count` even when filtering — it always reflects total unread, not filtered count.
7. To test email delivery end-to-end, assert on MongoDB `status: sent` and `sent_at` after async send completes.
8. Notification preferences (opt-in/opt-out) are under `/api/profile/notifications/` — separate from this inbox API.
9. Generate diverse `notification_type` values by running the full loan lifecycle (see `docs/LOANS_TESTING_GUIDE.md` smoke sequence).
