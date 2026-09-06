# Loans API Testing Guide

## Scope

The Loans module handles products, customer pre-qualification and applications,
administrator assignment, officer review, disbursement, repayment schedules,
payments, penalties, payoff, and optional blockchain settlement.

This guide is organized for manual testing in Insomnia and follows the actual
routes, request fields, roles, and state transitions in `loans/`. The main smoke
test uses cash/check, so blockchain is not required.

## Before Testing

Start the API and services required by your local configuration. Use test users
and non-sensitive documents. The base URL is:

```text
http://localhost:8000/api/loans
```

You need:

| Variable | Actor |
| --- | --- |
| `customer_access` | Customer with completed personal, business, and alternative-data profiles |
| `officer_access` | Active loan officer |
| `admin_access` | Administrator with the required named permissions |

The customer must have the documents required by the chosen product. Submission
accepts uploaded required documents, but final approval requires them to have
status `approved`. The baseline requirement is `valid_id`; a product may require
more. Accepted product document types are `valid_id`, `selfie_with_id`,
`proof_of_address`, `business_permit`, `business_photo`, `income_proof`, and
`other`.

Use the Accounts and Profiles guides to prepare users/profiles and the Documents
guide to upload and approve files. Resolve consent, scanning, or document-AI
problems before treating a Loans failure as a Loans bug.

## Insomnia Setup

### Environment

Create a `Capstone Local` environment:

```json
{
  "auth_url": "http://localhost:8000/api/auth",
  "loans_url": "http://localhost:8000/api/loans",
  "customer_access": "",
  "officer_access": "",
  "admin_access": "",
  "product_id": "",
  "application_id": "",
  "officer_id": "",
  "installment_number": 1,
  "disbursement_key": "loan-disburse-local-001",
  "payment_key": "loan-payment-local-001",
  "payoff_key": "loan-payoff-local-001"
}
```

Copy returned IDs into the environment as you proceed. Insomnia response tags
also work, but manual copying is easier to debug.

### Log in all three actors

Send JSON without Bearer authentication. Create these as three separate
requests:

Customer login — method: `POST`

```text
http://localhost:8000/api/auth/login/
```

Loan-officer login — method: `POST`

```text
http://localhost:8000/api/auth/loan-officer/login/
```

Administrator login — method: `POST`

```text
http://localhost:8000/api/auth/admin/login/
```

Customer/officer body:

```json
{ "email": "user@example.com", "password": "your-password" }
```

Admin body:

```json
{ "username": "your-admin", "password": "your-password" }
```

Copy `data.access` into the matching variable. If login returns `requires_2fa`,
complete 2FA as described in the Accounts guide. If an officer gets HTTP `423`,
complete the required password change first.

For protected requests select **Auth > Bearer Token** and enter the relevant
`{{ _.customer_access }}`, `{{ _.officer_access }}`, or
`{{ _.admin_access }}`. Select **Body > JSON** when a body is shown. Pure Bearer
requests do not need CSRF cookies or an `X-CSRFToken` header.

## Roles and State Flow

| Routes | Access |
| --- | --- |
| Customer products/applications | Customer |
| `admin/products/` | Admin + `manage_system` |
| Assignment/workload | Admin + `manage_loan_officers` |
| Admin blockchain log | Admin + `view_logs` |
| `officer/...` | Officer or admin |

Officers normally access only applications assigned to them. An out-of-scope
application may deliberately return `404`, concealing its existence.

```text
draft -> submitted -> under_review -> approved -> disbursed -> completed
                         |
                         +-> rejected -> draft (resubmit)
```

The model also supports `written_off` and `cancelled`. Perform each mutation
once unless explicitly testing idempotency. On an invalid-state response, GET
the application and check its current status.

## End-to-End Cash/Check Test

### 1. Create or select an active product

Admin create:

Method: `POST`

```text
http://localhost:8000/api/loans/admin/products/
```

Auth: Bearer `admin_access`

