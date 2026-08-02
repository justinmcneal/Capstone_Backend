# Loans Production Readiness Review

Last updated: 2026-08-02

Scope: `loans/` plus the accounts, profiles, documents, AI qualification,
notifications, analytics, MongoDB, Celery, and blockchain paths used by loans.

## Purpose and Status Definitions

This document is the source-of-truth implementation checklist for the loans
domain. It records verified behavior, production risks, and remediation order.

- **Complete**: implemented and covered by relevant automated tests.
- **Partial**: useful implementation exists, but important behavior is missing or
  unsafe.
- **Not implemented**: no production implementation was found.
- **Blocked for production**: implemented behavior has a correctness, security,
  financial-integrity, or durability problem that must be fixed before release.

Checklist convention:

- `[x]` with ~~strikethrough~~ means implemented and verified.
- `[ ]` means not implemented, not deployed, or still requiring validation.
- A **PARTIAL** stage contains both completed and unchecked work.

Passing unit tests alone does not make an item production-ready. The project uses
PyMongo directly, and mongomock does not reproduce every real MongoDB constraint,
transaction behavior, index, or data-type rule.

## Executive Summary

The loans module is feature-rich but is **not production-ready**. Product
management, application intake, qualification, officer review, assignment,
disbursement, repayment schedules, penalties, notifications, audit calls, and
blockchain services all exist. Role and ownership checks are generally strong.

Current remediation progress:

- [x] ~~Stage 1 — MongoDB persistence safety~~
- [x] ~~Stage 2 — Payment integrity for cash/check/ETH wallet~~ — GCash and bank
  provider verification intentionally deferred
- [x] ~~Stage 3 — Disbursement integrity for cash/check/ETH wallet~~ — GCash and
  bank provider execution intentionally deferred
- [x] ~~Stage 4 — Durable blockchain synchronization (code complete for current
  scope)~~ — production deployment/integration validation remains
- [x] ~~Stage 5 — Runtime/API defects~~
- [ ] Stage 6 — Qualification enforcement
- [ ] Stage 7 — Repayment accounting and lifecycle
- [ ] Stage 8 — Audit, encryption, and compliance
- [ ] Stage 9 — Schedule export hardening
- [ ] Stage 10 — Maintainability and documentation

## Verified Complete

### API and domain coverage

- Loan-product list/detail and administrator product management are implemented.
- Customer prequalification, application creation, draft update, submission,
  resubmission, list, and detail endpoints are implemented.
- Officer assigned-application list/detail, review, notes, missing-document,
  approval/rejection, disbursement, payment, schedule, penalty, and history
  endpoints are implemented.
- Administrator assignment, reassignment, workload, and blockchain reporting are
  implemented.
- Customer schedule, history, feedback, disbursement-method, blockchain, wallet
  payment, and system-wallet endpoints are implemented.
- Central JWT authentication, role checks, active privileged-account checks, and
  officer assignment scoping are implemented.

### Previously completed remediation

- `find_pending_paginated` includes submitted and under-review applications.
- Assigned pagination no longer hides approved or disbursed applications.
- Officer and administrator views were split into focused modules.
- Shared internal-note serialization was extracted to
  `loans/utils/serialization.py`.
- Officer/admin application access was refactored toward model query methods.
- AI qualification has a feature flag and rule-based fallback.
- Daily overdue processing has a Celery task and test coverage.
- Shared schedule/payment blockchain sync logic was extracted into
  `loans/blockchain/sync_common.py`.
- Assignment, qualification, serializer, model, task, repayment, disbursement,
  audit, blockchain, and event-listener test suites exist.
- `.DS_Store` cleanup and ignore rules were completed previously.

### Completed in the 2026-08-01 remediation pass

- `LoanApplication.save()`, `RepaymentSchedule.save()`, and `LoanPayment.save()`
  now remove `_id` from MongoDB `$set` payloads while retaining `_id` in the
  update selector.
- All five model-level save paths were audited. `LoanProduct` and
  `BlockchainTransaction` already excluded `_id` safely.
- Regression tests assert the exact update payload for all five persisted model
  types. This closes the real-Mongo immutable `_id` update defect that mongomock
  lifecycle tests did not expose and protects the already-correct paths.
