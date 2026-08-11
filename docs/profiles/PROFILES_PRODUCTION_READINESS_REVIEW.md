# Profiles Module Documentation and Status

Last updated: 2026-08-11

## Overview

The `profiles` module owns customer-supplied personal information, MSME/business
information, alternative credit data, profile completion, notification
preferences, informational profile-risk scoring, customer correction requests,
profile export/history, and scoped loan-officer profile access.

The module is implemented with Django REST Framework and direct PyMongo access.
MongoDB stores profile and risk-review records, the shared field-encryption layer
protects declared sensitive values, Redis/Celery supports asynchronous scoring
and reconciliation, and Prometheus metrics expose bounded operational state.

Detailed payloads, response fields, validation examples, and operational test
commands are maintained in
`docs/profiles/PROFILES_TESTING_GUIDE.md`. This document describes the current
technical contract, implementation status, security model, operational behavior,
and conditions that remain before a production deployment.

## Current Status

**Module implementation status: Complete**

**Production deployment status: Ready for production-environment validation**

All known Profiles code-level blockers have been addressed. Customer and
officer APIs, concurrency controls, completion policy, informational risk
scoring, encryption, lifecycle cleanup, audit recovery, export/history, manual
risk review, metrics, and dry-run-first maintenance tooling are implemented and
covered locally. Real-Mongo index and concurrency behavior has also been tested
against isolated temporary databases.

Production approval still requires deployment-target inventories and validation
of the selected MongoDB, Redis/Celery, encryption-key, proxy, logging, metrics,
alerting, backup, and recovery topology.

| Area | Status | Summary |
| --- | --- | --- |
| Personal profiles | Implemented | Customer-owned personal/contact/address data with validation, completion metadata, encryption, and revision control. |
| Business profiles | Implemented | MSME identity, location, age, registration, financial data, canonical month units, and conditional validation. |
| Alternative data | Implemented | Employment, housing, household, credit, banking, e-wallet, utility, and community information. |
| Profile completion | Implemented | Versioned section completion, percentages, stable missing-field codes, and profile-only application readiness. |
| Informational risk scoring | Implemented | Versioned, explainable, asynchronous, stale-safe heuristic with manual-review-only governance. |
| Risk review | Implemented | Customer correction requests and scoped officer resolution with optimistic concurrency. |
| Notification preferences | Implemented | Strict boolean allowlist, default merging, and narrow atomic updates. |
| Officer access | Implemented | Scoped directory/detail and risk-review queue with minimized payloads, concealed denials, and required audits. |
| Export and history | Implemented | Allowlisted in-memory profile export and metadata-only change history. |
| Lifecycle and retention | Implemented | Idempotent deletion during account finalization, durable cleanup status, and legacy dry-run inventory. |
| Field encryption | Implemented | Declared string and numeric fields use versioned, type-preserving encrypted BSON envelopes. |
| Local validation | Passing | Focused profile suites and the repository-wide suite pass; opt-in integrations remain gated. |
| Production environment validation | Pending | Deployment-target inventories and real infrastructure/operations evidence remain. |

## Module Responsibilities

### Profile data domains

Profiles owns four PyMongo collections:

| Collection | Model | Purpose |
| --- | --- | --- |
| `customer_profiles` | `CustomerProfile` | Personal identity details, contact data, addresses, emergency contact, optional wallet, and completion metadata. |
| `business_profiles` | `BusinessProfile` | Business identity, location, operating age, registration, income/expense declarations, employees, and completion metadata. |
| `alternative_data` | `AlternativeData` | Employment, housing, household, credit, financial-access, utility, community, scoring, and completion state. |
| `profile_risk_reviews` | `RiskReviewRequest` | Customer score-review requests, officer workflow state, encrypted descriptions/notes, and review revisions. |

Profiles does not own account credentials, consent records, uploaded documents,
loan decisions, blockchain state, or full account export. Those remain within
their respective domains.

### Persistence and concurrency

- Each primary profile collection has a unique `customer_id` index.
- Customer identifiers stored historically as strings or `ObjectId` values are
  tolerated during lookup and controlled reconciliation.
