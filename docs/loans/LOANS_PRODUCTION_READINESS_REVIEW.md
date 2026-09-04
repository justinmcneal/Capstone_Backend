# Loans Module Documentation and Status

Last updated: 2026-08-28

## Overview

The Loans module implements the MSME Pathways lending lifecycle: product
catalogs, customer qualification and applications, administrator assignment,
loan-officer review, disbursement, repayment schedules, cash/check payment
posting, penalties, early payoff, customer and staff retrieval/export, and
optional Ethereum wallet settlement and synchronization.

The approved non-blockchain baseline supports cash and check disbursement and
repayment. Wallet-to-wallet settlement is exposed only when blockchain is
explicitly enabled and its deployment has been validated. GCash, bank transfer,
and other unimplemented settlement rails are not accepted, advertised, stored,
or represented in the smart-contract settlement enum.

The module exposes 39 registered paths and 45 HTTP method/path operations under
`/api/loans/` across customer, administrator, and loan-officer roles. It uses
PyMongo directly; Django ORM migrations are not part of its persistence
lifecycle. MongoDB indexes and validators are installed through the project
bootstrap after inventory and duplicate review.

## Current Status

**Module implementation status: Complete for the approved cash/check baseline**

**Optional blockchain status: Implemented in code; deployment-gated**

**Production deployment status: Ready for production-environment validation,
not yet production-approved**

Product, qualification, application, assignment, review, cash/check
disbursement, centavo-based repayment, payoff, privacy, notification durability,
audit integration, bounded execution, monitoring, and release tooling are
implemented. Remaining work consists of target-environment evidence and
external business/legal approval, rather than another application-code stage.

| Area | Status | Summary |
| --- | --- | --- |
| Product catalog | Implemented | Administrator CRUD/soft deletion and bounded customer listing are available. |
| Qualification | Implemented | Deterministic readiness rules enforce profile, document, and product requirements; AI output is advisory. |
| Applications | Implemented; real-Mongo proof pending | Owner-scoped creation, retrieval, draft update, submission, rejection feedback, and resubmission use guarded transitions. |
| Assignment and review | Implemented; real-Mongo proof pending | Expected-state/assignee transitions, scoped officer access, atomic notes, document requests, and one-winner decisions are present. |
| Cash/check settlement | Implemented | Idempotent disbursement, schedule generation, payment allocation, penalties, waiver carry-forward, and exact payoff are covered locally. |
| Wallet settlement | Implemented; deployment-gated | Receipt verification, leases, exact rebroadcast, retries, reconciliation, recovery, and chain synchronization exist. |
| Persistence and privacy | Implemented; target proof/policy approval pending | Validators, indexes, inventory, backfill, encryption, retention, legal hold, export, and pseudonymization are available. |
| Notifications and audit | Implemented | Immutable transition IDs, Analytics audit events, and an encrypted leased notification outbox protect cross-domain side effects. |
| Background processing | Implemented; deployment proof pending | Bounded leased jobs, checkpoints, late acknowledgement, queue routing, and retry behavior are present. |
| Observability | Implemented; deployment proof pending | Metrics, Prometheus rules/tests, a Grafana dashboard, integrity/backlog gauges, and a fail-closed release check are available. |
| Local automated validation | Passing | Loans/blockchain selection: 533 passed, 20 opt-in tests skipped, and 790 deselected; full suite: 1,368 passed and 55 opt-in tests skipped on 2026-08-28. |
| Deployment validation | Pending | Real MongoDB, production Redis/Celery, HTTPS/load, monitoring/alerts, recovery, policy approval, and optional chain evidence remain. |

## Module Responsibilities

### Loan products and eligibility

- Let administrators create, update, retrieve, list, and soft-deactivate loan
  products under the `manage_system` permission.
- Validate product amount, term, interest, income, business-age/type, document,
  and settlement-policy fields.
- Publish a client-safe, versioned settlement policy with each product.
- Evaluate customer profile and approved current-document readiness before
  qualification or submission.
