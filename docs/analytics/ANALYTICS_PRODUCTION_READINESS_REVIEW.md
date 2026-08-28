# Analytics Module Documentation and Status

Last updated: 2026-08-28

## Overview

The Analytics module provides role-specific dashboards and protected audit-log
access for MSME Pathways. Seven read-only API operations under
`/api/analytics/` serve administrators, loan officers, and customers. The
module also owns the shared audit-event schema, protected audit persistence,
recovery queue, lifecycle controls, integrity verification, operational health,
and Analytics-specific Prometheus/Grafana assets.

Dashboard values are calculated from the Accounts, Profiles, Loans, Documents,
and AI Assistant source collections. Analytics does not own or change those
business records. It reads them using versioned metric definitions and bounded
MongoDB queries, then returns minimized, role-appropriate summaries.

This project uses PyMongo directly. Django ORM migrations are not part of the
Analytics persistence lifecycle; MongoDB validators and indexes are installed
through the project bootstrap.

## Current Status

**Module implementation status: Complete for the reviewed application scope**

**Production deployment status: Ready for production-environment validation**

The API contracts, metric definitions, audit-event protections, cross-domain
recovery, lifecycle handling, authorization, query bounds, health reporting,
monitoring assets, management commands, and local tests are implemented.
Isolated MongoDB, Redis, backup/restore, key-rotation, Prometheus, and Grafana
exercises have also been completed. Final production approval remains dependent
on the selected deployment topology and final release checks.

| Area | Status | Summary |
| --- | --- | --- |
| Dashboard APIs | Implemented | Administrator, officer, and customer dashboards use role- and owner-scoped, bounded database queries. |
| Audit-log APIs | Implemented | Administrator and officer audit views use strict filters, minimized serializers, database pagination, and privileged-read auditing. |
| Audit production | Implemented | Registered, versioned, integrity-signed events are written through a shared Analytics-owned writer. |
| Audit recovery | Implemented | Encrypted failed-write payloads are replayed idempotently by scheduled bounded reconciliation. |
| Privacy lifecycle | Implemented | Field encryption, blind subject indexes, retention, legal holds, export, deletion pseudonymization, inventory, and backfill are available. |
| Query scalability | Implemented; target proof required | Query timeouts, bounded offsets/cardinality, compound indexes, aggregation, and deterministic ordering are implemented. |
| Observability | Implemented; deployment proof pending | Metrics, health integration, Prometheus rules, and a Grafana dashboard are present and locally proven. |
| Local automated validation | Passing | Focused Analytics suite: 87 passed and 7 opt-in probes skipped; full repository suite: 1,367 passed and 55 opt-in tests skipped on 2026-08-28. |
| Deployment validation | Pending | HTTPS proxy, deployed multi-worker Redis, production monitoring/alerts, target recovery, and final release-check evidence remain. |

## Module Responsibilities

### Role-specific dashboards

- Provide system-wide administrator totals for accounts, loans, documents, AI
  interactions, recent activity, and active-loan-product performance.
- Provide each loan officer with assigned queue, decision, reviewed-total, and
  approval-rate metrics.
- Provide each customer with owner-scoped application, document, profile
  completion, valid-ID, and AI-interaction counts.
- Return `metric_definition_version` and an UTC `as_of` timestamp with each
  dashboard response.
- Count and aggregate in MongoDB instead of loading complete source collections
  into application memory.

### Audit event governance

- Maintain the versioned `AUDIT_ACTION_REGISTRY`, action groups, actor types,
  per-action detail contracts, resource types, and schema rules.
- Reject new events with unknown actions, invalid actor types, disallowed detail
  keys, credential-like nested keys, excessive depth/list/string size, or an
  oversized serialized details payload.
- Assign each event a stable unique event ID, category/action group, schema
  version, retention policy, blind subject index, canonical payload digest, and
  HMAC-SHA256 integrity signature.
- Preserve limited read compatibility for historical generic `admin_action`
  records without allowing new unregistered event shapes.

### Audit query and disclosure

- Support recent, actor, action, group, date, search, detail, count, and
  paginated audit queries.
- Parse dates once and use inclusive UTC day boundaries.
- Reject unknown parameters, unknown enums, invalid or inverted dates, excessive
  search text, and out-of-range pagination instead of silently broadening or
  clamping a request.