- GET and summary requests are side-effect-free. A missing profile returns an
  unsaved empty representation with `id: null` and revision zero.
- The first PUT uses an atomic upsert. Later PUT requests update only validated
  submitted fields and increment `profile_revision`.
- Clients may send the last observed `profile_revision`; a stale revision
  returns `409 Conflict` rather than overwriting another edit.
- Legacy full-model saves are revision guarded.
- Completion metadata is finalized only for the newest observed profile
  revision.
- `profile_risk_reviews` uniquely indexes customer plus calculated scoring
  revision, preventing duplicate correction requests for one score.
- Dry-run-first commands inventory legacy duplicates, obsolete completion
  metadata, obsolete scores, retained deleted-customer data, and legacy business
  ages before any approved write.

### Customer profile self-service

Authenticated customers can read and update personal, business, and alternative
data; retrieve the combined summary; manage notification preferences; download
a profile-only export; view metadata-only history; and request review of a
current completed risk score.

Customer endpoints enforce the customer role through the shared access-control
layer. Customers cannot read or update another customer's profile by supplying
an identifier; ownership comes from the authenticated account.

### Validation and normalization

- Text inputs use the shared sanitization mixin.
- Customer and emergency-contact mobile numbers accept Philippine `09` or
  `+639` forms and normalize to `+639XXXXXXXXX`.
- Birth dates enforce an inclusive age range of 18 through 100 and serialize as
  `YYYY-MM-DD` even when legacy BSON stores a datetime.
- Philippine ZIP codes require four digits.
- Location fields support Unicode letters, numbers after the first character,
  spaces, apostrophes, periods, and hyphens.
- Wallet addresses require `0x` plus 40 hexadecimal characters.
- Choice-backed identity, business, employment, housing, payment, credit, and
  digital-access fields reject unknown values.
- Monetary inputs are finite, nonnegative, and limited to two decimal places.
  Unencrypted values use MongoDB `Decimal128`; encrypted values restore the
  original decimal/numeric type after decryption.
- Partial updates merge with the existing record before conditional validation.
  Business registration and alternative rent/loan/bank/e-wallet/utility
  dependent fields are required or cleared according to their controlling
  answer.
- `business_age_months` is canonical. `years_in_operation` remains a deprecated
  input-only alias and must convert to exact whole months; conflicting dual
  values are rejected.

### Completion and profile-only readiness

Completion policy version `2026-08-09-v1` applies to all three sections. Each
section returns:

- `profile_completed`;
- `completion_percentage`;
- `profile_completion_policy_version`;
- stable `profile_missing_fields` codes; and
- `profile_revision`.

Personal completion covers birth date, gender, civil status, nationality,
mobile number, and core address fields. Business completion covers business
identity/location, operating age, registration state, declared income/expenses,
income range, and employees, plus conditional fields for `other` businesses and
registered businesses. Alternative completion covers employment, housing,
household, credit, banking, e-wallet, utility, and cooperative answers, plus the
applicable dependent fields.

False booleans and numeric zero are valid answered values. Completion is not
loan approval. `profile_ready_for_application` means only that all three profile
sections satisfy this versioned policy. It does not prove document approval,
identity, consent, affordability, product eligibility, or risk acceptance.
`ready_for_loan` remains a deprecated compatibility alias.

### Informational risk scoring

Alternative-data updates advance `risk_input_revision`, clear the superseded
result, mark scoring pending, and enqueue the exact revision. The Celery task
may publish only if that revision is still current. Duplicate completed work is
idempotent; stale work cannot overwrite newer customer data; failures persist a
safe error code and are eligible for reconciliation.

Risk policy `2026-08-09-v1` produces a bounded 0–100 informational signal:

| Dimension | Weight | Main signals |
| --- | ---: | --- |
| Financial stability | 25% | Household income and existing-loan payment history. |
| Payment behavior | 20% | Loan and utility payment histories. |
| Social capital | 15% | Cooperative membership and community involvement. |
| Housing stability | 25% | Housing status, address duration, and rent burden. |
| Digital footprint | 15% | Bank/e-wallet access, duration, and use. |

