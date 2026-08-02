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

The loans module implementation is **complete for the currently approved
cash, check, and verified ETH wallet scope**. Product management, application
intake, qualification, officer review, assignment, disbursement, repayment
schedules, penalties, notifications, auditing, and blockchain services are
implemented and covered by the backend test suite.

This code-complete milestone is distinct from production deployment approval.
GCash, bank transfer, and provider-backed card/payment integrations remain future
work. Reversal, refund, restructuring, and write-off operations also remain
future work until the institution approves their accounting policies.

Current remediation progress:

- [x] ~~Stage 1 — MongoDB persistence safety~~
- [x] ~~Stage 2 — Payment integrity for cash/check/ETH wallet~~ — GCash and bank
  provider verification intentionally deferred
- [x] ~~Stage 3 — Disbursement integrity for cash/check/ETH wallet~~ — GCash and
  bank provider execution intentionally deferred
- [x] ~~Stage 4 — Durable blockchain synchronization (code complete for current
  scope)~~ — production deployment/integration validation remains
- [x] ~~Stage 5 — Runtime/API defects~~
- [x] ~~Stage 6 — Qualification enforcement~~
- [ ] Stage 7 — Repayment accounting and lifecycle — **COMPLETE FOR CURRENT
  SCOPE / PARTIAL FOR FUTURE EXCEPTION FLOWS**; institution policy decisions
  remain for reversal, refund, restructuring, and write-off
- [x] ~~Stage 8 — Audit, encryption, and compliance~~
- [x] ~~Stage 9 — Schedule export hardening~~
- [x] ~~Stage 10 — Maintainability and documentation~~

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

**Status: Complete for the approved export scope**

`GET /api/loans/officer/schedules/export/` supports audited CSV/JSON exports with
customer, complete installment-status, and inclusive date filters. Twenty-one
dedicated export tests currently pass.

Completed in Stage 9:

- [x] ~~Export every repayment schedule when a customer has multiple loans.~~
- [x] ~~Reject unsupported formats, invalid calendar dates, and reversed ranges.~~
- [x] ~~Replace unbounded list loading and per-schedule N+1 lookups with lazy
  schedule cursors and related-record batches capped at 200 schedules.~~
- [x] ~~Stream CSV and JSON output instead of assembling the complete payload in
  memory.~~
- [x] ~~Neutralize formula-leading customer, product, reason, and other string
  cells before CSV output.~~
- [x] ~~Require a `repayment_schedule_exported` access audit before returning
  data, failing closed with `503` when it cannot be written.~~
- [x] ~~Return `404` consistently for empty CSV and JSON results.~~
- [x] ~~Treat invalid legacy related IDs as unavailable metadata rather than
  raising an unhandled ObjectId error.~~
- [x] ~~Name flattened JSON rows `installments` and expose an exact total and
  `X-Export-Row-Count` response header.~~

Bulk import remains intentionally unimplemented. It is not required for export
hardening and should only be added if finance operations approve a concrete input
schema, validation rules, authorization model, and rollback procedure.

Stage 9 validation on 2026-08-02: all 21 dedicated export tests and the 80-test
loan repayment/audit/export regression set pass. The full backend suite collects
792 tests: 783 pass and 9 live-blockchain integration tests are skipped, with zero
failures. Ruff passes for the production export module, and `git diff --check`
passes. Django's system check still reports only the pre-existing django-axes
cache configuration warning.

### Status-transition audit logging

**Status: Complete for implemented lifecycle operations**

Stage 8 corrected assignment/reassignment attribution so the audit actor is the
administrator or system that performed the action, while the assignee is retained
as transition metadata. Officer/admin endpoints now derive the actual request role
instead of hardcoding `loan_officer`. Submission, assignment/reassignment,
missing-document review, approval/rejection, disbursement pending/executed/failed,
resubmission, and paid-off closure all have an audit path. Disbursement sub-state
auditing is located at the atomic model transition, so background wallet completion
and failure are covered as well as request-driven cash/check operations.

Loan audit writes now use one observable wrapper. A failed primary write produces
an exception log, increments `loan_audit_write_failures_total`, and is queued
best-effort in `audit_write_failures` without copying sensitive event details.
Financial mutations are not falsely rolled back after completion; sensitive export
reads use the wrapper's fail-closed mode.

### Field encryption

**Status: Complete for the declared loan fields**

The shared helper now encrypts dict/list/tuple values as BSON before Fernet
encryption, preserving nested datetimes and ObjectIds. Existing plaintext nested
documents remain readable and are encrypted on their next model save. Application
`internal_notes` and repayment `installments` are now ciphertext at rest when a
key is configured. Repayment atomic payment/payoff writes encrypt their payloads
and use `accounting_version` optimistic concurrency, so encryption does not break
posting or replay protection. Direct disbursement reservation now also encrypts
its declared reference field instead of bypassing model serialization.

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

### 4. Qualification requirements enforcement

**Status: Complete**

Remediated in Stage 6:

