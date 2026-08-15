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
expose 46 HTTP method/path operations across customer, officer, and
administrator roles.

The most important blockers are not cosmetic:

1. The officer blockchain-status endpoint does not apply application assignment
   scope, so an officer who knows another application ID can retrieve its
   blockchain status.
2. Customer and officer blockchain responses serialize internal transaction
   fields, and customer application/error responses can expose stored provider
   exception text.
3. Approval, rejection, assignment, reassignment, submission, resubmission, and
   internal-note updates use read-modify-save behavior rather than guarded
   atomic transitions. Concurrent decisions or edits can overwrite each other.
4. GCash and bank-transfer payment/disbursement records can enter pending state,
   but no provider callback, verification, settlement, expiry, or operator
   resolution workflow completes them.
5. Loan collections have indexes but no MongoDB JSON-schema validators,
   inventory/backfill commands, or loan-specific real-Mongo integration suite.
6. Scheduled repayment scans and several payment/application query paths are
   unbounded or materialize large ID sets. Encrypted payment references cannot
   be searched with the current MongoDB regex query.
7. Loan data is not included in customer account export and has no documented
   retention, legal-hold, anonymization, or deletion policy integration.
8. Encryption covers selected free-text fields, but application purpose/AI
   recommendation and several provider/blockchain failure-detail fields remain
   plaintext in their domain collections.
9. Loans has one audit-failure counter but no complete loan/payment/disbursement
   metrics, dashboards, alerts, or bounded backlog gauges.

Current automated baseline:

- Loan/blockchain-related selection: **460 passed, 9 skipped, 713 deselected**
  on 2026-08-15.
- The nine skips are real-Ganache integration cases and are not production-chain
  evidence.
- The selection includes model, API, permission, qualification, payment,
  disbursement, repayment, export, audit, task, wallet-recovery, blockchain
  service, event-listener, and saga tests.
- No loan-specific real-Mongo validator, transaction, uniqueness, or query-plan
  suite was found.

## Current Status

| Area | Status | Summary |
| --- | --- | --- |
| Product catalog | Implemented; pagination gap | Admin CRUD and soft deletion exist; customer listing silently caps results at 200. |
| Qualification | Implemented | Rules enforce profile/document/product readiness; AI is advisory with deterministic fallback. |
| Applications | Partial | Owner-scoped create/list/detail/update/resubmit flows exist; several state changes are not atomic. |
| Assignment | Partial | Admin assign/reassign and workload views exist; auto-assignment is unused and concurrent assignment is not guarded. |
| Officer review | Partial | Assigned-scope review, notes, and missing-document requests exist; concurrent decisions/notes can overwrite. |
| Cash/check disbursement | Implemented with remaining hardening | Idempotency and atomic disbursement claims exist; public error minimization and deployment concurrency proof remain. |
| Wallet disbursement/payment | Partial; deployment-gated | Confirmation, durable retries, leases, exact rebroadcast, and recovery exist; real-chain and multi-worker evidence remain. |
| GCash/bank rails | Not complete | Requests are recorded as pending but no settlement lifecycle completes them. |
| Repayment accounting | Implemented with policy gaps | Centavo math, optimistic schedule updates, penalties, and payoff exist; waiver credit and reversal/write-off policies remain. |
| Retrieval/search/export | Partial | Role-scoped pagination and streaming audited exports exist; export totals and some supporting queries are unbounded, and encrypted-reference search is ineffective. |
| Security and privacy | Partial | JWT, role/permission checks, assignment scope, encryption, idempotency, and audit exist; one scope defect, response leakage, and lifecycle gaps remain. |
| MongoDB schema/indexes | Partial | Index declarations exist; validators, safe backfill tooling, and real-Mongo proof do not. |
| Background processing | Partial | Celery/Beat jobs and blockchain recovery exist; some scans are unbounded and lack leases/checkpoints. |
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
| `GET products/` | Active product catalog | Implemented; 200-row cap is not paginated |
| `GET products/<product_id>/` | Active product detail | Implemented |
| `POST pre-qualify/` | Rules, readiness, score, recommendation | Implemented |
| `POST apply/` | Validate readiness and submit application | Implemented; submission transition is not guarded |
| `GET applications/` | Owner-scoped filtered pagination | Implemented |
| `GET/PUT applications/<application_id>/` | Owner detail/draft update | Implemented |
| `GET applications/<application_id>/schedule/` | Owner repayment schedule | Implemented |
| `GET/POST applications/<application_id>/payments/` | History / external payment claim | Partial; POST only creates GCash/bank pending claims |
| `POST applications/<application_id>/resubmit/` | Rejected application back to draft | Implemented; non-atomic |
| `GET applications/<application_id>/feedback/` | Owner rejection feedback | Implemented |
| `POST applications/<application_id>/set-disbursement-method/` | Borrower preference | Implemented; external rails remain incomplete |
| `GET applications/<application_id>/blockchain/` | Owner chain status | Partial; response exposes internal transaction fields |
| `POST applications/<application_id>/wallet-payment/` | Verify confirmed ETH transfer and post | Partial; real-chain proof and public-error hardening remain |
| `GET system-wallet/` | Public payment wallet metadata for customer | Implemented when blockchain is configured |