- Use explicit administrator-summary, administrator-detail, officer-safe, and
  dashboard-activity serializers.
- Omit stored email, raw IP, free-form description, and unrestricted details
  from API responses.

### Cross-domain audit persistence and recovery

- Provide the shared writer used by Accounts, Profiles, Loans, Documents, and
  Analytics audit producers.
- Require stable event IDs so an identical retry remains idempotent.
- Store a protected recovery item in `audit_write_failures` when the primary
  audit write fails.
- Reconcile failed writes in bounded batches and treat an identical existing
  event as successful recovery.
- Allow sensitive reads to fail closed when their required privileged-access
  audit cannot be written or safely queued.

### Audit privacy and lifecycle

- Encrypt email, description, details, IP address, and legal-hold fields using
  the shared versioned field-encryption lifecycle.
- Use keyed blind indexes for subject lookup and event-time officer assignment
  scope.
- Retain audit events under a versioned policy and exclude legal-held events
  from expiry.
- Re-sign events when legal-hold state changes.
- Include a bounded audit section with total and truncation metadata in customer
  export.
- Pseudonymize eligible customer evidence during account deletion and remove
  subject-linked unresolved recovery items.
- Inventory plaintext, missing retention data, and missing or invalid integrity
  protection without exposing event content.

### Operational health and monitoring

- Report identifier-free Analytics health as part of `/api/health/`.
- Mark Analytics degraded when the recovery backlog reaches its threshold, the
  integrity inventory is unavailable/stale, or integrity findings exist.
- Export low-cardinality request, latency, response-size, audit-write, replay,
  backlog, backlog-age, and integrity metrics.
- Supply Prometheus recording/alert rules, a smoke configuration, and an
  importable Grafana operations dashboard under `monitoring/analytics/`.
- Schedule failed-write reconciliation, retention enforcement, integrity
  inventory, and operational-metric collection through Celery Beat.

## API Status

All paths below are relative to `/api/analytics/`. Every endpoint uses
`CustomJWTAuthentication`, requires an authenticated active session, is
read-only, and is subject to the dedicated Analytics throttle.

| Method and path | Access boundary | Status | Primary response |
| --- | --- | --- | --- |
| `GET admin/` | Administrator with `view_analytics`; recent activity additionally requires `view_logs` | Implemented | System account, loan, document, AI-usage, activity, and product statistics. |
| `GET audit-logs/` | Administrator with `view_logs` | Implemented | Strictly filtered, bounded, paginated audit summaries. |
| `GET audit-logs/users/` | Administrator with `view_logs` | Implemented | Bounded actor directory derived from protected audit data. |
| `GET audit-logs/<log_id>/` | Administrator with `view_logs` | Implemented | Minimized audit detail; the privileged read is itself audited. |
| `GET officer/` | Loan officer | Implemented | Assigned queue, decisions, reviewed total, and approval rate. |
| `GET officer/audit-logs/` | Loan officer | Implemented | Minimized logs for the officer's own actions or event-time assignment scope. |
| `GET customer/` | Customer | Implemented | Owner-scoped application, document, profile-completion, valid-ID, and AI-use statistics. |

The administrator dashboard returns an empty `recent_activity` plus
`recent_activity_restricted: true` when the administrator has `view_analytics`
but lacks `view_logs`. Administrators are not treated as loan officers and must
use the administrator routes.

Audit-list filters include registered action, action group, actor type where
permitted, date range, and bounded prefix search. Pagination sorts by
`timestamp` and `_id` descending. Page sizes are capped at 200, actor-directory
aggregation is capped at 500, and requests beyond the configured offset window
return HTTP 400.

Common response behavior includes:

- HTTP 400 for malformed IDs, invalid filters, inverted dates, unknown query
  parameters, or out-of-range pagination;
- HTTP 401 for missing, invalid, revoked, or inactive authentication;
- HTTP 403 for the wrong role or missing named administrator permission;
- HTTP 404 for a valid but unknown audit-event ID;
- HTTP 429 for the Analytics read throttle; and
- sanitized HTTP 503 when MongoDB times out/fails or a required privileged-read
  audit cannot be persisted.

## Metric Contract

Dashboard metric definition `2026-08-12-v1` applies these shared rules:

- Approved outcomes include `approved`, `disbursed`, `completed`, and
  `written_off`.