- Return eligibility, risk category, missing requirements, recommendation, and
  product/baseline scope. AI qualification is advisory and has a deterministic
  rules fallback; it does not approve a loan.

### Customer application lifecycle

- Create and submit owner-scoped applications after readiness validation.
- List and retrieve only the authenticated customer's applications.
- Allow edits only while an application is in the permitted draft state.
- Provide rejection feedback and guarded rejected-to-draft resubmission.
- Let customers select only settlement methods currently exposed by the product
  and runtime policy.
- Expose owner-scoped repayment schedules, payment history, and safe blockchain
  status.

### Assignment and officer review

- Let authorized administrators assign and reassign active loan officers using
  expected-status and expected-assignee guards.
- Return bounded officer workload and queue information.
- Restrict loan officers to assigned applications while allowing administrators
  through the explicit officer-or-administrator boundary.
- Append encrypted internal-note history with bounded compare-and-set retry and
  a latest-100-entry limit.
- Atomically record missing-document requests and their history.
- Approve or reject through one-winner expected-state transitions.
- Correlate lifecycle state, audit, notification, and optional blockchain work
  with immutable `loan_evt_*` transition identifiers.

### Disbursement and repayment accounting

- Require actor-scoped idempotency keys for disbursement, payment, and payoff
  settlement operations.
- Atomically claim an approved application for one disbursement attempt.
- Complete cash/check disbursement synchronously and generate the repayment
  schedule.
- Perform monetary allocation in integer Philippine centavos with explicit
  conversion and half-up rounding.
- Allocate principal remainders deterministically and calculate interest from
  product terms.
- Apply payments using accounting-version compare-and-swap and repeatable
  payment tokens.
- Prevent overpayment beyond the selected installment balance.
- Apply or waive explicit officer-entered penalties under the same accounting
  concurrency guard.
- Carry a collected waived-penalty credit into later unpaid installments;
  reject a waiver that would require an unsupported external refund.
- Quote and settle early payoff using the published exact scheduled-balance
  basis, timestamp, rounding, and policy version.
- Close fully paid schedules and applications as `paid_off`/`completed`.

### Optional blockchain settlement

- Verify wallet payments by receipt success, recipient, sender, transferred
  value, minimum confirmations, and transaction uniqueness before posting.
- Persist signed wallet-disbursement payloads in encrypted form and rebroadcast
  the exact prepared payload after recoverable failure.
- Use leases, late acknowledgement, retry limits, receipt reconciliation, nonce
  serialization, step-level saga progress, and operator recovery actions.
- Synchronize application, approval, rejection, disbursement, schedule, payment,
  overdue, penalty, consent, and audit events through ABI-backed contracts.
- Poll chain audit events and reconcile off-chain/on-chain domain state.
- Keep all blockchain work disabled for the ordinary cash/check baseline when
  `BLOCKCHAIN_ENABLED=False`.

### Retrieval, search, and export

- Provide bounded, filtered customer and officer application lists.
- Publish explicit `search_truncated` metadata when supporting customer/product
  search reaches its configured cap.
- Search exact payment references using keyed HMAC blind indexes rather than
  ciphertext regular expressions.
- Return recent officer-accessible payments with a maximum 50-row result.
- Require a search term or customer ID for active-loan lookup.
- Export scoped schedules as CSV or JSON with spreadsheet-formula protection
  and a configurable synchronous preflight ceiling.
- Include bounded, allowlisted loan applications, schedules, and payments in
  customer account export with totals and truncation metadata.

### Privacy, audit, notifications, and operations

- Encrypt purpose, AI recommendation, legal-hold reason, provider/disbursement
  errors, payment failure/synchronization details, raw wallet payloads,
  blockchain failure text, and recovery-history reasons.
- Assign versioned retention metadata to applications, preserve legal holds,
  delete due terminal records in bounded batches, and pseudonymize retained
  customer links during account deletion.