- Direct `$set` helpers in the loans domain were also checked and do not place
  `_id` in their update documents.
- Focused validation passed: 62 tests covering loan models, repayment and
  disbursement services, and schedule export. Ruff also passes for the expanded
  model regression test file.

## Partial Implementations

### Bulk repayment schedule export

**Status: Partial**

`GET /api/loans/officer/schedules/export/` supports CSV/JSON and customer,
installment-status, and date filters. Thirteen export tests currently pass.

Known gaps:

- Customer filtering uses `find_one`, so only one schedule is exported when a
  customer has multiple loans.
- Unsupported formats fall through to CSV instead of returning `400`.
- Reversed date ranges are not rejected.
- The export loads every schedule and performs per-schedule application, product,
  and customer lookups.
- CSV is assembled in memory instead of streamed or processed asynchronously.
- Customer/product/free-text fields are not protected against spreadsheet formula
  injection.
- Export access is not recorded as a dedicated sensitive-data audit event.
- Empty-result behavior differs between CSV and JSON.
- Invalid legacy IDs can produce an unhandled error.
- The response label `schedules` contains flattened installment rows rather than
  schedule objects.
- Bulk import is not implemented and should remain optional until finance
  operations define a concrete need.

### Status-transition audit logging

**Status: Partial**

Structured audit calls exist, including model-level assignment and resubmission
events. They are not yet comprehensive:

- Assignment can attribute the action to the assigned officer instead of the
  administrator or system that performed it.
- Reassignment lacks complete lifecycle audit coverage.
- Missing-document state changes lack a complete transition entry.
- Some view audit calls hardcode `loan_officer` for administrator actions.
- Audit failures can be swallowed without an operational alert.

### Field encryption

**Status: Partial**

String fields such as product descriptions and payment notes/references use the
field-encryption helper. Declaring list-valued fields such as application
`internal_notes` and schedule `installments` as encrypted does not encrypt their
nested contents because the helper only encrypts strings.

### Automated assignment

**Status: Partial**

Auto-assignment, manual assignment, reassignment, and workload services exist and
are tested. The application lifecycle does not invoke auto-assignment in
production. Officers cannot claim from an unassigned queue because officer list
queries are scoped to already assigned applications.

### Blockchain infrastructure

**Status: Partial; durable paths implemented, deployment validation outstanding**

Production sync entry points now enqueue named Celery tasks instead of starting
daemon threads. Blockchain and wallet tasks are routed to a dedicated queue,
sender nonce allocation is protected by a MongoDB lease, and task attempts use a
stable idempotency identity. The audit listener is polled by Celery Beat, keeps a
persistent next-block cursor, and uses deterministic MongoDB `_id` values for
database-backed event deduplication.

Multi-contract actions still need step-level saga/reconciliation state, and the
new queue, Beat jobs, worker-loss behavior, and indexes must be deployed and
validated against the real Redis/MongoDB/Web3 environment.

## Production Blockers

### 1. Payment integrity

**Status: Complete for the current cash/check/ETH wallet scope; provider methods
deferred**

Implemented in remediation stage 2:

- Customer GCash/bank-transfer claims are stored as `pending_verification` and do
  not mutate the repayment schedule or trigger blockchain payment sync.
- The generic customer endpoint rejects `wallet`; ETH payments must use the
  on-chain verification endpoint.
- Customer and officer endpoints require an 8–128 character idempotency key.
- Idempotency keys are actor-scoped and hashed before storage.
- Unique partial indexes cover idempotency keys, normalized external-reference
  fingerprints, and ETH transaction hashes.
- Verified officer/wallet posting creates a `posting` ledger record first, then
  atomically replaces the schedule installment array using optimistic concurrency.
- The same token is stored atomically with the balance update. A replay after an
  interrupted ledger-status write completes the existing payment without applying
  the balance twice.
- Payment totals include only `posted` records; pending/failed records are excluded.
- Wallet payments require a configurable confirmation depth, reject both under-
  and over-tolerance transfers, apply exactly the remaining PHP balance, and use
  the transaction hash as their idempotency identity.
- The invalid `except error_response.__class__` clause was removed.

Deferred or future-scope work:

- GCash and bank-transfer submissions need an authoritative provider webhook/API
  or a controlled operations-verification workflow before they can become posted.
