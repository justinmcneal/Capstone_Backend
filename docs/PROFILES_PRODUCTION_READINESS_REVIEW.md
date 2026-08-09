# Profiles Production Readiness Review

Last updated: 2026-08-09

Scope: `profiles/` plus profile routes, serializers, MongoDB persistence,
field-level encryption, Celery risk scoring, notification preferences, account
lifecycle integration, loan-readiness consumers, officer authorization, audit
logging, and profile-related automated tests.

## Purpose and Status Definitions

This document is the source-of-truth implementation checklist for customer
personal profiles, business profiles, alternative credit data, profile
completion, readiness summaries, notification preferences, risk scoring, and
staff access to profile information. It records verified behavior, production
risks, and remediation order.

- **Complete**: implemented and covered by relevant automated tests.
- **Partial**: useful implementation exists, but important behavior is missing,
  inconsistent, or unsafe.
- **Not implemented**: no production implementation was found.
- **Blocked for production**: implemented behavior has a security, privacy,
  correctness, concurrency, retention, or durability issue that must be fixed
  before release.

Checklist convention:

- `[x]` with ~~strikethrough~~ means implemented and statically verified.
- `[ ]` means not implemented, not deployed, or still requiring validation.
- A **PARTIAL** stage contains both completed and unchecked work.

Passing unit tests alone does not make an item production-ready. The project uses
PyMongo directly, and mongomock does not reproduce every real MongoDB constraint,
atomic-update, index, encryption, concurrency, or data-type behavior.

## Executive Summary

The Profiles module's planned production-readiness implementation is complete at
the code and local-test level, but deployment remains gated on the documented
live-environment validation.
Personal, business, and alternative-data CRUD; customer-only access control;
profile summaries; notification preferences; profile export/history; customer
risk review; officer directory/detail/review views; field encryption; recoverable
audit logging; metrics; rate limiting; and asynchronous risk scoring all exist.
The codebase also contains substantially more profile tests than the previous
version of this review recorded.

Stages 2–7 close the previously unrestricted loan-officer access, profile-data
retention, risk-input mismatch, stale-score publication, plaintext numeric-
financial data, read-side mutation, lost-update, weak-validation, and misleading
readiness, API inconsistency, notification-persistence, and audit-response
blockers. Production release still requires isolated real-Mongo validation and
review of dry-run operational inventories before production writes.

The original review was a static code audit. On 2026-08-09, the focused profile
suite is revalidated after every completed stage. Stage 4 adds opt-in real-Mongo
index and concurrency tests; executing them against an isolated real MongoDB
instance remains an operational validation step.

Current remediation status:

- [x] Stage 1 — API contract and regression baseline
- [x] Stage 2 — Officer privacy, authorization scope, and lifecycle retention
- [x] Stage 3 — Risk-scoring correctness, explainability, and task durability
- [x] Stage 4 — Encryption, persistence integrity, and concurrency
- [x] Stage 5 — Validation, completion, and readiness policy
- [x] Stage 6 — API consistency, audit completeness, and documentation
- [x] Stage 7 — Customer review capabilities and operational hardening

## Verified Implemented Foundations

### Models and persistence

- Three PyMongo-backed document models exist:
  - `CustomerProfile` in `customer_profiles`.
  - `BusinessProfile` in `business_profiles`.
  - `AlternativeData` in `alternative_data`.
- Each model supports save, lookup by customer, and index creation.
- Unique `customer_id` indexes are declared for all three collections.
- Profile index creation is wired into `init_db.py`.
- Lookups tolerate legacy customer IDs stored as either `ObjectId` or string and
  return the most recently updated matching record.
- Business age is stored and returned canonically as `business_age_months`.
  Legacy `years_in_operation` API input converts to exact whole months, matching
  dual fields are accepted, and ambiguous values are rejected.
- The legacy business-age reconciliation script is inventory-only by default,
  requires `--apply`, rejects ambiguous values for manual review, and uses a
  profile-revision guard when applying.
- Missing-profile GET and summary responses use unsaved empty representations and
  do not create MongoDB documents.
- PUT creation uses atomic upsert semantics. Validated updates `$set` only
  submitted fields and increment `profile_revision`.
- Clients may submit the revision returned by GET/PUT for optimistic concurrency;
  stale revisions return `409` instead of overwriting another update.
