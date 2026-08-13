# Analytics Production Readiness Review

Last updated: 2026-08-13

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

The Analytics module is **complete for the reviewed application-code scope and
ready for deployment when a production environment is selected**. Final
production certification is intentionally deferred until that deployment
exists.
Seven read-only endpoints provide administrator, loan-officer, and customer
dashboards plus administrator/officer audit-log views. Admin dashboard and log
routes use named permissions, customer counts are owner-scoped, officer queue
counts are assignment-scoped, audit lists paginate in MongoDB, and basic tests
pass.

Stages 1 through 6 have corrected the query contract, response disclosure,
permission separation, officer-route role semantics, privileged-read auditing,
protected audit persistence, cross-domain recovery, integrity verification, and
audit lifecycle controls. Officer audit visibility now uses event-time scope,
and dashboards share versioned lifecycle-aware definitions. Application-code
remediation and repository-side release tooling are complete for the reviewed
scope. Isolated real-Mongo, Redis, key-rotation, backup/restore, metrics-scrape,
and incident-recovery evidence has now been recorded. The owner has accepted a
single-account MongoDB administration/runtime exception and deferred HTTPS proxy
validation until deployment. Prometheus and Grafana are proven locally and may
remain local for the current operating plan. The final production-mode release
check still requires the selected deployment topology; these are recorded
operational decisions rather than unimplemented Analytics behavior.

Current local baseline:

- Local Analytics, restore-safety, and deployment-asset suites: **88 passed and 7
  opt-in integration tests skipped** on 2026-08-13.
- Full project suite after the isolated validation work: **1,122 passed and 28
  opt-in integration tests skipped**, with one third-party
  deprecation warning on 2026-08-13.
- Characterization cases call views directly for precision, while Stage 6
  request tests exercise real URL routing, JWT validation, live accounts,
  persisted sessions, named permissions, role isolation, and revocation.
- The earlier `datetime.strptime(datetime_value, ...)` failure is fixed and
  covered by valid, malformed, and inverted date-range regressions.
- The opt-in suites now cover real-Mongo query plans/lifecycle plus deployment
  MongoDB-role, Redis-sharing, Prometheus-scrape, and proxy/health probes.

## Verified Implemented Foundations

### API surface

All seven routes are registered under `/api/analytics/` and are read-only:

| Route | Current boundary | Implementation status |
| --- | --- | --- |
| `GET admin/` | Admin with `view_analytics`; activity additionally requires `view_logs` | Implemented and locally verified |
| `GET audit-logs/` | Admin with `view_logs` | Implemented and locally verified |
| `GET audit-logs/users/` | Admin with `view_logs` | Implemented and locally verified |
| `GET audit-logs/<log_id>/` | Admin with `view_logs` | Implemented with minimized response and access audit |
| `GET officer/` | Loan officer only | Implemented and locally verified |
| `GET officer/audit-logs/` | Loan officer only | Implemented with minimized, event-time-scoped response |
| `GET customer/` | Customer owner | Implemented and locally verified |

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
validator. Target-volume query-plan evidence is a deployment release condition.

## Implemented Controls and Remaining Release Conditions

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

The real key, backup/restore, retention, legal-hold, inventory, and backfill
procedures have isolated development evidence. The owner has accepted continued
use of the current `atlasAdmin` database identity instead of a separate
least-privilege runtime identity. This is an explicit security exception: a
leaked backend database URI carries `dropDatabase` and all-resource impact.

### 4. Legacy event normalization and registry governance

**Status: Implemented and applied to development data; production inventory/apply approval remain**

New writes use schema version 2, the action registry, per-action detail
contracts, category, retention metadata, encryption, and integrity protection.
The dry-run-first `backfill_audit_events` command inventories and prepares
eligible legacy events without rewriting their semantics. It refuses records
with invalid existing signatures or unregistered actions for manual review.

Before deployment, run and review the dry run against the target copy, resolve
unknown historical actions, take an approved backup, and only then authorize
`--apply`. Generic historical `admin_action` delete matching remains read-only
compatibility; new producers should use specific registered actions.

