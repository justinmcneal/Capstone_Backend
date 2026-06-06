# Analytics API Testing Guide

## Scope

This guide documents the **Analytics service API** under `/api/analytics/` for API testing. It covers:

- Admin, loan officer, and customer dashboard endpoints
- Audit log listing, filtering, and detail endpoints
- Every query parameter and response field

Analytics is **read-only** — all endpoints are `GET` only. Data is aggregated from MongoDB collections (`loan_applications`, `documents`, `audit_logs`, `ai_interactions`, etc.).

## Base URL and Auth

- **Base URL:** `http://localhost:8000/api/analytics`
- **Required headers:**
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

## Related Documentation

| Document | Purpose |
|----------|---------|
| `docs/ANALYTICS_IMPLEMENTATION_AND_TESTING_GUIDE.md` | Shorter implementation overview (legacy) |
| `docs/LOANS_TESTING_GUIDE.md` | Loan APIs that generate many audit log entries |
| `docs/AUTH_ACCESS_SECURITY_GUIDE.md` | Admin permissions (`view_analytics`, `view_logs`) |

## Role and Permission Matrix

| Endpoint | Allowed Role | Required Admin Permission |
|----------|--------------|---------------------------|
| `GET /admin/` | Admin | `view_analytics` |
| `GET /audit-logs/` | Admin | `view_logs` |
| `GET /audit-logs/users/` | Admin | `view_logs` |
| `GET /audit-logs/<log_id>/` | Admin | `view_logs` |
| `GET /officer/` | Loan Officer, Admin | None |
| `GET /officer/audit-logs/` | Loan Officer, Admin | None |
| `GET /customer/` | Customer | None |

---

## Reference Values

### Audit Log User Types (`user_type` filter)

`customer`, `loan_officer`, `admin`

### Audit Log Action Groups (`action_group` filter)

| Group | Matching `action` values |
|-------|--------------------------|
| `login` | `user_login`, `user_login_failed`, `user_logout` |
| `create` | `user_registered`, `loan_submitted`, `document_uploaded`, `payment_recorded` |
| `update` | `profile_updated`, `document_verified`, `document_rejected`, `loan_approved`, `loan_rejected`, `loan_disbursed`, `penalty_applied`, `penalty_waived`, `consent_recorded`, `admin_action` |
| `delete` | `admin_action` entries whose description matches delete/deactivate/remove (regex) |

### Canonical Audit Actions (`AUDIT_ACTIONS` in code)

`user_login`, `user_login_failed`, `user_logout`, `user_registered`, `profile_updated`, `document_uploaded`, `document_verified`, `document_rejected`, `loan_submitted`, `loan_approved`, `loan_rejected`, `loan_disbursed`, `payment_recorded`, `penalty_applied`, `penalty_waived`, `consent_recorded`, `admin_action`

### Extended Actions (also appear in logs from other modules)

`loan_draft_updated_and_submitted`, `customer_payment_recorded`, `disbursement_method_set`, `wallet_payment_verified`, `loan_internal_note_added`, `loan_missing_documents_requested`

### Resource Types (in audit log entries)

`loan`, `document`, `profile`, `payment`, `penalty`, `user` (and others as logged)

### Date Format

`YYYY-MM-DD` for `date_from`, `date_to`

---

# Admin Endpoints

Auth: **admin** role with specific permissions noted per endpoint.

---

### 1. `GET /admin/`

System-wide dashboard statistics.

**Permission:** `view_analytics`

**Query params:** none

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `users` | object | User counts |
| `users.customers` | int | Total customers |
| `users.loan_officers` | int | Total loan officers |
| `users.admins` | int | Total admins |
| `users.total` | int | Sum of all user types |
| `loans` | object | Loan application counts by status |
| `loans.total` | int | All applications |
| `loans.draft` | int | Status `draft` |
| `loans.pending` | int | Status `submitted` |
| `loans.under_review` | int | Status `under_review` |
| `loans.approved` | int | Status `approved` |
| `loans.rejected` | int | Status `rejected` |
| `loans.disbursed` | int | Status `disbursed` |
| `loans.cancelled` | int | Status `cancelled` |
| `documents` | object | Document stats |
| `documents.total` | int | All documents |
| `documents.pending` | int | Status `pending` |
| `documents.verified` | int | `verified: true` |
| `ai_usage` | object | AI chatbot usage |
| `ai_usage.sessions_last_7_days` | int | `ai_interactions` in last 7 days |
| `products` | array | Per active loan product |
| `products[].name` | string | Product name |
| `products[].applications` | int | Total applications for product |
| `products[].approved` | int | Approved applications for product |
| `products[].approval_rate` | string | e.g. `"75.0%"` |
| `recent_activity` | array | Last 10 audit log summaries |
| `recent_activity[].action` | string | Audit action |
| `recent_activity[].user_type` | string | Actor role |
| `recent_activity[].description` | string | Human-readable text |
| `recent_activity[].timestamp` | ISO datetime | When logged |