- Product `min_monthly_income` and `min_business_months` are now deterministic
  hard-fail gates enforced at three points:
  1. **Pre-AI gate** in `qualify_customer` — short-circuits before the LLM call
     when the customer fails a hard requirement.
  2. **Post-AI enforcement** in `_validate_and_normalize_ai_qualification` —
     defense-in-depth; merges hard failures into `missing_requirements` and
     forces `eligible=False` even if the AI returned `eligible=True`.
  3. **Rule-based path** in `rule_based_qualification` — income and business-age
     violations are added to `missing` as hard-fail entries instead of only
     reducing the score.
- A zero-valued minimum (`min_monthly_income=0` or `min_business_months=0`) is
  treated as "no minimum required" and skips the check.
- 14 dedicated enforcement tests verify each hard requirement in isolation,
  boundary values, AI override prevention, rule-based enforcement, and
  zero-minimum semantics. The additional orchestration test proves a hard failure
  returns before the LLM service is constructed.

### 5. Repayment accounting and lifecycle

**Status: Partial; exact accounting and payoff complete, institutional policies pending**

Implemented in Stage 7:

- Schedule, installment, penalty, and payment accounting now uses integer
  centavos as its calculation/persistence source of truth. Existing peso fields
  remain as two-decimal compatibility/display values, and legacy records without
  centavo fields are converted on read.
- Schedule generation distributes indivisible principal centavos into the final
  installment, so installment principal and total sums reconcile exactly.
- Payment aggregation and posted totals sum centavos rather than binary floats.
- Installment states distinguish `partial`, `overdue`, and `partial_overdue`;
  `get_next_payment()` returns the earliest unpaid installment in any of those
  states.
- Penalty application/waiver is centralized in the schedule model. Waiving a
  partially paid penalty normalizes status and records any amount above base due
  as an explicit `waiver_credit_amount` instead of producing a negative balance.
- Exact final payment marks the schedule `paid_off` and the application
  `completed`/`paid_off`. A daily reconciliation task repairs legacy or
  interrupted zero-balance schedules.
- Officers can quote and post idempotent verified cash/check early payoff through
  `GET`/`POST /officer/applications/<id>/payoff/`; one atomic schedule update
  allocates the payoff across every open installment and survives an interruption
  between schedule settlement and payment posting.
- Duplicate instance/class blockchain updater definitions were removed; the
  class-level persistence methods remain the single active implementation.

Still requires institution-approved policy before implementation:

- Reversal eligibility/window and whether a reversal reopens delinquency.
- Refund authorization, evidence, destination rail, and relationship to reversal.
- Restructuring treatment of accrued interest, penalties, term/rate changes, and
  required borrower consent.
- Write-off approval authority, accounting date/reason codes, recovery behavior,
  and whether written-off balances remain collectible.
- Dual-control requirements, audit evidence, notifications, and blockchain
  representation for all four actions. Early-payoff allocation is intentionally
  excluded from the current whole-peso blockchain payment mirror until its
  centavo/multi-installment contract is defined.

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

- [x] ~~The former 1,900-line `customer_views.py` implementation is split into
  product, application, repayment, and blockchain/wallet modules. The old module
  is now a 39-line compatibility facade.~~
- [x] ~~High-volume customer, product, officer, payment-history, active-loan, and
  export paths now use database pagination, bounded searches/streams, and bulk
  related-record loading instead of whole-collection Python pagination and N+1
  enrichment. Derived on-time/late payment filtering still requires a lazy scan
  because that value is computed from schedule installments, but memory use is
  bounded to the requested page and a 256-schedule LRU cache.~~
- [x] ~~Shared product-bound, application-term, and recommendation-clamping rules
  now live in `loans/services/product_rules.py` and are consumed by serializers
  and customer application/prequalification views.~~
- [x] ~~Required-document serializer values are constrained to the canonical
  document-type choices.~~
- MongoDB index creation depends on deployment initialization rather than an
  explicit verified startup/deployment contract. Blockchain event/transaction
  idempotency is implemented, but its production index deployment is unverified.
- [x] ~~MongoDB client construction is lazy, so importing Django settings no
  longer performs DNS/network work. The first real database operation still
  surfaces configuration/connectivity failures normally.~~
- [x] ~~`requirements.lock` provides the exact production dependency versions
  validated by this remediation pass; `requirements.txt` remains the flexible
  development/source manifest.~~

## Test Status and Coverage Gaps

Full-suite run during Stage 7 remediation on 2026-08-02:

- 780 tests collected
- 771 passed
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

### 6. Qualification enforcement — COMPLETE

- [x] ~~Enforce product income and business-age minimums before AI scoring.~~
- [x] ~~Add isolated tests for every hard product requirement.~~
- [x] ~~Ensure AI output cannot override deterministic eligibility requirements.~~

### 7. Repayment accounting and lifecycle — PARTIAL

- [x] ~~Adopt integer centavos for repayment and payment accounting while
  retaining compatible two-decimal peso response fields.~~
