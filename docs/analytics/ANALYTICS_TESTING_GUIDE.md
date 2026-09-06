# Analytics API Testing Guide

> **Status notice (2026-08-28):** This guide documents the current API and its
> development, integration, and release-validation procedures. Analytics
> application code is complete for the reviewed scope and is awaiting final
> production-topology validation. See
> `docs/ANALYTICS_PRODUCTION_READINESS_REVIEW.md` for the module contract,
> current status, operational evidence, and remaining release conditions.

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
| `GET /audit-logs/export/` | Admin | `view_logs` |
| `GET /audit-logs/users/` | Admin | `view_logs` |
| `GET /audit-logs/<log_id>/` | Admin | `view_logs` |
| `GET /officer/` | Loan Officer | None |
| `GET /officer/audit-logs/` | Loan Officer | None |
| `GET /officer/audit-logs/export/` | Loan Officer | None |
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
| `as_of` | ISO datetime | UTC time when dashboard evaluation began |
| `metric_definition_version` | string | Current metric contract version |
| `users` | object | User counts |
| `users.customers` | int | Total customers |
| `users.loan_officers` | int | Total loan officers |
| `users.admins` | int | Total admins |
| `users.total` | int | Sum of all user types |
| `loans` | object | Loan application counts by status |
| `loans.total` | int | All applications |
| `loans.draft` | int | Status `draft` |
| `loans.submitted` | int | Status `submitted` |
| `loans.pending` | int | Status `submitted` or `under_review` |
| `loans.under_review` | int | Status `under_review` |
| `loans.approved` | int | Approved outcome statuses |
| `loans.rejected` | int | Status `rejected` |
| `loans.reviewed` | int | Approved outcomes plus rejected |
| `loans.disbursed` | int | Disbursed outcome statuses |
| `loans.completed` | int | Status `completed` |
| `loans.written_off` | int | Status `written_off` |
| `loans.cancelled` | int | Status `cancelled` |
| `documents` | object | Document stats |
| `documents.total` | int | Current, storage-available documents |
| `documents.pending` | int | Status `pending` or `needs_review` |
| `documents.needs_review` | int | Status `needs_review` |
| `documents.approved` | int | Canonical status `approved` |
| `documents.verified` | int | Compatibility alias for approved count |
| `documents.rejected` | int | Status `rejected` |
| `documents.expired` | int | Status `expired` |
| `ai_usage` | object | AI chatbot usage |
| `ai_usage.sessions_last_7_days` | int | `ai_interactions` in last 7 days |
| `products` | array | Per active loan product |
| `products[].name` | string | Product name |
| `products[].applications` | int | Total applications for product |
| `products[].reviewed` | int | Approved outcomes plus rejected |
| `products[].approved` | int | Approved outcomes for product |
| `products[].approval_rate` | string | Approved / reviewed, e.g. `"75.0%"` |
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
| `search` | string | | Case-insensitive escaped prefix of action, actor ID/type, or resource ID/type; stored descriptions/emails are not searched |

The default maximum offset is 10,000. A page beyond that window returns HTTP
400; narrow the filters instead of performing an unbounded deep scan.

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

### 2a. `GET /audit-logs/export/`

Downloads one authoritative, bounded administrator audit snapshot. It accepts
the list filters except pagination, plus `export_format=csv|excel`. The server
freezes a UTC boundary, audits the read, and excludes newer events. Results over
10,200 rows return HTTP 400 and require narrower filters. Successful responses
include snapshot, row-count, and maximum-row headers and use `Cache-Control:
no-store`. `excel` is an Excel-compatible HTML `.xls`, not a native workbook.

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
| `as_of` | ISO datetime | UTC time when dashboard evaluation began |
| `metric_definition_version` | string | Current metric contract version |
| `my_reviews` | object | Officer's review history |
| `my_reviews.total_approved` | int | Assigned approved outcome statuses |
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
| `search` | string | | Escaped prefix of `action`, `resource_id`, or `resource_type` |

**Scope rules (what logs are included):**

- Logs where `user_id` = officer ID AND `user_type` = `loan_officer`, **OR**
- Logs whose blind `scope_officer_index` captured that officer when the event occurred.

The `event-time-assignment-v1` policy prevents reassignment from transferring
historical visibility and avoids an assigned-loan `$in` list. Legacy events
without the event-time field are visible only when the officer was the actor.
The response omits actor identity, email, IP, description, and details.

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