### 5. Officer audit scope and admin semantics

**Status: Complete at code and automated-test level**

Stage 4 adopts `event-time-assignment-v1`. Each new Loan audit event snapshots
the assigned officer as a blind HMAC index. Officer audit queries match the
officer's own events or that event-time index and no longer load every currently
assigned loan into an unbounded `$in` list. Reassignment therefore does not
transfer old customer/system event visibility to the new officer. Assignment
events explicitly scope to the assignee even when an administrator is the
actor. Legacy events without an event-time index remain visible only when the
officer was the actor; they are not broadened using current assignment.

The officer response remains minimized and administrators continue to use the
named-permission administrator routes. The compound officer-scope/time/ID index
is bootstrapped. Scope lookup and integrity verification consider configured
previous keys so controlled key rotation does not hide history. The Stage 6
test-cluster harness proved indexed execution over 5,000 events.

### 6. Dashboard metric contract

**Status: Complete at code and automated-test level**

All three dashboards now return `metric_definition_version` and an UTC `as_of`
timestamp. Version `2026-08-12-v1` defines approved outcomes as `approved`,
`disbursed`, `completed`, or `written_off`; disbursed outcomes include
`disbursed`, `completed`, or `written_off`; reviewed is approved outcomes plus
`rejected`; and pending is `submitted` plus `under_review`. Officer, customer,
administrator, and product metrics use those same definitions and product
approval rate uses reviewed decisions as its denominator.

Loan/customer/officer/product ownership queries accept string and legacy
`ObjectId` representations. Document counts use canonical status and include
only current, storage-available metadata, excluding deletion-state and
superseded records. A valid ID is ready only when its current available record
is `approved`. Customer breakdowns now expose the remaining lifecycle states.
Fixture tests reconcile these definitions across dashboards and cover mixed IDs,
reassignment, deleted/superseded documents, and pending-versus-approved IDs.

`as_of` describes when evaluation began; the independent MongoDB counts are not
a transactional snapshot. The approved policy accepts short-lived differences
during concurrent writes: once the writes settle, the next successful dashboard
refresh must converge to the source collections. Exact point-in-time snapshots
are not a release requirement for this version.

### 7. Query design and bounded execution

**Status: Complete with isolated real-Mongo query-plan evidence**

Stage 5 applies `maxTimeMS` to Analytics counts, cursors, and aggregations;
bounds page-number offsets and active-product cardinality; uses deterministic
time/ID ordering; and changes audit search to escaped prefix matching. Actor,
action, resource, officer-scope, lifecycle, and deterministic-sort compound
indexes are bootstrapped. All active product metrics now use one bounded grouped
aggregation instead of per-product count queries. A dedicated authenticated
Analytics throttle defaults to 300 requests per hour and uses the shared Django
cache configuration.

The compatibility page contract remains available inside the bounded offset
window; deeper requests fail with HTTP 400 and require narrower filters. No
Analytics response caching was introduced because the privacy, invalidation,
and staleness contract does not yet justify it. Stage 6 must record real-Mongo
`explain()` and load evidence before the indexes/performance budget are approved.

### 8. Observability and failure behavior

**Status: Complete at code and automated-test level; target import/routing remains deployment work**

Low-cardinality Prometheus metrics now cover request outcomes/latency/response
size, audit write failures and replay outcomes, recovery backlog/oldest age, and
integrity inventory categories. A five-minute task refreshes sanitized gauges
and operational state; the daily inventory persists its bounded summary.
`/api/health/` reports an identifier-free Analytics readiness component and
degrades when recovery backlog reaches the configured threshold or integrity
findings exist. MongoDB failures/timeouts return a stable sanitized HTTP 503
without exposing hosts, queries, identifiers, or event content.

Deployable Prometheus recording/alert rules and a Grafana dashboard now cover
rates, outcomes, p95 latency/response size, write/replay behavior, recovery
backlog/age, missing metrics, and integrity findings. Production still requires
importing them, calibrating thresholds, configuring alert routes, and proving
that scrapes and on-call notifications fire and resolve. Those are Stage 6
deployment gates, not missing application behavior.

