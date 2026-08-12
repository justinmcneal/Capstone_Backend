# Analytics Production Readiness Review

Last updated: 2026-08-12

Scope: `analytics/`, `/api/analytics/`, the shared `audit_logs` collection,
cross-domain audit producers and recovery paths, dashboard source collections,
PyMongo indexes/bootstrap, authentication and authorization dependencies, and
analytics-related automated tests and documentation.

## Purpose and Status Definitions

This document is the evidence-based implementation and remediation plan for the
Analytics module. It distinguishes an endpoint being present from its data
being correct, private, durable, scalable, and operationally supportable.

- **Complete**: implemented and covered by proportionate automated evidence.
- **Partial**: useful behavior exists, but important correctness, security,
  durability, scalability, or operational work remains.
- **Not implemented**: no production implementation was found.
- **Deployment validation**: implemented code that still needs evidence from
  the selected real MongoDB, proxy, monitoring, and recovery environment.

The project uses PyMongo directly. Django ORM migrations are not part of the
Analytics persistence model. Unit tests using `mongomock`, direct view calls,
or patched authentication do not prove real MongoDB query plans, live JWT
behavior, production load, or database access controls.

## Executive Summary

The Analytics module is **partially implemented and not yet production-ready**.
Seven read-only endpoints provide administrator, loan-officer, and customer
dashboards plus administrator/officer audit-log views. Admin dashboard and log
routes use named permissions, customer counts are owner-scoped, officer queue
counts are assignment-scoped, audit lists paginate in MongoDB, and basic tests
pass.

Stages 1 through 3 have corrected the query contract, response disclosure,
permission separation, officer-route role semantics, privileged-read auditing,
protected audit persistence, cross-domain recovery, integrity verification, and
audit lifecycle controls. Remaining application work is concentrated in
officer audit scope, dashboard metric consistency, query/index scalability, and
observability. Real-Mongo query plans, database roles, key operations,
backfill/restore procedures, and deployment monitoring still require isolated
environment evidence.

Current local baseline:

- Analytics Stage 1-3 suites: **60 passed** on 2026-08-12.
- Full project suite after Stage 3: **1,093 passed and 21 skipped** with one
  third-party deprecation warning on 2026-08-12.
- The suite calls views directly and temporarily disables their DRF
  authentication/permission classes. Explicit role/mixin checks are exercised,
  but the real JWT and middleware boundary is not.
- The earlier `datetime.strptime(datetime_value, ...)` failure is fixed and
  covered by valid, malformed, and inverted date-range regressions.
- No opt-in real-Mongo Analytics query-plan, concurrency, retention, or load
  suite was found.

## Verified Implemented Foundations

### API surface

All seven routes are registered under `/api/analytics/` and are read-only:

| Route | Current boundary | Implementation status |
| --- | --- | --- |
| `GET admin/` | Admin with `view_analytics`; activity additionally requires `view_logs` | Implemented; metric gaps remain |
| `GET audit-logs/` | Admin with `view_logs` | Implemented; scale gaps remain |
| `GET audit-logs/users/` | Admin with `view_logs` | Implemented; query-cost gaps remain |
| `GET audit-logs/<log_id>/` | Admin with `view_logs` | Implemented with minimized response and access audit |
| `GET officer/` | Loan officer only | Implemented; metric consistency needs correction |
| `GET officer/audit-logs/` | Loan officer only | Implemented with minimized response; scope and scale gaps remain |
| `GET customer/` | Customer owner | Implemented; lifecycle and mixed-ID counting gaps remain |

### Authentication and role checks

- Views declare `CustomJWTAuthentication` and `IsAuthenticated`.
- Administrator dashboard access requires `view_analytics`.
- Administrator audit-log list, user directory, and detail require `view_logs`.
- Customer dashboard access uses `AccessControlMixin.require_customer`.
- Officer endpoints require the `loan_officer` role; administrators use the
  administrator routes instead of being interpreted as an officer identity.