- Write loan-domain events through the shared Analytics audit boundary.
- Place customer/staff delivery intents in an encrypted, unique, leased outbox
  before publication so broker/email failure remains retryable without
  repeating financial mutation.
- Export low-cardinality request, lifecycle, settlement, delivery, job,
  integrity, backlog, and oldest-age metrics.

## API Status

Every path below is relative to `/api/loans/` and requires a valid authenticated
session. Detailed payload examples are maintained in
`docs/LOANS_TESTING_GUIDE.md`.

### Customer API

| Method and path | Status | Contract |
| --- | --- | --- |
| `GET products/` | Implemented | Bounded active-product catalog with settlement-policy metadata. |
| `GET products/<product_id>/` | Implemented | Active product detail. |
| `POST pre-qualify/` | Implemented | Owner readiness, eligibility, risk, missing requirements, and advisory recommendation. |
| `POST apply/` | Implemented | Validates prerequisites and submits an owner application with an immutable transition ID. |
| `GET applications/` | Implemented | Owner-scoped filtered pagination. |
| `GET applications/<application_id>/` | Implemented | Owner-scoped detail. |
| `PUT applications/<application_id>/` | Implemented | Owner draft update only. |
| `GET applications/<application_id>/schedule/` | Implemented | Owner schedule for a disbursed/closed lifecycle. |
| `GET applications/<application_id>/payments/` | Implemented | Read-only owner payment history. |
| `POST applications/<application_id>/resubmit/` | Implemented | Guarded rejected-to-draft transition. |
| `GET applications/<application_id>/feedback/` | Implemented | Owner rejection feedback. |
| `POST applications/<application_id>/set-disbursement-method/` | Implemented | Cash/check, plus wallet only when enabled and allowed. |
| `GET applications/<application_id>/blockchain/` | Implemented; deployment-gated | Owner-safe chain status allowlist. |
| `POST applications/<application_id>/wallet-payment/` | Implemented; deployment-gated | Verifies confirmed ETH transfer and posts a unique payment. |
| `GET system-wallet/` | Implemented; deployment-gated | Customer-safe payment-wallet metadata when blockchain is configured. |

### Administrator API

| Method and path | Permission | Status |
| --- | --- | --- |
| `GET admin/products/` | `manage_system` | Implemented bounded product management list. |
| `POST admin/products/` | `manage_system` | Implemented product creation. |
| `GET admin/products/<product_id>/` | `manage_system` | Implemented product detail. |
| `PUT admin/products/<product_id>/` | `manage_system` | Implemented guarded product update. |
| `DELETE admin/products/<product_id>/` | `manage_system` | Implemented soft deactivation. |
| `POST admin/applications/<application_id>/assign/` | `manage_loan_officers` | Implemented expected-state/assignee transition. |
| `POST admin/applications/<application_id>/reassign/` | `manage_loan_officers` | Implemented expected-assignee transition. |
| `GET admin/officers/workload/` | `manage_loan_officers` | Implemented database pagination and aggregated counts. |
| `GET admin/blockchain/transactions/` | `view_logs` | Implemented strict filters and administrator-safe allowlist; deployment-gated. |

### Loan-officer and administrator API

Loan officers must be assigned to the application unless the endpoint has its
own scoped list/query contract. Administrators using this shared boundary are
not assignment-limited.