```json
{
  "name": "Local Test Microloan",
  "code": "LOCAL-TEST-001",
  "description": "Disposable local Insomnia product",
  "min_amount": 1000,
  "max_amount": 50000,
  "interest_rate": 0.015,
  "min_term_months": 3,
  "max_term_months": 12,
  "required_documents": ["valid_id"],
  "min_business_months": 0,
  "min_monthly_income": 0,
  "business_types": [],
  "target_description": "Local API testing",
  "active": true
}
```

Expected: `201`; save `data.id` as `product_id`. `interest_rate` is a monthly
decimal, so `0.015` means 1.5% monthly. Name/code must be unique.

Alternatively list products as the customer:

Method: `GET`

```text
http://localhost:8000/api/loans/products/?page=1&page_size=20
```

Auth: Bearer `customer_access`

Save an item ID and note its amount, term, and document requirements.

### 2. Pre-qualify

Method: `POST`

```text
http://localhost:8000/api/loans/pre-qualify/
```

Auth: Bearer `customer_access`

```json
{
  "product_id": "{{ _.product_id }}",
  "amount": 25000,
  "term_months": 12,
  "purpose": "Expand store inventory",
  "requirements_scope": "product"
}
```

Expected: `200`. A successful HTTP response can still have `eligible` or
`can_apply` false. Read `missing_requirements` and
`required_documents_resolved`, then fix them. Use `product` for the real check;
`baseline` checks only baseline requirements and may be less strict.

### 3. Apply

Method: `POST`

```text
http://localhost:8000/api/loans/apply/
```

Auth: Bearer `customer_access`

```json
{
  "product_id": "{{ _.product_id }}",
  "requested_amount": 25000,
  "term_months": 12,
  "purpose": "Expand store inventory",
  "preferred_disbursement_method": "cash"
}
```

Expected: `201`, status `submitted`. Save `data.application_id`. Amount and term
must be within product bounds. Required documents must exist now and must be
approved before Step 7.

### 4. Find an officer and assign

Method: `GET`

```text
http://localhost:8000/api/loans/admin/officers/workload/?page=1&page_size=20
```

Auth: Bearer `admin_access`

Save an active officer ID as `officer_id`, then:

Method: `POST`

```text
http://localhost:8000/api/loans/admin/applications/<application_id>/assign/
```

Replace `<application_id>` with the saved ID. Auth: Bearer `admin_access`.

```json
{ "officer_id": "{{ _.officer_id }}" }
```

Expected: `200`, status `under_review`, with the chosen `assigned_officer`.
`reassign/` accepts the same body for a different active officer.

### 5. Inspect and add a note

Method: `GET`

```text
http://localhost:8000/api/loans/officer/applications/<application_id>/
```

Auth: Bearer `officer_access`.

This must be the assigned officer. Add a note:

Method: `POST`

```text
http://localhost:8000/api/loans/officer/applications/<application_id>/notes/
```

```json
{ "note": "Identity and application details reviewed" }
```

If a file is genuinely absent, request it with:

Method: `POST`

```text
http://localhost:8000/api/loans/officer/applications/<application_id>/request-missing-documents/
```

```json
{
  "missing_documents": ["valid_id"],
  "reason": "Please upload a clear government-issued ID"
}
```

This request does not approve a document.

### 6. Approve or reject

Ensure all product-required documents are approved. Then:

Method: `PUT`

```text
http://localhost:8000/api/loans/officer/applications/<application_id>/review/
```

Auth: Bearer `officer_access`.

```json
{
  "action": "approve",
  "approved_amount": 20000,
  "notes": "Required documents verified"
}
```

Expected: `200`, status `approved`. The amount must be greater than zero and not
exceed the requested amount. For a separate rejection-path application use:

```json
{
  "action": "reject",
  "rejection_reason": "Required documents could not be verified",
  "notes": "Local rejection test"
}
```

### 7. Set the method and disburse

Customer method request:

Method: `POST`

```text
http://localhost:8000/api/loans/applications/<application_id>/set-disbursement-method/
```

Auth: Bearer `customer_access`.

```json
{ "disbursement_method": "cash" }
```

The field here is `disbursement_method`, not
`preferred_disbursement_method`. Then the assigned officer sends:

Method: `POST`