- Payment search uses plaintext regex against references that may be encrypted.
- There is no reversal, refund, chargeback, or correction workflow.
- ETH conversion still uses the rate fetched during backend verification rather
  than a previously locked quote or historical transaction-time rate.
- The new unique indexes must be deployed through the approved index-initialization
  procedure and verified against existing production data.
- Real-Mongo concurrency and interrupted-write integration tests are still needed;
  mongomock tests validate the domain behavior but not server transaction/index
  semantics.

### 2. Disbursement integrity

**Status: Complete for cash/check/ETH wallet; provider methods deferred**

Implemented in remediation stage 3:

- Disbursement amount must equal the approved amount within one-cent tolerance.
- Applications now track `not_started`, `pending`, `executed`, and `failed`
  disbursement states independently from the loan lifecycle status.
- Disbursement requests require actor-scoped idempotency keys and have a unique
  partial MongoDB index.
- Cash/check disbursement creates or reuses the repayment schedule before marking
  the application `disbursed`/`executed`.
- Schedule failure leaves the application approved and records a failed
  disbursement attempt instead of returning false success.
- Replaying a completed manual disbursement reuses the existing schedule and does
  not repeat financial, email, or audit side effects.
- GCash, bank-transfer, and wallet requests initially return `202`/`pending`; GCash
  and bank remain pending, while the durable wallet worker can confirm ETH,
  generate the schedule, and atomically complete the loan.
- Completion audit and email occur only after a cash/check disbursement reaches
  `executed`.
- The missing `ObjectId` notification lookup import and validation were fixed.

Stage 4 additions for the supported wallet scope:

- The wallet transfer runs as an acknowledged-late Celery task with worker-loss
  rejection, bounded retries, and a per-disbursement MongoDB worker lease.
- Conversion data is persisted before sending, and transaction hash/nonce are
  persisted immediately after broadcast. A retry resumes receipt confirmation
  from the stored hash instead of sending the ETH transfer again.
- A confirmed transfer creates/reuses the schedule before completing the loan.
- Celery Beat re-enqueues pending wallet attempts every five minutes.

Remaining/deferred work:

- Implement provider execution/confirmation for GCash and bank transfer only if
  those methods are brought into scope.
- Add an authorized external-completion callback/operations endpoint only for
  provider-managed methods.
- An assigned officer/admin recovery endpoint can inspect state, safely reconcile
  or retry failed/reverted transfers, and cancel only before transaction
  preparation.
- Deploy and validate the new unique index against production data.
- Add real-Mongo concurrency and interrupted-transition integration tests.

### 3. Blockchain synchronization correctness and durability

**Status: Code complete for current scope; deployment validation outstanding**

Implemented in remediation stage 4:

- Production sync entry points enqueue Celery jobs; daemon-thread dispatch was
  removed.
- Submission, approval, rejection, disbursement, schedule, payment, overdue,
  penalty, and consent paths now have durable task dispatch.
- The undefined `call_view` import and missing `RepaymentSchedule` imports were
  fixed, and schedule/overdue/penalty metadata now uses schedule MongoDB `_id`.
- A MongoDB lease serializes sender nonce selection across processes, with a local
  lock fallback for tests/non-Mongo contexts.
- Blockchain transaction attempts have a stable idempotency key and deployment
  index; timestamps remain BSON datetimes for reporting filters.
- Wallet transfers persist the signed payload, hash, nonce, amount, and recipient
  before broadcast. The signed payload is encrypted at rest and removed after
  confirmation. Every crash point therefore resumes or rebroadcasts the exact
  same transaction identity rather than creating a second transfer.
- Multi-step blockchain tasks persist confirmed saga steps and skip those steps
  on retry.
- Celery Beat runs wallet reconciliation, state-derived reconciliation for missed
  application/approval/disbursement/schedule/payment jobs, and audit-event polling.
- Audit events use `tx_hash:log_index` as MongoDB `_id`; cursor advancement stops
  when event decoding/persistence fails.

Operational validation still required before production release:

- The state-derived reconciliation task supplies eventual recovery when an API
  database commit succeeds but broker publication fails; no provider is required.
- Generic smart-contract mirror calls are resumable at persisted saga boundaries.
  The financially critical ETH transfer additionally has pre-broadcast signed
  transaction persistence and exact rebroadcast protection.