---

### 2. `GET /audit-logs/`

Paginated, filterable audit logs (full system).

**Permission:** `view_logs`

**Query params (all optional):**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `page` | int | 1 | >= 1 |
| `page_size` | int | 20 | 1–200 |
| `action` | string | | Exact action match (see Reference Values) |
| `action_group` | string | | `login`, `create`, `update`, `delete` |
| `user_id` | string | | Filter by actor user ID |
| `user_type` | string | | `customer`, `loan_officer`, `admin` |
| `date_from` | string | | `YYYY-MM-DD` (start of day) |
| `date_to` | string | | `YYYY-MM-DD` (end of day 23:59:59) |
| `search` | string | | Matches `description`, `user_email`, `action`, `user_id`, `user_type` (case-insensitive) |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `logs` | array |
| `logs[].id` | string |
| `logs[].user_id` | string |
| `logs[].user_type` | string |
| `logs[].user_email` | string |
| `logs[].action` | string |
| `logs[].description` | string |
| `logs[].resource_type` | string |
| `logs[].resource_id` | string |
| `logs[].details` | object (free-form; varies by action) |
| `logs[].ip_address` | string |
| `logs[].timestamp` | ISO datetime |
| `total` | int |
| `page` | int |
| `page_size` | int |
| `total_pages` | int |

**Common `details` fields by action (when present):**

| Action | Typical `details` keys |
|--------|------------------------|
| `loan_submitted` | `product`, `amount`, `term` |
| `loan_approved` | `approved_amount`, `customer_id` |
| `loan_rejected` | `reason`, `customer_id` |
| `loan_disbursed` | `amount`, `method`, `reference`, `customer_id` |
| `payment_recorded` | `loan_id`, `amount`, `installment`, `method` |
| `customer_payment_recorded` | `loan_id`, `amount`, `installment`, `method` |
| `document_uploaded` | `document_type` |
| `profile_updated` | `profile_type` |
| `penalty_applied` | `loan_id`, `installment_number`, `amount`, `reason` |
| `penalty_waived` | `loan_id`, `installment_number`, `amount`, `reason` |
| `wallet_payment_verified` | `loan_id`, `installment_number`, `eth_amount`, `php_amount`, `eth_rate`, `tx_hash` |
| `admin_action` | Varies (admin CRUD operations) |

---

### 3. `GET /audit-logs/users/`

Distinct users appearing in audit logs (for filter dropdowns).

**Permission:** `view_logs`

**Query params (all optional):**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `search` | string | | Matches `user_email`, `user_type`, `user_id` |
| `limit` | int | 200 | 1–500 |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `users` | array |
| `users[].user_id` | string |
| `users[].user_type` | string |
| `users[].user_email` | string |
| `users[].label` | string | Display label, e.g. `"user@email.com (customer)"` |

---

### 4. `GET /audit-logs/<log_id>/`

Full detail for a single audit log entry.

**Permission:** `view_logs`

**Path params:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `log_id` | string | yes | Valid MongoDB ObjectId |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `user_id` | string |
| `user_type` | string |
| `user_email` | string |
| `action` | string |
| `description` | string |
| `resource_type` | string |
| `resource_id` | string |
| `details` | object |
| `ip_address` | string |
| `timestamp` | ISO datetime |

---

# Loan Officer Endpoints

Auth: **loan_officer** or **admin**.

---

### 5. `GET /officer/`

Loan officer personal dashboard — review activity and queue stats.

**Query params:** none