### 9. Automated evidence and release environment

**Status: Isolated development evidence complete; production-topology evidence pending**

Stage 6 adds full URL-dispatch tests with issued JWTs, persisted active sessions,
live-account resolution, named administrator permissions, role isolation, and
session revocation. These close the earlier request-stack limitation while the
lower-level cases remain useful for precise view behavior.

An explicitly gated real-Mongo harness creates and drops only a uniquely named
temporary database. It covers validator/index installation, a 5,000-event
officer-scope query with `executionStats`, concurrent-write convergence,
idempotent recovery, legal holds, retention, and integrity/encryption inventory.
All three cases passed against the approved test cluster on 2026-08-13, and
their random temporary databases were removed.
Separate double-opt-in deployment probes validate the runtime MongoDB identity
has no user/database-administration privilege, two Redis clients share one
counter, the deployed metrics endpoint exposes every Analytics metric family,
and the HTTPS proxy preserves a sanitized health contract. They are skipped
unless their individual approval flags and target URLs are supplied.

A local rotation rehearsal now proves that an old-key audit event remains
readable/verifiable while the previous key is configured, is re-encrypted and
re-signed by the dry-run-first backfill, and remains readable after the old key
is removed. This proves the procedure in code but not target secret-manager or
rollback operation.

The repository and approved development services still cannot prove HTTPS proxy
behavior, production secret-manager operation, always-on alert delivery, or a
final production-mode readiness result before deployment. The MongoDB
least-privilege control is owner-waived rather than technically proven. Exact
transactional dashboard snapshots are not required under the approved
short-lived-inconsistency policy.

### Owner-approved deployment decisions and exceptions

- **MongoDB identity:** the owner will retain the existing single
  `atlasAdmin@All Resources` database identity for administration and runtime.
  The least-privilege probe correctly fails on `dropDatabase`; this result is
  accepted as a documented risk, not represented as a passing control.
- **HTTPS proxy:** proxy/TLS configuration and its probe are deferred until the
  backend is deployed because local Daphne has no HTTPS termination layer.
- **Prometheus and Grafana:** the local stack is implemented and verified. It
  can monitor a deployed backend only while the local machine is running and
  can securely reach the remote metrics endpoint. A VPN, SSH tunnel, or other
  protected private path is required; the metrics port must not be exposed
  anonymously to the public internet.
- **Always-on monitoring:** deploying Prometheus/Grafana beside the backend or
  using managed monitoring is optional for initial deployment, but required if
  continuous collection, durable history, and alerts while the local computer
  is offline are release requirements.
- **Final gate:** `analytics_release_check` is deferred until the actual backend
  deployment has its production settings, bootstrap, first integrity inventory,
  Redis, and monitoring path configured.

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
- [x] Prove the audit key-rotation/backfill sequence locally, including removal
  of the previous key after re-encryption.
- [x] Prove key rotation, encrypted backup/restore, legacy backfill, and
  controlled command execution against an isolated restored database.
- [x] Record the owner-approved single-`atlasAdmin` runtime exception; the
  resulting all-resource and `dropDatabase` exposure is explicitly accepted.
- [x] Defer the production secret-manager procedure until a deployment target
  exists; the isolated key-rotation procedure is already proven.

### Stage 4 — Scope and metric correctness

**Status: Complete at code and automated-test level**

- [x] Implement bounded `event-time-assignment-v1` officer audit scope.
- [x] Use canonical mixed-ID and lifecycle-aware domain queries.
- [x] Version metric definitions, align status semantics, and add UTC `as_of`.
- [x] Test reassignment, mixed-ID, lifecycle, valid-ID, and cross-dashboard
  reconciliation invariants.
- [x] Prove indexed officer scope and post-write count convergence against the
  approved isolated real MongoDB target; transient in-flight drift is accepted.

### Stage 5 — Scalability and observability

**Status: Complete at code and automated-test level**

- [x] Add compound indexes, deterministic bounded pagination, prefix search,
  product aggregation, MongoDB timeouts, and a dedicated authenticated throttle.