- Disbursed outcomes include `disbursed`, `completed`, and `written_off`.
- Reviewed outcomes are approved outcomes plus `rejected`.
- Pending means `submitted` plus `under_review`.
- Product approval rate uses reviewed decisions as the denominator.
- Customer, officer, product, and administrator ownership queries accept current
  string IDs and supported legacy `ObjectId` shapes.
- Document counts include only the current, storage-available metadata version;
  deleted, deleting, unavailable, and superseded records are excluded.
- Valid-ID readiness requires a current, available, approved `valid_id` record.

`as_of` records when dashboard evaluation starts. The independent MongoDB
counts are not a transactionally frozen snapshot. The approved policy accepts
short-lived differences during concurrent writes; after writes settle, the
next successful refresh must converge to the source collections.

## Security and Privacy Features

### Authentication, authorization, and scope

- JWT validation, persisted active-session checks, role enforcement, account
  activity state, and named administrator permissions are tested through real
  URL dispatch.
- Customer metrics derive ownership from the authenticated customer identity.
- Officer dashboard counts are limited to applications assigned to that
  officer.
- Officer audit visibility uses `event-time-assignment-v1`: reassignment does
  not transfer historical customer/system event visibility to a new officer.
- Privileged Analytics reads generate their own audit event and fail closed if
  the required audit cannot be made durable.

### Data minimization and cryptographic protection

- API serializers expose explicit allowlisted fields instead of raw audit
  documents.
- Sensitive stored fields use application-level, versioned encryption.
- HMAC blind indexes support protected subject/officer lookup and consider
  configured previous keys during controlled rotation.
- Canonical event digests and HMAC-SHA256 signatures provide tamper evidence.
- Recovery payloads are encrypted and idempotently bound to their original
  event ID.
- Logs, metrics, health output, and release checks omit query text, email, IP,
  identifiers, event contents, database hosts, and credentials.

### Input and query safety

- Audit actions and actor types are registered and fail closed on write.
- Details use per-action allowlists and reject credential-like nested keys.
- Search values are escaped before prefix regular expressions are constructed.
- Query timeouts, page/offset limits, active-product limits, projected
  serializers, deterministic ordering, and compound indexes bound reads.
- Dependency errors return stable sanitized responses rather than driver or
  infrastructure details.

### Accepted database-identity exception

The owner has accepted use of the current single `atlasAdmin@All Resources`
MongoDB identity for both administration and runtime. The least-privilege probe
correctly fails because that identity has broad administration capabilities,
including `dropDatabase`. This is a documented accepted risk—not a passing
least-privilege control. Replacing it with a restricted runtime identity remains
a recommended hardening action, but is not a release blocker under the current
owner decision.

## Persistence and Query Design

The primary protected event collection is `audit_logs`. Failed writes are held
in `audit_write_failures`, and bounded health/inventory snapshots are stored in
`analytics_operational_state`.

`AuditLog.create_indexes()` and `AuditLog.create_validator()` are invoked by
`init_db.py`. The bootstrap provides unique event-ID, subject, officer-scope,
actor/action/resource, lifecycle, recovery, and deterministic timestamp/ID
indexes plus the JSON-schema validator. Analytics queries apply the configured
MongoDB `maxTimeMS`, bounded offsets, active-product cardinality, prefix search,
database aggregation, and deterministic ordering.

No dashboard response cache is currently used. This avoids introducing an
unapproved privacy, invalidation, or staleness contract. Shared Redis is still
required in multi-process deployments for consistent DRF throttling and shared
operational cache state.

## Operational Notes

### Management commands

| Command | Purpose |
| --- | --- |
| `audit_integrity_inventory` | Read-only bounded inventory of audit integrity, encryption, and retention metadata. |
| `backfill_audit_events` | Dry-run-first encryption, schema/retention metadata, subject indexes, and integrity protection for eligible legacy events. |
| `manage_audit_legal_hold` | Preview, set, or release a legal hold; writes require `--apply`. |
| `analytics_release_check` | Read-only, fail-closed deployment readiness report with optional JSON output. |

Before applying an audit backfill, run the inventory and dry run against an
approved target copy, resolve invalid or unregistered historical actions,
verify the field key, take and restore-test an encrypted backup, obtain mutation
approval, and repeat the inventory afterward. The command refuses invalid
existing signatures and update conflicts.