- Legacy full-model saves are revision-guarded and reject stale snapshots.
- `reconcile_duplicate_profiles` inventories legacy string/ObjectId duplicates
  by default and requires `--apply` to retain the newest canonical record.

### Customer API coverage

- Personal profile GET and PUT are implemented at `/api/profile/`.
- Business profile GET and PUT are implemented at `/api/profile/business/`.
- Alternative credit data GET and PUT are implemented at
  `/api/profile/alternative-data/`.
- Profile summary GET is implemented at `/api/profile/summary/`.
- Notification preference GET and PUT are implemented at
  `/api/profile/notifications/`.
- Customer endpoints use custom JWT authentication and customer-role checks.
- All profile views attach `ProfileRateThrottle`, currently configured at
  500 requests per hour per authenticated user.

### Staff API coverage

- A paginated/searchable and resource-scoped loan-officer customer directory is
  implemented at
  `/api/officer/profiles/`.
- A detailed loan-officer customer profile endpoint is implemented at
  `/api/officer/profiles/<customer_id>/`.
- A legacy duplicate detail route remains at
  `/api/profile/officer/<customer_id>/`.
- Directory queries use the shared loan-application/document-review scope. They
  include assigned customers and the legitimate unassigned review queue while
  excluding customers assigned to another officer.
- Detail reads enforce the same scope and conceal out-of-scope customer existence
  with `404`.
- Inactive, suspended, deactivated, pending-deletion, and deleted customers are
  hidden from both directory and detail access.
- The directory returns only customer ID, name, and email. Phone search and phone
  output were removed because randomized encrypted phone values cannot safely
  support plaintext regex queries.
- Detail responses use an explicit allowlist and omit account password/security
  fields, wallet address, and emergency-contact data.
- Directory access, successful sensitive reads, and denied out-of-scope reads are
  audited. Sensitive data fails closed with `503` when its required audit cannot
  be written.
- Administrator access is currently denied; the implementation is loan-officer
  only despite older documentation claiming officer-or-admin access.

### Officer privacy and profile retention

- Account finalization irreversibly deletes the customer's documents from
  `customer_profiles`, `business_profiles`, and `alternative_data` under the
  approved Profiles retention policy.
- Cleanup supports both string and ObjectId legacy customer identifiers and is
  idempotent.
- Account anonymization records a durable `profile_cleanup_status`. An interrupted
  cleanup remains `pending` and can be retried by the scheduled deletion task or
  administrative finalization endpoint; attempt count, last attempt, and last
  error type provide operational visibility.
- `cleanup_deleted_customer_profiles` inventories legacy retained profile data in
  dry-run mode by default and requires `--apply` for deletion.

### Validation and sanitization

- Serializer text fields pass through the shared input-sanitization mixin.
- Customer and emergency-contact mobile numbers accept `09` or `+639` form and
  normalize to `+639`.
- Birth dates enforce an inclusive 18–100 age range and API responses normalize
  stored BSON datetimes to date-only values.
- ZIP codes require four digits. Location validation supports Unicode letters and
  numbered Philippine barangays while retaining character controls.
- Wallet addresses require `0x` followed by 40 hexadecimal characters.
- Barangay, city, and province fields use a shared location-name validator.
- Business, income, education, employment, housing, credit, payment, and digital
  fields use explicit choice lists where applicable.
- Monetary inputs use two-decimal `Decimal` validation and reject NaN, infinity,
  and excess precision. Unencrypted storage uses `Decimal128` rather than binary
  float.
- Conditional validation uses the existing record during partial updates.
  Business type/registration and alternative rent/loan/bank/e-wallet/utility
  dependents are required or cleared with their controller.

### Completion and application readiness

- Completion policy `2026-08-09-v1` defines core and conditional requirements for
  personal, business, and alternative sections.
- Each section persists and returns policy version, completion percentage,
  completion boolean, and stable machine-readable missing-field codes.
- False boolean answers and numeric zero answers count as answered values.
- `profile_ready_for_application` means all three sections satisfy the current
  policy. It explicitly does not evaluate documents or product eligibility.
- `ready_for_loan` is retained only as a marked deprecated compatibility alias.
- AI context, customer analytics, officer payloads, and loan-qualification gates
  consume the authoritative model completion result rather than old local 7/2/2
  field heuristics.
