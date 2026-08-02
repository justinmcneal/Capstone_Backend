# Loan Lifecycle Implementation and Testing Guide

> Updated 2026-08-02 for idempotent cash/check and durable wallet flows. GCash
> and bank-transfer settlement remain intentionally deferred pending a provider.

## Scope
This guide covers loan lifecycle APIs under `/api/loans/`:
- product discovery and pre-qualification
- application submission and review
- assignment and workload management
- disbursement, schedules, and payment recording
- customer follow-up actions (resubmit, feedback)

## Base URL and Auth
- Base URL: `http://localhost:8000/api/loans`
- Required headers:
```http
Authorization: Bearer <access_token>
```
- All endpoints require authenticated JWT.

## Canonical Lifecycle Statuses
Application statuses (`loans/models/application.py`):
- `draft`
- `submitted`
- `under_review`
- `approved`
- `rejected`
- `disbursed`
- `completed`
- `written_off` (reserved for an approved future write-off policy)
- `cancelled`

Installment statuses (`loans/models/repayment.py`):
- `pending`
- `partial`
- `overdue`
- `partial_overdue`
- `paid`

Schedule statuses are `active`, `paid_off`, `restructured`, and `written_off`.
The latter two are reserved states; no restructuring/write-off operation is
available until the institution approves those policies.

Note: UI/API filters also support `pending` as a derived alias for apps in `submitted` or `under_review`.

## Access and Permission Matrix
| Method | Endpoint | Access |
|---|---|---|
| `GET` | `/products/` | Customer |
| `GET` | `/products/<product_id>/` | Customer |
| `POST` | `/pre-qualify/` | Customer |
| `POST` | `/apply/` | Customer |
| `GET` | `/applications/` | Customer |
| `GET` | `/applications/<application_id>/` | Customer (owner) |
| `GET` | `/applications/<application_id>/schedule/` | Customer (owner, disbursed only) |
| `GET` | `/applications/<application_id>/payments/` | Customer (owner) |
| `POST` | `/applications/<application_id>/payments/` | Customer (owner; pending provider claim only) |
| `POST` | `/applications/<application_id>/resubmit/` | Customer (owner, rejected only) |
| `GET` | `/applications/<application_id>/feedback/` | Customer (owner, rejected only) |
| `GET/POST` | `/admin/products/` | Admin + `manage_system` |
| `GET/PUT/DELETE` | `/admin/products/<product_id>/` | Admin + `manage_system` |
| `POST` | `/admin/applications/<application_id>/assign/` | Admin + `manage_loan_officers` |
| `POST` | `/admin/applications/<application_id>/reassign/` | Admin + `manage_loan_officers` |
| `GET` | `/admin/officers/workload/` | Admin + `manage_loan_officers` |
| `GET` | `/officer/applications/` | Loan Officer / Admin (scope-limited for officers) |
| `GET` | `/officer/applications/<application_id>/` | Loan Officer / Admin |
| `POST` | `/officer/applications/<application_id>/notes/` | Loan Officer / Admin |
| `POST` | `/officer/applications/<application_id>/request-missing-documents/` | Loan Officer / Admin |
| `PUT` | `/officer/applications/<application_id>/review/` | Loan Officer / Admin |
| `POST` | `/officer/applications/<application_id>/disburse/` | Loan Officer / Admin |
| `GET/POST` | `/officer/applications/<application_id>/wallet-disbursement/` | Loan Officer / Admin |
| `POST` | `/officer/payments/` | Loan Officer / Admin |
| `GET` | `/officer/active-loans/` | Loan Officer / Admin |
| `GET` | `/officer/applications/<application_id>/schedule/` | Loan Officer / Admin |
| `GET` | `/officer/applications/<application_id>/payments/` | Loan Officer / Admin |
| `GET` | `/officer/payments/search/` | Loan Officer / Admin |
| `GET` | `/officer/payments/recent/` | Loan Officer / Admin |
| `POST` | `/officer/applications/<application_id>/penalties/apply/` | Loan Officer / Admin |
| `POST` | `/officer/applications/<application_id>/penalties/waive/` | Loan Officer / Admin |
| `GET/POST` | `/officer/applications/<application_id>/payoff/` | Loan Officer / Admin |
| `GET` | `/officer/applications/<application_id>/blockchain/` | Loan Officer / Admin |
| `GET` | `/officer/exchange-rate/` | Loan Officer / Admin |
| `GET` | `/officer/schedules/export/` | Loan Officer / Admin |
| `GET` | `/admin/blockchain/transactions/` | Admin |

## Key Endpoint Contracts
1. `POST /pre-qualify/`
- Body:
```json
{
  "product_id": "<id>",
  "amount": 25000,
  "term_months": 12,
  "purpose": "Expand inventory",
  "requirements_scope": "product"
}
```
- `requirements_scope`: `baseline` or `product`.
- Runs basic requirements check first; returns `eligible`, `can_apply`, `missing_requirements`, and qualification output.