| Method and path | Status | Contract |
| --- | --- | --- |
| `GET officer/applications/` | Implemented | Assigned officer queue or broader administrator view, with bounded search/pagination. |
| `GET officer/applications/counts/` | Implemented | Role-scoped application status counts. |
| `GET officer/applications/<application_id>/` | Implemented | Scoped detail. |
| `POST officer/applications/<application_id>/notes/` | Implemented | Bounded encrypted note append with optimistic retry. |
| `POST officer/applications/<application_id>/request-missing-documents/` | Implemented | Atomic request/history plus durable customer delivery. |
| `PUT officer/applications/<application_id>/review/` | Implemented | One-winner approve/reject transition. |
| `POST officer/applications/<application_id>/disburse/` | Implemented by enabled rail | Cash/check or feature-gated wallet; requires idempotency. |
| `GET officer/applications/<application_id>/wallet-disbursement/` | Implemented; deployment-gated | Safe wallet execution/recovery status. |
| `POST officer/applications/<application_id>/wallet-disbursement/` | Implemented; deployment-gated | Reconcile, retry, or safely cancel supported wallet states. |
| `POST officer/payments/` | Implemented | Idempotent cash/check posting with centavo allocation. |
| `GET officer/payments/recent/` | Implemented | At most 50 recent accessible payments. |
| `GET officer/payments/search/` | Implemented | Indexed scope/time filtering, exact blind-reference search, pagination, summary, and truncation metadata. |
| `GET officer/active-loans/` | Implemented | Scoped lookup requiring search or customer ID. |
| `GET officer/applications/<application_id>/schedule/` | Implemented | Scoped schedule detail. |
| `GET officer/applications/<application_id>/payments/` | Implemented | Scoped payment history. |
| `POST officer/applications/<application_id>/penalties/apply/` | Implemented | Versioned, optimistic-concurrency penalty application. |
| `POST officer/applications/<application_id>/penalties/waive/` | Implemented | Atomic carry-forward or safe rejection when a refund would be required. |
| `GET officer/applications/<application_id>/payoff/` | Implemented | Exact early-payoff quote and policy metadata. |
| `POST officer/applications/<application_id>/payoff/` | Implemented | Idempotent exact cash/check payoff settlement. |
| `GET officer/applications/<application_id>/blockchain/` | Implemented; deployment-gated | Assignment-concealed officer-safe chain status. |
| `GET officer/exchange-rate/` | Implemented; deployment-gated | Current ETH/PHP rate when blockchain/provider is available. |
| `GET officer/schedules/export/` | Implemented | Bounded, audited CSV/JSON export. |

### Common API behavior

- Customer ownership and officer assignment are derived from authenticated
  identities rather than caller-supplied owner IDs.
- Out-of-scope officer records are concealed where appropriate.
- Invalid IDs, filters, settlement rails, state transitions, money values, and
  unbounded requests return stable client errors.
- HTTP 409 represents an expected-state, accounting-version, or idempotency
  conflict; it must not be treated as permission to retry with a new key.
- Provider, RPC, database, and internal settlement errors are minimized and
  correlated without exposing raw exception text, signed transactions, private
  keys, or internal idempotency data.

## Lifecycle and Financial Policy

### Application lifecycle

The implemented lifecycle includes draft, submitted, under-review, approved,
rejected, disbursed, completed, cancelled, and the supported terminal states.
The API's `pending` filter is a derived alias for `submitted` plus
`under_review`; it is not stored as an application status.

Submission/resubmission, assignment/reassignment, missing-document requests,
review, disbursement claims, payment application, penalties, and payoff use
expected-state, expected-assignee, or accounting-version selectors. Competing
stale requests receive a stable conflict rather than overwriting the winner.

### Settlement policy

The versioned `cash-check-wallet-v1` policy exposes cash and check, and adds
wallet only when `BLOCKCHAIN_ENABLED=True`. The client must read the returned
settlement policy rather than hard-code a rail list.

The versioned `scheduled-balance-v1` accounting policy uses PHP centavos,
half-up rounding, UTC timestamps, scheduled principal/interest/penalties as the
exact payoff basis, explicit officer-entered penalties, and no automatic
calendar adjustment. Wallet payments use the verification-time exchange rate
and publish the maximum permitted cached-rate age.

Reversal, refund, correction, chargeback, restructuring, and write-off remain
reserved or unexposed workflows. They must not be enabled until their business,
accounting, API, audit, reconciliation, and recovery lifecycles are separately
approved and implemented.

## Security and Privacy Features

### Authentication and authorization