- `recalculate_profile_completion` inventories obsolete stored metadata by
  default; `--apply` performs revision-guarded reconciliation.

### Services and background work

- `profiles/services/summary.py` centralizes profile summary construction.
- `profiles/services/notification_preferences.py` centralizes notification
  preference defaults, strict boolean validation, merging, and narrow atomic
  persistence.
- `profiles/services/officer_profile.py` builds an explicitly allowlisted officer
  response rather than serializing the account model wholesale.
- `profiles/services/risk_scoring.py` implements a versioned weighted heuristic
  across financial stability, payment behavior, social capital, housing
  stability, and digital footprint using the same numeric and enum contract as
  the API serializer.
- Alternative-data updates atomically increment an input revision, clear any
  superseded result, mark calculation pending, and enqueue that exact revision.
- The Celery task publishes only score fields and only when its expected revision
  is still current. Duplicate tasks are idempotent, stale tasks cannot publish,
  transient failures retry with backoff, and failure state is persisted.
- A one-minute reconciliation task requeues failed or abandoned pending scores,
  so a saved profile is not permanently missed after a broker or worker outage.
- Stored scoring output includes status, policy version, intended use, manual-
  review requirement, calculated revision, non-sensitive dimension breakdown,
  and reason codes. Success, failure, and stale task outcomes are audited.
- `recalculate_profile_risk_scores` inventories obsolete scores in dry-run mode
  by default and requires `--apply` to clear and enqueue recalculation.
- The current score is explicitly informational only. It is not an approval,
  pricing, limit, eligibility, or adverse-action control.
- Failed Profiles audit writes are queued with safe replay payloads and retried by
  a one-minute reconciler; resolved entries discard the payload.
- A 15-minute read-only inventory publishes duplicate, declared-encryption,
  audit-backlog, risk-backlog, and review-backlog gauges.

### Customer transparency and correction

- Customers can generate an allowlisted profile-only JSON export. It is created
  in memory, retained by neither filesystem nor object storage, and fails closed
  if its required primary audit record cannot be written. The failed write is
  queued separately for reconciliation.
- Customers can view metadata-only history containing sections, revisions,
  changed field names, and timestamps without historical values or IP addresses.
- A completed scoring revision can receive one customer review request. Scoped
  loan officers can list and resolve requests with optimistic concurrency,
  concealed out-of-scope behavior, terminal resolution notes, and audit events.
- Customer review descriptions and officer resolution notes are encrypted at
  rest and included in shared encryption lifecycle tooling.
- Risk-review records follow the profile account-deletion policy.

### Completion, summary, and downstream integration

- Completion is calculated by each profile model rather than duplicated in the
  summary view.
- The summary reports versioned section completion, stable missing-field codes,
  document counts/statuses, and an overall profile percentage.
- `profile_ready_for_application` is the canonical profile-only readiness signal;
  `ready_for_loan` is a marked deprecated alias and product eligibility remains
  explicitly unevaluated by the Profiles module.
- Loan qualification consumes authoritative section completion and separately
  evaluates product-specific income, age, amount, and approved-document rules.
- AI-assistant context, customer analytics, and officer loan views consume the
  same authoritative completion and risk data.

### Encryption and auditing foundations

- Customer contact/address fields, business address/registration/financial
  fields, and alternative rent/income/loan fields are declared for field-level
  encryption.
- The versioned BSON envelope encrypts integers, floats, Python `Decimal`, and
  MongoDB `Decimal128` while restoring the original numeric type on read.
- Encryption backfill, rotation, and verification derive their field map from
  model declarations. Populated declared numeric fields are supported rather
  than reported as `unsupported`.
- Personal, business, and alternative-data PUT operations create audit events.
- First mutations record profile creation; later changes record profile updates;
  notification changes are separately audited.
- Customer mutation audits use the shared trusted-proxy IP policy. Audit details
  avoid recording profile payloads or preference values.
- A profile mutation that is already durable remains a successful API operation
  if the best-effort audit write subsequently fails. The failure is logged for
  operations rather than returning a misleading `500` that invites duplicate
  mutation retries.

### Test foundations

- Dedicated endpoint tests cover personal, business, alternative, summary,
  preferences, officer access, role enforcement, validation, and throttling.
- Dedicated risk-scoring tests exercise individual dimensions and category
  thresholds.