```text
http://localhost:8000/api/loans/officer/applications/<application_id>/disburse/
```

Auth: Bearer `officer_access`. Add header:

```text
Idempotency-Key: loan-disburse-local-001
```

```json
{
  "amount": 20000,
  "method": "cash",
  "reference": "CASH-RECEIPT-LOCAL-001"
}
```

Expected for cash/check: `200`, application `disbursed`, disbursement
`executed`, and one schedule. Send the identical request once more with the same
key: it should report a replay and must not create another schedule. Never reuse
the key with a changed payload. A stored customer method takes precedence over
the request's `method`.

### 8. Read the schedule and record payment

Method: `GET`

```text
http://localhost:8000/api/loans/applications/<application_id>/schedule/
```

Auth: Bearer `customer_access`.

Officer equivalent:

Method: `GET`

```text
http://localhost:8000/api/loans/officer/applications/<application_id>/schedule/
```

Auth: Bearer `officer_access`.

Save an unpaid installment number and use an amount no greater than its balance:

Method: `POST`

```text
http://localhost:8000/api/loans/officer/payments/
```

Auth: Bearer `officer_access`. Add header:

```text
Idempotency-Key: loan-payment-local-001
```

```json
{
  "loan_id": "{{ _.application_id }}",
  "installment_number": {{ _.installment_number }},
  "amount": 1000,
  "payment_method": "cash",
  "reference": "OR-LOCAL-001",
  "notes": "Insomnia counter-payment test"
}
```

Only cash/check are accepted. Repeat exactly to verify no duplicate payment.
Customer payment history is GET-only:

Method: `GET`

```text
http://localhost:8000/api/loans/applications/<application_id>/payments/?page=1&page_size=20
```

Auth: Bearer `customer_access`.

### 9. Optional early payoff

Get the exact current amount:

Method: `GET`

```text
http://localhost:8000/api/loans/officer/applications/<application_id>/payoff/
```

Auth: Bearer `officer_access`.

Immediately copy `data.payoff_amount` into:

Method: `POST`

```text
http://localhost:8000/api/loans/officer/applications/<application_id>/payoff/
```

Auth: Bearer `officer_access`. Add header:

```text
Idempotency-Key: loan-payoff-local-001
```

```json
{
  "amount": 19000,
  "payment_method": "cash",
  "reference": "PAYOFF-LOCAL-001",
  "notes": "Exact payoff from current quote"
}
```

Replace `19000` with the quote. Expected: schedule `paid_off`, application
`completed`, remaining balance `0`. Get a new quote if the schedule changes.

## Rejection and Resubmission

After rejection, retrieve feedback.

Method: `GET`

```text
http://localhost:8000/api/loans/applications/<application_id>/feedback/
```

Then reset the application to draft.

Method: `POST`

```text
http://localhost:8000/api/loans/applications/<application_id>/resubmit/
```

Both requests use Bearer `customer_access`.

Resubmit resets it to `draft`. Then send a full body, not a partial patch:

Method: `PUT`

```text
http://localhost:8000/api/loans/applications/<application_id>/
```

Auth: Bearer `customer_access`.

```json
{
  "product_id": "{{ _.product_id }}",
  "requested_amount": 20000,
  "term_months": 12,
  "purpose": "Revised inventory plan",
  "preferred_disbursement_method": "cash"
}
```

The product ID must match the original. This path requires approved documents.

## Penalties

For an eligible installment on a disbursed loan:

Method: `POST`

```text
http://localhost:8000/api/loans/officer/applications/<application_id>/penalties/apply/
```

Auth: Bearer `officer_access`.

```json
{
  "installment_number": 1,
  "penalty_amount": 250,
  "reason": "Past due"
}
```

The implementation expects `penalty_amount`, not `penalty_rate`. To waive:

Method: `POST`

```text
http://localhost:8000/api/loans/officer/applications/<application_id>/penalties/waive/
```

Auth: Bearer `officer_access`.

```json
{ "installment_number": 1, "reason": "Approved hardship exception" }
```

GET the schedule after each request and verify one balance change.

## Endpoint Reference

