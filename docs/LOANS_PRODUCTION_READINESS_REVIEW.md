# Loans Production Readiness Review

Last updated: 2026-08-15

Scope: `loans/`, `/api/loans/`, loan products, qualification, applications,
assignment and review, disbursement, repayment accounting, penalties, payoff,
loan exports, blockchain synchronization, MongoDB persistence, Celery tasks,
notifications, audit integration, and loan-related automated tests.

## Purpose and Status Definitions

This document records what the Loans module currently does, the evidence for
those claims, and the work required before production approval. It distinguishes
an endpoint being present from the operation being private, atomic, durable,
bounded, observable, and supported by an approved business policy.

- **Complete**: implemented and covered by proportionate automated evidence.
- **Partial**: useful behavior exists, but important correctness, security,
  durability, scalability, policy, or operational work remains.
- **Not implemented**: no production implementation was found.
- **Deployment validation**: implemented code that still needs evidence from
  the selected MongoDB, Redis/Celery, blockchain, proxy, monitoring, backup, and
  recovery environment.

The project uses PyMongo directly. Django ORM migrations are not part of the
Loans persistence model. Mocked or `mongomock` tests do not prove real MongoDB
atomicity, validators, uniqueness, query plans, worker contention, provider
settlement, or blockchain behavior.

## Executive Summary

The Loans module is **feature-rich but not yet production-ready**. Product
management, qualification, customer applications, manual assignment, scoped
officer review, cash/check disbursement, centavo-based repayment accounting,
penalties, early payoff, encrypted sensitive fields, audit integration, and a
durable wallet-disbursement design are implemented. Thirty-nine registered paths
expose 45 HTTP method/path operations across customer, officer, and
administrator roles.

Stages 1 through 4 have closed the application-code authorization, response,
concurrent lifecycle, exposed-settlement-scope, persistence-tooling, and bounded
execution defects identified by this review. Stages 2 and 4 still require their
opt-in suites to run against an approved isolated real MongoDB target.
The settlement baseline exposes cash/check, with wallet-to-wallet available only
when blockchain is explicitly enabled. No other settlement rail is represented
in the API, persistence validator, AI guidance, or smart-contract enums. The
remaining blockers are release evidence, privacy, and operational concerns:

1. The isolated real-Mongo Stage 2 suite exists but has not been executed
   against an approved target; local `mongomock` concurrency is not deployment
   evidence.
2. Stage 4 inventory/backfill commands, validators, compound indexes, and an
   isolated real-Mongo suite exist, but have not been executed against a
   reviewed deployment copy or approved isolated MongoDB target.
3. Local query and job bounds are implemented; representative target-volume
   query plans, multi-worker contention, and load/latency evidence remain
   deployment validation.
4. Loan data is not included in customer account export and has no documented
   retention, legal-hold, anonymization, or deletion policy integration.
5. Encryption covers selected free-text fields, but application purpose/AI
   recommendation and several provider/blockchain failure-detail fields remain
   plaintext in their domain collections.
6. Loans has one audit-failure counter but no complete loan/payment/disbursement
   metrics, dashboards, alerts, or bounded backlog gauges.

Current automated baseline:

- Loan/blockchain-related selection: **502 passed, 13 skipped, 713 deselected**
  on 2026-08-15.
- Full repository regression: **1,268 passed, 39 skipped** on 2026-08-15.
- The 13 loan-selection skips are nine real-Ganache cases, three opt-in Stage 2
  real-Mongo cases, and one opt-in Stage 4 real-Mongo case; skips are not
  deployment evidence.
- The selection includes model, API, permission, qualification, payment,
  disbursement, repayment, export, audit, task, wallet-recovery, blockchain
  service, event-listener, and saga tests.
- Stage 4 focused validation: **11 passed, 1 skipped** on 2026-08-15. The skip
  is the deliberately opt-in isolated real-Mongo validator/index/query-plan
  case and is not deployment evidence.

## Current Status

