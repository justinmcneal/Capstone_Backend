# Profiles Production Readiness Review

Last updated: 2026-08-07

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

The Profiles module has functional foundations but is **not production-ready**.
Personal, business, and alternative-data CRUD; customer-only access control;
profile summaries; notification preferences; officer directory/detail views;
field encryption; audit logging; rate limiting; and asynchronous risk scoring
all exist. The codebase also contains substantially more profile tests than the
previous version of this review recorded.

Production release is blocked by unrestricted loan-officer access to all customer
profiles, a mismatch between accepted API values and the risk-scoring engine,
stale Celery tasks that can overwrite newer profile data, incomplete encryption
of numeric financial fields, and account deletion that leaves profile PII and
financial data behind. Profile completion and `ready_for_loan` also communicate a
stronger readiness guarantee than their current minimal rules provide.

This review was performed as a static code audit. Automated tests and live
MongoDB/index behavior were not executed as part of the 2026-08-07 review.

Current remediation status:

- [ ] Stage 1 — API contract and regression baseline
- [ ] Stage 2 — Officer privacy, authorization scope, and lifecycle retention
- [ ] Stage 3 — Risk-scoring correctness, explainability, and task durability
- [ ] Stage 4 — Encryption, persistence integrity, and concurrency
- [ ] Stage 5 — Validation, completion, and readiness policy
- [ ] Stage 6 — API consistency, audit completeness, and documentation
- [ ] Stage 7 — Optional customer capabilities and operational hardening

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
- Business age is stored canonically as `business_age_months`, and direct model
  construction can convert legacy `years_in_operation` values to months.

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

- A paginated/searchable loan-officer customer directory is implemented at
  `/api/officer/profiles/`.
- A detailed loan-officer customer profile endpoint is implemented at
  `/api/officer/profiles/<customer_id>/`.
- A legacy duplicate detail route remains at
  `/api/profile/officer/<customer_id>/`.
- Detail responses use an explicit allowlist and omit account password/security
  fields and the customer's wallet address.
- Administrator access is currently denied; the implementation is loan-officer
  only despite older documentation claiming officer-or-admin access.

### Validation and sanitization

- Serializer text fields pass through the shared input-sanitization mixin.
- Philippine mobile numbers accept `09` or `+639` form and normalize to `+639`.
- Wallet addresses require `0x` followed by 40 hexadecimal characters.
- Barangay, city, and province fields use a shared location-name validator.
- Business, income, education, employment, housing, credit, payment, and digital
  fields use explicit choice lists where applicable.
- Nonnegative validation exists for business age, income, expenses, employees,
  experience, rent, dependents, loan amounts, and account duration.
- `business_type_other` is required when `business_type=other` is submitted in
  the same request.

### Services and background work

- `profiles/services/summary.py` centralizes profile summary construction.
- `profiles/services/notification_preferences.py` centralizes notification
  preference defaults, allowlisting, and persistence.
- `profiles/services/officer_profile.py` builds an explicitly allowlisted officer
  response rather than serializing the account model wholesale.
- `profiles/services/risk_scoring.py` implements a weighted heuristic across
  financial stability, payment behavior, social capital, housing stability, and
  digital footprint.
- `profiles/tasks.py` exposes a Celery task that calculates and persists
  `risk_score`, `risk_category`, and `score_calculated_at`.
- Alternative-data PUT attempts to enqueue risk-score recalculation.

### Completion, summary, and downstream integration

- Completion is calculated by each profile model rather than duplicated in the
  summary view.
- The summary reports profile-section status, document counts/statuses, overall
  percentage, missing profile sections, and a `ready_for_loan` flag.
- Loan qualification independently checks that all three profile records are
  present and minimally complete and can require product-specific approved
  documents.
- AI-assistant context and officer loan views consume profile and risk data.

### Encryption and auditing foundations

- Customer personal contact/address fields and business address/registration
  fields are declared for field-level encryption.
- Alternative data declares `existing_loan_source`, `household_income`, and
  `existing_loan_amount` as sensitive fields and calls the shared encryption
  helper during serialization.
- Personal, business, and alternative-data PUT operations create audit events.
- Audit details avoid recording the complete submitted profile payload.

### Test foundations

- Dedicated endpoint tests cover personal, business, alternative, summary,
  preferences, officer access, role enforcement, validation, and throttling.
- Dedicated risk-scoring tests exercise individual dimensions and category
  thresholds.