### 6a. `GET /officer/audit-logs/export/`

Downloads the same fixed, bounded snapshot format while preserving the list's
event-time officer scope. It accepts the officer list filters except pagination,
plus `export_format=csv|excel`. The returned file never includes actor identity.

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
| `as_of` | ISO datetime | UTC time when dashboard evaluation began |
| `metric_definition_version` | string | Current metric contract version |
| `applications` | object | Customer's loan applications |
| `applications.total` | int | All applications |
| `applications.draft` | int | Status `draft` |
| `applications.pending` | int | Status `submitted` or `under_review` |
| `applications.approved` | int | Approved outcome statuses |
| `applications.rejected` | int | Status `rejected` |
| `applications.disbursed` | int | Disbursed outcome statuses |
| `applications.completed` | int | Status `completed` |
| `applications.written_off` | int | Status `written_off` |
| `applications.cancelled` | int | Status `cancelled` |
| `documents` | object | Customer's documents |
| `documents.total` | int | Current, storage-available documents |
| `documents.verified` | int | Canonical status `approved` |
| `documents.pending` | int | Status `pending` or `needs_review` |
| `documents.needs_review` | int | Status `needs_review` |
| `documents.rejected` | int | Status `rejected` |
| `documents.expired` | int | Status `expired` |
| `profile_completion` | object | Profile readiness |
| `profile_completion.percentage` | string | e.g. `"67%"` (3 core sections) |
| `profile_completion.personal_profile` | boolean | Personal section has meaningful data |
| `profile_completion.business_profile` | boolean | Business type + income info present |
| `profile_completion.alternative_data` | boolean | Education + housing status present |
| `profile_completion.valid_id_uploaded` | boolean | Current available `valid_id` is approved |
| `ai_sessions` | int | Total `ai_interactions` for customer |

**Profile completion logic:**

- each section boolean reflects that profile record's stored
  `profile_completed` value;
- `percentage` is the arithmetic mean of the stored personal, business, and
  alternative-data `completion_percentage` values; and
- `valid_id_uploaded` requires a current, storage-available `valid_id` whose
  canonical status is `approved`.

### Metric definition `2026-08-12-v1`

- Approved outcome: `approved`, `disbursed`, `completed`, or `written_off`.
- Disbursed outcome: `disbursed`, `completed`, or `written_off`.
- Reviewed: approved outcome plus `rejected`.
- Pending: `submitted` plus `under_review`.
- Product approval rate: approved outcomes divided by reviewed decisions.
- Document counts exclude unavailable/deletion-state and superseded records and
  use canonical `status` rather than the legacy `verified` boolean.
- String and legacy MongoDB `ObjectId` owner/assignee/product identifiers match.
- `as_of` is an evaluation-start timestamp, not a transactional snapshot across
  the independent source queries.

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
| `400 Bad Request` | Unknown query parameter; invalid/out-of-range/deep `page`, `page_size`, or `limit`; invalid/inverted dates; unknown action/group/actor type; search over 100 characters; invalid `log_id` format |
| `401 Unauthorized` | Missing or expired JWT |
| `403 Forbidden` | Wrong role; admin missing `view_analytics` or `view_logs` permission |
| `404 Not Found` | Audit log ID does not exist; officer account not resolved (`GET /officer/`) |
| `429 Too Many Requests` | Authenticated Analytics read rate exceeded (default 300/hour) |
| `503 Service Unavailable` | Required access audit failed or MongoDB timed out/unavailable |

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

## Implemented Baseline and Release-Environment Boundaries

Use these as negative and boundary cases while implementing the readiness plan:

1. Stage 1 now rejects invalid/unknown filters and bounds, parses dates once,
   stores a versioned action/category for new events, and reports zero pages for
   empty results. Legacy events may lack the new metadata.
2. Stages 2-3 separate response schemas, fail-closed audit privileged reads,
   encrypt sensitive stored fields and replay payloads, validate per-action
   details, sign events, and implement recovery, retention, legal holds,
   pseudonymization, export, and inventory. Target key/backfill/restore proof
   remains deployment work.
3. Stage 4 captures blind event-time officer scope, so reassignment does not
   transfer history and no assigned-loan list is materialized. Legacy unscoped
   events remain actor-only.
4. Stage 4 aligns loan/document status meanings, excludes unavailable and
   superseded documents, requires an approved valid ID, and supports mixed IDs.