2. `POST /apply/`
- Body:
```json
{
  "product_id": "<id>",
  "requested_amount": 25000,
  "term_months": 12,
  "purpose": "Business expansion"
}
```
- Enforces completed profiles + approved required docs before submission.
- Creates application and sets status to `submitted`.

3. `GET /applications/`
- Query params: `search`, `status`, `page`, `page_size`.
- `status=pending` maps to `submitted` + `under_review`.

4. `PUT /officer/applications/<application_id>/review/`
- Body:
```json
{
  "action": "approve",
  "approved_amount": 20000,
  "notes": "Optional"
}
```
or
```json
{
  "action": "reject",
  "rejection_reason": "Required when rejecting",
  "notes": "Optional"
}
```
- Allowed only for `submitted`/`under_review` applications.

5. `POST /officer/applications/<application_id>/disburse/`
- Body:
```json
{
  "amount": 20000,
  "method": "cash",
  "reference": "optional"
}
```
- Required header: `Idempotency-Key: <8-128 characters>`.
- Allowed only when application status is `approved`.
- `cash` and `check` generate the schedule and complete synchronously.
- `wallet` returns `202 pending`; the durable blockchain Celery worker confirms
  ETH and then creates the schedule/completes the loan.
- Wallet recovery is available at
  `GET|POST /officer/applications/<id>/wallet-disbursement/` with `reconcile`,
  `retry`, or safe pre-preparation `cancel` actions. The signed payload is never
  exposed by the API.
- `gcash` and `bank_transfer` remain pending until a provider workflow is added.
- Accepted method values are `bank_transfer`, `cash`, `gcash`, `check`, and
  `wallet`; only cash/check and wallet have completed settlement implementations.

6. `POST /officer/payments/`
- Body:
```json
{
  "loan_id": "<application_id>",
  "installment_number": 1,
  "amount": 2000,
  "payment_method": "cash",
  "reference": "optional",
  "notes": "optional"
}
```
- Required header: `Idempotency-Key: <8-128 characters>`.
- Officer posting accepts `cash` and `check`. Customer GCash/bank claims remain
  pending verification; verified ETH payments use the wallet endpoint.
- Validates installment exists, is not fully paid, and amount does not exceed remaining installment balance.

7. `POST /officer/applications/<application_id>/request-missing-documents/`
- Body:
```json
{
  "missing_documents": ["business_permit"],
  "reason": "Please upload missing permit"
}
```
- Allowed for `submitted` or `under_review`.
- Rejects document types already uploaded.

8. Admin assignment endpoints
- `POST /admin/applications/<application_id>/assign/`
- `POST /admin/applications/<application_id>/reassign/`
- Body:
```json
{ "officer_id": "<officer_id>" }
```

## Officer Search and Filter Notes
1. `GET /officer/applications/`
- Supported filters: `status`, `search`, `min_amount`, `max_amount`, `start_date`, `end_date`, `risk_category`, `page`, `page_size`, `sort_by`, `sort_order`.

2. `GET /officer/payments/search/`
- Supported filters: `search`, `loan_id`, `customer_id`, `disbursed_only`, `payment_status`, `payment_method`, `min_amount`, `max_amount`, `start_date`, `end_date`, `page`, `page_size`, `sort_by`, `sort_order`.

3. `GET /officer/active-loans/`
- Requires either `search` or `customer_id`; otherwise returns empty result set.

## End-to-End Smoke Test
1. Admin creates product via `POST /admin/products/`.
2. Customer confirms products via `GET /products/`.
3. Customer runs `POST /pre-qualify/`.
4. Customer submits `POST /apply/`.
5. Admin assigns the application via `POST /admin/applications/<id>/assign/`.
6. The assigned officer checks `GET /officer/applications/?status=pending`;
   officers cannot inspect or claim unassigned applications.
7. Officer approves via `PUT /officer/applications/<id>/review/`.
8. Officer disburses via `POST /officer/applications/<id>/disburse/`; for wallet,
   wait for `disbursement_status=executed` before reading the schedule.
9. Customer checks schedule via `GET /applications/<id>/schedule/`.
10. Officer records payment via `POST /officer/payments/`.
11. Customer verifies payment history via `GET /applications/<id>/payments/`.
12. Rejection branch: officer rejects, customer checks `GET /applications/<id>/feedback/`, then `POST /applications/<id>/resubmit/`.

## Common Error Cases
1. `400 Bad Request`
- Invalid amount/term, invalid filters, invalid status transitions, missing required review/disbursement/payment fields, overpayment attempt.

2. `401 Unauthorized`
- Missing or invalid JWT.

3. `403 Forbidden`
- Role or permission mismatch, or scope violation.

4. `404 Not Found`
- Product/application/officer/schedule/installment not found.

## References
- `loans/urls.py`
- `loans/models/application.py`
- `loans/models/repayment.py`
- `loans/views/customer/` (`customer_views.py` is an import compatibility facade)
- `loans/views/admin/`
- `loans/views/officer/`
- `loans/services/qualification.py`
- `loans/services/assignment.py`