Keep required previous field keys configured until re-encryption, blind-index
rebuilding, integrity verification, backup validation, and the rollback window
are complete.

### Scheduled tasks

| Celery task | Responsibility |
| --- | --- |
| `analytics.reconcile_audit_failures` | Replay bounded failed audit writes idempotently. |
| `analytics.enforce_audit_retention` | Remove expired non-held events in bounded batches. |
| `analytics.audit_integrity_inventory` | Refresh protected integrity/encryption/retention findings. |
| `analytics.collect_operational_metrics` | Refresh backlog, age, integrity gauges, and operational health state. |

Celery worker/Beat availability, schedule ownership, retry behavior, and alerting
must be validated in the deployed runtime.

### Runtime defaults

| Setting | Default | Purpose |
| --- | ---: | --- |
| `ANALYTICS_AUDIT_RETENTION_DAYS` | `2555` | Default audit retention period. |
| `ANALYTICS_QUERY_TIMEOUT_MS` | `3000` | MongoDB operation time budget. |
| `ANALYTICS_MAX_PAGE_OFFSET` | `10000` | Maximum page-number scan offset. |
| `ANALYTICS_MAX_ACTIVE_PRODUCTS` | `100` | Dashboard active-product cardinality bound. |
| `ANALYTICS_AUDIT_BACKLOG_ALERT_THRESHOLD` | `1` | Health degradation threshold. |
| `ANALYTICS_INTEGRITY_INVENTORY_MAX_AGE_SECONDS` | `90000` | Maximum healthy inventory age. |
| `ANALYTICS_READ_RATE` | `300/hour` | Per-authenticated-user API read limit. |

Deployment owners must approve retention, throttling, capacity, timeout, and
alert thresholds against expected traffic and policy.

### Monitoring and incident handling

- Keep the application exporter private and scrape it through protected service
  discovery, a VPN, or an SSH tunnel.
- Import `monitoring/analytics/prometheus-rules.yml` and
  `monitoring/analytics/grafana-dashboard.json`; checked-in thresholds are
  starting points, not approved service-level objectives.
- Generate authenticated Analytics API requests to populate endpoint series. A
  normal login audit event alone does not increment `analytics_requests_total`.
- If health reports a recovery backlog, restore the dependency and allow the
  idempotent reconciler to drain it; do not edit encrypted recovery payloads.
- If integrity findings appear, stop lifecycle/backfill mutations, preserve a
  backup, run the read-only inventory, and treat the result as an evidence
  incident.
- Record sanitized counts, deployment version, and alert firing/recovery times;
  never place audit documents or sensitive fields into tickets or metrics.

Prometheus and Grafana may run locally while monitoring a deployed backend only
while the local machine is online and can securely reach the private metrics
endpoint. Always-on history and alerts require a managed or deployed monitoring
stack.

## Client Notes

- Existing Analytics API paths remain stable.
- The administrator web client should use `admin/` and the administrator audit
  routes. It must not use officer routes as an implicit administrator view.
- The loan-officer web client should use `officer/` and
  `officer/audit-logs/`; historical scope follows event-time assignment rather
  than the application's current assignee.
- The customer mobile client should use `customer/`; the backend derives the
  customer identity and does not accept another customer's identifier.
- Display or retain `metric_definition_version` and `as_of` so count semantics
  and refresh timing are clear.
- Do not expect arbitrary audit `details`, description, actor email, or raw IP
  fields. Administrator summary/detail and officer responses intentionally have
  different minimized shapes.
- Treat invalid or excessive filters/pagination as HTTP 400. Narrow filters
  instead of requesting offsets beyond the configured window.
- Customer account export represents `audit_logs` as
  `{items, total, truncated}`, not as an unlimited raw event list.
- A dashboard refresh may briefly combine counts from adjacent moments during
  concurrent writes. Refresh after writes settle if a workflow requires
  convergence.
- Handle sanitized HTTP 503 responses as temporary dependency/audit-safety
  failures without displaying infrastructure details.

## Validation Evidence

Current repository evidence:

- Focused Analytics suite: **87 passed and 7 opt-in deployment tests skipped**
  on 2026-08-28.
- Full repository suite: **1,367 passed and 55 opt-in tests skipped** on
  2026-08-28.