- Malformed audit-log ObjectIds return HTTP 400 and missing records return 404.

The administrator dashboard returns an empty activity list plus
`recent_activity_restricted: true` when the administrator lacks `view_logs`.
Audit-derived response contracts omit stored email, IP, description, and
free-form details. Privileged administrator and officer reads are themselves
recorded and fail closed with HTTP 503 if that record cannot be written.

### Dashboard aggregation

- Admin statistics cover account totals, recent account creation, every main
  loan status, document totals, recent AI interactions, active product
  application/approval counts, and ten recent audit summaries.
- Officer statistics cover assigned approval/rejection totals, decisions today,
  assigned submitted/under-review queues, total reviewed, and approval rate.
- Customer statistics cover owned application/document counts, profile section
  completion, valid-ID presence, and owned AI-interaction count.
- Counts execute in MongoDB rather than loading entire source collections.

### Audit query and serialization support

- `AuditLog` supports recent, actor, action, filtered, counted, and paginated
  reads.
- Admin and officer log lists use `skip`/`limit` in MongoDB and cap page size at
  200.
- Audit-log user aggregation is capped at 500 results.
- Dashboard, administrator summary/detail, and officer-safe response serializers
  expose only their explicit fields.
- Search text is escaped before MongoDB regular expressions are constructed.
- Action groups provide `login`, `read`, `create`, `update`, and a derived
  `delete` filter.

### Audit production and cross-domain integration

- Accounts, Profiles, Loans, and Documents write security and business events
  to `audit_logs`.
- Accounts, Profiles, Loans, and Documents use one Analytics-owned writer with
  stable event IDs and encrypted replay payloads.
- Scheduled reconciliation replays each failed event with its original event ID
  and treats an identical existing event as success.
- Sensitive profile, loan, and document reads can require a durable audit before
  data is returned.
- Customer account export includes a bounded audit section with explicit total
  and truncation metadata, and account deletion pseudonymizes eligible events.

### Persistence bootstrap

`AuditLog.create_indexes()` and `AuditLog.create_validator()` are called by
`init_db.py`. Bootstrap provides a unique event-ID index, subject and lifecycle
indexes, deterministic timestamp/ID support, and a MongoDB JSON-schema
validator. This does not yet prove the remaining dashboard and filtered-list
query plans at production volume.

## Confirmed Production Blockers and Gaps

### 1. Query contract and action registry

**Status: Complete at code and automated-test level**

Stage 1 now parses each date exactly once and applies inclusive UTC day bounds.
Malformed or inverted dates return HTTP 400. Unknown query parameters, actions,
action groups, actor types, out-of-range pages/page sizes/limits, and searches
over 100 characters also return 400 rather than being ignored or clamped.

Pagination now sorts by `timestamp` and `_id` descending, and an empty result
reports zero total pages. `audit-logs/users/` uses the same strict validation.

The versioned `AUDIT_ACTION_REGISTRY` contains current Accounts, Profiles,
Loans, Documents, payment, consent, and administration actions. New writes fail
closed for unknown actions or actor types and persist `event_schema_version`
plus the stable `action_group`. Existing legacy `admin_action` delete-like
descriptions remain query-compatible until those historical records/producers
can be normalized without rewriting evidence.

Stage 1 adds 15 focused cases for valid date filtering, malformed/inverted
dates, unknown filters/enums, strict bounds, bounded search, zero-page results,
deterministic tie-breaking, registry metadata, and fail-closed writes.

### 2. Sensitive audit storage protection

**Status: Complete at code and automated-test level**

Stage 2 minimized administrator, officer, dashboard, detail, and actor-directory
responses. Stage 3 adds audit schema version 2, explicit detail-key contracts
for each registered action, nested credential-key rejection, depth/list/string/
total-size limits, encrypted email/description/details/IP/legal-hold fields, and
blind HMAC subject indexes. Account-deletion events are minimized at issuance.

