# Analytics API Testing Guide

> **Readiness notice (2026-08-12):** This guide documents the current API for
> development and characterization testing. Analytics is not yet production-
> ready. Stages 1-3 (query correctness, privacy, protected audit persistence,
> integrity, recovery, and lifecycle) are complete at code/test level. Officer
> scope, metric consistency, query scalability/observability, and real-
> environment validation remain open. See
> `docs/ANALYTICS_PRODUCTION_READINESS_REVIEW.md` for the evidence and staged
> remediation plan.

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
| `docs/LOANS_TESTING_GUIDE.md` | Loan APIs that generate many audit log entries |
| `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` | Authentication and admin permissions (`view_analytics`, `view_logs`) |
| `docs/ANALYTICS_PRODUCTION_READINESS_REVIEW.md` | Verified implementation, risks, remediation plan, and release gate |

## Role and Permission Matrix

| Endpoint | Allowed Role | Required Admin Permission |
|----------|--------------|---------------------------|
| `GET /admin/` | Admin | `view_analytics` |
| `GET /audit-logs/` | Admin | `view_logs` |
| `GET /audit-logs/users/` | Admin | `view_logs` |
| `GET /audit-logs/<log_id>/` | Admin | `view_logs` |
| `GET /officer/` | Loan Officer | None |
| `GET /officer/audit-logs/` | Loan Officer | None |
| `GET /customer/` | Customer | None |

---

## Reference Values

### Audit Log User Types (`user_type` filter)

`customer`, `loan_officer`, `admin`, `super_admin`, `system`

### Audit Log Action Groups (`action_group` filter)

| Group | Matching `action` values |
|-------|--------------------------|
| `login` | `user_login`, `user_login_failed`, `user_logout` |
| `read` | Profile/document directory, detail, history, export, and denied-read events registered in `ACTION_GROUPS` |
| `create` | Includes `user_registered`, `profile_created`, `loan_submitted`, `document_uploaded`, `payment_recorded` |
| `update` | Includes `profile_updated`, `notification_preferences_updated`, `document_verified`, `document_rejected`, `loan_approved`, `loan_rejected`, `loan_disbursed`, `penalty_applied`, `penalty_waived`, `consent_recorded`, `admin_action` |
| `delete` | Admin/officer deactivation actions plus `admin_action` entries whose description matches delete/deactivate/remove (regex) |

### Canonical Audit Actions (`AUDIT_ACTIONS` in code)

The versioned list is maintained by `AUDIT_ACTION_REGISTRY` in code. New schema
version 2 events reject unknown actions/actor types, enforce an explicit
per-action details contract, and store stable action-group, retention,
idempotency, subject-index, and integrity metadata. Legacy records may lack
those fields until the reviewed backfill is applied. Profile actions
include `profile_created`, `profile_updated`,
`notification_preferences_updated`, `profile_directory_viewed`,
`profile_sensitive_read`, `profile_access_denied`, `profile_exported`,
`profile_history_viewed`, the risk-review workflow, and the risk-score lifecycle
actions.

### Additional Registered Cross-Domain Actions

The Stage 1 registry also includes `loan_draft_updated_and_submitted`, `loan_assigned`,
`loan_reassigned`, `loan_resubmitted`, `loan_disbursement_pending`,
`loan_disbursement_failed`, `customer_payment_submitted`,
`customer_payment_recorded`, `disbursement_method_set`,
`wallet_payment_verified`, `repayment_schedule_exported`,
`loan_internal_note_added`, `loan_missing_documents_requested`, and the
Stage 2 `analytics_privileged_read` event.

### Resource Types (in audit log entries)