| Area | Status | Summary |
| --- | --- | --- |
| Product catalog | Implemented | Admin CRUD, soft deletion, and bounded customer pagination exist. |
| Qualification | Implemented | Rules enforce profile/document/product readiness; AI is advisory with deterministic fallback. |
| Applications | Implemented; real-Mongo proof pending | Owner-scoped create/list/detail/update/resubmit flows use guarded submit/resubmit transitions and stable conflicts. |
| Assignment | Implemented; real-Mongo proof pending | Admin assign/reassign transitions compare the expected status and assignee; competing stale requests cannot overwrite the winner. Auto-assignment remains unused. |
| Officer review | Implemented; delivery hardening remains | Review decisions are one-winner transitions, encrypted note appends use retrying compare-and-set, and document-request history is atomically preserved. Durable notifications remain Stage 5 work. |
| Cash/check disbursement | Implemented with remaining hardening | Idempotency, atomic disbursement claims, safe public failures, and a cash default exist; deployment concurrency proof remains. |
| Wallet disbursement/payment | Partial; deployment-gated | Confirmation, durable retries, leases, exact rebroadcast, and recovery exist; real-chain and multi-worker evidence remain. |
| Repayment accounting | Implemented for the baseline | Versioned centavo math, optimistic schedule updates, exact payoff terms, and atomic penalty/waiver handling exist. Collected waiver credit is carried forward; a waiver requiring an external refund is rejected. Reserved reversal/write-off workflows remain unavailable. |
| Retrieval/search/export | Implemented locally; load proof pending | Role-scoped pagination, keyed exact payment-reference search, explicit supporting-search truncation, and a configurable 10,000-row synchronous export ceiling are implemented. |
| Security and privacy | Stage 1 complete; later gaps remain | JWT, role/permission/assignment scope, explicit blockchain response contracts, stable public errors, encryption, idempotency, and audit exist. Lifecycle and data-governance work remains in later stages. |
| MongoDB schema/indexes | Implemented locally; real-Mongo proof pending | Count-only inventory, dry-run-first backfill, strict validator manifests, compound indexes, and an isolated real-Mongo suite exist. Target execution remains pending. |
| Background processing | Implemented locally; deployment proof pending | Overdue, lifecycle, and wallet reconciliation scans are batched, leased, checkpointed, routed to a dedicated queue, and time-bounded. Multi-worker/load proof remains. |
| Monitoring | Partial | Audit write failures are counted; end-to-end operational metrics, dashboards, and alerts are missing. |
| Production deployment | Not approved | Real MongoDB, Redis/Celery, chain/RPC, proxy, secrets, backup/restore, monitoring, and incident evidence remain. |

## Module Responsibilities

The Loans module currently owns:

- loan-product definitions and administrative management;
- customer eligibility checks and application submission;
- officer assignment, workload, review, notes, and missing-document requests;
- disbursement state and repayment-schedule generation;
- cash/check posting and verified ETH payment recording;
- penalty application/waiver and early payoff;
- customer/officer repayment history and officer schedule exports;
- off-chain/on-chain synchronization records and reconciliation tasks; and
- loan-domain audit events and customer/staff notifications.

It depends on Accounts for authentication, role/permission enforcement,
customers, and officers; Profiles and Documents for readiness and wallet data;
Notifications for in-app/WebSocket/email delivery; Analytics for audit storage;
Redis/Celery for durable background work; and an RPC/contracts deployment when
blockchain support is enabled.

## API Status

All routes are mounted under `/api/loans/` and require authenticated JWTs.

### Customer operations

| Method and route | Current behavior | Status |
| --- | --- | --- |
| `GET products/` | Active product catalog | Implemented with bounded pagination |
| `GET products/<product_id>/` | Active product detail | Implemented |
| `POST pre-qualify/` | Rules, readiness, score, recommendation | Implemented |
| `POST apply/` | Validate readiness and submit application | Implemented with an immutable transition ID |
| `GET applications/` | Owner-scoped filtered pagination | Implemented |
| `GET/PUT applications/<application_id>/` | Owner detail/draft update | Implemented |
| `GET applications/<application_id>/schedule/` | Owner repayment schedule | Implemented |
| `GET applications/<application_id>/payments/` | Owner-scoped payment history | Implemented; the route is read-only |
| `POST applications/<application_id>/resubmit/` | Rejected application back to draft | Implemented with expected-state conflict protection |
| `GET applications/<application_id>/feedback/` | Owner rejection feedback | Implemented |
| `POST applications/<application_id>/set-disbursement-method/` | Borrower preference | Cash/check, plus wallet only when blockchain is enabled |
| `GET applications/<application_id>/blockchain/` | Owner chain status | Implemented with a customer-safe field allowlist; deployment-gated |
| `POST applications/<application_id>/wallet-payment/` | Verify confirmed ETH transfer and post | Implemented with stable public failures; real-chain proof remains |
| `GET system-wallet/` | Public payment wallet metadata for customer | Implemented when blockchain is configured |