Application tests prove ciphertext storage and authorized round trips with the
local encryption configuration. Production approval still requires target key
provisioning, rotation/recovery evidence, and dry-run review of legacy records
before applying the specialized audit backfill.

### 3. Audit integrity, durability, and lifecycle

**Status: Complete at code and automated-test level; deployment validation remains**

New events receive a stable unique ID, canonical payload digest, retention
policy/version, blind subject index, and HMAC-SHA256 integrity signature. The
central writer validates before persistence, stores encrypted replay payloads
on backend failures, and reconciles them idempotently across Accounts, Profiles,
Loans, Documents, and Analytics. Required security reads remain fail closed.

Scheduled retention excludes legal holds. Legal-hold set/release recomputes the
signature, account deletion pseudonymizes eligible customer evidence and removes
subject-linked unresolved replay data, and account export reports bounded items,
total, and truncation. A read-only inventory detects missing/invalid integrity,
missing retention metadata, and plaintext sensitive fields. The specialized
backfill is dry-run-first, refuses invalid existing hashes and unregistered
legacy actions, and preserves event meaning.

Production still needs least-privilege MongoDB roles and evidence for the real
key, backup/restore, retention, legal-hold, inventory, and backfill procedures.
Stage 5 remains responsible for sanitized health/backlog metrics and alerts.

### 4. Legacy event normalization and registry governance

**Status: Implemented; deployment inventory and apply approval remain**

New writes use schema version 2, the action registry, per-action detail
contracts, category, retention metadata, encryption, and integrity protection.
The dry-run-first `backfill_audit_events` command inventories and prepares
eligible legacy events without rewriting their semantics. It refuses records
with invalid existing signatures or unregistered actions for manual review.

Before deployment, run and review the dry run against the target copy, resolve
unknown historical actions, take an approved backup, and only then authorize
`--apply`. Generic historical `admin_action` delete matching remains read-only
compatibility; new producers should use specific registered actions.

### 5. Officer audit scope and admin semantics need redesign

**Status: Blocked for production**

Officer logs include the officer's own events plus every loan event whose
resource ID belongs to a currently assigned application. This has several
problems:

- it materializes every assigned application ID into an unbounded Python list
  and sends it back to MongoDB as a large `$in` clause;
- current assignment determines visibility of historical events, so reassignment
  can transfer old event visibility to the new officer and remove it from the
  prior officer without an explicit history policy;
- Stage 2 now returns a minimal officer schema without actor identity, email,
  IP, description, or free-form details;
- Stage 2 removed customer-name and sensitive stored-field search expansion;
  officer search is limited to action and resource fields; and
- administrators are now rejected by officer routes and use administrator
  endpoints with named permissions.

Required remediation:

- choose and document current-scope versus event-time-scope semantics;
- persist an approved scope/assignment reference on each relevant event or use
  a bounded server-side join/materialized projection;
- prove the remaining scoped action/resource search plan under representative
  real-Mongo data volume.

### 6. Dashboard metrics are not yet a stable business contract

**Status: High priority**

The dashboards issue independent counts without an `as_of` timestamp, snapshot,
or definition version. Concurrent writes can make one response internally
inconsistent. Metric meanings also differ:

- officer “approved” includes `approved` and `disbursed`, while customer/admin
  approved counts and product approval rates use only `approved`;
- customer application totals include draft/cancelled/disbursed records, but
  the displayed breakdown omits some of those states;
- raw document counts can include `delete_pending`/`delete_failed` records and
  use legacy `verified` rather than canonical status;
- valid-ID presence accepts any status, including rejected, expired, or deleting
  records;
- raw string-only customer queries can miss legacy `ObjectId` identifiers even
  though domain models already support mixed IDs; and
- profile documentation previously described boolean completion, while the code
  averages three stored completion percentages and reports separate completion
  booleans.

Required remediation:

- publish versioned metric definitions and response `as_of` timestamps;
- align status buckets with canonical Loans/Documents lifecycle helpers;
- decide whether approved includes disbursed and use that definition everywhere;
- exclude unavailable/deleting documents and define valid-ID readiness;
- use mixed-ID-safe domain query helpers; and
- add reconciliation invariants and fixture-based cross-domain tests.

### 7. Query design and indexes are insufficient for production volume

**Status: High priority**

Single-field audit indexes do not fully support the actual filtered sort paths.
Lists sort only by `timestamp`, so equal timestamps have no deterministic `_id`
tie-breaker. Unanchored multi-field regex search is not index-supported.
`audit-logs/users/` sorts and groups across the event collection, and admin
product statistics perform two application counts per active product.

No `explain()` evidence, collection-size targets, response-time budget,
`maxTimeMS`, bounded product count, cache policy, or snapshot/materialized
dashboard strategy is documented. Analytics endpoints also have no dedicated
DRF throttles despite potentially expensive queries.

Required remediation:

- define query shapes and add compound indexes such as actor/type/time/id,
  resource/type/time/id, and action/time/id where explain evidence supports
  them;
- add deterministic `timestamp`/`_id` ordering and preferably cursor pagination
  for deep history;
- replace broad regex with bounded exact/prefix/blind-index search or a
  separately approved search service;
- replace unbounded officer `$in` and per-product N+1 counts with aggregation or
  maintained projections;
- add safe query timeouts, dedicated read throttles, and carefully keyed caching
  only where privacy and staleness rules allow; and
- run opt-in real-Mongo load/explain tests at representative cardinalities.

### 8. Observability and failure behavior are incomplete

**Status: Medium priority**

The module has no Analytics-specific request latency, query failure, response
size, audit-write failure, recovery backlog, integrity, or stale-dashboard
metrics. Dashboard database exceptions are not normalized into a stable API
error, and health does not report audit persistence/recovery readiness.

Required remediation:

- add low-cardinality counters/histograms and backlog/oldest-age gauges;
- alert on privileged-read failures, query timeouts, audit write/replay backlog,
  integrity mismatch, and dashboard latency/error budgets;
- return a sanitized stable service-unavailable response for dependency outages;
- ensure logs and metrics never include query text, emails, IPs, IDs, event
  details, or credentials; and
- document on-call diagnosis, backup/restore, and incident evidence procedures.

### 9. Automated evidence remains environment-limited

**Status: High priority**

The 60 Analytics Stage 1-3 tests establish useful behavior, but most API cases call view classes
directly after clearing DRF authentication and permission classes. The suite
does not cover:

- real JWT/cookie/middleware/live-account authentication;
- full historical officer reassignment semantics;
- production encryption-key rotation, database-level least privilege, or real
  backup/restore execution;
- mixed string/ObjectId records and delete-pending documents;
- dashboard metric invariants under complete lifecycle fixtures;
- database outage/timeouts beyond fail-closed privileged-read auditing; or
- real MongoDB indexes, query plans, deep pagination, and representative load.

## Remediation Plan

The stages below follow technical dependencies rather than an arbitrary stage
count.

### Stage 1 — Contract and query correctness

**Status: Complete**

- [x] Fix single-pass date parsing and strict filter/pagination/search validation.
- [x] Define deterministic pagination and empty-page behavior.
- [x] Register current emitted actions and categories and enforce new writes.
- [x] Add regressions for the reproduced date failure and all invalid/broadening
  filter cases.

### Stage 2 — Privacy and authorization boundary

**Status: Complete**

- [x] Separate dashboard summaries, admin log summaries/details, and officer-safe
  event schemas.
- [x] Enforce `view_logs` on all audit-derived administrator content.
- [x] Make officer routes officer-only; administrators use named-permission
  administrator routes.
- [x] Audit privileged Analytics reads with fail-closed behavior and add field-
  leakage tests.

### Stage 3 — Audit event integrity and lifecycle

