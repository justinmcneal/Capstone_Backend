# Loan Lifecycle Implementation and Testing Guide

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
- `cancelled`

Installment statuses (`loans/models/repayment.py`):
- `pending`
- `paid`
- `overdue`
- `partial`

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
| `POST` | `/officer/payments/` | Loan Officer / Admin |
| `GET` | `/officer/active-loans/` | Loan Officer / Admin |
| `GET` | `/officer/applications/<application_id>/schedule/` | Loan Officer / Admin |
| `GET` | `/officer/applications/<application_id>/payments/` | Loan Officer / Admin |
| `GET` | `/officer/payments/search/` | Loan Officer / Admin |

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
  "method": "bank_transfer",
  "reference": "optional"
}
```
- Allowed only when application status is `approved`.
- Generates repayment schedule automatically on success.
- Accepted methods in view validation: `bank_transfer`, `cash`, `gcash`, `check`, `other`.

6. `POST /officer/payments/`
- Body:
```json
{
  "loan_id": "<application_id>",
  "installment_number": 1,
  "amount": 2000,
  "payment_method": "gcash",
  "reference": "optional",
  "notes": "optional"
}
```
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
5. Officer checks queue via `GET /officer/applications/?status=pending`.
6. Admin assigns app via `POST /admin/applications/<id>/assign/` (or officer picks from scope).
7. Officer approves via `PUT /officer/applications/<id>/review/`.
8. Officer disburses via `POST /officer/applications/<id>/disburse/`.
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
- `loans/views/customer_views.py`
- `loans/views/admin_views.py`
- `loans/views/officer_views.py`
- `loans/services/qualification.py`
- `loans/services/assignment.py`