- All views use `CustomJWTAuthentication` and `IsAuthenticated`.
- Customer endpoints require the customer role and enforce ownership.
- Administrator product and assignment APIs require named permissions.
- Loan-officer operations enforce assignment scope; direct model-layer review
  guards also prevent cross-officer mutation.
- Administrators use the explicit shared officer/admin path when operationally
  permitted and preserve the assigned officer during review.
- Customer, officer, and administrator blockchain serializers have separate
  allowlists.

### Atomicity and idempotency

- Lifecycle changes use atomic expected-state selectors and immutable transition
  IDs.
- Disbursement, payment, and payoff idempotency keys have unique indexed
  persistence and actor/operation scope.
- Financial schedule updates use accounting-version compare-and-swap.
- Retry/recovery paths reuse the original transition/payment/provider identity
  rather than inventing a replacement operation.
- Wallet rebroadcast counts increment only after a successful broadcast.

### Sensitive data protection

- Declared loan, payment, wallet, recovery, provider, and legal-hold fields use
  the shared versioned field-encryption lifecycle.
- Payment-reference lookup uses normalized keyed HMAC blind indexes and supports
  configured previous keys during rotation.
- Public responses omit raw transactions, internal notes where unauthorized,
  provider errors, failure internals, idempotency values, and sensitive chain
  metadata.
- CSV export neutralizes spreadsheet formulas.
- Metrics and labels are bounded and exclude customer identifiers, payment
  references, messages, raw errors, and financial payloads.

### Privacy lifecycle and audit

- Customer export is bounded and allowlisted with totals/truncation.
- Applications use a versioned retention policy and encrypted legal-hold reason.
- Retention excludes held records and runs in bounded batches.
- Account deletion pseudonymizes retained customer links through resumable
  `loan_cleanup_status` tracking.
- Financial and privileged lifecycle events are written to the shared protected
  Analytics audit system.
- Delivery intents are encrypted, uniquely keyed, leased, and retryable.

## Persistence and Scalability

The persistence layer covers loan products, applications, repayment schedules,
payments, blockchain transactions, notification delivery records, and job
state. `loan_data_inventory` reports count-only schema/encryption/index/backfill
findings without printing sensitive values. `backfill_loan_data` is dry-run-
first, compare-and-set protected, and refuses invalid, conflicting, or
truncated runs.

Strict MongoDB validator manifests cover products, applications, schedules,
payments, and blockchain transactions. Compound indexes support customer and
officer application pages, status counts, payment scope/reference/time pages,
active schedules, pending disbursement, notification recovery, and blockchain
reconciliation. `init_db.py` fails closed if required index/validator
installation fails.

Customer products, administrator workload, customer/officer applications,
payments, supporting search, exports, and scheduled work have explicit bounds.
Overdue, paid-off, wallet, retention, delivery, and operational tasks use
bounded batches/runs; critical financial scans use MongoDB leases and durable
`_id` checkpoints so a failed record remains eligible for the next run.

## Operational Notes

### Management commands

| Command | Purpose |
| --- | --- |
| `loan_data_inventory` | Read-only count inventory for schema, encryption, duplicate, index, and backfill readiness. |
| `backfill_loan_data` | Dry-run-first encryption, centavo, scope, timing, lifecycle, and blind-index backfill. |
| `manage_loan_legal_hold` | Preview, set, or release a loan legal hold; mutation requires `--apply`. |
| `loan_release_check` | Read-only, fail-closed runtime, persistence, task, monitoring, baseline, and evidence summary. |

Before applying a backfill or running `init_db.py` against an existing target:

1. Run a complete inventory with a sufficient limit.
2. Review duplicate-sensitive keys and every invalid/truncated finding.
3. Take and restore-test an encrypted backup.
4. Run and approve the backfill dry run.
5. Apply the reviewed backfill and repeat inventory until clean.
6. Install indexes/validators and verify representative query plans.

Keep previous field-encryption keys until ciphertext, recovery entries, and
blind indexes have been rotated and verified and the rollback window closes.

### Background workers