- [x] Add low-cardinality metrics, recovery/integrity gauges, health readiness,
  scheduled snapshots, sanitized logging, and stable dependency-outage errors.
- [x] Document configuration, diagnosis, and incident evidence procedures.
- [x] Provide structurally validated Prometheus recording/alert rules and an
  importable Grafana Analytics operations dashboard.
- [x] Prove real query plans and representative test-cluster load in Stage 6.
- [x] Import and test the dashboard locally with live Analytics metrics; retain
  local-only monitoring for the current plan and defer an always-on alert route.

### Stage 6 — Real-environment release validation

**Status: Partially complete; deployment execution remains**

- [x] Add request-level JWT/session/permission tests through real URL routing.
- [x] Add a double-opt-in isolated real-Mongo load/explain, validator, recovery,
  retention, legal-hold, and integrity harness.
- [x] Add a read-only `analytics_release_check` command for production mode,
  key/decryption/cache configuration, MongoDB connectivity, indexes, validator,
  metrics/monitoring assets, proxy configuration, and Analytics health readiness.
- [x] Add double-opt-in MongoDB-role, Redis-sharing, metrics-scrape, and
  proxy/health deployment probes.
- [x] Add and structurally validate deployable Prometheus alert/recording rules
  and a Grafana dashboard.
- [x] Re-run local focused and full suites and record the evidence above.
- [x] Execute and review the real-Mongo harness against the approved isolated
  test target.
- [x] Validate isolated key rotation, encrypted backup/restore, Redis sharing,
  metric scraping, alert-rule firing/resolution logic, and the Analytics
  incident recovery procedure.
- [x] Record owner-approved deployment exceptions: single administrative
  MongoDB identity, local-only monitoring, and deferred HTTPS/secret-manager/
  always-on alert validation until a production target exists.
- [ ] Run `analytics_release_check` in the target after bootstrap, the first
  integrity inventory, and all deployment integrations are configured.

Development validation evidence recorded on 2026-08-13:

| Check | Result |
| --- | --- |
| Real MongoDB | Three opt-in tests passed; 5,000-event indexed scope, lifecycle/recovery, and concurrent-write convergence were proven. |
| Current MongoDB identity | Probe correctly failed because the single owner-approved identity has `dropDatabase`; the least-privilege control is explicitly waived and must be reconsidered if the risk decision changes. |
| Legacy audit protection | Encrypted backup taken; 39-event dry run and apply completed with zero conflicts/invalid events; final inventory has zero findings. |
| Restore and rotation | Owner-only encrypted backup restored 94 documents with zero failures; isolated key rotation remained valid after previous-key removal; restore target was deleted afterward. |
| Redis/Celery | Shared Redis counter passed; one Celery worker replied; Beat holds the schedule containing all Analytics periodic tasks. |
| Health | Local `/api/health/` returns HTTP 200 with Analytics ready, fresh inventory, zero backlog, and zero findings. |
| Monitoring | Local Prometheus reports the live Daphne Analytics target up and loads all eight rules; Grafana 13.1.3 has the datasource and dashboard provisioned with real request series; rule simulations pass. |
| Proxy | Expected local limitation; HTTPS/proxy proof is deferred until backend deployment. |
| Release command | Expected development failure only for `DEBUG`, strict decryption, Prometheus enablement, and secure-proxy configuration; every database/health/index/validator gate passed. |

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
- Stage 4 changed dashboard counts under metric definition `2026-08-12-v1`:
  approved/disbursed outcomes include downstream terminal states, pending loans
  include submitted plus under-review, unavailable/superseded documents are
  excluded, and valid-ID readiness requires approval. Clients should display
  the returned definition version and be regression-tested against these rules.
- Page-number pagination is retained within a bounded offset window; clients
  receive HTTP 400 for deeper requests and should narrow their filters.

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

Analytics is application-ready and deployment-prepared. Do not classify the
actual production deployment as certified until `analytics_release_check`
passes against that deployed target after bootstrap and the first integrity
inventory. The owner-approved MongoDB least-privilege exception and any
local-only monitoring limitations must remain visible in the release record;
they are accepted risks, not passing technical controls.

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