### Administrator operations

| Method and route | Required boundary | Status |
| --- | --- | --- |
| `GET/POST admin/products/` | Admin + `manage_system` | Implemented |
| `GET/PUT/DELETE admin/products/<product_id>/` | Admin + `manage_system` | Implemented; delete is soft deactivation |
| `POST admin/applications/<application_id>/assign/` | Admin + `manage_loan_officers` | Implemented with expected-assignee conflict protection |
| `POST admin/applications/<application_id>/reassign/` | Admin + `manage_loan_officers` | Implemented with expected-assignee conflict protection |
| `GET admin/officers/workload/` | Admin + `manage_loan_officers` | Implemented with database pagination and aggregated workload counts |
| `GET admin/blockchain/transactions/` | Admin + `view_logs` | Implemented with strict bounded filters and an administrator field allowlist; deployment-gated |

### Officer and administrator operations

The shared officer mixin permits a loan officer or administrator. Loan officers
must normally be assigned to the application; administrators are not
assignment-limited.

| Method and route | Current behavior | Status |
| --- | --- | --- |
| `GET officer/applications/` | Filtered, paginated assigned queue | Implemented with bounded supporting search and explicit truncation metadata |
| `GET officer/applications/<application_id>/` | Scoped detail | Implemented |
| `POST .../notes/` | Append bounded encrypted internal note history | Implemented with retrying compare-and-set; real-Mongo proof pending |
| `POST .../request-missing-documents/` | Atomically record request/history and notify customer | State transition implemented; email remains best effort pending Stage 5 |
| `PUT .../review/` | Approve or reject | Implemented as a one-winner expected-state transition |
| `POST .../disburse/` | Cash/check or feature-gated wallet disbursement | Implemented by enabled rail; all other values are invalid input |
| `GET/POST .../wallet-disbursement/` | Inspect/reconcile/retry/safely cancel | Implemented; deployment-gated |
| `POST officer/payments/` | Post cash/check payment | Implemented with idempotency and centavo allocation |
| `GET officer/payments/recent/` | Recent accessible payments | Implemented with indexed officer scope and a maximum 50-row result |
| `GET officer/payments/search/` | Filtered payment list and summary | Implemented with indexed scope/timing metadata, exact blind-reference search, pagination, and explicit supporting-search truncation |
| `GET officer/active-loans/` | Scoped active-loan lookup | Implemented; requires search or customer ID |
| `GET .../schedule/` | Scoped schedule detail | Implemented |
| `GET .../payments/` | Scoped payment history | Implemented |
| `POST .../penalties/apply/` | Apply explicit officer-entered late penalty | Implemented with versioned policy metadata and optimistic concurrency |
| `POST .../penalties/waive/` | Waive penalty | Implemented; collected credit carries to later installments atomically, while unsupported external refunds are rejected |
| `GET/POST .../payoff/` | Quote / settle exact early payoff | Implemented with explicit quote basis, centavo rounding, timestamp, and policy version |
| `GET .../blockchain/` | Scoped chain transaction/audit status | Implemented with assignment concealment and an officer-safe field allowlist; deployment-gated |
| `GET officer/exchange-rate/` | Current ETH/PHP rate | Deployment-gated |
| `GET officer/schedules/export/` | Streaming audited CSV/JSON export | Partial; no total-row cap and results are scanned once to count and again to stream |

The exact request/response examples and test sequence are maintained in
`docs/LOANS_TESTING_GUIDE.md`.

## Verified Implemented Foundations

### Product and qualification rules

- Administrators create, update, list, and soft-delete products.
- Product bounds cover amount, monthly interest rate, terms, income, business
  age/type, and required document types.