### Administrator operations

| Method and route | Required boundary | Status |
| --- | --- | --- |
| `GET/POST admin/products/` | Admin + `manage_system` | Implemented |
| `GET/PUT/DELETE admin/products/<product_id>/` | Admin + `manage_system` | Implemented; delete is soft deactivation |
| `POST admin/applications/<application_id>/assign/` | Admin + `manage_loan_officers` | Partial; not concurrency guarded |
| `POST admin/applications/<application_id>/reassign/` | Admin + `manage_loan_officers` | Partial; not concurrency guarded |
| `GET admin/officers/workload/` | Admin + `manage_loan_officers` | Implemented; active-officer source is materialized before paging |
| `GET admin/blockchain/transactions/` | Admin + `view_logs` | Partial; invalid filters/dates are ignored or clamped and free-form internals are returned |

### Officer and administrator operations

The shared officer mixin permits a loan officer or administrator. Loan officers
must normally be assigned to the application; administrators are not
assignment-limited.

| Method and route | Current behavior | Status |
| --- | --- | --- |
| `GET officer/applications/` | Filtered, paginated assigned queue | Implemented with bounded 500-candidate search joins |
| `GET officer/applications/<application_id>/` | Scoped detail | Implemented |
| `POST .../notes/` | Append bounded internal note history | Partial; concurrent appends can be lost |
| `POST .../request-missing-documents/` | Record request and notify customer | Partial; state write is non-atomic and email is best effort |
| `PUT .../review/` | Approve or reject | Partial; decision transition is non-atomic |
| `POST .../disburse/` | Cash/check/wallet/external disbursement initiation | Partial by rail |
| `GET/POST .../wallet-disbursement/` | Inspect/reconcile/retry/safely cancel | Implemented; deployment-gated |
| `POST officer/payments/` | Post cash/check payment | Implemented with idempotency and centavo allocation |
| `GET officer/payments/recent/` | Recent accessible payments | Partial; assigned application IDs are materialized without a bound |
| `GET officer/payments/search/` | Filtered payment list and summary | Partial; unbounded supporting queries and ineffective ciphertext regex search |
| `GET officer/active-loans/` | Scoped active-loan lookup | Implemented; requires search or customer ID |
| `GET .../schedule/` | Scoped schedule detail | Implemented |
| `GET .../payments/` | Scoped payment history | Implemented |
| `POST .../penalties/apply/` | Apply late penalty | Implemented with policy assumptions |
| `POST .../penalties/waive/` | Waive penalty | Partial; previously paid penalty becomes recorded credit with no disposition workflow |
| `GET/POST .../payoff/` | Quote / settle early payoff | Implemented |
| `GET .../blockchain/` | Chain transaction/audit status | **Security blocker: assignment scope is missing** |
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
- GCash/bank-transfer initiation is deliberately pending rather than falsely
  marked executed.