- Deploy and validate the dedicated blockchain worker/queue, Beat scheduler,
  MongoDB indexes, nonce contention, and chain-reorg behavior in staging.

### 4. Qualification requirements are not authoritative

**Status: Blocked for products that rely on minimum income/business age**

- Product `min_monthly_income` and `min_business_months` are not hard-fail rules.
- The fallback scorer can treat violations as score deductions rather than
  disqualifying requirements.
- AI output can return eligible despite those product minimums.
- Existing insufficient-income/business-age tests can pass because another
  required document is missing, so they do not isolate the intended condition.

### 5. Repayment accounting and lifecycle

**Status: Blocked for production hardening**

- Monetary calculations use binary floats rather than integer centavos or
  `Decimal128`.
- The final installment is not reconciled against accumulated rounding.
- `get_next_payment()` ignores partial and overdue installments.
- Penalty waiver after a partial payment can leave an inconsistent status or
  negative remaining amount.
- There is no explicit paid-off/completed state, early payoff, reversal, refund,
  restructuring, or write-off workflow.
- Duplicate repayment blockchain updater names cause later classmethods to
  overwrite earlier instance methods. The previous review's instance-method
  `KeyError` diagnosis is therefore stale; duplicate definitions and incorrect
  call identifiers are the active defects.

## Resolved Runtime and API Defects (Stage 5)

- [x] ~~Recent payments now consumes the `LoanPayment` objects returned by the
  model query directly.~~
- [x] ~~Payment search uses model-supported `skip` pagination on its default path.~~
- [x] ~~Workload customer/officer name enrichment imports and validates
  `ObjectId` correctly instead of silently returning `Unknown`.~~
- [x] ~~The disbursement notification `ObjectId` lookup was verified as already
  fixed during the earlier disbursement remediation.~~
- [x] ~~Product partial updates validate the merged stored/requested min/max
  amount and term values.~~
- [x] ~~Product edit/deactivation protection now includes disbursed active loans.~~
- [x] ~~Draft update/resubmission persists an explicitly supplied
  `preferred_disbursement_method`.~~
- [x] ~~Payment-search summary amount/count cover the complete filtered result,
  independently of the requested page.~~
- [x] ~~Officer payment-history totals count only posted payments and expose each
  record's verification/posting status.~~
- [x] ~~Workload officer rows now report both assigned and pending counts.~~
- [x] ~~Audit-service action decoding supports the current contract ABI and the
  legacy tuple layout rather than interpreting a state hash as the enum.~~

## Scalability and Maintainability Gaps

- `customer_views.py` remains a very large, multi-responsibility module.
- Several list/search/export paths load unbounded results or paginate in Python.
- Customer/product/officer enrichment frequently causes N+1 MongoDB queries.
- Product validation is concentrated in serializers/views instead of a reusable
  domain service.
- Required-document values are not constrained to a shared canonical enum.
- MongoDB index creation depends on deployment initialization rather than an
  explicit verified startup/deployment contract. Blockchain event/transaction
  idempotency is implemented, but its production index deployment is unverified.
- Import-time MongoDB client creation makes test startup depend on external DNS or
  network state unless `MONGODB_URI` is overridden.
- Dependency lower bounds without a lock file allow major framework-version drift.

## Test Status and Coverage Gaps

Full-suite run after remediation Stage 5 on 2026-08-02:

- 757 tests collected
- 748 passed
- 0 failed
- 9 skipped live-blockchain integration tests

The four failures remaining after Stage 4 are resolved: three audit-service
action-decoding cases and the recent-payments object/dictionary defect. Six
dedicated Stage 5 API/model regressions now cover default payment pagination and
full-result summaries, merged product validation, draft disbursement preference
persistence, disbursed-product mutation protection, workload name enrichment,
and posted-only officer payment totals. A current-ABI audit tuple regression was
also added alongside the legacy-layout tests.

The Stage 4 base-fee handling also resolved the previous four incomplete-mock
blockchain client failures. `git diff --check` passes.

Payment integrity has 13 dedicated tests covering pending submissions, wallet
bypass prevention, actor-scoped idempotency, duplicate references, single-apply
replays, overpayment rejection, interrupted-write recovery, posted-only totals,
officer endpoint replay, and wallet replay without rate re-evaluation. The latest
focused check reports 43 passing payment/wallet tests.