5. Independent dashboard counts are not a transactional snapshot; validate the
   approved consistency SLO under concurrent writes.
6. Database least-privilege roles, key rotation, legacy backfill, retention,
   legal-hold, integrity inventory, and backup/restore still need controlled
   target-environment evidence.
7. Stage 5 bounds prefix search, offsets, active products, and MongoDB execution
   time; aggregates product metrics; and bootstraps compound indexes. The
   approved test-cluster explain/load suite passed; repeat it after selecting
   the production topology.
8. Stage 5 adds a 300/hour authenticated throttle, request/audit/backlog/
   integrity metrics, health readiness, and sanitized HTTP 503 behavior.
   Production scrape/dashboard/alert delivery remains deployment validation.

---

## Automated Test Baseline and Commands

Focused local suites:

```bash
pytest -q tests/test_analytics_api.py \
  tests/test_analytics_stage3_integrity_lifecycle.py \
  tests/test_analytics_stage4_scope_metrics.py \
  tests/test_analytics_stage5_scalability_operations.py \
  tests/test_analytics_stage6_request_auth.py \
  tests/test_analytics_monitoring_assets.py \
  tests/test_analytics_real_mongo.py \
  tests/test_analytics_deployment_integrations.py
```

Latest local result on 2026-08-28: the focused Analytics suites passed
**87 tests** and skipped **7 opt-in deployment tests**. The complete-project
suite passed **1,367 tests** and skipped **55 opt-in integration tests**.

Most API characterization cases use `mongomock` and direct view calls. Stage 6
also exercises URL routing, issued JWT validation, persisted active sessions,
live-account checks, permissions, role isolation, and revocation with DRF's
`APIClient`. Neither group proves real MongoDB plans, deployment roles, proxy
behavior, backup/restore, monitoring, or load.

The local suite now includes the controlled audit key-rotation/backfill sequence
and validation of the deployable Prometheus/Grafana assets. Environment
execution remains necessary for production-topology query-plan confirmation,
secret-manager rotation/rollback, HTTPS proxy behavior, imported monitoring,
on-call delivery, and the remaining opt-in probes below. The approved
short-lived-inconsistency policy and post-write convergence are already proven.

Do not point future load, retention, or recovery harnesses at a production
database. They must create uniquely named temporary databases and remove only
their own test data after explicit mutation approval.

### Opt-in isolated real-Mongo suite

This suite mutates and drops only its generated `an_<random>` database. Use a
non-production cluster/account with permission to create and drop that database,
then obtain explicit approval before running:

```bash
RUN_ANALYTICS_REAL_MONGO_TESTS=1 \
REAL_MONGO_TEST_URI='<isolated MongoDB URI>' \
pytest -q -m real_mongo tests/test_analytics_real_mongo.py
```

Record the server version, topology, test database prefix, dataset cardinality,
execution time, winning index/stats, and final cleanup result. Never paste the
URI or credentials into test output or release evidence.

### Opt-in deployment integration probes

Each probe is independently gated. Use only the variables for the approved
service being tested, and never paste their values into evidence:

```bash
RUN_ANALYTICS_DEPLOYMENT_MONGO_TESTS=1 \
ANALYTICS_DEPLOYMENT_MONGO_URI='<runtime MongoDB URI>' \
ANALYTICS_DEPLOYMENT_MONGO_DB='<database name>' \
pytest -q -m deployment_integration \
  tests/test_analytics_deployment_integrations.py::test_runtime_mongodb_identity_is_least_privilege

RUN_ANALYTICS_DEPLOYMENT_REDIS_TESTS=1 \
ANALYTICS_DEPLOYMENT_REDIS_URL='<isolated/shared Redis URL>' \
pytest -q -m deployment_integration \
  tests/test_analytics_deployment_integrations.py::test_two_clients_share_the_redis_throttle_counter

RUN_ANALYTICS_DEPLOYMENT_HTTP_TESTS=1 \
ANALYTICS_DEPLOYMENT_METRICS_URL='<private metrics URL>' \
ANALYTICS_DEPLOYMENT_HEALTH_URL='<public HTTPS health URL>' \
pytest -q -m deployment_integration tests/test_analytics_deployment_integrations.py
```

The Redis probe creates one random key with a 60-second TTL and deletes it in
cleanup. The MongoDB, metrics, and health probes are read-only. The MongoDB
probe rejects broad administrative roles/actions; retain the sanitized role
report generated by the platform separately because test output intentionally
does not print credentials or privilege documents.