Scores at least 70 map to `low`, scores from 40 through 69.99 map to `medium`,
and lower scores map to `high`. Stored output includes policy/intended-use
metadata, input/calculated revisions, a non-sensitive dimension breakdown,
reason codes, category, timestamps, and manual-review state.

The score is `informational_only` and
`risk_score_manual_review_required` is always true. It must not approve or
reject a loan, set pricing or limits, establish eligibility, prioritize an
adverse workflow, or serve as an adverse-action reason. Any future authoritative
use requires a new policy version, representative calibration/fairness review,
client and legal review, and controlled recalculation.

### Risk explanation and correction

Customers may create one review request for a completed current scoring
revision. Reasons are allowlisted and an optional customer description is
encrypted. Loan officers list only requests belonging to customers inside their
existing application/document scope.

Review transitions use `review_revision`. Terminal `resolved` or `rejected`
states require an encrypted resolution note and cannot be changed afterward.
Stale transitions return `409`; inaccessible requests return concealed `404`.
This is a human explanation/correction workflow, not a second automated lending
decision.

### Officer directory and sensitive reads

Loan officers use `/api/officer/profiles/` and
`/api/officer/profiles/<customer_id>/`. Scope includes assigned customers and
eligible unassigned application/document review work. Customers assigned to a
different officer are excluded.

Inactive, suspended, deactivated, pending-deletion, and deleted customers are
hidden. Directory rows contain only customer ID, name, and email; phone search
and output are intentionally unsupported because phone values are randomized
ciphertext. Detail responses are explicitly allowlisted and omit credentials,
account-security state, wallet address, and emergency-contact data.

Directory access, successful sensitive detail reads, review-queue reads, and
denied out-of-scope reads are audited. Required sensitive-read audits fail
closed with `503` if neither the primary audit nor its required durability
boundary can be confirmed.

Administrators currently have no direct Profiles API access. A future admin
feature requires a separate permissioned endpoint, explicit response allowlist,
documented purpose, and required sensitive-read auditing.

### Notification preferences

Customers can manage three email preferences: loan updates, payment reminders,
and promotions. Values must be actual JSON booleans and unknown keys are
rejected. Stored partial dictionaries merge over documented defaults; PUT uses
narrow dot-field updates so unrelated customer or preference changes are not
lost. Changes are audited without recording preference values.

### Export and history

`GET /api/profile/export/` produces an allowlisted profile-only JSON object in
memory. It stores no export file and excludes credentials, account-security
state, documents, loans, AI history, and internal task identifiers. Risk reviews
are bounded to 100 entries with total/truncation metadata. The required export
audit fails closed with `503` before data is returned.

`GET /api/profile/history/` exposes paginated metadata such as section,
revision, changed field names, action, status, and timestamp. It intentionally
omits historical values, IP addresses, and security data and is not represented
as a cryptographic or statutory snapshot.

### Account deletion and retention

Final account deletion removes customer, business, alternative-data, and
risk-review documents, plus unresolved Profiles audit-recovery payloads for the
customer. Cleanup supports string/ObjectId legacy identifiers and is idempotent.
The Accounts lifecycle stores durable cleanup status, attempts, timestamps,
counts, and safe error type so interrupted work can be retried.

Legacy records belonging to already-deleted customers are inventoried by
`cleanup_deleted_customer_profiles`. The command is read-only unless an
explicitly approved `--apply` run follows retention review, backup, and staging
validation.

### Audit durability

Profile creation/updates, notification changes, scoring outcomes, customer
review activity, exports, history, officer reads, and denied sensitive access
produce allowlisted audit events. Audit payloads exclude raw profile values,
preference values, encrypted fields, and sensitive request bodies.

Customer mutations that are already durable are not reported as failed merely
because a best-effort audit write subsequently fails. Allowlisted replay data is
queued and reconciled every minute; resolved queue entries discard the replay
payload. Required sensitive reads and exports remain fail closed.