- Model/task tests cover CRUD, index declarations, zero-month business age,
  alternative-data round trips, and synchronous task execution under mongomock.
- Business-age conversion tests cover direct model construction.
- Blockchain/profile tests cover wallet-field serialization and validation.
- On 2026-08-09, 164 focused tests passed across API, business-age, model/task,
  scoring, Stage 1 characterization, Stage 2 privacy/lifecycle, Stage 3 risk
  durability, Stage 4 persistence/encryption, Stage 5 validation/readiness, and
  Stage 6 API/audit, and Stage 7 customer-operations modules.
- The post-Stage 7 full suite collected 1,003 tests: 986 passed and 17 opt-in
  integration tests skipped, including three real-Mongo profile tests.

## Resolved Production Blockers

- Numeric profile financial fields now use type-preserving encrypted BSON
  envelopes and have raw-database ciphertext/backfill verification tests.
- Profile GET and summary paths are side-effect-free; lazy creation is restricted
  to mutation paths and uses an atomic upsert.
- Validated profile writes are narrow atomic updates. `profile_revision` provides
  optional optimistic concurrency, and stale full saves fail instead of silently
  replacing newer state.

Randomized Fernet ciphertext cannot support ordinary equality or range queries.
The newly encrypted financial fields are not used for MongoDB search or sorting;
any future query requirement needs a separate reviewed indexing design.

## Remaining Operational Validation

No known code-level Stage 1–6 blocker remains. Before production deployment:

- Execute the opt-in unique-index, concurrent-upsert, and optimistic-concurrency
  tests against an isolated real MongoDB instance.
- Review duplicate, completion, risk-score, retained-profile, encryption, and
  business-age inventories in dry-run mode before authorizing any production
  reconciliation or index operation.
- Validate configured MongoDB transactions/index behavior, Redis/Celery delivery,
  encryption keys, trusted-proxy depth, throttles, logging, and monitoring in the
  deployment environment.

## API and Documentation Alignment

`docs/PROFILES_TESTING_GUIDE.md`, `docs/PROFILES_COMPLETION_POLICY.md`,
`docs/PROFILES_RISK_SCORING_POLICY.md`, and
`docs/PROFILES_CLIENT_MIGRATION.md` now describe the verified Stage 6 contract.
Canonical responses, compatibility aliases, role boundaries, strict notification
booleans, asynchronous scoring state, audit failure semantics, and client changes
are explicitly documented.

## Staged Remediation Plan

### Stage 1 — API contract and regression baseline

**Status: Complete / contract decisions and defect baseline recorded**

- [x] ~~Decide canonical customer and staff routes and legacy-route deprecation.~~
- [x] ~~Decide whether admins may read profiles and under which permission.~~
- [x] ~~Define canonical types/enums for income, payment history, and housing.~~
- [x] ~~Define business-age alias precedence and deprecation behavior.~~
- [x] ~~Define completion and `ready_for_loan` semantics.~~
- [x] ~~Add regression/characterization tests for every confirmed production-
  blocker category before fixes.~~
- [x] ~~Record current client-impact decisions for customer mobile, officer web,
  and admin web applications.~~

Stage 1 contract decisions:

- Customer self-service remains canonical under `/api/profile/`. Staff directory
  and detail access are canonical under `/api/officer/profiles/` and
  `/api/officer/profiles/<customer_id>/`. The duplicate
  `/api/profile/officer/<customer_id>/` route remains a temporary compatibility
  alias and must be deprecated after the officer web client migrates.
- Administrators do not inherit profile access merely from the `admin` role. The
  current profile API continues to deny them. Any future administrative profile
  access must use a separate endpoint, an explicit permission such as
  `manage_users`, an allowlisted payload, a purpose, and a sensitive-read audit.
- `household_income`, rent, and loan amounts are nonnegative PHP monetary values,
  not income-band enum strings. `income_range` remains a separate optional band.
  Canonical loan history values are `on_time`, `sometimes_late`, `often_late`,
  `defaulted`, and `no_history`; canonical utility history values are `on_time`,
  `sometimes_late`, and `often_late`; canonical housing values are `owned`,
  `rented`, `living_with_family`, and `company_provided`. Scoring must consume
  these exact values rather than undocumented legacy aliases.