---

## Audit Lifecycle Operator Commands

These commands were exercised against the approved development/test database
and isolated restored copy on 2026-08-13. Production use remains separately
approval-gated.

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

## Analytics Operations Runbook

Configuration defaults:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `ANALYTICS_QUERY_TIMEOUT_MS` | `3000` | MongoDB operation time budget |
| `ANALYTICS_MAX_PAGE_OFFSET` | `10000` | Maximum page-number scan offset |
| `ANALYTICS_MAX_ACTIVE_PRODUCTS` | `100` | Dashboard product-cardinality bound |
| `ANALYTICS_AUDIT_BACKLOG_ALERT_THRESHOLD` | `1` | Health degradation threshold |
| `ANALYTICS_INTEGRITY_INVENTORY_MAX_AGE_SECONDS` | `90000` | Maximum healthy inventory age |
| `ANALYTICS_READ_RATE` | `300/hour` | Per-authenticated-user read limit |

Operational signals contain only endpoint class, outcome class, queue/domain,
and integrity category labels—never query text, email/IP, identifiers, event
details, credentials, or MongoDB hosts.

When `/api/health/` reports Analytics degraded:

1. Check `audit_backlog`, `oldest_backlog_age_seconds`,
   `integrity_findings`, and `inventory_available` in the Analytics component.
2. Verify MongoDB, Celery workers/Beat, Redis/cache, and the most recent
   `analytics.collect_operational_metrics` and integrity-inventory executions.
3. If backlog exists, restore the dependency and let the idempotent reconciler
   drain it; do not edit encrypted payloads or event IDs manually.
4. If integrity findings exist, stop lifecycle/backfill mutations, preserve a
   backup, run the read-only inventory, and escalate as an evidence incident.
5. Record sanitized counts, timestamps, deployment version, alert firing and
   recovery times. Do not copy event documents into tickets or logs.

Production release evidence must show Prometheus scraping, dashboard panels,
alert delivery/resolution, MongoDB timeout behavior, throttle sharing through
Redis, and real query plans at representative cardinality.

Import `monitoring/analytics/prometheus-rules.yml` into Prometheus-compatible
rule evaluation and `monitoring/analytics/grafana-dashboard.json` into Grafana.
The checked-in thresholds are safe starting points, not approved SLOs: calibrate
them from representative traffic and record the approved values before release.

### Local live Prometheus and Grafana

The development `.env` may enable the ASGI metrics sidecar without changing
`DEBUG=True`:

```dotenv
PROMETHEUS_METRICS_ENABLED=True
PROMETHEUS_METRICS_HTTP_SERVER_ENABLED=True
PROMETHEUS_METRICS_HTTP_SERVER_PORT=8001
PROMETHEUS_METRICS_URL=http://127.0.0.1:8001/metrics
```

Restart Daphne after changing those values, then keep these commands running in
separate terminals from the repository root:

```bash
.venv/bin/dotenv -f .env run -- \
  .venv/bin/daphne -b 0.0.0.0 -p 8000 config.asgi:application

prometheus \
  --config.file="$PWD/monitoring/analytics/prometheus-smoke.yml" \
  --storage.tsdb.path=/tmp/capstone-analytics-prometheus-live \
  --web.listen-address=127.0.0.1:9090

ANALYTICS_DASHBOARD_PATH="$PWD/monitoring/analytics" \
GF_SECURITY_ADMIN_USER=admin \
GF_SECURITY_ADMIN_PASSWORD=admin \
/opt/homebrew/opt/grafana/bin/grafana server \
  --homepath /opt/homebrew/opt/grafana/share/grafana \
  --config /opt/homebrew/etc/grafana/grafana.ini \
  --packaging=brew \
  cfg:default.paths.provisioning="$PWD/monitoring/grafana/provisioning" \
  cfg:default.paths.data=/tmp/capstone-grafana-data \
  cfg:default.paths.logs=/tmp/capstone-grafana-logs \
  cfg:server.http_addr=127.0.0.1 \
  cfg:server.http_port=3000
```

Open:

- `http://127.0.0.1:8001/metrics` for raw metrics;
- `http://127.0.0.1:9090/targets` for Prometheus target health; and
- `http://127.0.0.1:3000/d/capstone-analytics/capstone-analytics-operations`
  for the dashboard.