### Field encryption

Declared personal contact/address, business address/registration/financial,
alternative rent/income/loan, and risk-review text fields use the shared
versioned encryption envelope when `FIELD_ENCRYPTION_KEY` is configured.

The envelope preserves string and numeric BSON semantics on read. Backfill,
rotation, and verification tooling derives field coverage from model
declarations. Production strict-decryption behavior and previous-key support are
owned by the shared encryption lifecycle. Randomized ciphertext is never used
for plaintext equality/range search; a future search requirement needs a
separate reviewed indexing design.

## API Status

All paths below are relative to the API host.

### Customer endpoints

| Method and route | Status | Purpose |
| --- | --- | --- |
| `GET /api/profile/` | Implemented | Read the authenticated customer's personal profile or an unsaved empty representation. |
| `PUT /api/profile/` | Implemented | Atomically create/update validated personal fields with optional revision precondition. |
| `GET /api/profile/business/` | Implemented | Read business/MSME profile and completion state. |
| `PUT /api/profile/business/` | Implemented | Atomically create/update business fields and canonical age. |
| `GET /api/profile/alternative-data/` | Implemented | Read alternative data, completion, and scoring state. |
| `PUT /api/profile/alternative-data/` | Implemented | Update alternative data and request scoring for the new input revision. |
| `GET /api/profile/summary/` | Implemented | Return section completion, risk state, separate document summary, and overall profile-only readiness. |
| `GET /api/profile/notifications/` | Implemented | Return complete notification defaults merged with stored values. |
| `PUT /api/profile/notifications/` | Implemented | Atomically update allowlisted boolean preferences. |
| `GET /api/profile/export/` | Implemented | Generate an audited, allowlisted, in-memory profile-only export. |
| `GET /api/profile/history/` | Implemented | Return bounded metadata-only profile history. |
| `GET /api/profile/risk-reviews/` | Implemented | List the customer's score-review requests. |
| `POST /api/profile/risk-reviews/` | Implemented | Create one correction request for the current completed score revision. |

### Loan-officer endpoints

| Method and route | Status | Purpose |
| --- | --- | --- |
| `GET /api/officer/profiles/` | Implemented | Paginated/searchable directory restricted to authorized customer scope. |
| `GET /api/officer/profiles/<customer_id>/` | Implemented | Audited allowlisted profile detail for an in-scope customer. |
| `GET /api/officer/profile-risk-reviews/` | Implemented | List review requests within officer customer scope. |
| `PUT /api/officer/profile-risk-reviews/<review_id>/` | Implemented | Revision-guarded review transition and resolution. |
| `GET /api/profile/officer/<customer_id>/` | Deprecated alias | Temporary scoped alias of the canonical officer detail route. |

### Unsupported access

- Admin and super-admin roles have no direct Profiles endpoint.
- Profiles does not provide arbitrary customer lookup, plaintext phone search,
  avatar upload, address-reference lookup, or automated lending decisions.

## Security and Privacy Features

- Custom JWT authentication resolves the live account and role.
- Customer endpoints derive ownership from the authenticated customer.
- Officer access reuses application/document customer scope and conceals denied
  resources with `404`.
- Sensitive response fields use explicit allowlists.
- Required sensitive-read/export audits fail closed.
- Mutation/audit payloads exclude submitted profile values and PII.
- Declared sensitive strings and numeric financial data are encrypted at rest.
- Optimistic concurrency prevents silent lost updates.
- Side-effect-free reads prevent unwanted empty records.
- Strict serializers reject malformed identifiers, invalid enums, unsafe text,
  non-finite/excess-precision money, and inconsistent conditional answers.
- Profile risk is informational and manually reviewable, never authoritative.
- Account finalization deletes Profiles-owned customer data idempotently.
- All Profiles views use `ProfileRateThrottle`, currently 500 requests per hour
  per authenticated user. Deployment owners must tune/validate the rate against
  real traffic and shared Redis behavior.
- Trusted proxy handling comes from the shared Accounts security utilities;
  forwarded client IPs are trusted only at configured proxy depth.