**Status: Complete at code and automated-test level**

- [x] Add validated, allowlisted, versioned events and stable idempotency IDs.
- [x] Apply encryption/minimization and an approved blind subject index.
- [x] Centralize encrypted, idempotent failure recovery across Accounts,
  Profiles, Loans, Documents, and Analytics.
- [x] Implement retention, legal holds, pseudonymization, bounded export,
  tamper evidence, and integrity inventory.
- [x] Add dry-run-first legacy backfill and legal-hold operator commands.
- [ ] Prove key operations, backup/restore, database roles, and controlled
  command execution in Stage 6's isolated deployment environment.

### Stage 4 — Scope and metric correctness

- Implement bounded officer event-time/current-scope policy.
- Use canonical mixed-ID and lifecycle-aware domain queries.
- Version metric definitions, align status semantics, add `as_of`, and test
  cross-domain reconciliation invariants.

### Stage 5 — Scalability and observability

- Add evidence-driven compound indexes, deterministic/cursor pagination,
  bounded search, aggregations/projections, query timeouts, and throttles.
- Add Analytics metrics, health/backlog signals, alerts, sanitized logging, and
  an operational runbook section in the testing guide.

### Stage 6 — Real-environment release validation

- Add end-to-end JWT/permission tests and opt-in real-Mongo load/explain,
  durability, retention, and recovery harnesses.
- Validate database roles, encryption keys, proxy behavior, backup/restore,
  monitoring, alerting, and incident procedures in an isolated deployment-like
  environment.
- Re-run the focused and full project suites and record evidence here.

## API and Client Impact Notes

- Existing endpoint paths can remain stable.
- Clients should expect invalid filters and out-of-range pagination to return
  HTTP 400 after Stage 1 instead of being ignored or clamped.
- Stage 2 made audit list/detail fields smaller and role-specific. Frontends
  must use the documented summary/detail contracts and must not expect arbitrary
  `details`, descriptions, raw IP, or actor email.
- Customer account export now represents `audit_logs` as
  `{items, total, truncated}` instead of a raw latest-200 array.
- Officer/admin clients must not use the officer route as an implicit admin
  dashboard. Any admin target-officer workflow should be explicit.
- Metric-definition alignment may change counts such as approved/disbursed,
  pending/deleting documents, and valid-ID readiness. Versioning or a coordinated
  client release is required.
- Cursor pagination may supplement or replace deep page-number navigation while
  retaining a bounded compatibility window.

## Review Boundaries

This review verifies repository implementation and local automated behavior. It
does not certify production MongoDB roles, encryption at rest, network controls,
legal retention periods, staffing/SLAs, live data quality, or the accuracy of
business definitions without product/compliance approval.

Accounts owns authentication, admin permissions, account lifecycle, and shared
encryption keys. Profiles, Loans, Documents, and AI Assistant own their source
records and event semantics. Analytics must validate and minimize the events it
accepts instead of assuming every producer is safe.

## Release Gate

Do not classify Analytics as production-ready until Stages 1–5 are implemented
and tested, Stage 6 evidence is recorded, no privileged query can silently
broaden, audit-derived data requires the correct permission, sensitive event
fields are minimized/protected, officer scope is proven, event integrity and
lifecycle controls are operational, dashboard definitions reconcile with source
domains, and representative real-Mongo query plans meet an approved performance
budget.

## Related Documentation

- `docs/ANALYTICS_TESTING_GUIDE.md` — current API behavior, endpoint examples,
  test baseline, known limitations, and future validation procedures
- `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` — authentication,
  permissions, account lifecycle, consent, and encryption contracts
- `docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md` — profile completion,
  officer directory scope, audit recovery, and customer cleanup
- `docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` — document lifecycle,
  audit and retention integration
- `docs/LOANS_PRODUCTION_READINESS_REVIEW.md` — loan lifecycle, assignment,
  financial audit, and dashboard source semantics