- Pre-qualification and submission inspect customer profile and approved
  current documents.
- Qualification returns eligibility, risk category, missing requirements,
  recommendation, and product/baseline scope.
- AI qualification has a deterministic rule-based fallback. It is advisory and
  does not replace officer approval.

### Application, assignment, and review

- Customer lists and details are owner-scoped.
- The `pending` list alias maps to `submitted` plus `under_review`.
- Admin assignment and reassignment validate officer identity and active state.
- Officer application list/detail/mutation endpoints generally conceal records
  outside assignment scope.
- Internal notes retain the latest 100 entries.
- Missing-document requests reject already-present document types.
- Rejected customers can read feedback and reset an application to draft for
  revision.

### Disbursement integrity

- Disbursement requires an 8–128 character idempotency key and scopes it to the
  officer actor.
- An atomic MongoDB claim moves an approved application into one pending
  disbursement attempt; incompatible key reuse is rejected.
- Cash/check execution creates the repayment schedule and completes the
  application state synchronously.
- Wallet execution uses a Celery task with late acknowledgement, worker leases,
  prepared signed payload persistence, exact-payload rebroadcast, receipt
  reconciliation, retry limits, and operator recovery actions.
- Prepared raw transactions are encrypted and are not returned by the recovery
  endpoint.
- Settlement values are limited to cash, check, and wallet. Unsupported values
  fail validation before any financial state mutation.

### Repayment and accounting

- Money allocation uses integer centavos with explicit conversion helpers.
- Schedule generation allocates principal remainders deterministically and
  calculates monthly interest using product terms.
- Payment keys and external-reference fingerprints have unique indexes.
- Schedule mutation uses an accounting version and compare-and-swap update.
- Payment tokens make schedule application repeatable after partial failures.
- Overpayment above the selected installment balance is rejected.
- Paid schedules close the application as `completed`/`paid_off`.
- Penalty apply/waive actions use the same accounting-version guard as payments
  and payoff. A collected waived amount is atomically carried to later unpaid
  installments; if value would remain and require a refund, the waiver is
  rejected without mutation.
- Product responses publish a client-safe settlement policy. Payoff quotes
  identify their balance basis, exact-amount rule, timestamp, rounding, and
  accounting-policy version. Wallet metadata identifies verification-time rate
  valuation and its maximum cache age.
- Customer wallet payments verify receipt success, recipient, sender, value,
  minimum confirmations, and transaction uniqueness before posting.

### Blockchain synchronization

- Ten ABI-backed contract boundaries cover applications, review, approval,
  disbursement, schedules, payments, audit, access control, and core state.
- Transaction records use stable idempotency keys and pending/confirmed/failed
  state.
- Celery tasks implement retries, step-level saga progress, event cursoring,
  nonce serialization, and off-chain/on-chain reconciliation.
- Beat schedules poll audit events every minute and reconcile domain state every
  five minutes.
- Blockchain can be disabled for the ordinary cash/check baseline.

### Authentication, authorization, audit, and encryption

- Views use `CustomJWTAuthentication` and `IsAuthenticated`.
- Customer endpoints require the customer role and derive ownership from the
  authenticated identity.
- Admin product, assignment, workload, and blockchain views use named
  permissions.
- Most officer application operations enforce assignment-based ABAC and conceal
  out-of-scope existence.
- Product descriptions, application internal/officer notes, rejection and
  missing-document reasons, disbursement references, schedule installments,
  payment notes/references, and prepared wallet payloads use shared versioned
  field encryption.
- Loan actions write structured Analytics audit events with event-time officer
  scope. Failed best-effort audit writes enter the shared replay pipeline, while
  schedule exports fail closed if their required access audit cannot be stored.
- CSV exports stream in 200-schedule processing batches, fail closed when their
  access audit cannot be recorded, and protect against spreadsheet formula
  injection. The total export is not bounded.

## Persistence and Background Processing

Primary collections are:

- `loan_products`;
- `loan_applications`;
- `repayment_schedules`;
- `loan_payments`;
- `blockchain_transactions`; and
- supporting blockchain sender-lock and audit-cursor records.

`init_db.py` installs model indexes, including unique product code, one schedule
per loan, payment/disbursement idempotency, external reference fingerprints,
wallet transaction hashes, and blockchain transaction keys. It does **not**
install loan JSON-schema validators.