## Background and Scheduled Work

| Task | Schedule/trigger | Responsibility |
| --- | --- | --- |
| `profiles.calculate_risk_score` | After accepted alternative-data update | Calculate and conditionally publish one exact scoring revision. |
| `profiles.reconcile_risk_scores` | Every minute | Recover failed or abandoned pending calculations. |
| `profiles.reconcile_audit_failures` | Every minute | Replay allowlisted Profiles audit failures and remove resolved payloads. |
| `profiles.collect_operational_metrics` | Every 15 minutes | Publish duplicate, encryption, audit, scoring, and review backlog gauges. |

Broker enqueue failure does not discard an accepted profile update. It records
recoverable scoring state for the reconciler. Celery Beat and workers are
therefore required production dependencies when risk scoring is enabled.

## Metrics and Operational Signals

| Metric | Meaning |
| --- | --- |
| `profiles_audit_write_failures_total{action}` | Initial Profiles audit-write failures. |
| `profiles_operations_total{operation,outcome}` | Export, history, review, reconciliation, and denied-access outcomes. |
| `profiles_risk_score_events_total{outcome}` | Completed, failed, stale, and enqueue-failed scoring events. |
| `profiles_risk_score_backlog{status}` | Failed or abandoned-pending score work. |
| `profiles_duplicate_records{collection}` | Extra records sharing a canonical customer identifier. |
| `profiles_unprotected_sensitive_fields{collection}` | Populated declared fields not using the encrypted envelope. |
| `profiles_audit_failure_backlog` | Audit writes awaiting replay. |
| `profiles_risk_review_backlog{status}` | Pending and in-review correction requests. |

Alert thresholds must be calibrated to real traffic. Any duplicate or
unprotected-sensitive-field gauge above zero requires investigation. Persistent
audit, scoring, or review backlog and elevated denied-access rates require an
operational response.

## Maintenance Commands

The project uses PyMongo rather than Django ORM migrations. These commands are
dry-run/read-only by default unless `--apply` is explicitly supplied:

| Command | Default purpose | `--apply` effect |
| --- | --- | --- |
| `python manage.py reconcile_duplicate_profiles` | Inventory string/ObjectId duplicate profile groups. | Retain the newest canonical record and remove older duplicates. |
| `python manage.py recalculate_profile_completion` | Inventory obsolete completion metadata. | Revision-guarded completion reconciliation. |
| `python manage.py recalculate_profile_risk_scores` | Inventory obsolete policy/revision results. | Clear and enqueue controlled recalculation. |
| `python manage.py cleanup_deleted_customer_profiles` | Count retained data for deleted customers. | Delete Profiles-owned retained records under approved policy. |
| `.venv/bin/python scripts/backfill_business_age_months.py` | Inventory legacy business-age candidates. | Add canonical month values with revision conflict protection. |

`init_db.py`, encryption backfill/rotation, and every `--apply` form are
state-changing. They require explicit authorization, current backup, reviewed
dry-run output, staging validation, a maintenance plan, and post-operation
verification.

## Automated Validation Status

Profiles has focused coverage for:

- customer and officer endpoint contracts;
- customer ownership and officer scope/concealment;
- model persistence, type conversion, and index declarations;
- atomic creation and revision conflicts;
- encryption raw-storage and numeric round trips;
- validation, conditional clearing, and completion transitions;
- risk scoring rules, stale/duplicate task handling, reconciliation, and audits;
- notification concurrency;
- export/history boundaries;
- risk-review uniqueness, officer scope, and revision conflicts;
- account-deletion cleanup and operational metrics; and
- dry-run/apply command behavior under isolated test storage.

The opt-in real-Mongo suite passed atomic profile creation, concurrent profile
revision, and risk-review unique-index tests using randomly named temporary
databases that were removed afterward. The normal suite uses mongomock and does
not contact production services.

On 2026-08-11, the focused Profiles suite collected and passed 164 tests. The
most recent repository-wide run passed 1,058 tests and skipped 21 explicitly
gated integration tests.