Disbursement integrity has eight dedicated tests covering approved-amount
enforcement, schedule-before-completion ordering, completed replay, safe schedule
failure, external pending behavior, idempotency conflicts, `202` endpoint behavior,
and required idempotency keys. The focused disbursement/loan suites report 76
passing tests.

Stage 4 validation includes eight dedicated wallet-worker, saga,
state-reconciliation, and officer-recovery tests plus the client, sync,
event-listener, Celery-task,
payment, and disbursement suites. Coverage includes encrypted signed-payload
persistence before broadcast, exact post-crash rebroadcast, schedule/completion,
saga-step resume, state-derived missing-job recovery, scoped retry/cancel
operations, nonce-safe client behavior, and listener cursor/deduplication.

Important missing coverage:

- Real MongoDB integration for immutable fields, indexes, data types, and
  transactions
- Real-Mongo concurrent and replayed payments
- Provider callback and reconciliation behavior for deferred payment methods
- Disbursement execution failure/retry/reconciliation
- Every state-changing loan endpoint's RBAC, ABAC, audit, and persisted reload
- Qualification tests that isolate each hard product requirement
- Event-listener default startup and database-backed duplicate handling
- Multi-loan export, invalid format/range, scale, CSV injection, and export audit
- End-to-end blockchain reconciliation and nonce contention

## Ordered Remediation Plan

Work should proceed in this order. Do not mark a stage complete until its focused
tests and relevant full-suite checks pass.

### 1. MongoDB persistence safety — COMPLETE

- [x] ~~Remove immutable `_id` from `LoanApplication` update payloads.~~
- [x] ~~Remove immutable `_id` from `RepaymentSchedule` update payloads.~~
- [x] ~~Remove immutable `_id` from `LoanPayment` update payloads.~~
- [x] ~~Audit all five model-level loan save paths.~~
- [x] ~~Add exact MongoDB update-payload regression tests.~~
- [ ] Add an optional real-Mongo integration job when isolated CI infrastructure
  is available. This is an infrastructure follow-up; the code defect is fixed.

### 2. Payment integrity — COMPLETE FOR CURRENT SCOPE

Implemented:

- [x] ~~Add `pending_verification`, `posting`, `posted`, `failed`, and `reversed`
  payment states.~~
- [x] ~~Prevent customer GCash/bank-transfer claims from reducing balances before
  verification.~~
- [x] ~~Prevent the generic customer endpoint from bypassing wallet verification.~~
- [x] ~~Require actor-scoped, hashed idempotency keys for customer and officer
  payment requests.~~
- [x] ~~Add unique partial indexes for idempotency keys, external-reference
  fingerprints, and ETH transaction hashes.~~
- [x] ~~Add optimistic atomic schedule updates with payment replay tokens.~~
- [x] ~~Recover an interrupted payment-status write without applying the balance
  twice.~~
- [x] ~~Return completed officer and wallet payments safely on identical replay.~~
- [x] ~~Exclude pending and failed records from `total_paid`.~~
- [x] ~~Require configurable ETH confirmation depth.~~
- [x] ~~Reject ETH underpayment and overpayment outside the configured tolerance.~~
- [x] ~~Prevent wallet replays from being recalculated at a newer exchange rate.~~
- [x] ~~Add dedicated payment-integrity and endpoint regression tests.~~
- [x] ~~Update the main loans testing guide with the new payment contract.~~

Intentionally deferred or future scope:

- [ ] Implement authoritative GCash/bank-transfer verification through a provider
  webhook/API or an explicitly approved operations-verification workflow.
  **Decision: intentionally deferred; customer submissions remain pending while
  cash/check and verified ETH wallet payments remain supported.**
- [ ] Define and implement refund, reversal, chargeback, and correction behavior.
- [ ] Define a locked-quote or historical transaction-time ETH conversion policy.
- [ ] Deploy the new MongoDB indexes using the approved state-changing deployment
  procedure and verify existing data has no conflicts.
- [ ] Add real-Mongo concurrency, unique-index, and interrupted-write integration
  tests.
- [ ] Add scheduled reconciliation for records left in `posting` or `failed` after
  infrastructure failures.