Scheduled work currently includes daily overdue marking, daily paid-off
reconciliation, five-minute wallet-disbursement reconciliation, one-minute
blockchain audit polling, and five-minute blockchain domain reconciliation.
Wallet execution is routed to the `blockchain` queue; the repayment scans use
the default queue.

## Implemented Controls and Remaining Release Conditions

### 1. Authorization and response minimization

**Status: Complete in application code and automated tests**

1. Officer blockchain status now requires explicit application assignment
   scope and conceals out-of-scope records as not found.
2. Customer, officer, and administrator blockchain serializers expose explicit
   role-appropriate field allowlists. Raw details, idempotency values, provider
   errors, signed data, and contract internals are excluded.
3. Customer and officer application/disbursement responses map stored failures
   to stable public codes instead of returning `disbursement_error`.
4. Wallet verification, wallet connection, exchange-rate, and unexpected
   disbursement failures use stable codes while protected logs retain detail.
5. Administrator blockchain filters reject unknown parameters, invalid enum or
   date values, oversized searches, and out-of-range pagination. Search text is
   treated literally and results are deterministically ordered.

Evidence: `tests/test_loans_stage1_security_contract.py` provides 17 focused
regressions. The broader Loans selection passes with 477 passed and 9 opt-in
Ganache tests skipped.

### 2. Atomic lifecycle and financial correctness

**Status: Implemented locally — isolated real-Mongo execution pending**

1. Approve/reject now use one guarded `find_one_and_update` requiring a
   reviewable status and the expected assignee; a stale loser receives
   `LOAN_TRANSITION_CONFLICT`.
2. Persisted submission, resubmission, missing-document requests, assignment,
   and reassignment use expected-state selectors and stable conflict responses.
3. Because internal-note history is encrypted as one field, note appends use a
   bounded compare-and-set retry over the exact stored ciphertext instead of an
   unsafe stale save. Accepted concurrent notes and the 100-entry bound are
   preserved.
4. Lifecycle mutations append immutable `loan_evt_*` identifiers. The same ID
   is carried into audit metadata, idempotent notifications, and submission/
   decision blockchain jobs.
5. Wallet rebroadcast count now increments only from the successful broadcast
   callback; failed sends do not inflate it.
6. Eight focused local Stage 2 regressions pass. Three opt-in real-Mongo tests
   cover review, assignment, notes, disbursement claims, payment tokens, payoff,
   and schedule completion but remain unexecuted pending target approval.

Release evidence: one-winner concurrent transition tests and crash/replay tests
at every mutation boundary.

### 3. Settlement rails and business-policy decisions

**Status: Complete in application code for the approved baseline**

- The versioned `cash-check-wallet-v1` settlement policy exposes cash/check and
  adds wallet only when `BLOCKCHAIN_ENABLED=True`. All other values are invalid
  rather than advertised as planned or dormant methods.
- Product list/detail responses publish the client-safe available methods and
  policy metadata. Clients must use that contract instead of hard-coded rail
  lists.
- The versioned `scheduled-balance-v1` policy uses PHP centavos, half-up
  rounding, UTC timestamps, scheduled principal/interest/penalties as the exact
  payoff basis, explicit officer-entered penalties, and no automatic calendar
  adjustment.
- Waiving a collected penalty carries the resulting credit into later unpaid
  installments atomically. A waiver is rejected without mutation when it would
  require an unsupported external refund.
- Reversal, refund, correction, chargeback, restructuring, and write-off remain
  reserved/unexposed workflows. They must not be enabled until a separately
  approved policy and complete accounting lifecycle are implemented.
- Customer wallet payments are valued at verification time. The API publishes
  a 300-second maximum cached-rate age; deployed rate-provider/chain proof remains a
  Stage 6 condition whenever wallet support is enabled.

Release evidence still required outside Stage 3: institutional/legal approval
of the documented lending policy and deployed wallet proof if that optional rail
is enabled.

### 4. MongoDB schema, inventory, and query correctness

**Status: Implemented locally — deployment-copy execution pending**

Implemented:

- `loan_data_inventory` provides bounded, count-only detection of missing
  fields/metadata, invalid statuses, plaintext or old-key ciphertext, and
  duplicate unique values without returning sensitive values.
- `backfill_loan_data` is dry-run-first, compare-and-set protected, rejects
  truncated/invalid/conflicting runs, rotates configured encrypted fields, and
  derives centavo, accounting, payment-scope, timing, lifecycle, and blind-index
  metadata.
- Strict JSON-schema validator manifests cover products, applications,
  schedules, payments, and blockchain transactions, including encrypted-field
  shapes. `init_db.py` now fails closed on index/validator errors.
- Query-specific compound indexes cover customer/officer application pages,
  payment reference/scope/timing pages, schedule scans, disbursement recovery,
  and blockchain reconciliation.
- Payment-reference search now uses a normalized keyed HMAC blind index and
  supports previous encryption keys during rotation; ciphertext regex is gone.
- An opt-in isolated real-Mongo suite installs the validators/indexes, rejects
  invalid writes, inserts a representative payment fixture, and requires an
  indexed reference-search plan.

Release evidence: reviewed inventory, approved backup, applied backfill,
validator/index manifest, clean post-inventory, and target query plans.

### 5. Bounded queries and background jobs

**Status: Implemented locally — deployment load proof pending**

- Customer products and officer workload now use database pagination.
- Payments store indexed officer scope, loan lifecycle, and timing metadata, so
  recent/search/timing queries no longer materialize all assigned/disbursed loan
  IDs or scan the full result in Python.
- Supporting customer/product searches remain deliberately capped and publish
  `search_truncated`; payment references use an exact blind index.
- Synchronous schedule export rejects results above `LOAN_EXPORT_MAX_ROWS`
  before returning a partial file.
- Overdue, paid-off, and wallet reconciliation jobs use MongoDB leases, durable
  `_id` checkpoints, bounded batches/runs, a dedicated Celery queue, late
  acknowledgement, worker-loss rejection, and soft/hard time limits. Failed
  financial records are not skipped into a lossy dead-letter path: the durable
  checkpoint remains before the failure so the next scheduled run retries it.

Release evidence: query-plan assertions, large-fixture tests, overlapping-worker
tests, and representative load/latency measurements.

### 6. Privacy, notification durability, and observability

**Status: Partial — production blocker for regulated financial data**

- Add loan applications, schedules, and payments to customer account export
  with explicit bounds/truncation and safe decryption.
- Classify every loan field and extend versioned encryption to sensitive fields
  currently stored in plaintext, including application purpose/AI
  recommendation and provider/blockchain failure detail where retention is
  justified. Add dry-run inventory, rotation, and strict verification tooling.
- Approve retention/legal-hold/anonymization rules. Financial records may need
  retention instead of deletion, but that exception must be explicit and must
  pseudonymize customer linkage where legally appropriate.
- Add resumable account-lifecycle cleanup/pseudonymization status and tests.
- Move loan email/in-app deliveries to a leased, retryable outbox. Current email
  delivery is synchronous best effort after the state mutation, so failure can
  leave the customer uninformed.
- Add low-cardinality request, transition, payment, disbursement, overdue,
  reconciliation, queue/backlog, oldest-age, audit-failure, and blockchain/RPC
  metrics.
- Add Grafana dashboards and Prometheus alerts for failure ratio, latency,
  pending age, stuck disbursement, reconciliation drift, overdue-job silence,
  and audit/notification backlog.

Release evidence: export/deletion/hold tests, notification crash/replay tests,
Prometheus rule tests, a healthy dashboard, and delivered test alerts.

## Remediation Plan

The stages below are the implementation order for taking Loans from its current
partial state to production approval. They are based on dependency and risk,
not an arbitrary stage count.

### Stage 1 — Authorization and public response contract

**Status: Complete — 2026-08-15**

- Enforce officer assignment scope on blockchain-status reads.
- Introduce separate customer, officer, and administrator blockchain response
  serializers.
- Remove internal transaction details, idempotency keys, provider exceptions,
  raw errors, and unsafe disbursement failure data from public responses.
- Return stable, correlated error codes and make blockchain query validation
  strict.
- Add authenticated owner, role, permission, cross-officer, and disclosure
  regressions.