Loan delivery, retention, overdue/lifecycle reconciliation, wallet execution,
wallet reconciliation, metrics, and blockchain synchronization use Celery.
Financial lifecycle work is routed to the dedicated `loans` queue; blockchain
work also requires its approved queue/runtime. Production must supervise Daphne,
Redis, Celery workers, and Beat separately and prove that at least two workers
can consume the Loans queue without violating leases or idempotency.

### Monitoring and incident response

Prometheus assets and the six-panel Grafana dashboard are under
`monitoring/loans/`. Monitor request failures/latency, lifecycle and settlement
outcomes, delivery failures, notification/recovery backlog count and age, job
freshness, pending financial work, and integrity findings. A pending count alone
is insufficient; age and forward progress matter.

If a financial task fails, preserve the original idempotency/transition identity
and use the supported reconciliation path. Do not manually edit prepared wallet
payloads, accounting versions, payment tokens, encrypted errors, or durable
checkpoints. A successful off-chain mutation does not prove successful on-chain
synchronization.

### Blockchain operations

Keep signer/private keys in the deployment secret store and out of logs, API
responses, source files, and clients. The contract settlement enum is
`Cash=0`, `Check=1`, and `Wallet=2`. Deploy a fresh reviewed contract set for
this version; do not upgrade a chain containing settlement records without an
approved state/data migration.

If the release excludes blockchain, configure `BLOCKCHAIN_ENABLED=False`, show
only cash/check in every client, and do not run wallet/chain workers. The release
check accepts this baseline without blockchain evidence.

## Client Notes

- Customer mobile and officer/admin web clients should consume the returned
  `settlement_policy`; do not hard-code GCash, bank transfer, wallet, or any
  other rail that the current response does not expose.
- Send a stable `Idempotency-Key` for disbursement, officer payment, and payoff
  settlement. Reuse it only for the same logical retry.
- After an uncertain financial response, retrieve the current application,
  schedule, payment, or recovery state before retrying. Never silently create a
  new idempotency key.
- Treat HTTP 409 as a lifecycle/accounting/idempotency conflict and refresh the
  current state.
- Application status and disbursement execution status are separate. An enabled
  wallet disbursement may remain `approved` with a pending execution state until
  receipt confirmation succeeds.
- Treat `pending` list filtering as submitted plus under-review, not as a stored
  lifecycle value.
- Display server-calculated PHP amounts, schedule allocation, penalty, waiver,
  and payoff terms; do not independently recompute financial values for posting.
- Wallet clients must wait for the configured confirmation threshold and use
  server-verified valuation/status.
- Respect `search_truncated`, pagination, export ceilings, and role-specific
  response fields.
- `restructured` and `written_off` may exist as reserved persistence states but
  are not available customer/staff workflows.

## Validation Evidence

Current repository evidence:

- Loans/blockchain-related selection: **533 passed, 20 opt-in tests skipped,
  and 790 deselected** on 2026-08-28.
- Full repository suite: **1,368 passed and 55 opt-in tests skipped** on
  2026-08-28.
- The skipped selection contains nine Ganache/RPC tests, six isolated atomic-
  lifecycle MongoDB tests, one isolated persistence/query-plan test, and four
  deployment probes. A skip is not deployment evidence.
- Local security, atomic lifecycle, settlement policy, persistence/scalability,
  privacy/notification/monitoring, release-check, worker recovery, and complete
  cash/check lifecycle suites pass.
- Disposable local Redis shared-state and two-worker Loans-queue probes passed;
  these prove the tooling locally, not the selected deployment topology.
- Prometheus validates the Loans rule/config assets, and rule simulations pass.

Attempted real-Mongo evidence:

- The expanded atomic-lifecycle suite was pointed at the approved configured
  target on 2026-08-27, but Atlas rejected the TLS handshake during the
  preflight ping. No temporary test database was created or mutated.
- The persistence validator/index/query-plan suite is implemented but has not
  yet been executed against an approved isolated real MongoDB target.