## Remaining Gaps and Release Conditions

No known Profiles application-code blocker remains. Production release requires:

- rerunning duplicate, completion, risk-score, retained-deleted-customer,
  business-age, and encryption inventories against the selected deployment
  target immediately before index or reconciliation work;
- reviewing every non-zero inventory result before any `--apply` operation;
- validating MongoDB index/atomic behavior and backup/restore in that topology;
- validating Redis/Celery task delivery, retry, stale-work recovery, and Beat;
- validating encryption-key access, previous-key rotation, and strict reads;
- validating trusted-proxy depth, shared throttles, structured logging,
  Prometheus scraping, dashboards, and alerts; and
- coordinating client migration before removing compatibility aliases.

Development inventory on 2026-08-09 found no duplicate groups, obsolete
completion metadata, obsolete scores, retained deleted-customer profile data,
or legacy business-age candidates. Real-Mongo concurrency/index tests passed.
These results are development evidence and do not replace deployment-target
inventory.

## Client Notes

### Customer mobile

- Use `business_age_months`; `years_in_operation` is input-only and deprecated.
- Use `profile_ready_for_application` for profile-only readiness. Do not treat it
  as loan approval or document readiness.
- Render `profile_missing_fields` and policy version rather than duplicating
  completion rules in the client.
- Preserve/send `profile_revision`; after `409`, reload and reconcile edits.
- Treat scoring as asynchronous and informational. Refresh while pending and
  offer correction review without describing the score as a decision.
- Send notification settings as actual JSON booleans.
- Describe `/export/` as profile-only and `/history/` as metadata-only.

### Loan-officer web

- Use canonical `/api/officer/profiles/` routes.
- Treat out-of-scope customers and review requests as concealed `404`.
- Do not expect phone search/output, wallet fields, security state, or emergency
  contact data.
- Show policy version, safe reason codes, scoring status, and manual-review
  requirement; never use the risk score as an approval or adverse reason.
- Submit the latest `review_revision` when transitioning a correction request.

### Admin web

No direct Profiles integration exists or is required. A future admin feature
must be separately designed and permissioned.

### Compatibility surfaces

| Surface | Current behavior | Client action |
| --- | --- | --- |
| `years_in_operation` | Deprecated input-only conversion to exact months. | Migrate requests to `business_age_months`. |
| `ready_for_loan` | Deprecated alias of profile-only readiness. | Read `profile_ready_for_application`. |
| `/api/profile/officer/<id>/` | Scoped legacy detail alias. | Use `/api/officer/profiles/<id>/`. |

Remove aliases only after deployed-client telemetry or a coordinated release
confirms no supported client still uses them.

## Operational Notes

- Profile exports are generated in memory and not retained server-side.
- History contains metadata, not before/after values.
- Risk scoring and review are correction/triage aids, not automated credit
  decisions.
- Operational inventory tasks report aggregate state and do not repair data.
- Avatar uploads remain deliberately unimplemented because no approved product
  requirement justifies the media validation, moderation, storage, privacy, and
  retention surface.
- A bundled Philippine address reference dataset remains deliberately
  unimplemented pending an authoritative maintained source, stable identifiers,
  update/version policy, and client migration design.

## Review Boundaries

This documentation is based on code inspection, automated tests, development
inventories, and isolated real-Mongo validation. It is not a penetration test,
privacy/legal opinion, fairness validation, live production data audit, or
disaster-recovery certification.

The informational risk implementation provides traceability and explanations;
it does not prove predictive validity, fairness, or legal suitability for an
authoritative lending use. Such a use is outside the approved module boundary.

## Related Documentation

- `docs/profiles/PROFILES_TESTING_GUIDE.md` — endpoint payloads, validation,
  smoke tests, operational commands, and compatibility testing.
- `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` — authentication,
  roles, consent, encryption lifecycle, and account deletion orchestration.
- `docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` — document approval,
  storage, review, and deployment conditions.
- `docs/LOANS_TESTING_GUIDE.md` — loan qualification and downstream profile use.