The local Grafana bootstrap login is `admin` / `admin`; replace it when Grafana
prompts. Generate authenticated Analytics traffic to populate endpoint panels.
Backlog, replay, and integrity panels remain at zero or empty until those event
types occur. Stop local servers with `Ctrl+C`; do not expose ports 8001, 9090,
or 3000 publicly.

After deployment bootstrap and the first scheduled/manual integrity inventory,
run the read-only readiness command:

```bash
python manage.py analytics_release_check
python manage.py analytics_release_check --json
```

It reports only booleans and bounded health counts. A failure exits non-zero;
fix the failed gate rather than bypassing it.

### Remaining deployment evidence checklist

- [x] The real-Mongo harness completed against the approved test cluster; its
  indexed scope, lifecycle, and convergence cases passed.
- [ ] The production Analytics runtime database identity is limited to required collection
  reads/writes and cannot administer users/roles or unrelated databases.
- [x] Current/previous encryption-key rotation was exercised on an isolated
  restored database and verified after removing the previous key.
- [ ] Reverse-proxy request/response limits and timeouts preserve the sanitized API
  error contract.
- [x] A real encrypted backup restored 94 documents into an isolated target;
  the post-backfill integrity inventory was clean and the target was removed.
- [x] Two independent Redis clients observed one shared counter; repeat through
  multiple production application workers after deployment.
- [x] A temporary real Prometheus instance reported the Analytics scrape target
  up and loaded all eight rules; `promtool` passed firing/resolution simulations.
- [ ] Production Prometheus scrapes every Analytics metric; dashboards render expected rates,
  latency, response size, backlog age, replay, and integrity signals.
- [ ] Test alerts fire and resolve through the approved on-call route without PII.
- [x] The Analytics incident path was rehearsed from missing inventory/degraded
  health through protected backfill, fresh inventory, and HTTP 200 readiness.

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
| Query bounds and health | `analytics/services/operations.py` |
| Prometheus metrics | `analytics/metrics.py` |
| Prometheus rules | `monitoring/analytics/prometheus-rules.yml` |
| Prometheus rule tests | `monitoring/analytics/prometheus-rules.test.yml` |
| Local Prometheus smoke config | `monitoring/analytics/prometheus-smoke.yml` |
| Grafana dashboard | `monitoring/analytics/grafana-dashboard.json` |
| Cross-domain adapters | `accounts/services/audit.py`, `profiles/services/audit.py`, `loans/services/audit.py`, `documents/services/audit.py` |
| Operator commands | `analytics/management/commands/` |
| Request-level Stage 6 tests | `tests/test_analytics_stage6_request_auth.py` |
| Opt-in real-Mongo Stage 6 tests | `tests/test_analytics_real_mongo.py` |
| Opt-in deployment probes | `tests/test_analytics_deployment_integrations.py` |
| Index bootstrap | `init_db.py` |
| Focused tests | `tests/test_analytics_api.py`, `tests/test_analytics_stage3_integrity_lifecycle.py`, `tests/test_analytics_stage4_scope_metrics.py`, `tests/test_analytics_stage5_scalability_operations.py` |

---

## Notes for API Test Automation

1. All endpoints are **GET only** — no request bodies.
2. Admin audit log endpoints require specific permissions beyond the admin role.
3. Officer audit logs use the officer's own actions plus the blind officer scope
   captured under `event-time-assignment-v1`; reassignment does not transfer old
   event visibility. Legacy unscoped events remain actor-only.
4. Customer dashboard counts `pending` applications as `submitted` + `under_review` (not `draft`).
5. Admin and customer dashboard `loans.pending` both count `submitted` plus
   `under_review`.
6. New events store a stable action group; description matching exists only for
   legacy `admin_action` compatibility.
7. Audit `details` are action-specific, bounded, checked recursively for secret-
   shaped keys, and encrypted at rest. Unknown top-level keys fail validation.
8. Generate test data by exercising auth, loans, documents, and profiles APIs
   first; Analytics reads their side effects.
9. Dashboard responses include `as_of`, but counts remain separate queries rather
   than one database snapshot. The approved policy accepts transient differences
   during concurrent writes; after writes settle, the next successful refresh
   must converge to the source collections.
10. Do not assert that a passing `mongomock` test proves an index is used; use an
    explicitly gated real-Mongo `explain()` harness.
