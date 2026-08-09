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

The Profiles module has functional foundations but is **not production-ready**.
Personal, business, and alternative-data CRUD; customer-only access control;
profile summaries; notification preferences; officer directory/detail views;
field encryption; audit logging; rate limiting; and asynchronous risk scoring
all exist. The codebase also contains substantially more profile tests than the
previous version of this review recorded.

Stages 2 and 3 close the previously unrestricted loan-officer access,
profile-data retention, risk-input mismatch, and stale-score publication
blockers. Production release remains blocked by incomplete encryption of numeric
financial fields. Profile persistence/concurrency, completion, validation, and
`ready_for_loan` semantics also require the later remediation stages.

The original review was a static code audit. On 2026-08-09, the focused profile
suite was executed after the Stage 3 implementation: all 88 profile tests passed.
Live MongoDB/index and true concurrency behavior remain unverified.

Current remediation status:

- [x] Stage 1 — API contract and regression baseline
- [x] Stage 2 — Officer privacy, authorization scope, and lifecycle retention
- [x] Stage 3 — Risk-scoring correctness, explainability, and task durability
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
- On 2026-08-09, 88 focused tests passed across API, business-age, model/task,
  scoring, Stage 1 characterization, Stage 2 privacy/lifecycle, and Stage 3 risk
  durability modules.
- The post-Stage 3 full suite collected 924 tests: 910 passed and 14 opt-in
  integration tests skipped.

## Production Blockers

### 1. Numeric financial fields are not encrypted by the current helper

**Status: Blocked for production**

`AlternativeData` now declares and passes its sensitive fields to
`encrypt_fields()`, so the previous claim that it performs no encryption is
obsolete. However, `encrypt_value()` encrypts strings and structured
dict/list/tuple values but returns integers and floats unchanged.

Consequently:

- `existing_loan_source` can be encrypted because it is a string.
- `household_income` remains plaintext when stored as a number.
- `existing_loan_amount` remains plaintext when stored as a number.

The shared encryption lifecycle now uses versioned ciphertext, previous-key reads,
strict decryption, rotation, and verification. Its management command derives the
field map from model declarations, so `alternative_data`, `mobile_number`, and
other declared profile fields are no longer omitted. However, the helper still
returns numeric values unchanged; the command reports those values as
`unsupported`, and verification does not make unsupported numeric declarations
encrypted.

Required work:

- Extend encryption to supported numeric/Decimal values using a reversible,
  type-preserving representation.
- Add raw-database ciphertext and type-preserving round-trip tests under an
  enabled encryption key.
- Treat any populated `unsupported` count for a field declared encrypted as a
  failed production-readiness condition.
- Decide which encrypted fields require searching or sorting before encryption;
  randomized Fernet ciphertext cannot support ordinary equality/range queries.

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
- Normalize stored BSON datetimes back to date-only API values; a reloaded birth
  date can currently serialize as `YYYY-MM-DDT00:00:00` instead of `YYYY-MM-DD`.
- Validate `emergency_contact_phone`, not only the customer's mobile number.
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
- Reject non-finite monetary values. DRF currently accepts `NaN` and positive
  infinity for fields such as `household_income`.

### Notification preference validation and persistence are incomplete

**Status: Partial**

The service enforces a fixed preference-key allowlist, but converts submitted
values with Python `bool()`. A string such as `"false"` therefore becomes `True`
instead of being rejected or parsed as false. Preference updates save the complete
customer document and do not generate an audit event. Reads also return an
existing stored preference dictionary as-is, so older or partial dictionaries can
omit documented default keys instead of being merged with the defaults.

Remaining work:

- Introduce a DRF serializer with strict BooleanFields and the fixed key set.
- Merge stored preferences over the complete defaults on every read and update.
- Atomically `$set` only `notification_preferences`.
- Audit preference changes without storing unrelated customer data.
- Test JSON booleans, invalid strings/numbers/nulls, partial updates, defaults,
  concurrent account updates, and unknown keys.

The same partial-commit response problem applies to mutation audit failures:
profile data is saved before `AuditLog.log_action()`, but the broad outer exception
handler can then return `500`. A client retry may therefore repeat a mutation that
already succeeded. Mutation persistence, audit requirements, and retry semantics
must be made explicit and tested.

### Audit coverage is incomplete

**Status: Partial**

Personal, business, and alternative-data PUT operations create basic audit
records. Officer directory access, successful sensitive reads, and denied scoped
reads now create required audit records using the shared trusted-proxy IP helper.
Notification changes and automatic profile creation are not audited. Score
success, failure, and stale-task outcomes now record policy/revision/task metadata
without raw scoring inputs. The three customer mutation paths still use
`REMOTE_ADDR`; their proxy handling must be aligned with the shared helper.

Remaining work:

- Audit notification preference changes.
- Add audit success/failure tests and trusted-proxy operational guidance.

## Test Coverage Gaps

The prior review's statements that model, serializer, service, task, and
encryption tests were entirely absent are no longer accurate. Tests now exist in
all or most of those areas, but important assertions and realistic end-to-end
contracts are missing.

Required additions:

- Raw MongoDB ciphertext assertions for every declared encrypted field with an
  enabled test key, including numeric fields.
- Real MongoDB unique-index and concurrent upsert tests.
- GET side-effect tests proving reads do not create records.
- Concurrent partial-update/lost-update tests.
- Legacy business-age endpoint conversion and dual-field precedence tests.
- Date-of-birth range and date-only response-shape tests.
- Emergency-contact phone, ZIP, location edge-case, and cross-field validation
  tests.