### 3. Disbursement integrity — COMPLETE FOR CURRENT SCOPE

Implemented:

- [x] ~~Enforce equality with the approved disbursement amount.~~
- [x] ~~Add idempotent `not_started -> pending -> executed/failed` state
  transitions.~~
- [x] ~~Require actor-scoped disbursement idempotency keys.~~
- [x] ~~Create/reuse the repayment schedule before completing cash/check
  disbursement.~~
- [x] ~~Keep the application approved and record failure when schedule generation
  fails.~~
- [x] ~~Tie cash/check completion audit, notification, and response to confirmed
  execution.~~
- [x] ~~Return GCash, bank-transfer, and wallet disbursement as pending instead of
  claiming successful settlement.~~
- [x] ~~Remove view-triggered unsafe wallet/blockchain daemon sync from the
  disbursement request.~~
- [x] ~~Add focused state, replay, failure, amount, and endpoint tests.~~
- [x] ~~Add a nonce-safe, leased, idempotent durable ETH wallet transfer worker.~~
- [x] ~~Persist wallet conversion and broadcast identity, then resume confirmation
  without sending a second transfer.~~
- [x] ~~Generate/reuse the schedule before wallet completion.~~
- [x] ~~Add bounded retry and five-minute reconciliation for pending wallet
  attempts.~~
- [x] ~~Add focused wallet broadcast, completion, and post-broadcast resume tests.~~
- [x] ~~Add an assignment-scoped operator inspect/reconcile/retry workflow and
  safe cancellation before transaction preparation.~~

Intentionally deferred or deployment follow-up:

- [ ] Add provider confirmation for GCash/bank-transfer disbursement only if those
  methods enter the supported scope.
- [ ] Add an authorized completion callback/operations endpoint for pending
  provider disbursements only if those methods enter scope.
- [ ] Deploy the disbursement idempotency index through the approved procedure.
- [ ] Add real-Mongo concurrency and interruption integration tests.

### 4. Durable blockchain synchronization — CODE COMPLETE FOR CURRENT SCOPE

Implemented:

- [x] ~~Route production synchronization through named Celery tasks instead of
  daemon threads.~~
- [x] ~~Route blockchain and wallet work to a dedicated Celery queue.~~
- [x] ~~Correct the undefined `call_view`/`RepaymentSchedule` imports and schedule
  identifiers.~~
- [x] ~~Coordinate sender nonces across processes with a MongoDB lease.~~
- [x] ~~Give blockchain transaction attempts stable idempotency identities and a
  unique partial deployment index.~~
- [x] ~~Preserve blockchain transaction timestamps as BSON datetimes.~~
- [x] ~~Add acknowledged-late wallet retries and scheduled pending-wallet
  reconciliation.~~
- [x] ~~Poll audit events through Celery Beat with persistent cursor handling and
  database-backed `tx_hash:log_index` deduplication.~~
- [x] ~~Stop cursor advancement when an event cannot be decoded or persisted.~~
- [x] ~~Replace obsolete daemon-thread tests with durable-dispatch tests and add
  wallet worker recovery tests.~~
- [x] ~~Encrypt and persist the signed ETH transaction, hash, nonce, recipient,
  and amount before broadcast.~~
- [x] ~~Rebroadcast only the exact prepared transaction after a pre/post-broadcast
  worker crash, and clear the signed payload after confirmation.~~
- [x] ~~Add step-level persisted saga progress so completed multi-contract steps
  are not repeated by ordinary task retries.~~
- [x] ~~Add five-minute state-derived reconciliation for application, approval,
  rejection, disbursement, schedule, and posted-payment sync jobs missed during
  broker/API failures.~~
- [x] ~~Add an assignment-scoped officer/admin status, reconcile, retry, and safe
  pre-preparation cancel endpoint for wallet disbursements.~~
- [x] ~~Add focused crash-window, exact-rebroadcast, saga-resume,
  state-reconciliation, encryption, and operator-recovery tests.~~

Deployment/integration follow-up (no missing application implementation):

- [ ] Deploy the `blockchain` queue worker and Celery Beat process and verify their
  health/alerts.
- [ ] Deploy the blockchain transaction idempotency index through the approved
  state-changing procedure; `init_db.py` is updated but was not run here.