- `business_age_months` is the canonical stored and response field. The legacy
  `years_in_operation` input remains temporarily accepted and converts years to
  months. If both are supplied, they must agree after conversion or validation
  must reject the request; the canonical field takes no silent precedence.
- `profiles_complete` means the approved, versioned cross-section profile
  requirements are satisfied. It does not include document approval or product
  eligibility. The misleading `ready_for_loan` field will remain a deprecated
  compatibility alias during client migration and will be replaced by
  `profile_ready_for_application`; product qualification and document readiness
  remain separate signals.
- Customer mobile must migrate to canonical months, exact enums, and the renamed
  readiness signal. Loan-officer web must migrate to the scoped officer routes
  and treat concealed out-of-scope results as `404`. Admin web requires no profile
  change because direct admin access is intentionally not part of this contract.

Stage 1 validation adds nine passing characterization tests for GET-side writes,
scoring type/enum fallback, stale-task overwrites, plaintext numeric financial
fields, the former deletion-retention defect, lost updates, weak readiness,
discarded business-age aliases, and string-to-boolean preference coercion. Stage
2 converted the deletion assertion to the secure target behavior. Stage 3
converted scoring-contract and stale-task assertions and added a dedicated risk-
durability module. Stage 4 converted plaintext-financial, read-side-write, and
lost-update assertions. Stage 5 converted the weak-readiness assertion and added
dedicated validation/readiness coverage. Remaining characterization assertions
were converted to the canonical business-age and strict notification targets in
Stage 6.

### Stage 2 — Officer privacy, authorization scope, and lifecycle retention

**Status: Complete**

- [x] ~~Scope officer directory queries to authorized customer IDs.~~
- [x] ~~Enforce officer customer scope on detail reads.~~
- [x] ~~Conceal out-of-scope customer existence.~~
- [x] ~~Minimize staff directory/detail payloads and remove phone search.~~
- [x] ~~Audit sensitive staff reads, directory access, and denied reads.~~
- [x] ~~Exclude inactive, suspended, deactivated, pending-deletion, and deleted
  customers from operational profile access.~~
- [x] ~~Integrate all profile collections into retryable account finalization and
  define irreversible deletion as the Profiles retention policy.~~
- [x] ~~Add dry-run legacy cleanup and authorization, privacy, audit, lifecycle,
  retry, and reconciliation tests.~~

Stage 2 behavior:

- Assigned customers are visible only to their assigned officer. Submitted or
  under-review customers with no assigned officer remain visible in the shared
  review queue. A customer actively assigned to someone else is excluded.
- Out-of-scope detail requests return the same `404 Resource not found` response
  regardless of whether the customer exists.
- Directory output is limited to ID, name, and email. Detail output no longer
  includes wallet, account-security, or emergency-contact data.
- Required read audits fail closed: no sensitive payload is returned when the
  audit record cannot be stored.
- Final account deletion removes personal, business, and alternative profile
  documents. A durable pending marker and idempotent cleanup make interruptions
  retryable. Existing deleted accounts can be inventoried with
  `cleanup_deleted_customer_profiles` and are changed only with `--apply`.
- Eleven Stage 2 tests cover cross-officer concealment, assigned and unassigned
  scope, inactive/deleted states, payload minimization, removed phone behavior,
  audit success/failure, deletion of all collections, retry, and dry-run legacy
  cleanup.

### Stage 3 — Risk-scoring correctness, explainability, and task durability

**Status: Complete**

- [x] ~~Align API/model/scorer types and enums.~~
- [x] ~~Add full serializer-to-task integration tests.~~
- [x] ~~Make score writes atomic and stale-task-safe.~~
- [x] ~~Add idempotency, retries, failure state, and reconciliation.~~
- [x] ~~Persist scoring policy version, input revision, breakdown/reason codes,
  intended use, manual-review requirement, and calculation status.~~
- [x] ~~Document governance and prohibit approval, pricing, limit, eligibility,
  or adverse-action use without representative calibration and fairness review.~~
- [x] ~~Provide a dry-run-default command to inventory and recalculate scores
  created under obsolete policies or mappings.~~

Stage 3 behavior:

- The serializer, model, and scorer share the exact canonical housing, loan-
  history, utility-history, and e-wallet values. Household income is scored as
  the numeric PHP value accepted by the API.
- Each alternative-data mutation advances `risk_input_revision`. A task may
  publish only if that revision still matches, preventing an older task from
  overwriting a newer result or customer update.