- Non-finite and precision-boundary monetary-value tests.
- Strict notification boolean and concurrent-update tests.
- Completion/readiness transition and missing-field-code tests.
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
- Notification preference boolean-like values are not strictly parsed or
  validated.
- Partial stored notification preferences are not merged with documented
  defaults.
- A reloaded MongoDB birth date may be returned as a datetime string rather than
  the guide's date-only value.
- `emergency_contact_phone` has no phone-format validation, and non-finite float
  values can pass monetary serializers.

Stage 2 officer behavior and Stage 3 scoring behavior are now reflected in the
testing guide. The remaining mismatches must be corrected with their owning
implementation stages so the guide does not preserve accidental behavior.

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
durability module. Remaining characterization assertions must be converted as
Stages 4–6 fix each issue.

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

**Status: Not started / production blocker**

- [ ] Add type-preserving encryption for numeric financial fields.
- [x] ~~Derive encryption migration and verification field maps from model
  declarations, including profile collections and newer declared fields.~~
- [ ] Add raw-ciphertext and round-trip tests with an enabled key.
- [ ] Replace GET `get_or_create()` writes with side-effect-free reads or atomic
  registration-time creation.
- [ ] Replace full-document updates with validated atomic field updates.
- [ ] Add optimistic concurrency where required.
- [ ] Verify indexes, duplicate cleanup, and races against real MongoDB.

### Stage 5 — Validation, completion, and readiness policy

**Status: Not started**

- [ ] Add date-of-birth and identity validation.
- [ ] Normalize birth-date responses to date-only values and validate emergency
  contact phone numbers.
- [ ] Add conditional field validation and stale-value clearing.
- [ ] Review Philippine location validation and ZIP rules.
- [ ] Replace monetary floats with a precise representation.
- [ ] Reject NaN and infinite monetary inputs.
- [ ] Implement the approved, versioned completion/readiness definition.
- [ ] Add machine-readable missing-field codes and transition tests.
- [ ] Keep product-specific eligibility distinct from profile completion.

### Stage 6 — API consistency, audit completeness, and documentation

**Status: Not started**

- [ ] Implement and test legacy business-age conversion or remove the alias.
- [ ] Make GET response fields consistent with the canonical schema.
- [ ] Introduce strict notification preference serialization, default merging,
  and atomic updates.
- [ ] Complete mutation, score, and sensitive-read audit coverage.
- [ ] Define atomic/partial-commit behavior when audit recording or task enqueue
  fails after profile persistence.
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

- [x] ~~Officer access is resource-scoped, minimized, concealed, and audited.~~
- [x] ~~Deleted-account profile data is irreversibly removed under the approved
  Profiles retention policy with retry and legacy reconciliation support.~~
- [x] ~~Risk-scoring inputs match serializer-accepted values.~~
- [x] ~~Risk task writes are atomic, versioned, idempotent, stale-safe, retryable,
  and reconciled.~~
- [x] ~~Risk output is explainable, versioned, manually reviewable, and explicitly
  restricted to informational use.~~
- [ ] Numeric alternative financial fields are encrypted at rest.
- [ ] Encryption backfill covers every declared profile field.
- [ ] GET endpoints are side-effect-free.
- [ ] Profile creation and updates are concurrency-safe.
- [ ] Completion/readiness semantics are formally defined and accurately named.
- [ ] Cross-field, date, location, and monetary validation is production-safe.
- [ ] Legacy business-age behavior is implemented as documented or removed.
- [ ] Notification preferences use strict booleans and atomic persistence.
- [ ] Audit coverage includes preferences and automatic profile creation; scoring
  and sensitive staff reads are now covered.
- [ ] Canonical API responses, roles, and routes match the testing guide.
- [x] ~~Focused profile and full local test suites pass.~~
- [ ] Real-Mongo index/concurrency behavior is validated.

## Client Impact

The customer mobile application, loan-officer web application, and potentially the
admin web application require coordinated changes as later stages complete:

- Customer mobile must treat risk scoring as asynchronous, poll or refresh
  `risk_score_status`, display the score as informational with manual review, and
  avoid using it as an approval result. It may also need canonical
  `business_age_months`, stricter validation, and machine-readable missing fields.
- Loan-officer web must use `/api/officer/profiles/` routes, handle scoped/404
  results, stop relying on directory phone search/output or emergency-contact
  detail fields, and display only the approved allowlisted profile fields.
- Admin web requires a product decision: current code denies admins even though
  older documentation promises admin access. If access is required, it must use
  an explicit permission and sensitive-read audit trail.
- All clients must treat generic profile completion separately from product loan
  eligibility and approved-document requirements.

## Notes

- This is a code-level review, not a live penetration test, data audit, fairness
  validation, or deployment verification.
- The scoring contract and governance boundary are documented in
  `docs/PROFILES_RISK_SCORING_POLICY.md`. Representative calibration and fairness
  validation remain mandatory before any future authoritative lending use.
- `init_db.py`, profile backfills, encryption migrations, and account-retention
  operations are state-changing and require explicit approval, backups, dry-run
  review, and staging validation before use.
- The current 500/hour profile throttle is documented as implemented behavior,
  not an endorsement of that value for production.
- Optional avatar/export features should not be prioritized ahead of scoring,
  encryption, validation, and concurrency blockers.