`loan`, `document`, `profile`, `payment`, `penalty`, `user`,
`analytics_endpoint` (and others as logged)

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
| `recent_activity` | array | Last 10 minimized audit summaries; empty without `view_logs` |
| `recent_activity_restricted` | boolean | `true` when the caller lacks `view_logs` |
| `recent_activity[].action` | string | Audit action |
| `recent_activity[].action_group` | string | Stable action category |
| `recent_activity[].actor_type` | string | Actor role |
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
| `action_group` | string | | `login`, `read`, `create`, `update`, `delete` |
| `user_id` | string | | Filter by actor user ID |
| `user_type` | string | | `customer`, `loan_officer`, `admin` |
| `date_from` | string | | `YYYY-MM-DD`; inclusive UTC start of day |
| `date_to` | string | | `YYYY-MM-DD`; inclusive UTC end of day and must not precede `date_from` |
| `search` | string | | Matches action, actor ID/type, and resource ID/type; stored descriptions and emails are not searched |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `logs` | array |
| `logs[].id` | string |
| `logs[].action` | string |
| `logs[].action_group` | string |
| `logs[].actor_type` | string |
| `logs[].resource_type` | string |
| `logs[].resource_id` | string |
| `logs[].timestamp` | ISO datetime |
| `total` | int |
| `page` | int |
| `page_size` | int |
| `total_pages` | int |

Results sort by `timestamp` descending and then `_id` descending. An empty
result reports `total_pages: 0`; a page beyond the end returns an empty `logs`
array while preserving `total` and `total_pages`.

Stored descriptions, actor emails, IP addresses, and free-form `details` are
deliberately absent from the list response. Clients must not depend on those
legacy stored fields.

---

### 3. `GET /audit-logs/users/`

Distinct users appearing in audit logs (for filter dropdowns).

**Permission:** `view_logs`

**Query params (all optional):**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `search` | string | | Matches `user_type` and `user_id` only |
| `limit` | int | 200 | 1–500 |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `users` | array |
| `users[].user_id` | string |
| `users[].user_type` | string |
| `users[].label` | string | Redacted display label, e.g. `"customer (65ab12cd...)"` |

---

### 4. `GET /audit-logs/<log_id>/`

Minimized privileged detail for a single audit log entry.

**Permission:** `view_logs`

**Path params:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `log_id` | string | yes | Valid MongoDB ObjectId |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `action` | string |
| `action_group` | string |
| `event_schema_version` | int |
| `actor.id` | string or null |
| `actor.type` | string |
| `resource_type` | string |
| `resource_id` | string |
| `timestamp` | ISO datetime |

---

# Loan Officer Endpoints

Auth: **loan_officer** only. Administrators use the administrator dashboard and
audit-log routes with their named permissions.

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
| `queue.pending_total` | int | Officer's assigned `submitted` + `under_review` |
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
| `action_group` | string | | `login`, `read`, `create`, `update`, `delete` |
| `date_from` | string | | `YYYY-MM-DD`; inclusive UTC start of day |
| `date_to` | string | | `YYYY-MM-DD`; inclusive UTC end of day and must not precede `date_from` |
| `search` | string | | Matches `action`, `resource_id`, and `resource_type` |

**Scope rules (what logs are included):**

- Logs where `user_id` = officer ID AND `user_type` = `loan_officer`, **OR**
- Logs where `resource_type` = `loan` AND `resource_id` is in the officer's assigned application IDs

This remains a current-assignment visibility policy and builds an unbounded
assigned-ID list; Stage 4 owns that scope/query redesign. Stage 2 makes the
response safe for officers by removing all actor identity, email, IP,
description, and free-form details.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `logs` | array |
| `logs[].id` | string |
| `logs[].action` | string |
| `logs[].action_group` | string |
| `logs[].resource_type` | string |
| `logs[].resource_id` | string |
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

- each section boolean reflects that profile record's stored
  `profile_completed` value;
- `percentage` is the arithmetic mean of the stored personal, business, and
  alternative-data `completion_percentage` values; and
- `valid_id_uploaded` currently means any matching document record exists. It
  does not yet exclude rejected, expired, superseded, or deletion-state records.

---

## Complete URL Index (7 endpoints)