**Scope:** Stats are for the authenticated officer's `id` (assigned applications).

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `my_reviews` | object | Officer's review history |
| `my_reviews.total_approved` | int | Assigned apps with status `approved` or `disbursed` |
| `my_reviews.total_rejected` | int | Assigned apps with status `rejected` |
| `my_reviews.approved_today` | int | Approved/disbursed today (`decision_date >= today`) |
| `my_reviews.rejected_today` | int | Rejected today |
| `queue` | object | Application queue |
| `queue.pending_total` | int | System-wide `submitted` + `under_review` |
| `queue.assigned_to_me` | int | Officer's `under_review` apps |
| `performance` | object | Review performance |
| `performance.total_reviewed` | int | `total_approved + total_rejected` |
| `performance.approval_rate` | string | e.g. `"72.5%"` |

---

### 6. `GET /officer/audit-logs/`

Audit logs scoped to the officer and their assigned loan applications.

**Query params (all optional):**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `page` | int | 1 | >= 1 |
| `page_size` | int | 20 | 1–200 |
| `action` | string | | Exact action match |
| `action_group` | string | | `login`, `create`, `update`, `delete` |
| `date_from` | string | | `YYYY-MM-DD` |
| `date_to` | string | | `YYYY-MM-DD` |
| `search` | string | | Matches `description`, `action`, `resource_id`, `resource_type` |

**Scope rules (what logs are included):**

- Logs where `user_id` = officer ID AND `user_type` = `loan_officer`, **OR**
- Logs where `resource_type` = `loan` AND `resource_id` is in the officer's assigned application IDs

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `logs` | array |
| `logs[].id` | string |
| `logs[].user_id` | string |
| `logs[].user_type` | string |
| `logs[].user_email` | string |
| `logs[].action` | string |
| `logs[].description` | string |
| `logs[].resource_type` | string |
| `logs[].resource_id` | string |
| `logs[].details` | object |
| `logs[].ip_address` | string |
| `logs[].timestamp` | ISO datetime |
| `total` | int |
| `page` | int |
| `page_size` | int |
| `total_pages` | int |

---

# Customer Endpoints

Auth: **customer** only.

---

### 7. `GET /customer/`

Customer personal dashboard statistics.

**Query params:** none

**Scope:** All counts filtered to authenticated `customer_id`.

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `applications` | object | Customer's loan applications |
| `applications.total` | int | All applications |
| `applications.pending` | int | Status `submitted` or `under_review` |
| `applications.approved` | int | Status `approved` |
| `applications.rejected` | int | Status `rejected` |
| `documents` | object | Customer's documents |
| `documents.total` | int | All uploaded documents |
| `documents.verified` | int | `verified: true` |
| `documents.pending` | int | Status `pending` |
| `profile_completion` | object | Profile readiness |
| `profile_completion.percentage` | string | e.g. `"67%"` (3 core sections) |
| `profile_completion.personal_profile` | boolean | Personal section has meaningful data |
| `profile_completion.business_profile` | boolean | Business type + income info present |
| `profile_completion.alternative_data` | boolean | Education + housing status present |
| `profile_completion.valid_id_uploaded` | boolean | At least one `valid_id` document |
| `ai_sessions` | int | Total `ai_interactions` for customer |

**Profile completion logic:**

- `personal_profile`: `completion_percentage > 0` on customer profile
- `business_profile`: `business_type` set AND (`income_range` OR `estimated_monthly_income`)
- `alternative_data`: `education_level` AND `housing_status` set
- `percentage`: average of the 3 boolean sections × 100 (valid ID is tracked separately)

---

## Complete URL Index (7 endpoints)

| # | Method | URL | Role | Permission |
|---|--------|-----|------|------------|
| 1 | GET | `/api/analytics/admin/` | Admin | `view_analytics` |
| 2 | GET | `/api/analytics/audit-logs/` | Admin | `view_logs` |
| 3 | GET | `/api/analytics/audit-logs/users/` | Admin | `view_logs` |
| 4 | GET | `/api/analytics/audit-logs/<log_id>/` | Admin | `view_logs` |
| 5 | GET | `/api/analytics/officer/` | Officer, Admin | — |
| 6 | GET | `/api/analytics/officer/audit-logs/` | Officer, Admin | — |
| 7 | GET | `/api/analytics/customer/` | Customer | — |

---

## Smoke Test Sequence

### Prerequisites

