# Loans Testing Guide

Last updated: 2026-08-28

Scope: local automated tests, authenticated API checks, MongoDB persistence,
Redis/Celery work, and optional blockchain validation for the Loans module.

This is the canonical Loans test guide. The former separate lifecycle guide has
been merged into this document.

## What This Guide Proves

The test layers have different purposes:

| Layer | Proves | Does not prove |
| --- | --- | --- |
| Unit/service tests | Validation, calculations, state helpers, error mapping | Real MongoDB/Redis/RPC behavior |
| `mongomock` API tests | Routing, response shape, role/owner/scope behavior | MongoDB validators, transactions, query plans |
| Isolated real-Mongo tests | Unique indexes, validators, atomic competition, plans | Production volume or privileges unless using that topology |
| Redis/Celery tests | Shared leases, retries, worker-loss recovery | Correct production supervision unless deployed similarly |
| Local Ganache tests | ABI/client/contract behavior on a development chain | Production network, wallet, RPC, reorg, or gas behavior |
| Deployed smoke/load tests | Proxy, process, network, monitoring, and recovery behavior | Business/legal approval |

Passing local tests is necessary but is not production approval. Known gaps and
release conditions are tracked in `LOANS_PRODUCTION_READINESS_REVIEW.md`.

## Current Automated Baseline

The following repository selection passed on 2026-08-28:

```bash
.venv/bin/pytest -q tests \
  -k 'loan or blockchain or qualification or wallet_disbursement or repayment'
```

Current result after the Loans documentation validation: **533 passed, 20
skipped, 790 deselected**. Nine skips require Ganache/RPC, six are the
explicitly opt-in Stage 2 real-Mongo suite, one is the opt-in Stage 4 real-Mongo
suite, and four are the new Stage 6 deployment probes.

Stage 1 focused validation also passed:

```bash
.venv/bin/pytest -q tests/test_loans_stage1_security_contract.py
```

Result: **17 passed**. These cases cover cross-officer concealment, role-safe
blockchain payloads, strict administrator queries, stable public failures, and
disbursement/recovery response minimization.

The full repository regression result on 2026-08-28 is **1,368 passed and 55
skipped**. The skips remain explicitly opt-in external-service suites; they are
not counted as deployment evidence.

Stage 6 release-tooling validation:

```bash
.venv/bin/pytest -q \
  tests/test_loans_stage6_release_validation.py \
  tests/test_loans_stage6_worker_recovery.py \
  tests/test_loans_cash_check_release_smoke.py \
  tests/test_loans_stage6_deployment_integrations.py
```

Result on 2026-08-27: **10 passed, 4 skipped**. The four opt-in probes skip in
the ordinary local suite. The Redis shared-state and Celery queue probes were
then run separately against a disposable local Redis and two independent local
workers; both passed. HTTPS/load and deployed metrics remain deployment-only.

Stage 2 local validation:

```bash
.venv/bin/pytest -q tests/test_loans_stage2_atomic_lifecycle.py
```

Result: **9 passed**. This includes the direct cross-officer review guard and
administrator-review assignment-preservation regression.

Stage 3 focused policy validation:

```bash
.venv/bin/pytest -q tests/test_loans_stage3_settlement_policy.py
```

Result: **7 passed**. These cases prove the published rail scope, unsupported
method rejection, penalty concurrency, waiver-credit
carry-forward, and rejection when a waiver would require an external refund.

The complete settlement set is cash, check, and wallet-to-wallet when
blockchain is enabled. No additional method is retained as a planned API,
persistence, AI-knowledge, or smart-contract value.

Run the complete repository suite before merging or releasing:

```bash
.venv/bin/pytest -q
```

Do not convert an integration skip into a pass. Record why it skipped and run it
against the intended isolated service when that evidence is required.

## Safety and Test Data

- Use `config.settings_test` (the default in `pytest.ini`) for ordinary tests.
- Never point destructive fixtures at a production database or chain.
- Use a unique isolated MongoDB database and a disposable funded development
  wallet for integration testing.
- Never paste JWTs, private keys, database URIs, customer data, or provider
  credentials into committed test files or reports.
- `python init_db.py`, database backfills, contract deployment, blockchain
  transactions, and Celery production operations are state-changing. Run them
  only against an approved target after backup and inventory review.
- Keep `BLOCKCHAIN_ENABLED=False` for the cash/check baseline unless the chain
  test environment is intentionally configured.

## API Base and Authentication

Default local base:

```text
http://127.0.0.1:8000/api/loans/
```

Authenticated requests require the project JWT transport. When using an access
token header:

```http
Authorization: Bearer <access-token>
Content-Type: application/json
```

Financial POST requests also require a stable client-generated key:

```http
Idempotency-Key: <8-to-128-character-value>
```

Use separate customer, assigned-officer, other-officer, limited-admin, and
fully authorized admin identities. A single superuser test cannot prove role or
assignment isolation.

## Canonical Statuses

Application statuses:

- `draft`
- `submitted`
- `under_review`
- `approved`
- `rejected`
- `disbursed`
- `completed`
- `written_off` (reserved; no approved write-off workflow exists)
- `cancelled`

`pending` is a list-filter alias for `submitted` and `under_review`; it is not a
stored application status.

Disbursement statuses:

- `not_started`
- `pending`
- `executed`
- `failed`
- `cancelled`

Payment statuses:

- `pending_verification`
- `posting`
- `posted`
- `failed`
- `reversed` (reserved; no reversal workflow exists)

Installment statuses:

- `pending`
- `partial`
- `overdue`
- `partial_overdue`
- `paid`

Schedule statuses are `active`, `paid_off`, `restructured`, and `written_off`.
The latter two are reserved until corresponding policy and API workflows exist.

## Access and Endpoint Matrix

### Customer

| Method | Route | Expected boundary |
| --- | --- | --- |
| `GET` | `products/` | Customer role |
| `GET` | `products/<product_id>/` | Customer role; active product |
| `POST` | `pre-qualify/` | Customer role; own readiness context |
| `POST` | `apply/` | Customer role; own completed prerequisites |
| `GET` | `applications/` | Customer role; owner rows only |
| `GET/PUT` | `applications/<application_id>/` | Owner; PUT only for draft |
| `GET` | `applications/<application_id>/schedule/` | Owner; disbursed/closed lifecycle |
| `GET` | `applications/<application_id>/payments/` | Owner-scoped payment history; POST is not supported |
| `POST` | `applications/<application_id>/resubmit/` | Owner; rejected only |
| `GET` | `applications/<application_id>/feedback/` | Owner; rejected only |
| `POST` | `applications/<application_id>/set-disbursement-method/` | Owner; allowed lifecycle |
| `GET` | `applications/<application_id>/blockchain/` | Owner |
| `POST` | `applications/<application_id>/wallet-payment/` | Owner; disbursed loan; verified chain tx |
| `GET` | `system-wallet/` | Customer role; blockchain configured |

### Administrator

| Method | Route | Expected boundary |
| --- | --- | --- |
| `GET/POST` | `admin/products/` | Admin + `manage_system` |
| `GET/PUT/DELETE` | `admin/products/<product_id>/` | Admin + `manage_system` |
| `POST` | `admin/applications/<application_id>/assign/` | Admin + `manage_loan_officers` |
| `POST` | `admin/applications/<application_id>/reassign/` | Admin + `manage_loan_officers` |
| `GET` | `admin/officers/workload/` | Admin + `manage_loan_officers` |
| `GET` | `admin/blockchain/transactions/` | Admin + `view_logs` |

### Officer or administrator

Loan officers must be assigned to the application unless the endpoint is a
queue/list operation with its own scoped query. Administrators use the shared
officer-or-admin boundary without assignment restriction.

| Method | Route | Expected behavior |
| --- | --- | --- |
| `GET` | `officer/applications/` | Assigned rows for officer; admin broader view |
| `GET` | `officer/applications/<application_id>/` | Scoped detail |
| `POST` | `officer/applications/<application_id>/notes/` | Scoped note append |
| `POST` | `officer/applications/<application_id>/request-missing-documents/` | Scoped submitted/review state |
| `PUT` | `officer/applications/<application_id>/review/` | Scoped submitted/review state |
| `POST` | `officer/applications/<application_id>/disburse/` | Scoped approved state + idempotency key |
| `GET/POST` | `officer/applications/<application_id>/wallet-disbursement/` | Scoped wallet recovery |
| `POST` | `officer/payments/` | Scoped cash/check posting + idempotency key |
| `GET` | `officer/payments/recent/` | Accessible loans only |
| `GET` | `officer/payments/search/` | Accessible loans only |
| `GET` | `officer/active-loans/` | Scoped search/customer lookup |
| `GET` | `officer/applications/<application_id>/schedule/` | Scoped schedule |
| `GET` | `officer/applications/<application_id>/payments/` | Scoped history |
| `POST` | `officer/applications/<application_id>/penalties/apply/` | Scoped eligible installment |
| `POST` | `officer/applications/<application_id>/penalties/waive/` | Scoped penalized installment |
| `GET/POST` | `officer/applications/<application_id>/payoff/` | Quote / exact cash-check payoff |
| `GET` | `officer/applications/<application_id>/blockchain/` | Assigned officer/admin; out-of-scope records are concealed |
| `GET` | `officer/exchange-rate/` | Blockchain enabled and provider available |
| `GET` | `officer/schedules/export/` | Scoped, streaming, audited CSV/JSON with a configurable synchronous row ceiling |