Every table below uses a complete local URL. Replace `<product_id>` or `<id>`
with the real value before sending the request.

### Customer

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `http://localhost:8000/api/loans/products/` | Active products |
| GET | `http://localhost:8000/api/loans/products/<product_id>/` | Active product detail |
| POST | `http://localhost:8000/api/loans/pre-qualify/` | Readiness check |
| POST | `http://localhost:8000/api/loans/apply/` | Submit application |
| GET | `http://localhost:8000/api/loans/applications/` | Own list; supports filters |
| GET/PUT | `http://localhost:8000/api/loans/applications/<id>/` | Own detail/full draft update |
| GET | `http://localhost:8000/api/loans/applications/<id>/schedule/` | Own schedule |
| GET | `http://localhost:8000/api/loans/applications/<id>/payments/` | Own payment history |
| POST | `http://localhost:8000/api/loans/applications/<id>/resubmit/` | Rejected to draft |
| GET | `http://localhost:8000/api/loans/applications/<id>/feedback/` | Rejection feedback |
| POST | `http://localhost:8000/api/loans/applications/<id>/set-disbursement-method/` | Save method |
| GET | `http://localhost:8000/api/loans/applications/<id>/blockchain/` | Optional chain status |
| POST | `http://localhost:8000/api/loans/applications/<id>/wallet-payment/` | Optional chain payment |
| GET | `http://localhost:8000/api/loans/system-wallet/` | Optional system wallet info |

Customer `status=pending` groups `submitted` and `under_review`.

### Administrator

| Method | Path | Permission |
| --- | --- | --- |
| GET/POST | `http://localhost:8000/api/loans/admin/products/` | `manage_system` |
| GET/PUT/DELETE | `http://localhost:8000/api/loans/admin/products/<product_id>/` | `manage_system`; PUT is partial |
| POST | `http://localhost:8000/api/loans/admin/applications/<id>/assign/` | `manage_loan_officers` |
| POST | `http://localhost:8000/api/loans/admin/applications/<id>/reassign/` | `manage_loan_officers` |
| GET | `http://localhost:8000/api/loans/admin/officers/workload/` | `manage_loan_officers` |
| GET | `http://localhost:8000/api/loans/admin/blockchain/transactions/` | `view_logs` |

Product filters: `active=true|false|all`, `search`, `page`, `page_size`.
`true` returns active products, `false` returns inactive products, and `all`
returns both.

### Officer or administrator

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `http://localhost:8000/api/loans/officer/applications/` | Scoped queue |
| GET | `http://localhost:8000/api/loans/officer/applications/counts/` | Scoped counts |
| GET | `http://localhost:8000/api/loans/officer/applications/<id>/` | Scoped detail |
| POST | `http://localhost:8000/api/loans/officer/applications/<id>/notes/` | Internal note |
| POST | `http://localhost:8000/api/loans/officer/applications/<id>/request-missing-documents/` | Missing docs |
| PUT | `http://localhost:8000/api/loans/officer/applications/<id>/review/` | Approve/reject |
| POST | `http://localhost:8000/api/loans/officer/applications/<id>/disburse/` | Disbursement |
| GET/POST | `http://localhost:8000/api/loans/officer/applications/<id>/wallet-disbursement/` | Optional recovery |
| POST | `http://localhost:8000/api/loans/officer/payments/` | Cash/check payment |
| GET | `http://localhost:8000/api/loans/officer/payments/recent/` | Recent payments |
| GET | `http://localhost:8000/api/loans/officer/payments/search/` | Payment search |
| GET | `http://localhost:8000/api/loans/officer/active-loans/` | Scoped active loans |
| GET | `http://localhost:8000/api/loans/officer/applications/<id>/schedule/` | Schedule |
| GET | `http://localhost:8000/api/loans/officer/applications/<id>/payments/` | Payment history |
| POST | `http://localhost:8000/api/loans/officer/applications/<id>/penalties/apply/` | Apply penalty |
| POST | `http://localhost:8000/api/loans/officer/applications/<id>/penalties/waive/` | Waive penalty |
| GET/POST | `http://localhost:8000/api/loans/officer/applications/<id>/payoff/` | Exact payoff |
| GET | `http://localhost:8000/api/loans/officer/applications/<id>/blockchain/` | Optional chain status |
| GET | `http://localhost:8000/api/loans/officer/exchange-rate/` | Optional exchange rate |
| GET | `http://localhost:8000/api/loans/officer/schedules/export/` | Audited CSV/JSON export |