- Model/task tests cover CRUD, index declarations, zero-month business age,
  alternative-data round trips, and synchronous task execution under mongomock.
- Business-age conversion tests cover direct model construction.
- Blockchain/profile tests cover wallet-field serialization and validation.
- At the time of this review, 73 profile-related test functions were present
  across the five identified profile test files, including 28 in
  `tests/test_profiles_api.py`. This is a static inventory, not a passing-test
  claim.

## Production Blockers

### 1. Loan officers can enumerate and read every customer profile

**Status: Blocked for production**

`OfficerCustomerProfilesListView` queries the full customer collection for every
loan officer. `OfficerProfileView` checks only that the actor has the
`loan_officer` role and does not check whether the customer has an application
assigned to that officer or is otherwise within the officer's review scope.

The detail payload includes personal addresses, emergency contacts, registration
information, income and expenses, household income, existing-loan information,
bank/e-wallet indicators, payment history, and risk results. The directory also
exposes names, email addresses, and telephone numbers across the customer base.

`accounts/utils/access_control.py` already provides
`require_customer_scope_for_officer()` and scoped customer-ID discovery for this
purpose, but the profile views do not use them. Throttling does not replace
authorization: at the current 500 requests/hour and maximum page size of 100, the
directory could expose up to 50,000 records per hour to one officer account.

Required work:

- Scope directory results to customers assigned to or legitimately reviewable by
  the requesting officer.
- Apply `require_customer_scope_for_officer()` to profile detail access.
- Return a concealed 404 for out-of-scope customer IDs.
- Audit officer directory searches and detailed profile reads.
- Minimize directory fields and evaluate whether all detailed financial fields
  are necessary before an application is assigned.
- Decide and document whether administrators require profile access; do not
  silently broaden access while fixing officer scope.
- Add cross-officer, assigned, unassigned, admin, deactivated-account, and
  concealed-existence tests.

### 2. API values and risk-scoring inputs are incompatible

**Status: Blocked for production**

`AlternativeDataSerializer` accepts `household_income` as a nonnegative float,
but `_income_score()` and rent-burden scoring expect categorical strings such as
`30000_50000` and `above_100000`. Real API submissions therefore default to the
neutral income score, and rent burden is not calculated as intended.

The serializer accepts loan and utility histories of `sometimes_late` and
`often_late`, while the scorer recognizes only `late`. It also accepts
`company_provided` housing, which the scorer does not explicitly handle.

Current unit tests call the risk service with the scorer's private categorical
income and `late` values instead of passing serializer-valid API data through the
complete update-to-score path. The tests therefore validate an input contract
that customers cannot submit through the API.

Required work:

- Define one canonical type and enum set shared by the serializer, model, scoring
  service, task, tests, testing guide, and clients.
- Decide whether income is an exact numeric amount, an income range, or both, and
  define which value the scorer uses.
- Give every accepted housing/payment value an explicit scoring rule.
- Add serializer-to-service integration tests using realistic API payloads.
- Recalculate existing scores after the corrected scoring contract is deployed.
- Review every downstream consumer before treating the heuristic as a credit
  decision or qualification result.

### 3. Asynchronous risk scoring can overwrite newer customer data

**Status: Blocked for production**

The task loads the full `AlternativeData` record, calculates a score, and calls
`alternative.save()`, which writes every model field with `$set`. Concurrent or
out-of-order tasks can therefore save an older snapshot over newer customer
changes. The general model update pattern has a similar lost-update risk when
multiple requests update the same record.

Required work:

- Persist only score-related fields from the Celery task using an atomic update.
- Add a profile input revision or compare-and-set condition so stale tasks cannot
  publish a result for superseded inputs.
- Record score state (`pending`, `complete`, `failed`, `stale`) and scoring-policy
  version.
- Make task behavior idempotent and define retry policy.
- Add out-of-order task, duplicate task, concurrent update, and retry tests.

### 4. Numeric financial fields are not encrypted by the current helper

**Status: Blocked for production**

`AlternativeData` now declares and passes its sensitive fields to
`encrypt_fields()`, so the previous claim that it performs no encryption is
obsolete. However, `encrypt_value()` encrypts strings and structured
dict/list/tuple values but returns integers and floats unchanged.

Consequently:

- `existing_loan_source` can be encrypted because it is a string.
- `household_income` remains plaintext when stored as a number.
- `existing_loan_amount` remains plaintext when stored as a number.