- A duplicate task for an already-completed revision/policy returns the stored
  result without changing its calculation timestamp.
- Enqueue and calculation failures are recorded while the customer update remains
  durable. Retried and abandoned work is recovered by the minute reconciler.
- API, summary, and officer payloads expose calculation status, policy version,
  intended use, manual-review requirement, revisions, breakdown, reason codes,
  and safe error metadata where applicable.
- The current policy is `2026-08-09-v1` and `informational_only`. See
  `docs/PROFILES_RISK_SCORING_POLICY.md` for weights, thresholds, explanation,
  publication, change-control, and future validation requirements.
- Ten Stage 3 tests cover canonical rules, serializer-to-task flow, explanation
  safety, out-of-order and duplicate delivery, broker/scoring failures,
  reconciliation, audit metadata, and dry-run/apply recalculation behavior.

### Stage 4 — Encryption, persistence integrity, and concurrency

**Status: Implementation complete / live MongoDB validation pending**

- [x] ~~Add type-preserving encryption for numeric financial fields.~~
- [x] ~~Derive encryption migration and verification field maps from model
  declarations, including profile collections and newer declared fields.~~
- [x] ~~Add raw-ciphertext and type-preserving round-trip tests with an enabled
  key.~~
- [x] ~~Replace GET `get_or_create()` writes with side-effect-free reads and use
  atomic upsert for mutation-time creation.~~
- [x] ~~Replace API full-document updates with validated atomic field updates.~~
- [x] ~~Add `profile_revision` optimistic concurrency and stale-save rejection.~~
- [x] ~~Add dry-run-default duplicate reconciliation and opt-in real-Mongo index,
  creation-race, and revision-race tests.~~
- [ ] Execute the opt-in tests against an isolated real MongoDB instance and
  review the duplicate-reconciliation dry run before any production index work.

Stage 4 behavior:

- Sensitive numeric values are ciphertext in raw MongoDB while API/model reads
  receive their original numeric type and value.
- Personal, business, alternative-data, and summary GET requests no longer create
  empty records.
- PUT responses return `profile_revision`. A client that sends this value on its
  next PUT receives `409` if another request updated the profile first. Omitting
  it retains backward compatibility while narrow `$set` updates protect unrelated
  fields.
- Profile completion is finalized only for the newest observed revision, so a
  stale completion calculation cannot overwrite newer state.
- The duplicate reconciliation command retains the newest record and canonicalizes
  `customer_id`; it performs no writes unless `--apply` is explicitly supplied.

### Stage 5 — Validation, completion, and readiness policy

**Status: Complete**

- [x] ~~Add date-of-birth and identity validation.~~
- [x] ~~Normalize birth-date responses to date-only values and validate emergency
  contact phone numbers.~~
- [x] ~~Add existing-state conditional validation and stale-value clearing.~~
- [x] ~~Support numbered/Unicode Philippine locations and enforce ZIP rules.~~
- [x] ~~Replace profile monetary floats with two-decimal `Decimal`/`Decimal128`
  representation.~~
- [x] ~~Reject NaN, infinity, and excess monetary precision.~~
- [x] ~~Implement the approved, versioned completion/readiness definition.~~
- [x] ~~Add machine-readable missing-field codes and transition tests.~~
- [x] ~~Keep documents and product-specific eligibility distinct from profile
  completion.~~
- [x] ~~Add dry-run-default completion metadata reconciliation.~~

Stage 5 behavior:

- Customer age is accepted from 18 through 100; customer and emergency phones
  normalize consistently; ZIP, Unicode, numbered-location, and date-only output
  rules are covered by tests.
- Conditional values are evaluated against the authoritative existing instance
  during partial updates. Enabling a controller requires its dependent values;
  disabling it clears obsolete data.
- Monetary serializer values are exact two-decimal `Decimal` objects. With no
  encryption key they persist as `Decimal128`; with a key the existing encrypted
  envelope preserves the decimal value.
- Completion policy `2026-08-09-v1` replaces the legacy 7/2/2 rules. Section and
  summary responses return policy versions and stable missing-field codes.
- `profile_ready_for_application` is the canonical profile-only signal.
  `ready_for_loan` is a deprecated alias, and `product_eligibility_evaluated`
  remains false in the profile summary.