**Exit condition:** every loan read/mutation has an explicit role, permission,
owner/assignment, and response-field contract, and the Stage 1 security suite
passes. This exit condition is met by the 17 focused Stage 1 regressions and the
477-test broader Loans selection. Deployment-gated blockchain behavior remains
part of Stage 6, not a Stage 1 application-code gap.

### Stage 2 — Atomic lifecycle and financial mutation correctness

**Status: Implemented locally — real-Mongo execution pending**

- Make approval/rejection, submission/resubmission, assignment/reassignment,
  missing-document requests, and internal-note appends expected-state atomic.
- Add immutable transition IDs for audit, notification, and blockchain
  reconciliation.
- Correct the duplicate wallet rebroadcast-counter update.
- Prove one-winner concurrency and repeatable crash recovery against isolated
  real MongoDB.

**Exit condition:** concurrent decisions cannot overwrite one another, accepted
notes are not lost, financial operations execute once, and every interrupted
mutation has a tested reconciliation path. Local evidence passes; execute
`tests/test_loans_stage2_real_mongo.py` against an approved isolated database to
close the remaining Stage 2 release-evidence condition.

### Stage 3 — Settlement scope and approved lending policies

**Status: Complete in application code — 2026-08-15**

- Selected the safe initial cash/check baseline with optional feature-gated
  wallet support.
- Limited API, model, validator, and on-chain settlement enums to cash, check,
  and feature-gated wallet, and exposed a versioned client settlement policy.
- Added optimistic concurrency and explicit policy metadata to penalty apply and
  waive operations.
- Implemented atomic carry-forward of collected waiver credit and rejection of
  waivers that would need an unsupported external refund.
- Made payoff basis, exact amount, timestamp, rounding, and policy version
  explicit; documented wallet verification-time valuation and quote age.
- Kept reversal/refund/chargeback/restructure/write-off states unavailable until
  their own approved workflow exists.

**Exit condition:** met for the exposed application-code baseline. Every
available rail has a complete implementation path; unavailable rails cannot
mutate financial state. Institutional policy approval and optional deployed
wallet evidence remain release conditions, not missing Stage 3 code.

### Stage 4 — MongoDB schema and bounded execution

**Status: Implemented locally — real-Mongo and load execution pending**

- Added inventory and dry-run-first backfill commands.
- Added validator and compound-index manifests; duplicate inventory must be
  reviewed and reconciled before installation on a deployment copy.
- Replaced ciphertext regex search with keyed exact blind indexes.
- Bounded product, officer, payment, search, export, overdue, paid-off, and
  wallet reconciliation paths.
- Added isolated real-Mongo validator/index/query-plan proof and local
  large-fixture/overlapping-worker coverage. Target execution remains pending.

**Exit condition:** target-volume operations have deterministic bounds and
query plans, validators reject invalid data, and scheduled work is batched,
leased, checkpointed, and safe under overlap.

The application-code exit condition is met by 11 focused local regressions.
Final closure requires reviewing inventory/backfill against a deployment copy,
then running the isolated Stage 4 real-Mongo suite and representative
multi-worker/load evidence. No production database mutation was performed as
part of this stage.

### Stage 5 — Privacy lifecycle, notification durability, and observability

**Status: Not started**

- Add bounded loan data to customer export and implement the approved
  retention, legal-hold, pseudonymization, and account-lifecycle behavior.
- Complete sensitive-field classification, encryption, inventory, backfill,
  key rotation, and verification.
- Replace best-effort loan delivery with a leased, retryable notification
  outbox.
- Add loan request, transition, settlement, reconciliation, queue, failure, and
  age metrics plus Prometheus alerts and a Grafana dashboard.

**Exit condition:** privacy operations are resumable and tested, failed
notifications recover without duplicating state changes, and operators can
detect and diagnose every critical loan backlog/failure mode.

### Stage 6 — Real-environment release validation

**Status: Pending — begins after Stages 1–5 and deployment-topology selection**

- Run reviewed inventory/backfill, backup/restore, validators, indexes, and
  real-Mongo query plans against a deployment copy.
- Prove multi-worker Redis/Celery leases, retries, queue routing, Beat overlap,
  worker loss, and backlog recovery.