The existing alternative-data encryption test verifies only model round-trip
values. It does not enable a known encryption key and assert that raw MongoDB
values use encrypted ciphertext markers. The legacy encryption management command
also does not include the `alternative_data` collection and omits newer declared
personal fields such as `mobile_number`.

Required work:

- Extend encryption to supported numeric/Decimal values using a reversible,
  type-preserving representation.
- Add raw-database ciphertext and type-preserving round-trip tests under an
  enabled encryption key.
- Reconcile each model's `encrypted_fields` with the backfill command field map.
- Add a dry-run inventory for plaintext profile records and a reviewed migration
  procedure.
- Decide which encrypted fields require searching or sorting before encryption;
  randomized Fernet ciphertext cannot support ordinary equality/range queries.

### 5. Account deletion leaves profile PII and financial data behind

**Status: Blocked for production**

`AccountLifecycleService.finalize_deletion()` anonymizes the customer account
document but does not delete, anonymize, or apply retention state to
`customer_profiles`, `business_profiles`, or `alternative_data`. Those records
can retain addresses, emergency contacts, business registration details, income,
debt, payment behavior, digital-footprint indicators, and derived risk scores
under the original customer ID after the account reports an anonymized/deleted
state.

Required work:

- Define retention requirements for profile, financial, document, loan, audit,
  and blockchain records.
- Add a coordinated deletion/anonymization service covering all customer-owned
  profile collections.
- Preserve only fields required by an explicit legal/financial retention policy.
- Prevent deleted customers from appearing in the officer directory.
- Add lifecycle tests proving retained records are appropriately anonymized and
  non-retained profile data is removed or irreversibly de-identified.

## Partial Implementations and High-Priority Gaps

### GET endpoints mutate state

**Status: Partial / correctness hardening required**

Personal, business, and alternative GET endpoints call model `get_or_create()`.
The summary service does the same for all three sections. Reading an absent
profile therefore inserts empty MongoDB records and changes timestamps. A GET can
also fail with a duplicate-key error if concurrent first requests both complete
the find step before either insert completes.

Remaining work:

- Return an unsaved empty representation for missing profiles or create profile
  shells during customer registration.
- Replace find-then-insert creation with an atomic upsert if lazy creation remains.
- Keep GET and summary endpoints side-effect-free.
- Add safe-method and concurrent first-access tests.

### Profile updates are full-document, last-write-wins saves

**Status: Partial / concurrency hardening required**

Views load a complete model, change submitted attributes, and save every field.
Notification preferences similarly load and save the full customer document.
Concurrent updates can silently overwrite unrelated changes.

Remaining work:

- Use atomic `$set` updates for only validated fields.
- Add optimistic concurrency with a revision or `updated_at` precondition where
  clients can edit the same profile concurrently.
- Recalculate completion atomically from the resulting authoritative state.
- Add concurrency tests against real MongoDB, not only mongomock.

### Completion and readiness rules are weaker than their names imply

**Status: Partial / product-policy decision required**

Actual completion requirements are:

- Personal: seven fields (`date_of_birth`, `gender`, `civil_status`, address line
  1, barangay, city/municipality, and province).
- Business: only `business_type` and `income_range`.
- Alternative data: only `education_level` and `housing_status`.

`ready_for_loan` is true when those three minimal section rules pass. It does not
require a risk score, any uploaded document, approved documents, a contact number,
business age, exact income, or registration information. The summary does report
document state separately, and product-specific loan qualification later enforces
required documents; however, the name `ready_for_loan` can mislead clients and
users into treating it as actual eligibility.

Remaining work:

- Define and version the formal meaning of profile completion and loan readiness.
- Either strengthen `ready_for_loan` or rename it to a narrower signal such as
  `minimum_profile_sections_complete`.
- Decide whether current risk score, required documents, customer consent, and
  contact verification belong in readiness.
- Return machine-readable missing field codes instead of display strings alone.
- Keep product-specific eligibility separate from generic profile completeness.
- Add boundary tests for every required field and readiness transition.

### Legacy business-age compatibility is not implemented through PUT

**Status: Partial / documented compatibility is false**

The serializer accepts `years_in_operation`, but the update view only sets fields
already present on `BusinessProfile`. The model has no `years_in_operation`
attribute, so the validated legacy field is silently discarded. Conversion works
only when constructing a model directly, which is what existing conversion tests
cover.

Remaining work:

- Convert `years_in_operation` to `business_age_months` inside serializer
  validation and remove the alias before view assignment.