## Remaining Gaps and Release Conditions

No known application-code stage remains for the approved cash/check baseline.
The following conditions remain for production certification:

1. Resolve target MongoDB TLS/connectivity and run the isolated atomic lifecycle
   suite to prove one-winner transitions, note preservation, disbursement/payment
   idempotency, crash/replay recovery, payoff, and reconciliation.
2. Against a reviewed deployment copy, run complete inventory and backfill dry
   run, reconcile duplicates/findings, take and restore an encrypted backup,
   apply approved changes, install validators/indexes, and repeat inventory.
3. Run the isolated persistence suite and retain indexed query plans for the
   critical application, payment, schedule, disbursement, notification, and
   blockchain shapes at representative volume.
4. Obtain authorized business, accounting, legal, privacy, and security approval
   for lending terms, penalties, payoff, collections, and the configured
   seven-year retention/pseudonymization policy in the release jurisdiction.
5. Prove Redis/Celery queue sharing, leases, retries, Beat overlap, worker loss,
   notification recovery, and bounded job progress across deployed workers.
6. Exercise authenticated APIs, pagination/search, the maximum accepted export,
   stable errors, and representative read load through the deployed HTTPS proxy.
7. Generate representative traffic, inspect the deployed Prometheus/Grafana
   signals, and prove alert firing/delivery/recovery without sensitive labels.
8. Rehearse deployed key rotation, secret isolation, backup/restore, incident
   response, and rollback with named owners and retained evidence.
9. If blockchain is enabled, verify deployed contracts/ABIs, roles, chain ID,
   signer funding, confirmations, reorg handling, nonce contention, RPC failure,
   exact rebroadcast, event replay, and reconciliation on the intended network.
10. Run the final full suite and cash/check smoke flow on the release revision,
    then require every check and `overall` from `loan_release_check` to pass.

The current cash/check application baseline can proceed without blockchain by
keeping `BLOCKCHAIN_ENABLED=False`. Wallet readiness does not block that
baseline, but wallet must remain unavailable until its deployment conditions
are satisfied.

Until the applicable conditions pass, the accurate status is
**application-complete and awaiting production-environment validation**, not a
certified production deployment.

## Review Boundaries

This document verifies repository code, API contracts, local automated tests,
and the specifically recorded local process evidence. It does not certify
production MongoDB atomicity/query plans, Redis/Celery topology, HTTPS proxy
behavior, live alert delivery, secret management, backup restorability,
blockchain contracts/network behavior, external exchange-rate accuracy, live
customer data, or production load.

The review does not approve lending, pricing, underwriting, interest,
penalties, payoff, collections, retention, pseudonymization, restructuring,
write-off, refund, or regulatory policy. Those require authorized product,
business, accounting, legal, privacy, compliance, and security review for the
deployment jurisdiction.

Accounts owns authentication, sessions, roles, administrators, customers, and
loan officers. Profiles and Documents own readiness source records.
Notifications owns delivery channels; Analytics owns protected audit storage.
The Loans module owns financial lifecycle semantics and must not infer approval
from AI qualification or another module's display state.

This document describes backend behavior. Mobile/customer and web/officer/admin
presentation, accessibility, offline behavior, and end-to-end usability require
separate client validation.

## Related Documentation

- `docs/LOANS_TESTING_GUIDE.md` — endpoint examples, test commands, security and
  atomicity matrices, deployment probes, smoke flows, and operations runbook.
- `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` — authentication,
  permissions, account lifecycle, and shared encryption contracts.
- `docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md` — readiness/profile
  source data and customer lifecycle integration.
- `docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` — document readiness,
  lifecycle, and audit integration.
- `docs/analytics/ANALYTICS_PRODUCTION_READINESS_REVIEW.md` — protected audit
  persistence, dashboard source semantics, and operational monitoring.
- `docs/NOTIFICATIONS_PRODUCTION_READINESS_GUIDE.md` — durable delivery and
  customer/staff notification behavior.