1. Seed or create accounts: **admin** (with `view_analytics` + `view_logs`), **loan_officer**, **customer** — each with JWT.
2. Generate audit log data by performing actions in other modules (login, loan submit, document upload, etc.).

### Steps

| Step | Actor | Endpoint | Expected |
|------|-------|----------|----------|
| 1 | Admin | `GET /admin/` | 200; `users`, `loans`, `documents`, `ai_usage`, `products`, `recent_activity` present |
| 2 | Admin | `GET /audit-logs/?page=1&page_size=20` | 200; paginated `logs` array |
| 3 | Admin | `GET /audit-logs/?action_group=login` | 200; only login-related actions |
| 4 | Admin | `GET /audit-logs/users/?limit=50` | 200; `users` array with `label` |
| 5 | Admin | `GET /audit-logs/<log_id>/` | 200; full log detail (use ID from step 2) |
| 6 | Officer | `GET /officer/` | 200; `my_reviews`, `queue`, `performance` |
| 7 | Officer | `GET /officer/audit-logs/?page=1` | 200; scoped logs only |
| 8 | Customer | `GET /customer/` | 200; `applications`, `documents`, `profile_completion`, `ai_sessions` |
| 9 | Customer | `GET /admin/` | 403 Forbidden |
| 10 | Officer | `GET /audit-logs/` | 403 Forbidden (admin-only) |
| 11 | Admin | `GET /audit-logs/<invalid_id>/` | 400 Bad Request |
| 12 | Admin | `GET /audit-logs/nonexistent_objectid/` | 404 Not Found |

### Filter Combination Tests (Admin audit logs)

```
GET /audit-logs/?user_type=customer&date_from=2026-01-01&date_to=2026-12-31
GET /audit-logs/?action=loan_submitted&page_size=50
GET /audit-logs/?search=login&action_group=login
GET /audit-logs/?user_id=<customer_id>
```

### Officer Scope Test

1. Assign a loan to Officer A only.
2. Perform loan actions on that application.
3. Officer A: `GET /officer/audit-logs/` → should see related loan logs.
4. Officer B (not assigned): `GET /officer/audit-logs/` → should NOT see Officer A's loan resource logs.

---

## Common Error Cases

| Code | When |
|------|------|
| `400 Bad Request` | Invalid `page`, `page_size`, `limit`; invalid `log_id` format (not ObjectId) |
| `401 Unauthorized` | Missing or expired JWT |
| `403 Forbidden` | Wrong role; admin missing `view_analytics` or `view_logs` permission |
| `404 Not Found` | Audit log ID does not exist; officer account not resolved (`GET /officer/`) |

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

## Data Sources (what each dashboard reads)

| Dashboard section | MongoDB collection(s) |
|-------------------|----------------------|
| User counts | `customer`, `loan_officers`, `admins` |
| Loan stats | `loan_applications` |
| Document stats | `documents` |
| AI usage | `ai_interactions` |
| Product performance | `loan_products`, `loan_applications` |
| Recent activity / audit logs | `audit_logs` |
| Customer profile completion | `customer_profiles`, `business_profiles`, `alternative_data`, `documents` |

---

## Where to Look in Code

| Area | Path |
|------|------|
| URL routing | `analytics/urls.py` |
| Admin dashboard + audit logs | `analytics/views/admin_dashboard.py` |
| Officer dashboard + audit logs | `analytics/views/officer_dashboard.py` |
| Customer dashboard | `analytics/views/customer_dashboard.py` |
| Audit log model + filters | `analytics/models/audit_log.py` |
| Audit tracker service | `analytics/services/tracker.py` |

---

## Notes for API Test Automation

1. All endpoints are **GET only** — no request bodies.
2. Admin audit log endpoints require specific permissions beyond the admin role.
3. Officer audit logs are **ABAC-scoped** — only the officer's own actions and assigned loan resources.
4. Customer dashboard counts `pending` applications as `submitted` + `under_review` (not `draft`).
5. Admin dashboard `loans.pending` counts only `submitted` status (not `under_review`).
6. `action_group=delete` uses a description regex, not a dedicated action name.
7. Audit log `details` is a free-form object — assert on known keys per action type, not a fixed schema.
8. Generate test data by exercising auth, loans, documents, and profiles APIs first; analytics reads their side effects.