- Define precedence or reject the request when both fields are supplied.
- Add endpoint tests proving persisted conversion.
- Return only canonical months from GET and publish a deprecation schedule.

### Conditional and identity validation is incomplete

**Status: Partial**

Serializers enforce types, lengths, choices, and nonnegative values, but important
cross-field and identity rules are absent. Stale dependent values can remain after
their controlling boolean/status changes.

Remaining work:

- Reject future dates of birth and define plausible minimum/maximum customer age.
- Validate Philippine ZIP codes where applicable.
- Consider checksum-aware Ethereum address normalization if the wallet field
  remains part of the product.
- Require or clear rent when housing changes to or from `rented`.
- Require or clear loan amount/source/history based on `has_existing_loans`.
- Require or clear bank duration based on `has_bank_account`.
- Require or clear e-wallet usage based on `has_ewallet`.
- Require or clear utility history based on `pays_utilities`.
- Require or clear registration type/number based on `is_registered`.
- Validate conditional business fields against existing instance state during
  partial updates, not only the fields in the current request.
- Review the ASCII-only location regex for valid numbered and non-ASCII Philippine
  location names.
- Store monetary values as Decimal128 or integer centavos rather than binary
  floats.

### Notification preference validation and persistence are incomplete

**Status: Partial**

The service enforces a fixed preference-key allowlist, but converts submitted
values with Python `bool()`. A string such as `"false"` therefore becomes `True`
instead of being rejected or parsed as false. Preference updates save the complete
customer document and do not generate an audit event.

Remaining work:

- Introduce a DRF serializer with strict BooleanFields and the fixed key set.
- Atomically `$set` only `notification_preferences`.
- Audit preference changes without storing unrelated customer data.
- Test JSON booleans, invalid strings/numbers/nulls, partial updates, defaults,
  concurrent account updates, and unknown keys.

### Celery broker failure behavior is narrower than documented

**Status: Partial / durability gap**

Alternative-data PUT catches only `RuntimeError` and `ImportError` around
`calculate_risk_score_task.delay()`. Common broker failures may use other
exception types. Because profile persistence occurs before enqueueing, the client
can receive a 500 even though its data was saved, and no score recalculation may
be scheduled.

Remaining work:

- Define whether enqueue failure returns success-with-pending-state, 202, or a
  retryable service error.
- Catch the specific Celery/Kombu broker exceptions expected by the deployment.
- Add an outbox/reconciliation path so a saved profile cannot permanently miss
  scoring.
- Test broker outage, timeout, duplicate enqueue, retry, and recovery behavior.

### Audit coverage is incomplete

**Status: Partial**

Personal, business, and alternative-data PUT operations create basic audit
records. Notification changes, officer searches and reads, score recalculation,
score failures, and automatic profile creation are not audited. IP capture uses
`REMOTE_ADDR`; deployment proxy trust must be configured consistently with the
rest of the application.

Remaining work:

- Audit notification preference changes.
- Audit access to detailed customer financial/profile information.
- Record scoring policy version, input revision, result category, task identity,
  and failure state without storing raw sensitive inputs in logs.
- Add audit success/failure tests and trusted-proxy operational guidance.

### Risk score explainability and governance are incomplete

**Status: Partial / not suitable as a production credit decision**

The service constructs a dimension breakdown but the task discards it and stores
only score/category/timestamp. No scoring-policy version, reason codes,
recalculation status, manual-review state, calibration record, or fairness review
is retained. Several inputs represent sensitive socioeconomic proxies and are
self-reported.

Remaining work:

- Persist a versioned, non-sensitive explanation and reason codes.
- Establish ownership and change approval for weights and thresholds.
- Validate performance and fairness using representative data before using the
  score for approval, pricing, limits, or adverse decisions.
- Provide a manual-review and correction path.
- Record whether the score is informational, prequalification support, or an
  authoritative lending control.

## Test Coverage Gaps

The prior review's statements that model, serializer, service, task, and
encryption tests were entirely absent are no longer accurate. Tests now exist in
all or most of those areas, but important assertions and realistic end-to-end
contracts are missing.

Required additions:

- Officer assignment/scope tests across two officers and multiple customers.
- Officer directory privacy, pagination, enumeration, and sensitive-read audit
  tests.
- Serializer-to-risk-service integration tests using accepted API values.
- Out-of-order and duplicate Celery task tests.
- Broker outage and reconciliation tests.
- Raw MongoDB ciphertext assertions for every declared encrypted field with an
  enabled test key, including numeric fields.