### Repayment and accounting

- Money allocation uses integer centavos with explicit conversion helpers.
- Schedule generation allocates principal remainders deterministically and
  calculates monthly interest using product terms.
- Payment keys and external-reference fingerprints have unique indexes.
- Schedule mutation uses an accounting version and compare-and-swap update.
- Payment tokens make schedule application repeatable after partial failures.
- Overpayment above the selected installment balance is rejected.
- Paid schedules close the application as `completed`/`paid_off`.
- Penalty apply/waive actions and payoff quotation/settlement are implemented.
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

**Status: Partial — production blocker**

1. Apply `check_application_scope(..., allow_unassigned=False)` to officer
   blockchain status before returning any data.
2. Add customer/officer blockchain serializers that return only approved
   status, transaction hash, block/confirmation state, action, and safe dates.
   Do not expose idempotency keys, free-form details, contract internals, or raw
   exception fields.
3. Remove `disbursement_error` from customer application responses or map it to
   a stable customer-safe reason.
4. Replace wallet verification and disbursement responses containing
   `str(exc)` with stable public codes; retain correlated detail in protected
   logs/audit only.
5. Make admin blockchain query validation strict and bound free-form response
   data according to the `view_logs` contract.

Release evidence: cross-officer negative tests, customer disclosure tests,
stable-error tests, and authenticated route tests.

### 2. Atomic lifecycle and financial correctness

**Status: Partial — production blocker**

1. Replace approve/reject with one guarded `find_one_and_update` that requires
   the expected status and current assignee. Exactly one concurrent decision
   must win.
2. Guard submission, resubmission, missing-document requests, assignment, and
   reassignment with expected-state selectors and stable conflict responses.
3. Append notes atomically with `$push`/`$slice`, rather than saving a stale
   application copy.
4. Add immutable transition/event IDs so mutation, audit, notification, and
   blockchain synchronization can reconcile one logical action.
5. Remove the duplicate `record_eth_rebroadcast()` call in wallet recovery and
   test the rebroadcast counter.
6. Add concurrency tests for review, assignment, notes, disbursement, payment,
   payoff, and schedule completion against real MongoDB.

Release evidence: one-winner concurrent transition tests and crash/replay tests
at every mutation boundary.

### 3. Settlement rails and business-policy decisions

**Status: Partial — required unless release scope is explicitly cash/check only**

- Either disable GCash/bank choices in server responses and clients, or
  implement provider-bound initiation, signed callbacks/webhooks, reference
  verification, expiry, retries, reconciliation, manual review, and executed/
  failed/cancelled state transitions.
- Define reversal, refund, correction, chargeback, cancellation, restructuring,
  write-off, and recovery workflows before activating the reserved statuses.
- Decide how `waiver_credit_centavos` is refunded, carried forward, or applied;
  do not leave value as an informational field only.
- Approve penalty rates/grace rules, payoff interest policy, rounding, timezone,
  non-business-day behavior, and accounting/audit evidence with the institution.
- Define ETH quote lifetime and whether payment value uses a locked quote or the
  verification-time rate. Current disbursement stores its conversion before
  sending, while customer payment uses the verification-time rate.

Release evidence: approved policy matrix, provider sandbox certification,
callback replay/signature tests, reconciliation, and ledger balancing.

### 4. MongoDB schema, inventory, and query correctness

**Status: Partial — production blocker**

1. Add count-only inventory and dry-run-first backfill commands for legacy IDs,
   statuses, money fields, encryption metadata, payment keys, and schedule
   accounting versions.
2. Reconcile duplicates before installing unique indexes.
3. Add JSON-schema validators for all primary loan collections and blockchain
   transaction records, including encrypted-field shapes.
4. Add loan-specific real-Mongo tests for validators, indexes, unique claims,
   atomic transitions, centavo updates, transactions where supported, and query
   plans at representative volume.
5. Add deterministic compound indexes for the actual owner/officer/status/date
   list and scheduled-job queries.
6. Replace regex search on encrypted payment `reference` with a normalized keyed
   blind index or remove reference search from the contract.