- AI profile context, the customer dashboard, officer payloads, and loan profile
  gates now consume model completion rather than maintaining weaker local rules.
- See `docs/PROFILES_COMPLETION_POLICY.md` for the exact core, conditional,
  response, validation, and reconciliation contract.

### Stage 6 — API consistency, audit completeness, and documentation

**Status: Implementation complete / live MongoDB validation pending**

- [x] ~~Implement and test legacy business-age conversion or remove the alias.~~
- [x] ~~Make GET response fields consistent with the canonical schema.~~
- [x] ~~Introduce strict notification preference serialization, default merging,
  and atomic updates.~~
- [x] ~~Complete mutation, score, and sensitive-read audit coverage.~~
- [x] ~~Define atomic/partial-commit behavior when audit recording or task enqueue
  fails after profile persistence.~~
- [x] ~~Update `docs/PROFILES_TESTING_GUIDE.md` to the verified contract.~~
- [x] ~~Publish client migration notes for changed routes, fields, roles, and
  asynchronous score status.~~
- [x] ~~Run focused profile tests and lint/static checks.~~
- [ ] Execute the opt-in integration tests against an isolated real MongoDB
  instance before production index or reconciliation work.

Stage 6 behavior:

- `years_in_operation` is a deprecated input-only alias. It converts to exact
  whole months, is removed before persistence, and must agree with canonical
  months when both are sent. GET returns canonical months only.
- The legacy age reconciliation script is dry-run by default and revision-guarded
  under `--apply`; ambiguous values are left untouched for manual review.
- Business and alternative-data GET key sets are tested against the documented
  canonical schemas. Alternative PUT now returns the documented completion
  metadata as well as risk and profile revisions.
- Notification settings require actual JSON booleans and known keys. Partial
  stored dictionaries merge with defaults, while partial PUT uses dot-field
  updates so unrelated account and preference changes are preserved.
- Profile creation, profile updates, notification changes, risk outcomes, and
  scoped staff reads/denials have tested audit coverage using the shared client-IP
  helper. Customer mutation audit failure after a durable write is logged but
  does not change the API result to a misleading `500`.
- Client changes and compatibility removal requirements are published in
  `docs/PROFILES_CLIENT_MIGRATION.md`.

### Stage 7 — Optional customer capabilities and operational hardening

**Status: Complete for approved scope / two optional features deferred by design**

- [x] ~~Add customer profile export with secure authorization, allowlisting,
  required audit, and no retained server artifact.~~
- [x] ~~Add metadata-only profile history/version visibility.~~
- [x] ~~Add a customer risk explanation/correction request and scoped officer
  resolution workflow.~~
- [x] ~~Evaluate avatar support and defer it until a validated product requirement
  justifies secure media processing and retention.~~
- [x] ~~Evaluate a maintained Philippine address source and defer it until source
  ownership, versioning, and client migration are defined.~~
- [x] ~~Add Prometheus metrics, audit reconciliation, and documented alert queries
  for scoring, duplicates, encryption state, audit backlog, reviews, and denied
  access.~~

Stage 7 behavior:

- Export scope is `profiles_only`; credentials, account security, documents,
  loans, AI history, and internal scoring task IDs are excluded.
- History is derived from safe audit metadata. Failed mutation audits are queued
  for replay, but the endpoint is not represented as a cryptographic snapshot of
  historical field values.
- Review requests are bound to the current completed risk revision and policy.
  Duplicate requests return `409`; officer profile scope is reused; terminal
  transitions require a note and stale `review_revision` returns `409`.
- `docs/PROFILES_OPERATIONS.md` documents tasks, metrics, starting alert rules,
  export retention, review operations, and deliberate deferrals.

## Production Readiness Checklist

### Implemented foundations

- [x] ~~Three PyMongo profile models with CRUD helpers and declared indexes.~~
- [x] ~~Customer personal, business, and alternative-data GET/PUT endpoints.~~
- [x] ~~Customer profile summary endpoint.~~
- [x] ~~Notification preference GET/PUT endpoint with key allowlist.~~
- [x] ~~Allowlisted ephemeral profile export and metadata-only history endpoints.~~
- [x] ~~Customer risk-review request and scoped officer resolution endpoints.~~
- [x] ~~Customer-role enforcement on customer profile endpoints.~~
- [x] ~~Loan-officer directory and detailed profile endpoints.~~
- [x] ~~Shared profile rate throttle attached to all profile views.~~
- [x] ~~Profile service layer for summary, preferences, staff payloads, and risk
  scoring.~~