- [ ] Run real-Mongo/Web3 nonce-contention, worker-crash, reorg, and reconciliation
  integration tests.

### 5. Runtime/API defects — COMPLETE

- [x] ~~Fix recent payments.~~
- [x] ~~Fix default payment-search pagination.~~
- [x] ~~Fix/verify missing imports in workload and disbursement paths.~~
- [x] ~~Fix product partial-update validation.~~
- [x] ~~Prevent edits/deactivation when disbursed loans still use the product.~~
- [x] ~~Persist preferred disbursement method during draft update.~~
- [x] ~~Correct workload and payment reporting inconsistencies.~~
- [x] ~~Correct audit action decoding for current and legacy contract tuple
  layouts.~~

### 6. Qualification enforcement — NOT STARTED

- [ ] Enforce product income and business-age minimums before AI scoring.
- [ ] Add isolated tests for every hard product requirement.
- [ ] Ensure AI output cannot override deterministic eligibility requirements.

### 7. Repayment accounting and lifecycle — NOT STARTED

- [ ] Adopt integer centavos or `Decimal128` for money.
- [ ] Reconcile final-installment rounding.
- [ ] Normalize partial, overdue, penalty, and waiver states.
- [ ] Add completed/paid-off and early-payoff behavior.
- [ ] Add approved reversal, refund, restructuring, and write-off policies.

### 8. Audit, encryption, and compliance — NOT STARTED

- [ ] Correct audit actor attribution.
- [ ] Cover every lifecycle transition.
- [ ] Make audit failures observable.
- [ ] Encrypt intended nested application and schedule data.
- [ ] Audit sensitive exports.

### 9. Schedule export hardening — NOT STARTED

- [ ] Export every loan for a matching customer.
- [ ] Validate format and date ranges.
- [ ] Remove unbounded/N+1 query behavior and stream large exports.
- [ ] Add CSV formula-injection protection.
- [ ] Correct response semantics and add missing regression tests.
- [ ] Add bulk import only if operations approve a defined use case.

### 10. Maintainability and documentation — NOT STARTED

- [ ] Refactor `customer_views.py` into focused modules.
- [ ] Remove N+1 and unbounded query paths.
- [ ] Centralize product rules.
- [ ] Pin/lock production dependencies.
- [ ] Synchronize both loan testing guides with actual routes and behavior.

## Documentation Drift to Correct

### `docs/LOAN_LIFECYCLE_TESTING_GUIDE.md`

- [ ] Officer payment examples use GCash, while manual officer posting accepts only
  cash/check.
- [ ] Disbursement-method examples do not match current accepted methods.
- [ ] It implies officers can inspect/pick unassigned applications, which current
  assignment scoping does not allow.
- [x] ~~Correct the former implication that schedule failure could still return a
  successful disbursement; cash/check execution now fails safely before completion.~~
- [ ] It omits many customer, admin, penalty, blockchain, exchange-rate,
  recent-payment, and export endpoints.

### `docs/LOANS_TESTING_GUIDE.md`

- [x] ~~Expand the URL inventory to 44 method/endpoint combinations, including
  recent payments and schedule export.~~ Detailed prose for those newer endpoints
  remains Stage 10 documentation work.
- [x] ~~Align workload response fields with the implementation.~~
- [x] ~~Implement and document preferred disbursement persistence during draft
  update/resubmission.~~
- [x] ~~Update customer payment documentation for pending verification,
  idempotency, provider references, and posted-only totals.~~
- [x] ~~Align wallet tolerance documentation with enforced lower and upper bounds.~~
- [x] ~~Document wallet confirmation depth and idempotent replay behavior.~~
- [x] ~~Document officer payment idempotency requirements.~~
- [x] ~~Fix the documented payment-search default pagination path and define its
  summary as the complete filtered result.~~
- [ ] Several cross-document filenames/paths are stale.

## Release Decision

**Current decision: Not ready for production financial operations.**

Authentication and the breadth of functionality are strong foundations, but the
payment, disbursement, repayment, and blockchain consistency blockers above must
be resolved. Release readiness should be reassessed after remediation stages 1
through 8 and a clean full-suite plus real-Mongo integration run.

This is a code-level review. It does not include live penetration testing,
provider certification, blockchain deployment validation, accounting approval, or
production data migration/repair.