Release evidence: reviewed inventory, approved backup, applied backfill,
validator/index manifest, clean post-inventory, and target query plans.

### 5. Bounded queries and background jobs

**Status: Partial — required before production-scale traffic**

- Paginate the customer product list rather than silently returning at most 200.
- Replace officer payment queries that materialize every assigned/disbursed loan
  ID with indexed aggregation or direct assignment metadata on payments.
- Make `payment_status=on_time|late` database-computable or use a bounded
  materialized classification; it currently scans all matches in Python.
- Replace 500-record search candidate joins with indexed search/blind indexes or
  explicit truncation metadata.
- Page officer workload from MongoDB rather than loading all active officers.
- Enforce an approved maximum/snapshot contract for synchronous schedule
  exports or move large exports to a leased asynchronous job. Avoid the current
  full pre-count plus second full streaming scan.
- Batch and lease overdue, paid-off, and wallet reconciliation jobs. Persist a
  checkpoint and prevent overlapping Beat runs.
- Configure queue routing, time limits, batch sizes, and retry/dead-letter
  behavior for all loan tasks.

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
not an arbitrary stage count. No remediation stage was implemented during this
documentation-only audit.

### Stage 1 — Authorization and public response contract

**Status: Not started**

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
passes.

### Stage 2 — Atomic lifecycle and financial mutation correctness

**Status: Not started**

- Make approval/rejection, submission/resubmission, assignment/reassignment,
  missing-document requests, and internal-note appends expected-state atomic.
- Add immutable transition IDs for audit, notification, and blockchain
  reconciliation.
- Correct the duplicate wallet rebroadcast-counter update.
- Prove one-winner concurrency and repeatable crash recovery against isolated
  real MongoDB.

**Exit condition:** concurrent decisions cannot overwrite one another, accepted
notes are not lost, financial operations execute once, and every interrupted
mutation has a tested reconciliation path.

### Stage 3 — Settlement scope and approved lending policies

**Status: Not started; product and policy decisions required**

- Choose the initial production rail scope. Either complete GCash/bank provider
  settlement or disable those choices across API responses and clients.
- Implement any approved callback, verification, expiry, retry, reconciliation,
  and operator-review workflow.
- Approve and implement the treatment of waiver credits, reversals, refunds,
  corrections, chargebacks, cancellation, restructuring, and write-off.
- Approve penalty, payoff, rounding, calendar, and ETH quote policies.

**Exit condition:** every exposed payment/disbursement/status choice has a
complete settlement lifecycle and an owner-approved accounting policy.

### Stage 4 — MongoDB schema and bounded execution

**Status: Not started**

- Add inventory and dry-run-first backfill commands.
- Reconcile duplicate/legacy records, then add loan collection validators and
  the compound indexes required by production queries.
- Replace ciphertext regex search with blind indexes or remove the unsupported
  search contract.
- Bound product, officer, payment, search, export, overdue, paid-off, and wallet
  reconciliation paths.
- Add isolated real-Mongo validator, index, atomicity, and query-plan tests plus
  large-fixture/overlapping-worker coverage.

**Exit condition:** target-volume operations have deterministic bounds and
query plans, validators reject invalid data, and scheduled work is batched,
leased, checkpointed, and safe under overlap.

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

- Clients must send `Idempotency-Key` for disbursement, officer payment, customer
  external-payment claim, and payoff settlement operations.
- Treat HTTP 409 as an idempotency/state conflict; never silently generate a new
  key after an uncertain financial response without first retrieving state.
- Application status and disbursement status are separate. A wallet or external
  disbursement may remain `approved` + `pending` until execution is proven.
- The `pending` application filter is a derived alias for `submitted` and
  `under_review`; it is not a stored application status.
- Clients must not present GCash/bank transfer as settled merely because the API
  accepted a claim.
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

If the first release deliberately excludes blockchain and external providers,
set `BLOCKCHAIN_ENABLED=False`, expose only cash/check operations, remove or
disable wallet/GCash/bank choices in every client, and document that approved
baseline as a product decision.

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