- Real MongoDB unique-index and concurrent upsert tests.
- GET side-effect tests proving reads do not create records.
- Concurrent partial-update/lost-update tests.
- Legacy business-age endpoint conversion and dual-field precedence tests.
- Date-of-birth, ZIP, location edge-case, and cross-field validation tests.
- Strict notification boolean and concurrent-update tests.
- Completion/readiness transition and missing-field-code tests.
- Account deletion/anonymization tests covering all profile collections.
- Score version, explanation, stale status, and recalculation tests.
- Tests proving business and alternative GET responses match the published API
  schema, including completion fields if those remain part of the contract.

## API and Documentation Misalignment

`docs/PROFILES_TESTING_GUIDE.md` and the previous version of this review do not
match current code in several material areas:

- Personal completion uses seven fields, not ten.
- `AlternativeData.to_dict()` now calls encryption helpers, but numeric financial
  fields still remain plaintext.
- `business_age_months` already accepts zero.
- Model, API, task, risk, conversion, and encryption-related tests now exist.
- `years_in_operation` is present in the serializer but is silently discarded by
  the PUT view instead of converted.
- Business GET does not return `years_in_operation`.
- Business and alternative GET responses do not currently include the documented
  completion fields.
- There are seven throttled profile views, not six.
- The canonical officer routes are `/api/officer/profiles/` and
  `/api/officer/profiles/<customer_id>/`; the guide primarily documents the legacy
  `/api/profile/officer/<customer_id>/` route.
- Officer detail access is loan-officer only, not officer-or-admin.
- Officer detail returns a full allowlisted profile, not the customer summary
  structure.
- The officer customer directory is not documented.
- Notification preference boolean-like values are not strictly parsed or
  validated.
- Celery broker failure is not guaranteed to be skipped gracefully.
- The current 500/hour throttle reduces request volume but does not mitigate the
  missing officer resource scope.

The testing guide should be updated only after Stage 1 establishes the intended
canonical contract, so documentation does not preserve accidental behavior.

## Staged Remediation Plan

### Stage 1 — API contract and regression baseline

**Status: Not started**

- [ ] Decide canonical customer and staff routes and legacy-route deprecation.
- [ ] Decide whether admins may read profiles and under which permission.
- [ ] Define canonical types/enums for income, payment history, and housing.
- [ ] Define business-age alias precedence and deprecation behavior.
- [ ] Define completion and `ready_for_loan` semantics.
- [ ] Add regression tests that demonstrate every confirmed defect before fixes.
- [ ] Record current client-impact decisions for customer mobile, officer web, and
  admin web applications.

### Stage 2 — Officer privacy, authorization scope, and lifecycle retention

**Status: Not started / production blocker**

- [ ] Scope officer directory queries to authorized customer IDs.
- [ ] Enforce officer customer scope on detail reads.
- [ ] Conceal out-of-scope customer existence.
- [ ] Minimize staff directory/detail payloads.
- [ ] Audit sensitive staff reads and searches.
- [ ] Exclude deleted/inactive customers from operational directories.
- [ ] Integrate profile collections into account deletion/anonymization and
  retention policy.
- [ ] Add authorization, privacy, and lifecycle tests.

### Stage 3 — Risk-scoring correctness, explainability, and task durability

**Status: Not started / production blocker**

- [ ] Align API/model/scorer types and enums.
- [ ] Add full serializer-to-task integration tests.
- [ ] Make score writes atomic and stale-task-safe.
- [ ] Add idempotency, retries, failure state, and reconciliation.
- [ ] Persist scoring policy version, input revision, breakdown/reason codes, and
  calculation status.
- [ ] Establish governance, calibration, fairness, and manual-review requirements.
- [ ] Backfill/recalculate scores created under invalid input mappings.

### Stage 4 — Encryption, persistence integrity, and concurrency

**Status: Not started / production blocker**

- [ ] Add type-preserving encryption for numeric financial fields.
- [ ] Reconcile model encryption declarations and encryption-backfill field maps.
- [ ] Add raw-ciphertext and round-trip tests with an enabled key.
- [ ] Replace GET `get_or_create()` writes with side-effect-free reads or atomic
  registration-time creation.
- [ ] Replace full-document updates with validated atomic field updates.
- [ ] Add optimistic concurrency where required.
- [ ] Verify indexes, duplicate cleanup, and races against real MongoDB.