- [x] ~~Reconcile final-installment rounding.~~
- [x] ~~Normalize partial, overdue, penalty, and waiver states.~~
- [x] ~~Add completed/paid-off state, daily reconciliation, and idempotent
  cash/check early-payoff behavior.~~
- [ ] Add approved reversal, refund, restructuring, and write-off policies.
  This is awaiting the institution decisions listed in the repayment section;
  no financial policy was invented in code.

### 8. Audit, encryption, and compliance — COMPLETE

- [x] ~~Correct audit actor attribution.~~
- [x] ~~Cover every implemented lifecycle transition.~~
- [x] ~~Make audit failures observable.~~
- [x] ~~Encrypt intended nested application and schedule data.~~
- [x] ~~Audit sensitive exports and fail closed when the access audit is
  unavailable.~~

Focused Stage 8 regression coverage includes nested BSON encryption round trips,
encrypted atomic payment writes, administrator assignment attribution, persistent
audit-failure visibility, required-audit failure behavior, export event metadata,
and export fail-closed behavior. Reversal/refund/restructuring/write-off audit
events remain part of the deferred Stage 7 policy work because those operations do
not yet exist.

Validation on 2026-08-02: the 74-test focused Stage 7/8, audit, export,
disbursement, and repayment set passes. The full backend suite collects 786 tests:
777 pass and 9 live-blockchain integration tests are skipped, with zero failures.
Targeted Ruff `F`/`E9` checks and `git diff --check` pass. Django's system check
continues to report the pre-existing django-axes cache configuration warning.

### 9. Schedule export hardening — COMPLETE

- [x] ~~Export every loan for a matching customer.~~
- [x] ~~Validate format and date ranges.~~
- [x] ~~Remove unbounded/N+1 query behavior and stream large exports.~~
- [x] ~~Add CSV formula-injection protection.~~
- [x] ~~Correct response semantics and add missing regression tests.~~
- [ ] Add bulk import only if operations approve a defined use case. This is an
  optional future capability, not a production-readiness blocker for exports.

### 10. Maintainability and documentation — COMPLETE

- [x] ~~Refactor `customer_views.py` into focused modules while retaining the
  legacy import surface.~~
- [x] ~~Replace the identified N+1 enrichment and unbounded list/export paths
  with bulk loaders, database pagination, bounded searches, lazy scans, or
  streaming batches as appropriate.~~
- [x] ~~Centralize product bounds, requested-term validation, and recommendation
  normalization.~~
- [x] ~~Constrain required-document serializer values to the canonical enum.~~
- [x] ~~Make the MongoDB handle lazy so application import does not require DNS.~~
- [x] ~~Add an exact production dependency lock file.~~
- [x] ~~Synchronize both loan testing guides with current routes, lifecycle
  states, payment/disbursement behavior, assignment scope, and source paths.~~

Stage 10 added focused regressions for the shared rule service, three-query bulk
application enrichment, focused/compatibility view imports, lazy MongoDB client
construction, and exact dependency pins. Validation on 2026-08-02: the full
backend suite collects 797 tests; 788 pass and 9 live-blockchain integration
tests are skipped, with zero failures. Targeted Ruff undefined-name/import and
syntax checks plus `git diff --check` pass.

## Documentation Drift to Correct

### `docs/LOAN_LIFECYCLE_TESTING_GUIDE.md`

- [x] ~~Clarify that manual officer posting accepts cash/check and that GCash/bank
  submissions require a future verified provider workflow.~~
- [x] ~~Separate accepted customer preference values from currently executable
  cash/check/wallet disbursement methods.~~
- [x] ~~Correct the implication that officers can inspect or claim unassigned
  applications; current assignment scope does not allow it.~~
- [x] ~~Correct the former implication that schedule failure could still return a
  successful disbursement; cash/check execution now fails safely before completion.~~
- [x] ~~Add the omitted customer, admin, penalty, blockchain, exchange-rate,
  recent-payment, payoff, recovery, and export routes/behavior.~~

### `docs/LOANS_TESTING_GUIDE.md`

- [x] ~~Expand the URL inventory to 44 method/endpoint combinations and add
  detailed recent-payment, payoff, recovery, and export behavior.~~
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
- [x] ~~Update stale source paths and cross-document route references.~~

## Release Decision

**Current-scope implementation decision: Complete.**

**Production deployment approval: Pending environment and operational
validation.**

Code remediation for the approved cash, check, and ETH wallet scope is complete.
Institution-defined reversal/refund/restructuring/write-off policies and GCash,
bank, Stripe, or other provider verification/execution are intentionally deferred
future capabilities and are not part of this completed scope. Production approval
still requires clean real-Mongo/index validation, live blockchain
deployment/integration validation, resolution of the django-axes cache warning,
environment/security review, and finance/accounting acceptance of the supported
operational scope.

This is a code-level review. It does not include live penetration testing,
provider certification, blockchain deployment validation, accounting approval, or
production data migration/repair.