## Core Request Examples

### Pre-qualify

```http
POST /api/loans/pre-qualify/
```

```json
{
  "product_id": "<product-id>",
  "amount": 25000,
  "term_months": 12,
  "purpose": "Expand inventory",
  "requirements_scope": "product"
}
```

Test both `baseline` and `product` requirements scope. Assert the response
contains `eligible`, `can_apply`, missing requirements, score/risk information,
and a recommendation that remains inside product bounds.

### Submit application

```http
POST /api/loans/apply/
```

```json
{
  "product_id": "<product-id>",
  "requested_amount": 25000,
  "term_months": 12,
  "purpose": "Business expansion",
  "preferred_disbursement_method": "cash"
}
```

Assert incomplete profiles, missing/unapproved documents, inactive products,
out-of-range amounts, and invalid terms fail without creating an application.

### Review

Approve:

```http
PUT /api/loans/officer/applications/<application-id>/review/
```

```json
{
  "action": "approve",
  "approved_amount": 20000,
  "notes": "Verified supporting information"
}
```

Reject:

```json
{
  "action": "reject",
  "rejection_reason": "Required documents could not be verified",
  "notes": "Internal review note"
}
```

The approved amount must not exceed the requested amount. Test invalid states,
wrong assignee, and concurrent approve/reject attempts. The guarded MongoDB
transition now permits exactly one decision; the loser receives `409` with
`LOAN_TRANSITION_CONFLICT`.

### Assign and reassign

```http
POST /api/loans/admin/applications/<application-id>/assign/
```

```json
{
  "officer_id": "<active-officer-id>"
}
```

Use the same body for `reassign/`. Test inactive/nonexistent officers, missing
permission, same-officer replay, invalid application state, and concurrent
admins.

### Disburse

```http
POST /api/loans/officer/applications/<application-id>/disburse/
Idempotency-Key: disburse-<uuid>
```

```json
{
  "amount": 20000,
  "method": "cash",
  "reference": "CASH-RECEIPT-001"
}
```

- Cash/check should return an executed disbursement and one schedule.
- Wallet should return HTTP 202 pending, then complete only after the worker
  confirms the transfer and creates/reuses the schedule.
- Unsupported values return HTTP 400 without creating a disbursement. Wallet is
  accepted only when blockchain is enabled.
- Replaying an identical key/payload must not create another schedule or send
  another transfer.
- Reusing a key for an incompatible request must fail.

### Officer payment

```http
POST /api/loans/officer/payments/
Idempotency-Key: payment-<uuid>
```

```json
{
  "loan_id": "<application-id>",
  "installment_number": 1,
  "amount": 2000,
  "payment_method": "cash",
  "reference": "OR-0001",
  "notes": "Counter payment"
}
```

Only cash and check are accepted here. Assert exact centavo allocation, partial
payment state, full installment state, remaining balance, repeated-key replay,
incompatible reuse conflict, and overpayment rejection.

### Wallet payment

```http
POST /api/loans/applications/<application-id>/wallet-payment/
```

```json
{
  "tx_hash": "0x<64-hex-characters>",
  "installment_number": 1
}
```

Test failed receipt, insufficient confirmations, wrong recipient, customer
sender mismatch, insufficient ETH/PHP value, duplicate transaction hash,
transaction used for another loan/installment, rate-provider failure, and exact
replay. Public failures must not expose RPC/provider exception text.

### Penalties

```http
POST /api/loans/officer/applications/<application-id>/penalties/apply/
```

```json
{
  "installment_number": 1,
  "penalty_rate": 0.05,
  "reason": "Past due"
}
```

```http
POST /api/loans/officer/applications/<application-id>/penalties/waive/
```

```json
{
  "installment_number": 1,
  "reason": "Approved hardship exception"
}
```

Assert optimistic-concurrency conflict behavior, policy-version audit fields,
and balance recalculation. If part of a collected penalty is waived, assert its
credit is atomically applied to later unpaid installments. If no later balance
can absorb all credit, assert the waiver fails without mutation because an
external refund rail is not implemented.

### Early payoff

Quote:

```http
GET /api/loans/officer/applications/<application-id>/payoff/
```

Post the exact quoted amount:

```http
POST /api/loans/officer/applications/<application-id>/payoff/
Idempotency-Key: payoff-<uuid>
```

```json
{
  "amount": 18450.25,
  "payment_method": "cash",
  "reference": "PAYOFF-001"
}
```

Assert the quote includes its timestamp, all-remaining-scheduled-balance basis,
exact-amount requirement, half-up centavo rounding, and accounting-policy
version. The schedule must become `paid_off`, the application `completed`, the
remaining balance zero, and replay must create no second payment.

### Wallet disbursement recovery

```http
GET /api/loans/officer/applications/<application-id>/wallet-disbursement/
```

```http
POST /api/loans/officer/applications/<application-id>/wallet-disbursement/
```

```json
{
  "action": "reconcile"
}
```

Actions are `reconcile`, `retry`, and safe pre-preparation `cancel`. Assert raw
signed transaction bytes and wallet private keys are never returned. Cancel
must fail once a transaction has been prepared, claimed, or broadcast.

## Search, Pagination, and Export Tests

### Customer applications

Supported query parameters are `search`, `status`, `page`, and `page_size`.
Test owner scope, invalid status, invalid/nonpositive pages, maximum size, empty
results, and deterministic newest-first order.

### Officer applications

Test `status`, `search`, `min_amount`, `max_amount`, `start_date`, `end_date`,
`risk_category`, `page`, `page_size`, `sort_by`, and `sort_order`. Include:

- inverted and malformed ranges;
- invalid enums/sort fields;
- other-officer and unassigned applications;
- identical timestamps requiring deterministic tie behavior; and
- more than 500 supporting search candidates and assert
  `search_truncated=true` rather than silent omission.

### Payment search

Test `search`, `loan_id`, `customer_id`, `disbursed_only`, `payment_status`,
`payment_method`, amount/date ranges, pagination, and sorting. Specifically test:

- officer scope when many applications are assigned;
- `on_time`/`late` classification at large result counts;
- posted versus pending/failed records;
- summaries over the complete filtered result, not just the page; and
- exact reference search after encryption and across configured previous keys;
  assert that neither plaintext nor ciphertext regex is queried.

### Schedule export

Test officer scope, admin scope, required audit failure, JSON output, CSV
streaming, date/status filters, and values beginning with `=`, `+`, `-`, or `@`
to prove spreadsheet formula protection. Verify that a result above
`LOAN_EXPORT_MAX_ROWS` is rejected before a partial synchronous export begins.

## Stage Validation Map

The production review uses six remediation stages. This table is the canonical
mapping between each stage and its required test evidence.

| Stage | Primary test scope | Current evidence status |
| --- | --- | --- |
| Stage 1 — Authorization and public response contract | Authenticated routes, role/permission/owner/assignment isolation, blockchain field allowlists, stable errors | **Complete:** 17 focused regressions pass; broader Loans selection passes |
| Stage 2 — Atomic lifecycle and financial correctness | Concurrent review/assignment/notes, idempotent disbursement/payment/payoff, crash/replay | Application code and nine focused local regressions pass; the expanded six-case isolated real-Mongo run was attempted but its configured Atlas target failed the TLS preflight before test-database creation |
| Stage 3 — Settlement scope and approved policies | Cash/check, feature-gated wallet, public policy contract, concurrent penalty/waiver credit, explicit payoff/rate terms | **Complete in application code:** seven focused regressions and the broader Loans selection pass; institutional policy approval and optional deployed-wallet evidence remain release gates |
| Stage 4 — MongoDB schema and bounded execution | Validators, inventory/backfill, unique indexes, query plans, large fixtures, overlapping jobs | **Implemented locally:** 11 focused regressions pass; the isolated suite now covers all five validators and eleven critical query plans, but target execution remains pending |
| Stage 5 — Privacy, notifications, and observability | Export/retention/hold/pseudonymization, encryption rotation, outbox recovery, metrics/rules/dashboard | **Complete locally:** eight focused regressions and Prometheus rule/config validation pass; policy and deployed alert evidence remain release gates |
| Stage 6 — Real-environment release validation | Deployment MongoDB, Redis/Celery, optional chain, HTTPS, load, backup/restore, rollback, dashboards/alerts | **Tooling/local proof complete:** ten local regressions and the disposable Redis/two-worker probes pass; HTTPS, deployed metrics, recovery rehearsals, and final target evidence remain pending |

When implementing a stage, add its focused tests in the same change and update
both this guide and the production review with the exact result. Do not mark a
stage complete because an unrelated full-suite run passed.

## Required Security Regression Matrix

For every application-specific endpoint, test:

1. unauthenticated request;
2. wrong role;
3. customer A requesting customer B's ID;
4. officer A requesting officer B's assigned ID;
5. unassigned application where assignment is required;
6. malformed ObjectId;
7. nonexistent ObjectId; and
8. admin with and without the named permission, where applicable.

Out-of-scope customer/officer records should normally be concealed as 404 rather
than confirming existence.

Stage 1 now covers item 4 for officer blockchain access and verifies concealed
404 behavior. Customer/officer blockchain payload tests also reject
`idempotency_key`, free-form `details`, internal `error`, raw signed transaction,
and contract-only fields. Preserve these regressions whenever the blockchain
models or serializers change.

## Atomicity and Idempotency Tests

Run these against real MongoDB, using independent clients/threads rather than
multiple references to one in-memory object:

- concurrent approve versus reject: exactly one winner;
- concurrent assign/reassign: one expected-state winner;
- concurrent note appends: no accepted note lost and history remains bounded;
- repeated disbursement key: one financial execution and one schedule;
- repeated payment/payoff key: one payment and one balance mutation;
- duplicate external reference: one accepted claim;
- duplicate ETH transaction: one posted payment;
- worker loss after wallet preparation, after broadcast, and before completion;
- simultaneous schedule payments: accounting-version conflict and safe retry;
- payment stored before schedule mutation: reconciliation completes once; and
- schedule paid off before application closure: lifecycle reconciliation closes
  once.

The opt-in suite is `tests/test_loans_stage2_real_mongo.py`. It creates and
drops only a random database whose name ends in `_isolated`:

```bash
RUN_LOANS_REAL_MONGO_TESTS=1 \
REAL_MONGO_TEST_URI='<approved isolated MongoDB URI>' \
.venv/bin/pytest -q tests/test_loans_stage2_real_mongo.py
```

Do not run this command against production. Record the exact target class and
result before checking Stage 2 off below.

## Background Task Tests

Direct task/unit coverage should verify:

- overdue dates become `overdue` or `partial_overdue` once;
- paid installments remain paid;
- paid-off reconciliation is idempotent;
- wallet reconciliation re-enqueues eligible pending records only;
- a live worker lease prevents a second worker claim;
- an expired lease is recoverable;
- prepared raw transaction rebroadcast uses exactly the same signed bytes;
- reverted receipts fail safely;
- uncertain/missing receipts are not treated as successful or immediately
  replaced with a new transfer; and
- audit/event reconciliation is repeatable.

Deployment/load coverage must additionally verify bounded batches, checkpoints,
overlapping Beat executions, queue separation, time limits, broker outage,
worker termination, retry-from-checkpoint, and backlog alerting. Overdue,
paid-off, and wallet reconciliation are now locally bounded, leased, and
checkpointed; failed records deliberately remain before the checkpoint rather
than being skipped into a lossy dead-letter path.

## Stage 5 Privacy and Delivery Validation

Run the focused local suite:

```bash
.venv/bin/pytest -q \
  tests/test_loans_stage5_privacy_notifications_observability.py
```

It verifies encrypted sensitive fields, bounded customer export, idempotent
account pseudonymization, retention/legal hold, encrypted outbox retry/replay,
broker outage recovery, bounded operational gauges, and monitoring assets.

Legal-hold changes are dry-run-first:

```bash
.venv/bin/python manage.py manage_loan_legal_hold \
  '<application-id>' set --reason 'Approved case reference' --actor '<admin-id>'
```

Repeat with `--apply` only after authorization. Release uses `release` and still
requires `--apply`. Do not put customer details in the reason.

Validate monitoring configuration locally:

```bash
promtool check rules monitoring/loans/prometheus-rules.yml
promtool test rules monitoring/loans/prometheus-rules.test.yml
promtool check config monitoring/loans/prometheus-smoke.yml
```

## Stage 6 Release Validation

Run the non-secret, read-only summary at any time:

```bash
.venv/bin/python manage.py loan_release_check
.venv/bin/python manage.py loan_release_check --json
```

It intentionally exits non-zero until every production condition is proven.
The `LOANS_*_VERIFIED` values in `.env.example` are evidence acknowledgements,
not switches that perform a test. Keep them `False` in development. In the
final deployment, set a flag to `True` only after retaining the corresponding
test output or approved operational record. If blockchain remains disabled,
`LOANS_BLOCKCHAIN_VERIFIED` may remain `False`; the release command accepts the
cash/check baseline when `BLOCKCHAIN_ENABLED=False`.

Run the deployment probes against the approved target:

```bash
RUN_LOANS_REDIS_DEPLOYMENT_TESTS=1 \
LOANS_DEPLOYMENT_REDIS_URL='<deployment Redis URL>' \
.venv/bin/pytest -q \
  tests/test_loans_stage6_deployment_integrations.py::test_two_processes_share_deployment_redis_state

RUN_LOANS_CELERY_DEPLOYMENT_TESTS=1 \
CELERY_BROKER_URL='<deployment Redis broker URL>' \
.venv/bin/pytest -q \
  tests/test_loans_stage6_deployment_integrations.py::test_multiple_deployed_workers_consume_the_loans_queue

RUN_LOANS_HTTPS_DEPLOYMENT_TESTS=1 \
LOANS_DEPLOYMENT_PRODUCTS_URL='https://<host>/api/loans/products/' \
LOANS_DEPLOYMENT_CUSTOMER_TOKEN='<short-lived synthetic customer token>' \
LOANS_DEPLOYMENT_LOAD_REQUESTS=20 \
LOANS_DEPLOYMENT_LOAD_CONCURRENCY=4 \
.venv/bin/pytest -q \
  tests/test_loans_stage6_deployment_integrations.py::test_authenticated_api_contract_and_representative_read_load_through_https

RUN_LOANS_METRICS_DEPLOYMENT_TESTS=1 \
LOANS_DEPLOYMENT_METRICS_URL='https://<monitoring-only-host>/metrics/' \
.venv/bin/pytest -q \
  tests/test_loans_stage6_deployment_integrations.py::test_deployed_metrics_expose_every_loans_metric_family
```

Use a synthetic account/token and a private monitoring endpoint. These probes
do not create loans or payments. The Redis probe creates one expiring random
key and removes it; the Celery probe only inspects worker pings and queues.
Deployment workers must be started so at least two consume the dedicated
`loans` queue, for example with `-Q loans` in their approved worker command.

## Loans Operations Runbook

Enable the existing metrics endpoint and start Prometheus with the Loans smoke
configuration:

```bash
.venv/bin/python manage.py toggle_prometheus enable --url
prometheus \
  --config.file="$PWD/monitoring/loans/prometheus-smoke.yml" \
  --storage.tsdb.path=/tmp/capstone-loans-prometheus
```

Provision Grafana with the Loans dashboard path before starting the server:

```bash
export LOANS_DASHBOARD_PATH="$PWD/monitoring/loans"
```

Use the same Grafana startup command documented in the root `README.md`, then
open the **Capstone Loans Operations** dashboard. Authenticated Loans API
requests populate request rate/latency. Celery Beat refreshes backlog gauges
every five minutes; for a local check, run the task directly without changing
loan records:

```bash
.venv/bin/python manage.py shell -c \
  "from loans.tasks import collect_loan_operational_metrics_task as t; print(t.run())"
```

Respond to alerts as follows:

1. notification backlog: confirm the Loans worker/queue and SMTP health, then
   let the idempotent reconciler retry; do not resend by repeating a financial
   API mutation;
2. stuck disbursement: inspect the stable status, lease, and reconciliation
   record before retry/cancel authorization;
3. audit backlog: restore MongoDB/audit availability and run the existing audit
   reconciler;
4. blockchain failures: stop new wallet work if needed, preserve signer/RPC
   evidence, and reconcile before issuing another transaction; and
5. high error ratio/latency: correlate by low-cardinality scope and method,
   inspect application logs by request correlation ID, and check MongoDB/Redis
   query and queue health.

Never place customer IDs, loan IDs, payment references, wallet addresses, or
exception text in Prometheus labels.

## Blockchain Testing

### Mocked suite

```bash
.venv/bin/pytest -q tests/blockchain \
  --ignore=tests/blockchain/test_integration.py
```

This covers client validation, transaction records, services, sync tasks,
wallet phases, nonce behavior, saga recovery, event listening, and
reconciliation without sending a real transaction.

### Local Ganache integration

The existing integration file runs only when blockchain is enabled, RPC is
reachable, and contract addresses are configured:

```bash
.venv/bin/pytest -v tests/blockchain/test_integration.py
```

Use only a disposable development chain and wallet. A skip such as “contract
preconditions not met” is not passing evidence. Ensure the configured account
has the exact contract roles required by the test.

Before enabling blockchain in production, repeat equivalent tests against the
approved network topology and prove:

- chain ID and deployed bytecode/ABI/address manifest;
- signer identity, minimum balance, secret isolation, and access-control roles;
- RPC timeout/failover and rate-limit behavior;
- confirmation threshold and reorg recovery;
- multiple-worker nonce contention;
- process loss before preparation, after preparation, after broadcast, and
  after confirmation;