| # | Method | URL | Role | Permission |
|---|--------|-----|------|------------|
| 1 | GET | `/api/analytics/admin/` | Admin | `view_analytics` |
| 2 | GET | `/api/analytics/audit-logs/` | Admin | `view_logs` |
| 3 | GET | `/api/analytics/audit-logs/users/` | Admin | `view_logs` |
| 4 | GET | `/api/analytics/audit-logs/<log_id>/` | Admin | `view_logs` |
| 5 | GET | `/api/analytics/officer/` | Officer | — |
| 6 | GET | `/api/analytics/officer/audit-logs/` | Officer | — |
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
| 5 | Admin | `GET /audit-logs/<log_id>/` | 200; minimized privileged detail (use ID from step 2) |
| 6 | Officer | `GET /officer/` | 200; `my_reviews`, `queue`, `performance` |
| 7 | Officer | `GET /officer/audit-logs/?page=1` | 200; scoped logs only |
| 8 | Customer | `GET /customer/` | 200; `applications`, `documents`, `profile_completion`, `ai_sessions` |
| 9 | Customer | `GET /admin/` | 403 Forbidden |
| 10 | Officer | `GET /audit-logs/` | 403 Forbidden (admin-only) |
| 11 | Admin | `GET /audit-logs/<invalid_id>/` | 400 Bad Request |
| 12 | Admin | `GET /audit-logs/nonexistent_objectid/` | 404 Not Found |
| 13 | Admin | `GET /officer/` | 403 Forbidden (officer-only) |
| 14 | Admin without `view_logs` | `GET /admin/` | 200; `recent_activity: []`, `recent_activity_restricted: true` |

### Filter Combination Tests (Admin audit logs)

```
GET /audit-logs/?user_type=customer&date_from=2026-01-01&date_to=2026-12-31
GET /audit-logs/?action=loan_submitted&page_size=50
GET /audit-logs/?search=login&action_group=login
GET /audit-logs/?user_id=<customer_id>
```

These are now passing Stage 1 contract cases. Invalid dates, inverted ranges,
unknown actions/groups/parameters, out-of-range pagination, and searches longer
than 100 characters return HTTP 400 instead of silently broadening the query.

### Officer Scope Test

1. Assign a loan to Officer A only.
2. Perform loan actions on that application.
3. Officer A: `GET /officer/audit-logs/` → should see related loan logs.
4. Officer B (not assigned): `GET /officer/audit-logs/` → should NOT see Officer A's loan resource logs.

---

## Common Error Cases

| Code | When |
|------|------|
| `400 Bad Request` | Unknown query parameter; invalid/out-of-range `page`, `page_size`, or `limit`; invalid/inverted dates; unknown action/group/actor type; search over 100 characters; invalid `log_id` format |
| `401 Unauthorized` | Missing or expired JWT |
| `403 Forbidden` | Wrong role; admin missing `view_analytics` or `view_logs` permission |
| `404 Not Found` | Audit log ID does not exist; officer account not resolved (`GET /officer/`) |
| `503 Service Unavailable` | A privileged Analytics read could not be audit-recorded |

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

## Remaining Gaps to Characterize Before Release

Use these as negative and boundary cases while implementing the readiness plan:

1. Stage 1 now rejects invalid/unknown filters and bounds, parses dates once,
   stores a versioned action/category for new events, and reports zero pages for
   empty results. Legacy events may lack the new metadata.
2. Stages 2-3 separate response schemas, fail-closed audit privileged reads,
   encrypt sensitive stored fields and replay payloads, validate per-action
   details, sign events, and implement recovery, retention, legal holds,
   pseudonymization, export, and inventory. Target key/backfill/restore proof
   remains deployment work.
3. Officer historical visibility follows current assignment and the query
   materializes every assigned loan ID.
4. Customer/admin document counts can include deletion-state records; valid-ID
   presence ignores review/lifecycle status; approved/disbursed meanings differ
   between dashboards.
5. Raw string-only counts can miss legacy `ObjectId` owner fields.
6. Database least-privilege roles, key rotation, legacy backfill, retention,
   legal-hold, integrity inventory, and backup/restore still need controlled
   target-environment evidence.
7. Current regex/assigned-ID and dashboard query shapes lack real-Mongo explain
    and representative-load evidence.
8. Analytics has no dedicated throttles, latency/error/backlog metrics, health
   component, alerts, or dependency-outage response contract.

---

## Automated Test Baseline and Commands

Focused local suites:

```bash
pytest -q tests/test_analytics_api.py tests/test_analytics_stage3_integrity_lifecycle.py
```

Latest Stage 3 result on 2026-08-12: the focused suites passed **60 tests** and
the complete project suite passed **1,093 tests**, skipped **21 opt-in
integration tests**, and reported one third-party deprecation warning.