Officer list filters include `status`, `search`, amount/date ranges,
`risk_category`, pagination, and sorting. Payment search supports loan/customer,
status/method, amount/date, pagination, and sorting filters. Export supports
`customer_id`, `status`, dates, and `format=csv|json`.

## Optional Blockchain Testing

Skip this for the cash/check smoke test. Sending `wallet` does not enable the
feature; RPC, contracts, wallet configuration, and a worker must be configured.
Wallet payment body:

```json
{ "tx_hash": "0x<64-hex-characters>", "installment_number": 1 }
```

Wallet disbursement normally returns `202`. Recovery actions are
`{"action":"reconcile"}`, `{"action":"retry"}`, and safe pre-preparation
`{"action":"cancel","reason":"..."}`. A non-empty cancellation reason is
required. The recovery response's `available_actions` is authoritative for the
current wallet state. Never record private keys, signed raw transactions,
provider secrets, or wallet/customer data in reports.

## Negative Tests and HTTP Results

Test missing token (`401`), wrong role or permission (`403`), wrong owner or
officer scope (concealed `404`), invalid product bounds/prerequisites/state
(`400`), unapproved documents at approval (`400`), approval above requested
amount (`400`), disbursement before approval (`400`), unsupported method (`400`),
different payload with a reused idempotency key (`409`), concurrent transition
(`409`), and invalid pagination (`400`). Pre-qualification throttling may return
`429`; disabled external settlement/dependencies may return `503`.

Common diagnoses:

- `401`: use the access token, not refresh token.
- Admin `403`: verify `manage_system`, `manage_loan_officers`, or `view_logs`.
- Officer `404`: assign the application to that exact officer.
- Cannot apply: complete all three profiles and upload resolved product docs.
- Cannot approve: uploaded/pending is insufficient; required docs need approval.
- Wallet `503`: use cash/check or configure every blockchain dependency.
- Duplicate/conflict: same key is only for an exact retry; use a new key for a
  new financial operation.
- Old record unchanged: GET the newly returned application ID; prior records
  retain their own persisted results.

## Automated Verification

Manual Insomnia tests prove the running local stack, not every concurrency or
integration property. From the repository root:

```bash
./.venv/bin/python -m pytest -q tests/test_loans_smoke.py tests/test_loans_api.py
./.venv/bin/python -m pytest -q tests -k "loan or blockchain or qualification or wallet_disbursement or repayment"
```

Plain pytest uses `config.settings_test`. Real-Mongo, Redis/Celery, Ganache, and
deployed probes are opt-in; a skip is not proof that an external integration
works. Never point destructive/concurrency fixtures at production services.

## Manual Checklist

- [ ] All three tokens belong to the intended roles.
- [ ] Customer profiles are complete.
- [ ] Product-required documents exist and are approved before approval.
- [ ] Product is active; amount and term are within bounds.
- [ ] `can_apply` and missing requirements were inspected.
- [ ] New application ID was saved and assigned to the token's officer.
- [ ] Decision and disbursement changed state once.
- [ ] Disbursement replay created no second schedule.
- [ ] Payment changed the intended installment and is customer-visible.
- [ ] Payment replay created no duplicate.
- [ ] Wrong-owner/officer access was denied or concealed.
- [ ] Screenshots/files contain no JWTs, PII, keys, or service credentials.

## Implementation References

- `loans/urls.py`
- `loans/serializers/loan_serializers.py`
- `loans/views/customer/`
- `loans/views/admin/`
- `loans/views/officer/`
- `loans/models/application.py`
- `loans/models/repayment.py`
- `loans/services/qualification.py`
- `loans/services/disbursement.py`
- `loans/services/payment.py`
- `docs/accounts/ACCOUNTS_TESTING_GUIDE.md`