- duplicate event/replay and cursor recovery;
- off-chain/on-chain reconciliation; and
- transaction/gas/backlog metrics and delivered alerts.

The current contract settlement enum is `Cash=0`, `Check=1`, `Wallet=2`.
Validate a fresh deployment of this contract version. Existing local deployment
manifests may still contain historical compiler input and must not be treated as
an upgrade-safe migration plan.

Never run a value-transfer test against a real funded wallet without explicit
approval of the wallet, network, amount, and recipient.

## MongoDB Inventory, Backfill, and Deployment Tests

Run the read-only inventory first:

```bash
.venv/bin/python manage.py loan_data_inventory --limit 10000
```

Backfill defaults to a dry run. If any collection is truncated, increase the
limit and repeat; the command refuses to report a clean run when it did not scan
the complete collection:

```bash
.venv/bin/python manage.py backfill_loan_data --limit 10000
```

Only after backup, reviewed duplicate reconciliation, and an approved dry run,
apply the backfill, repeat inventory until clean, and then run `python init_db.py`
to install indexes and strict validators. Both apply/init commands mutate
MongoDB and require explicit approval for the exact target.

The opt-in Stage 4 suite creates and drops only a random database whose name
ends in `_isolated`:

```bash
RUN_LOANS_STAGE4_REAL_MONGO_TESTS=1 \
REAL_MONGO_TEST_URI='<approved isolated MongoDB URI>' \
.venv/bin/pytest -q tests/test_loans_stage4_real_mongo.py
```

Do not point this command at production. The present suite proves installation
and invalid-write rejection for all five validator manifests, every required
index, duplicate-sensitive key integrity, a 500-payment fixture, and indexed
plans for eleven application, disbursement, schedule, payment, blockchain, and
notification query shapes. The Stage 2 isolated suite separately proves atomic
lifecycle and crash/replay behavior.

Use a dedicated opt-in marker and a unique temporary database. At minimum:

1. install every loan validator and index;
2. reject invalid status, money, ownership, encrypted-field, and date shapes;
3. prove unique product code, schedule-per-loan, idempotency, reference
   fingerprint, ETH hash, and blockchain transaction keys;
4. run the atomicity matrix above;
5. explain owner/status/date, officer/status/date, loan/payment/date, pending
   disbursement, active schedule, and reconciliation queries; and
6. clean up the temporary database even after failure.

Do not run index installation against an existing target until duplicate
inventory and dry-run backfill have been reviewed and backed up.

## End-to-End Smoke Flows

### Cash/check happy path

1. Admin creates an active product.
2. Customer reads the product and passes pre-qualification.
3. Customer submits an application.
4. Admin assigns it to an active officer.
5. Other officer receives 404 for detail/review/disbursement/blockchain status.
6. Assigned officer adds a note and requests any truly missing document.
7. Assigned officer approves the application.
8. Assigned officer disburses by cash/check with an idempotency key.
9. Replaying disbursement returns the same execution and schedule.
10. Customer reads the schedule.
11. Assigned officer records partial then exact remaining payment(s).
12. Customer sees only posted history and updated balances.
13. Final payment or payoff closes schedule/application exactly once.
14. Audit and notification records use the correct customer, officer, resource,
    and event-time scope.

### Rejection and resubmission branch

1. Assigned officer rejects a submitted/under-review application.
2. Customer reads feedback.
3. Customer calls `resubmit/`, returning the same application to `draft`.
4. Customer updates the draft with the original product ID.
5. The same record is submitted again without retaining stale decision,
   assignment, or missing-document state.

### Wallet branch

1. Customer has an approved valid wallet address.
2. Officer initiates wallet disbursement with one idempotency key.
3. Worker claims, prepares, persists, broadcasts, and confirms one transfer.
4. Worker creates/reuses one schedule and completes disbursement.
5. Customer submits a distinct sufficiently confirmed repayment transaction.
6. Backend verifies chain facts and posts it once.
7. Reconciliation reports no off-chain/on-chain drift.

### Unsupported-method branch

Submit an unrecognized payment/disbursement method and assert HTTP 400 without
creating a payment, disbursement attempt, schedule balance, or application state
change. Product responses must advertise only cash/check and optional wallet.

## Expected HTTP Outcomes

| Status | Typical meaning |
| --- | --- |
| `200` | Successful read/update or idempotent replay |
| `201` | New product/application/payment resource created where applicable |
| `202` | Enabled wallet operation accepted but not yet confirmed |
| `400` | Invalid body/filter/state/amount/term/key format |
| `401` | Missing, invalid, expired, or revoked authentication |
| `403` | Role or named-permission denial |
| `404` | Missing resource or concealed owner/assignment scope |
| `409` | Idempotency mismatch, duplicate claim, or concurrent-state conflict |
| `429` | Pre-qualification or shared request throttle exceeded |
| `500` | Unexpected internal failure; response must not include exception text |
| `503` | Disabled settlement rail, unavailable chain/rate provider, or required dependency |