- Focused coverage includes API contracts, strict filters, integrity/lifecycle,
  event-time officer scope, metric reconciliation, query bounds, request-level
  JWT/session/permission behavior, and monitoring assets.

Recorded isolated/development evidence from 2026-08-13:

- Three real-Mongo tests passed over 5,000 events, proving validator/index
  installation, indexed officer scope, lifecycle/recovery, and concurrent-write
  convergence; generated temporary databases were removed.
- The protected legacy backfill processed 39 events with no conflict/invalid
  result, and the final integrity inventory had no finding.
- An encrypted backup restored 94 documents with no failure into an isolated
  target; key rotation remained valid after removal of the previous key, and
  the restore target was removed.
- Two Redis clients shared one counter; one Celery worker replied and Beat held
  every Analytics periodic schedule.
- Local health returned HTTP 200 with fresh inventory, zero backlog, and zero
  findings.
- Local Prometheus reported the Daphne target up with all eight rules loaded;
  Grafana 13.1.3 loaded the datasource/dashboard with real request series and
  rule firing/resolution simulations passed.
- The incident path was rehearsed from missing inventory/degraded health through
  protected backfill, fresh inventory, and recovered HTTP 200 readiness.

These exercises prove the code and operator tooling in the tested environments;
they do not certify a future production topology.

## Remaining Gaps and Release Conditions

No known application-code stage remains for the reviewed Analytics scope. The
following conditions remain for production certification:

1. Immediately before release, repeat the integrity inventory and legacy
   backfill dry run against the target database, review intervening records,
   verify encryption/integrity, and retain approved backup evidence.
2. After target bootstrap, verify validators, indexes, TTL/lifecycle behavior,
   representative query plans, MongoDB timeouts, and post-write dashboard
   convergence at representative cardinality.
3. Record the accepted single-`atlasAdmin` database-identity exception in the
   release decision, or replace it with a restricted runtime identity and pass
   the least-privilege probe.
4. Verify Analytics throttling and shared operational state across the actual
   Redis service and multiple deployed backend workers.
5. Test request/response limits, timeouts, sanitized errors, and health behavior
   through the deployed HTTPS reverse proxy/load balancer.
6. Scrape authenticated Analytics traffic in the selected monitoring topology,
   inspect the Grafana panels, calibrate thresholds, and prove alert firing and
   resolution through the approved on-call route.
7. Repeat backup/restore, field-key rotation, retention/legal-hold, incident
   response, and rollback procedures with deployed secret/storage ownership.
8. Run the first deployed integrity inventory and final authenticated smoke
   sequence, then pass `analytics_release_check` in production mode.

The accepted short-lived dashboard inconsistency policy is not a remaining gap.
Local-only Prometheus/Grafana is acceptable for development, but it cannot
provide continuous monitoring while the local machine is offline.

Until the applicable deployment conditions pass, the accurate status is
**application-complete and awaiting production-environment validation**, not a
fully certified production deployment.

## Review Boundaries

This document verifies the current repository implementation, API contracts,
local automated behavior, and the dated isolated exercises above. It does not
certify production database roles, cloud/network controls, TLS/proxy behavior,
secret-manager operation, deployed alert delivery, legal retention periods,
live data quality, staffing, incident ownership, service-level objectives, or
business metric policy without the appropriate owner approval.

Accounts owns authentication, sessions, administrator permissions, customer
lifecycle, and shared encryption keys. Profiles, Loans, Documents, and AI
Assistant own their source records and business/event semantics. Analytics owns
the accepted audit schema and must validate, protect, minimize, and scope events
rather than assuming every producer or stored legacy event is safe.

This document covers backend contracts. Dashboard presentation, accessibility,
client-side caching, offline behavior, chart correctness, and usability require
separate customer-mobile and officer/admin-web validation.

## Related Documentation

- `docs/ANALYTICS_TESTING_GUIDE.md` — endpoint examples, current test commands,
  real-environment probes, local monitoring, runbooks, and troubleshooting.
- `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` — authentication,
  permissions, account lifecycle, consent, and encryption contracts.
- `docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md` — profile source data,
  review scope, audit recovery, and customer cleanup.
- `docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` — document lifecycle,
  audit, and retention integration.
- `docs/LOANS_PRODUCTION_READINESS_REVIEW.md` — loan lifecycle, assignment,
  financial audit, and dashboard source semantics.