- If enabled, validate deployed contracts, signer roles, confirmations, reorgs,
  nonce contention, RPC failure, event replay, and chain reconciliation.
- Test authenticated APIs, large exports, and stable errors through HTTPS.
- Rehearse key rotation, incident response, rollback, and alert delivery; then
  run the full suite and end-to-end release smoke flows.

**Exit condition:** the release checklist has recorded evidence from the actual
deployment topology and contains no unresolved production blocker.

## API and Client Impact Notes

- Clients must send `Idempotency-Key` for disbursement, officer payment, and
  payoff settlement operations.
- Treat HTTP 409 as an idempotency/state conflict; never silently generate a new
  key after an uncertain financial response without first retrieving state.
- Application status and disbursement status are separate. A wallet
  disbursement may remain `approved` + `pending` until execution is proven.
- The `pending` application filter is a derived alias for `submitted` and
  `under_review`; it is not a stored application status.
- Read `settlement_policy` from product responses. Do not hard-code or display
  methods outside the returned cash/check and optional wallet values.
- Wallet clients must wait for the configured confirmation threshold and should
  display the server response rather than independently valuing ETH.
- `written_off` and `restructured` are reserved states, not available workflows.

## Operational Notes

- `init_db.py` is state-changing and must be run only after inventory, duplicate
  review, backup, and explicit approval.
- Run Daphne, Redis, Celery worker, and Celery Beat as separately supervised
  processes. Wallet tasks require the configured `blockchain` queue.
- Keep the backend wallet private key in a secret store; never place it in logs,
  API responses, repository files, or client applications.
- The settlement enums are now `Cash=0`, `Check=1`, and `Wallet=2`. Deploy a
  fresh contract set for this contract version; do not upgrade a chain that
  already contains settlement records without an explicitly reviewed data/state
  migration.
- Preserve prior field-encryption keys until all loan ciphertext and blind
  indexes have been rotated and verified.
- Monitor pending payments/disbursements by age, not only count.
- A successful off-chain mutation does not imply successful on-chain sync; use
  reconciliation state and alerting as separate evidence.

## Review Boundaries

This review inspected repository code and documentation and ran local automated
tests. It did not read `.env`, customer uploads, ML data, private keys, cloud
credentials, backups, logs, `dump.rdb`, or production data. It did not initialize
or mutate MongoDB, deploy contracts, send blockchain transactions, run Celery
operations, or call external payment providers.

The review does not approve lending, pricing, collections, write-off, privacy,
or regulatory policy. Those require authorized business, accounting, legal,
privacy, and security review for the deployment jurisdiction.

## Release Gate

After Stages 1–5 are complete, Stage 6 production approval requires:

1. run inventory and dry-run backfill against a deployment copy;
2. take and restore an encrypted backup before applying changes;
3. apply validators/indexes with reviewed duplicate reconciliation;
4. repeat inventory immediately before production index work;
5. run the isolated real-Mongo suite and inspect query plans;
6. prove Redis/Celery queues, leases, retries, Beat singleton/overlap behavior,
   and worker-loss recovery across multiple workers;
7. if blockchain is enabled, verify deployed contracts, roles, wallet funding,
   chain ID, RPC failover, confirmations, reorg handling, nonce contention,
   event replay, and reconciliation on the intended network;
8. test authenticated APIs and large exports through the deployed HTTPS proxy;
9. verify key provisioning/rotation, secret isolation, log redaction, backup/
   restore, incident response, and rollback;
10. generate representative traffic and prove metrics, dashboards, and alert
    delivery; and
11. run the full repository suite plus an end-to-end loan lifecycle smoke test.

If the first release deliberately excludes blockchain, set
`BLOCKCHAIN_ENABLED=False`, expose only cash/check operations, disable wallet in
every client, and document that approved baseline as a product decision.

## Related Documentation and Code

- `loans/urls.py`
- `loans/models/`
- `loans/serializers/loan_serializers.py`
- `loans/services/`
- `loans/views/customer/`
- `loans/views/officer/`
- `loans/views/admin/`
- `loans/tasks.py`
- `loans/blockchain/`
- `config/celery.py`
- `init_db.py`
- `docs/LOANS_TESTING_GUIDE.md`