The API suite uses `mongomock`, calls views directly, and temporarily clears
their DRF authentication/permission classes before `force_authenticate`. It is
useful for view/mixin behavior but does not prove live JWT authentication,
middleware, URL dispatch, real MongoDB query plans, database roles, encryption,
retention, recovery, load, or deployment monitoring.

Required future test groups:

- request-level JWT and complete role/permission matrix tests through URLs;
- strict pagination/date/enum/search validation and non-broadening regressions;
- admin summary-versus-log permission and sensitive-field redaction tests;
- officer cross-assignment, reassignment, historical-scope, admin-target, and
  bounded-search tests;
- production-key rotation/recovery and controlled legacy-backfill tests;
- lifecycle-complete dashboard fixtures with mixed string/ObjectId ownership and
  reconciliation invariants; and
- opt-in isolated real-Mongo index/explain, deep-history, aggregation, timeout,
  and representative-cardinality tests.

Do not point future load, retention, or recovery harnesses at a production
database. They must create uniquely named temporary databases and remove only
their own test data after explicit mutation approval.

---

## Audit Lifecycle Operator Commands

These commands are documented for an approved isolated/deployment workflow;
they were not run against a real database during Stage 3.

Read-only integrity/encryption/retention inventory:

```bash
python manage.py audit_integrity_inventory --limit 10000
```

Legacy protection preview (dry run is the default):

```bash
python manage.py backfill_audit_events --limit 10000
```

After reviewing invalid/unregistered events, verifying the encryption key,
taking an approved backup, and obtaining mutation approval:

```bash
python manage.py backfill_audit_events --limit 10000 --apply
```

Legal holds also preview by default and require `--apply` to mutate data:

```bash
python manage.py manage_audit_legal_hold <event_id> --action set --actor <operator_id> --reason "<approved reason>"
python manage.py manage_audit_legal_hold <event_id> --action release --actor <operator_id>
```

Append `--apply` only after the preview and authorization are complete. Record
the command result and repeat the read-only inventory afterward.

---

## Where to Look in Code

| Area | Path |
|------|------|
| URL routing | `analytics/urls.py` |
| Admin dashboard + audit logs | `analytics/views/admin_dashboard.py` |
| Officer dashboard + audit logs | `analytics/views/officer_dashboard.py` |
| Customer dashboard | `analytics/views/customer_dashboard.py` |
| Audit log model + filters | `analytics/models/audit_log.py` |
| Shared audit query helpers | `analytics/services/audit_queries.py` |
| Central audit writer/recovery | `analytics/services/audit_writer.py` |
| Retention, holds, export, deletion, inventory | `analytics/services/lifecycle.py` |
| Scheduled lifecycle/recovery tasks | `analytics/tasks.py`, `config/celery.py` |
| Cross-domain adapters | `accounts/services/audit.py`, `profiles/services/audit.py`, `loans/services/audit.py`, `documents/services/audit.py` |
| Operator commands | `analytics/management/commands/` |
| Index bootstrap | `init_db.py` |
| Focused tests | `tests/test_analytics_api.py`, `tests/test_analytics_stage3_integrity_lifecycle.py` |

---

## Notes for API Test Automation

1. All endpoints are **GET only** — no request bodies.
2. Admin audit log endpoints require specific permissions beyond the admin role.
3. Officer audit logs currently use the officer's own actions plus loan resources
   in the officer's current assignment set. Treat this as provisional scope,
   not a proven event-time ABAC policy.
4. Customer dashboard counts `pending` applications as `submitted` + `under_review` (not `draft`).
5. Admin dashboard `loans.pending` counts only `submitted` status (not `under_review`).
6. New events store a stable action group; description matching exists only for
   legacy `admin_action` compatibility.
7. Audit `details` are action-specific, bounded, checked recursively for secret-
   shaped keys, and encrypted at rest. Unknown top-level keys fail validation.
8. Generate test data by exercising auth, loans, documents, and profiles APIs
   first; Analytics reads their side effects.
9. Dashboard counts are separate queries with no snapshot or `as_of` value, so
   concurrent source writes can make one response internally inconsistent.
10. Do not assert that a passing `mongomock` test proves an index is used; use an
    explicitly gated real-Mongo `explain()` harness.
