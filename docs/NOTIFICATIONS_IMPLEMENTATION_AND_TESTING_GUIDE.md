# Notifications Implementation and Testing Guide

## Scope
Notifications in this project have two parts:
- Automatic email notifications triggered by loan/document workflows.
- Notification inbox APIs under `/api/notifications/` for reading and managing notification records.

## Configuration
Set in `.env`:
```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=your-email@gmail.com
```
Use app passwords for Gmail. Do not commit real credentials.

## Delivery Model
- Each send attempt creates a record in MongoDB `notifications`.
- Status lifecycle is typically: `pending` -> `sent` or `failed`.
- Inbox APIs can mark records as `read`.

## Automatic Trigger Map
| Notification Type | Triggering Action | Endpoint |
|---|---|---|
| `loan_submitted` | Customer submits application | `POST /api/loans/apply/` |
| `loan_approved` / `loan_rejected` | Officer reviews application | `PUT /api/loans/officer/applications/<application_id>/review/` |
| `loan_disbursed` | Officer disburses approved loan | `POST /api/loans/officer/applications/<application_id>/disburse/` |
| `payment_received` | Officer records payment | `POST /api/loans/officer/payments/` |
| `missing_documents_requested` | Officer requests missing docs | `POST /api/loans/officer/applications/<application_id>/request-missing-documents/` |
| `document_pending_review` | Customer uploads document (reviewer notification) | `POST /api/documents/upload/` |
| `document_verified` / `document_flagged` | Reviewer approves/rejects document | `PUT /api/documents/<document_id>/verify/` |
| `document_flagged` | Reviewer requests re-upload | `POST /api/documents/<document_id>/request-reupload/` |
| `new_application` | Admin assigns/reassigns application | `POST /api/loans/admin/applications/<application_id>/assign/` and `POST /api/loans/admin/applications/<application_id>/reassign/` |

## Notification Inbox API
Base URL: `http://localhost:8000/api/notifications`

Required headers:
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

Allowed roles: `customer`, `loan_officer`, `admin`, `super_admin`.

1. `GET /api/notifications/`
- List notifications (newest first).
- Query params:
  - `page` (default `1`)
  - `page_size` (default `20`, max `100`)
  - `unread` (`true|false`)
  - `channel` (`email|in_app`)
- Returns:
  - `notifications`
  - `unread_count`
  - `pagination` (`page`, `page_size`, `total_items`, `total_pages`, `has_next`, `has_previous`)

2. `GET /api/notifications/unread-count/`
- Returns `unread_count`.

3. `POST /api/notifications/mark-all-read/`
- Marks all owned unread notifications as read.
- Returns `marked_count`.

4. `POST /api/notifications/<notification_id>/read/`
- Marks one owned notification as read.
- Returns `notification_id` and `status`.

## Smoke Test Sequence
1. Configure email env vars and restart server.
2. Trigger one notification event (fastest: `POST /api/loans/apply/` as customer).
3. Call `GET /api/notifications/` for that user and verify a new entry exists.
4. Call `GET /api/notifications/unread-count/` and note count.
5. Call `POST /api/notifications/<notification_id>/read/` on one item.
6. Call `POST /api/notifications/mark-all-read/` and verify `marked_count`.
7. Re-check `GET /api/notifications/unread-count/` and confirm `0` (or expected remaining).

## Common Error Cases
1. `400 Bad Request`
- Invalid pagination values.
- Invalid `unread` boolean.
- Invalid `channel` value.
- Invalid `notification_id` format.

2. `404 Not Found`
- Notification does not exist or is not owned by current user.

3. `401/403`
- Missing auth token or role access denied.