- [x] ~~Celery risk-scoring task and asynchronous enqueue attempt.~~
- [x] ~~Basic serializer choice, range, text, mobile, location, and wallet
  validation.~~
- [x] ~~Basic mutation audit events for the three profile sections.~~
- [x] ~~Profile-related API, model, scoring, conversion, task, and wallet tests.~~
- [x] ~~Recoverable audit queue plus profile-specific Prometheus inventories and
  alert guidance.~~

### Required before production

- [x] ~~Officer access is resource-scoped, minimized, concealed, and audited.~~
- [x] ~~Deleted-account profile data is irreversibly removed under the approved
  Profiles retention policy with retry and legacy reconciliation support.~~
- [x] ~~Risk-scoring inputs match serializer-accepted values.~~
- [x] ~~Risk task writes are atomic, versioned, idempotent, stale-safe, retryable,
  and reconciled.~~
- [x] ~~Risk output is explainable, versioned, manually reviewable, and explicitly
  restricted to informational use.~~
- [x] ~~Declared numeric profile financial fields are encrypted at rest with
  type-preserving round trips.~~
- [x] ~~Encryption backfill and verification cover every declared profile field.~~
- [x] ~~GET and summary endpoints are side-effect-free.~~
- [x] ~~Profile creation and API updates are atomic, revisioned, and stale-safe.~~
- [x] ~~Completion/readiness semantics are formally defined and accurately
  named.~~
- [x] ~~Cross-field, date, location, and monetary validation is production-safe.~~
- [x] ~~Legacy business-age behavior is implemented as documented.~~
- [x] ~~Notification preferences use strict booleans and atomic persistence.~~
- [x] ~~Audit coverage includes preferences, profile creation/updates, scoring,
  and sensitive staff reads.~~
- [x] ~~Canonical API responses, roles, and routes match the testing guide.~~
- [x] ~~Focused profile and full local test suites pass.~~
- [ ] Real-Mongo index/concurrency behavior is validated.

## Client Impact

The customer mobile and loan-officer web applications require the coordinated
contract changes below. Admin web has no direct Profiles API integration:

- Customer mobile must treat risk scoring as asynchronous, poll or refresh
  `risk_score_status`, display the score as informational with manual review, and
  avoid using it as an approval result. It must use
  `profile_ready_for_application` as the profile-only signal, retain temporary
  compatibility with the deprecated `ready_for_loan` alias, render validation
  failures by field, and use `profile_missing_fields` for incomplete-section
  guidance. It must send canonical `business_age_months`; the legacy years alias
  is input-only and pending coordinated removal.
  For edit conflict protection it should store the returned `profile_revision`,
  send it on the next PUT, and reload the form after a `409` response.
- Loan-officer web must use `/api/officer/profiles/` routes, handle scoped/404
  results, stop relying on directory phone search/output or emergency-contact
  detail fields, and display only the approved allowlisted profile fields.
- Admin web requires a product decision: current code denies admins even though
  older documentation promises admin access. If access is required, it must use
  an explicit permission and sensitive-read audit trail.
- All clients must treat generic profile completion separately from product loan
  eligibility and approved-document requirements.
- Detailed migration instructions are in
  `docs/PROFILES_CLIENT_MIGRATION.md`.

## Notes

- This is a code-level review, not a live penetration test, data audit, fairness
  validation, or deployment verification.
- The scoring contract and governance boundary are documented in
  `docs/PROFILES_RISK_SCORING_POLICY.md`. Representative calibration and fairness
  validation remain mandatory before any future authoritative lending use.
- The versioned completion contract and stable missing-field codes are documented
  in `docs/PROFILES_COMPLETION_POLICY.md`.
- `init_db.py`, profile backfills, encryption migrations, duplicate reconciliation,
  and account-retention operations are state-changing and require explicit
  approval, backups, dry-run review, and staging validation before use.
- The current 500/hour profile throttle is documented as implemented behavior,
  not an endorsement of that value for production.
- Avatar and bundled address-reference features are deliberately deferred as
  documented in `docs/PROFILES_OPERATIONS.md`; profile export is implemented.