### Stage 5 — Validation, completion, and readiness policy

**Status: Not started**

- [ ] Add date-of-birth and identity validation.
- [ ] Add conditional field validation and stale-value clearing.
- [ ] Review Philippine location validation and ZIP rules.
- [ ] Replace monetary floats with a precise representation.
- [ ] Implement the approved, versioned completion/readiness definition.
- [ ] Add machine-readable missing-field codes and transition tests.
- [ ] Keep product-specific eligibility distinct from profile completion.

### Stage 6 — API consistency, audit completeness, and documentation

**Status: Not started**

- [ ] Implement and test legacy business-age conversion or remove the alias.
- [ ] Make GET response fields consistent with the canonical schema.
- [ ] Introduce strict notification preference serialization and atomic updates.
- [ ] Complete mutation, score, and sensitive-read audit coverage.
- [ ] Update `docs/PROFILES_TESTING_GUIDE.md` to the verified contract.
- [ ] Publish client migration notes for changed routes, fields, roles, and
  asynchronous score status.
- [ ] Run focused profile tests, lint/static checks, and real-Mongo integration
  validation.

### Stage 7 — Optional customer capabilities and operational hardening

**Status: Not started / optional after blockers**

- [ ] Add customer data export only with secure authorization, redaction, audit,
  and retention controls.
- [ ] Add profile history/version visibility where it supports review or disputes.
- [ ] Add customer-facing risk explanation and correction/review workflow if the
  score is exposed or used operationally.
- [ ] Add profile photo/avatar support only if required by a validated product
  need and backed by secure media processing.
- [ ] Consider maintained Philippine address reference data rather than increasingly
  complex free-text regular expressions.
- [ ] Add metrics and alerts for scoring backlog/failures, duplicate profiles,
  encryption migration state, and unauthorized profile-access attempts.

## Production Readiness Checklist

### Implemented foundations

- [x] ~~Three PyMongo profile models with CRUD helpers and declared indexes.~~
- [x] ~~Customer personal, business, and alternative-data GET/PUT endpoints.~~
- [x] ~~Customer profile summary endpoint.~~
- [x] ~~Notification preference GET/PUT endpoint with key allowlist.~~
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

### Required before production

- [ ] Officer access is resource-scoped and audited.
- [ ] Deleted-account profile data follows an approved retention/anonymization
  policy.
- [ ] Risk-scoring inputs match serializer-accepted values.
- [ ] Risk task writes are atomic, versioned, idempotent, and stale-safe.
- [ ] Risk policy is explainable, governed, calibrated, and reviewed for fairness.
- [ ] Numeric alternative financial fields are encrypted at rest.
- [ ] Encryption backfill covers every declared profile field.
- [ ] GET endpoints are side-effect-free.
- [ ] Profile creation and updates are concurrency-safe.
- [ ] Completion/readiness semantics are formally defined and accurately named.
- [ ] Cross-field, date, location, and monetary validation is production-safe.
- [ ] Legacy business-age behavior is implemented as documented or removed.
- [ ] Notification preferences use strict booleans and atomic persistence.
- [ ] Audit coverage includes preferences, scoring, and sensitive staff reads.
- [ ] Canonical API responses, roles, and routes match the testing guide.
- [ ] Focused tests pass, and real-Mongo index/concurrency behavior is validated.

## Client Impact

The customer mobile application, loan-officer web application, and potentially the
admin web application will require coordinated changes once the canonical
contract is decided:

- Customer mobile may need canonical `business_age_months`, stricter validation,
  machine-readable missing fields, and asynchronous risk status rather than
  assuming an immediate score.
- Loan-officer web must use `/api/officer/profiles/` routes, handle scoped/404
  results, and display only the approved allowlisted profile fields.
- Admin web requires a product decision: current code denies admins even though
  older documentation promises admin access. If access is required, it must use
  an explicit permission and sensitive-read audit trail.
- All clients must treat generic profile completion separately from product loan
  eligibility and approved-document requirements.

## Notes

- This is a code-level review, not a live penetration test, data audit, fairness
  validation, or deployment verification.
- `init_db.py`, profile backfills, encryption migrations, and account-retention
  operations are state-changing and require explicit approval, backups, dry-run
  review, and staging validation before use.
- The current 500/hour profile throttle is documented as implemented behavior,
  not an endorsement of that value for production.
- Optional avatar/export features should not be prioritized ahead of privacy,
  scoring, encryption, deletion-lifecycle, and concurrency blockers.