## Manual API Checklist

When using Insomnia or another client, record:

- request method/path and non-secret body;
- actor role and whether the officer is assigned;
- status code and stable response code/message;
- application, disbursement, schedule, installment, and payment status before
  and after;
- idempotency key identifier (redacted if treated as sensitive);
- audit/notification/transaction record IDs;
- Celery task ID and terminal state for async operations; and
- relevant metric/alert evidence.

Never use screenshots containing access tokens, customer PII, private keys,
database URIs, raw signed transactions, or internal exception detail.

## Release Test Checklist

- [x] **Stage 1:** scope, permission, response-minimization, and stable-error
      regressions pass.
- [ ] **Stage 2:** application code and nine local regressions pass. Resolve the
      configured Atlas TLS preflight failure, then execute and record the
      six-case isolated real-Mongo atomic lifecycle/idempotency suite.
- [x] **Stage 3 application code:** cash/check are active, wallet is
      feature-gated, unsupported methods are rejected, waiver credits are
      carried forward or rejected safely, and
      payoff/rate/accounting contracts are explicit. Institutional/legal policy
      approval and optional deployed-wallet proof remain release conditions.
- [ ] **Stage 4 deployment evidence:** local inventory/backfill,
      validators/indexes, bounded exports/jobs, and overlap regressions pass;
      execute the isolated real-Mongo suite and representative multi-worker/load
      tests against an approved target.
- [x] **Stage 5 application code:** customer export, retention/legal hold/anonymization,
      encryption rotation, notification outbox recovery, metrics, dashboards,
      and Prometheus rule tests pass. Authorized policy approval and deployed
      dashboard/alert evidence remain Stage 6 release conditions.
- [x] **Stage 6 validation tooling:** the fail-closed release command and
      opt-in Redis, Celery-worker, HTTPS/load, and metrics probes are implemented
      and ten focused local regressions pass. The shared-Redis and two-worker
      probes also pass with disposable local processes.
- [ ] **Stage 6 deployment evidence:** multi-worker Redis/Celery recovery,
      optional blockchain, HTTPS proxy, load, backup/restore, key rotation,
      rollback, dashboards, and delivered alerts are proven in the selected
      topology; `loan_release_check` reports overall `PASS`.
- [x] Current revision's full repository suite and automated cash/check
      lifecycle smoke pass. Repeat both on the final release revision; manually
      exercise rejection/resubmission and any enabled wallet branch there.

## Canonical Test Files

- `tests/test_loan_audit_logging.py`
- `tests/test_loan_disbursement_integrity.py`
- `tests/test_loan_models.py`
- `tests/test_loan_payment_integrity.py`
- `tests/test_loan_qualification.py`
- `tests/test_loan_repayment_disbursement_services.py`
- `tests/test_loan_schedule_export.py`
- `tests/test_loan_serializers.py`
- `tests/test_loan_services.py`
- `tests/test_loan_tasks.py`
- `tests/test_loans_api.py`
- `tests/test_loans_api_stubs.py`
- `tests/test_loans_cash_check_release_smoke.py`
- `tests/test_loans_smoke.py`
- `tests/test_loans_stage1_security_contract.py`
- `tests/test_loans_stage2_atomic_lifecycle.py`
- `tests/test_loans_stage2_real_mongo.py`
- `tests/test_loans_stage4_persistence_scalability.py`
- `tests/test_loans_stage4_real_mongo.py`
- `tests/test_loans_stage5_privacy_notifications_observability.py`
- `tests/test_loans_stage6_release_validation.py`
- `tests/test_loans_stage6_deployment_integrations.py`
- `tests/test_loans_stage6_worker_recovery.py`
- `tests/test_loans_stage3_settlement_policy.py`
- `tests/test_qualification_enforcement.py`
- `tests/test_wallet_disbursement_tasks.py`
- `tests/test_stage4_blockchain_recovery.py`
- `tests/test_stage7_repayment_lifecycle.py`
- `tests/test_blockchain_event_listener.py`
- `tests/blockchain/`

## Implementation References

- `loans/urls.py`
- `loans/models/`
- `loans/serializers/loan_serializers.py`
- `loans/services/`
- `loans/views/`
- `loans/tasks.py`
- `loans/blockchain/`
- `config/celery.py`
- `init_db.py`
