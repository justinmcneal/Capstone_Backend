# Loans API Testing Guide

## Scope
This guide documents the Loan service API under `/api/loans/` and provides endpoints, request/response shapes, testing notes, and pointers to on-chain smart contract artifacts included in the repository.

## Base URL and Auth
- Base URL: `http://localhost:8000/api/loans`
- Required headers:
  - `Authorization: Bearer <access_token>`
  - JSON endpoints use `Content-Type: application/json` unless noted (multipart for uploads where applicable).

## Smart Contracts and On-chain Artifacts
- The repository includes ABIs and on-chain integration code under `loans/blockchain/` (see `abis/` JSON files).
- Higher-level smart contract design and testing docs live under `smartcontracts/docs/` (e.g. `TESTING_GUIDE.md`).
- Integration endpoints that surface blockchain info are included in the loans API (see endpoints with `blockchain`/`transactions` in their path).

## Customer Endpoints
- `GET /api/loans/products/`
  - Lists available loan products. Query params: `search`, `page`, `page_size`.
- `GET /api/loans/products/<product_id>/`
  - Product detail.
- `POST /api/loans/pre-qualify/`
  - Body: `{ "product_id": "<id>", "amount": <number>, "term_months": <int>, "purpose": "..." }`
  - Response: eligibility object `{ eligible, can_apply, missing_requirements, details }`.
- `POST /api/loans/apply/`
  - Body: `{ "product_id": "<id>", "requested_amount": <number>, "term_months": <int>, "purpose": "...", "preferred_disbursement_method": "bank_transfer|gcash|cash|check|wallet" }`
  - Creates application; response contains application `id` and `status`.
- `GET /api/loans/applications/`
  - Customer's applications. Query params: `status`, `search`, `page`, `page_size`.
- `GET /api/loans/applications/<application_id>/`
  - Application detail (owner-only).
- `PUT /api/loans/applications/<application_id>/`
  - Edit a draft application and submit (only allowed when application status is `draft`).
- `GET /api/loans/applications/<application_id>/schedule/`
  - Repayment schedule for approved/disbursed apps.
- `GET /api/loans/applications/<application_id>/payments/`
  - Payment history for an application.
- `POST /api/loans/applications/<application_id>/payments/`
  - Record a payment as the customer (only allowed for `disbursed` loans).
  - Body (customer manual payment via bank/cash):
    - `installment_number` (int, required) — installment sequence number (>=1).
    - `amount` (number, required) — amount in PHP (must be > 0).
    - `payment_method` (string, required) — one of `cash`, `gcash`, `bank_transfer`, `check`, `wallet`.
    - `reference` (string, optional) — system or bank reference.
    - `notes` (string, optional).
- `POST /api/loans/applications/<application_id>/resubmit/`
  - Resubmit a rejected application. Body: none — this endpoint resets the application status to `draft`. After this call you must `PUT /api/loans/applications/<id>/` to update fields and re-submit.
- `GET /api/loans/applications/<application_id>/feedback/`
  - Rejection feedback for a rejected application.
- `POST /api/loans/applications/<application_id>/set-disbursement-method/`
  - Set preferred disbursement method for an application.
  - Body:
    - `disbursement_method` (string, required) — one of `cash`, `gcash`, `bank_transfer`, `check`, `wallet`.
- `GET /api/loans/applications/<application_id>/blockchain/`
  - Returns on-chain transaction/status for this application (if applicable).
- `POST /api/loans/applications/<application_id>/wallet-payment/`
  - Trigger a wallet payment for this application.
  - Body:
    - `tx_hash` (string, required) — ETH tx hash (must start with `0x` and be 66 chars long).
    - `installment_number` (int, required) — installment being paid (>=1).
- `GET /api/loans/system-wallet/`
  - System wallet info (balances, supported currencies).

Detailed request field reference for Customer endpoints:

- `POST /api/loans/pre-qualify/` (PreQualifyRequestSerializer)
  - `product_id`: string (required) — product identifier.
  - `amount`: number (required, min_value=1000) — requested amount in PHP.
  - `term_months`: integer (optional, default=12, min_value=1) — term length in months.
  - `purpose`: string (optional, max_length=500) — purpose text.
  - `requirements_scope`: string (optional, choices: `baseline`, `product`) — scope used to resolve document requirements.

- `POST /api/loans/apply/` (LoanApplicationSerializer)
  - `product_id`: string (required).
  - `requested_amount`: number (required, min_value=1000) — must be within product min/max.
  - `term_months`: integer (required, min_value=1) — must be within product min/max.
  - `purpose`: string (optional, max_length=500).
  - `preferred_disbursement_method`: string (optional, choices: `cash`,`gcash`,`bank_transfer`,`check`,`wallet`).

- `PUT /api/loans/applications/<id>/` (partial update expected)
  - Allowed editable fields (when `status == 'draft'` or partial update allowed by view):
    - `requested_amount` (number) — validated against product limits.
    - `term_months` (int).
    - `purpose` (string).
    - `preferred_disbursement_method` (string — same choices as above).

- `POST /api/loans/applications/<id>/payments/` (customer manual payments — shared with officer flow)
  - `installment_number`: integer (required)
  - `amount`: number (required, >0)
  - `payment_method`: string (required; allowed: `cash`,`gcash`,`bank_transfer`,`check`,`wallet`)
  - `reference`: string (optional)
  - `notes`: string (optional)

- `POST /api/loans/applications/<id>/wallet-payment/` (WalletPaymentView)
  - `tx_hash`: string (required) — must be 66-char `0x` prefixed hex string.
  - `installment_number`: integer (required, >=1)

## Admin Endpoints
- `GET/POST /api/loans/admin/products/`
  - Manage loan products.
- `GET/PUT/DELETE /api/loans/admin/products/<product_id>/`
  - Product admin operations.
- `POST /api/loans/admin/applications/<application_id>/assign/`
  - Body: `{ "officer_id": "<id>" }`.
- `POST /api/loans/admin/applications/<application_id>/reassign/`
  - Body: `{ "officer_id": "<id>" }`.
- `GET /api/loans/admin/officers/workload/`
  - Officer workload summary.
- `GET /api/loans/admin/blockchain/transactions/`
  - Admin view of blockchain transactions (filter by type/date/status).

## Loan Officer Endpoints
- `GET /api/loans/officer/applications/`
  - Officers see scoped applications. Query params: `status`, `search`, `page`, `page_size`.
- `GET /api/loans/officer/applications/<application_id>/`
  - Officer application detail.
- `POST /api/loans/officer/applications/<application_id>/notes/`
  - Add internal notes.
- `POST /api/loans/officer/applications/<application_id>/request-missing-documents/`
  - Request missing documents from customer: `{ "missing_documents": [...], "reason": "..." }`.
- `PUT /api/loans/officer/applications/<application_id>/review/`
  - Body: `{ "action": "approve"|"reject", "approved_amount"?: number, "rejection_reason"?: string, "notes"?: string }`.
- `POST /api/loans/officer/applications/<application_id>/disburse/`
  - Disburse funds (triggers on-chain transfer when configured).
  - Body: `{ "amount": <number>, "method": "bank_transfer"|"wallet"|... , "reference": "..." }`
- `POST /api/loans/officer/payments/`
  - Record a payment on behalf of a customer.
- `GET /api/loans/officer/payments/search/`
  - Search payments.
- `GET /api/loans/officer/active-loans/`
  - Currently active loans filtered by scope.
- `GET /api/loans/officer/applications/<application_id>/schedule/`
  - Officer view of repayment schedule.
 - `GET /api/loans/officer/applications/<application_id>/payments/`
   - Officer view of payment history for a specific application.
- `POST /api/loans/officer/applications/<application_id>/penalties/apply/`
  - Apply penalty to an installment.
- `POST /api/loans/officer/applications/<application_id>/penalties/waive/`
  - Waive a penalty.
- `GET /api/loans/officer/applications/<application_id>/blockchain/`
  - Officer-facing blockchain status for application.
- `GET /api/loans/officer/exchange-rate/`
  - Current exchange rate endpoint used by officer workflows.

## Request/Response Patterns
- Authentication: JWT bearer token required for all endpoints.
- Pagination: `page`, `page_size` (max 200).
- Errors follow standard `{ "status": "error", "message": "...", "errors": { ... } }`.

Detailed request field reference for Admin endpoints:

- `POST /api/loans/admin/products/` and `PUT /api/loans/admin/products/<id>/` (LoanProductSerializer)
  - `name` (string, required on create) — product name.
  - `code` (string, required on create) — unique product code.
  - `description` (string, optional).
  - `min_amount` (number, required) — minimum loan amount (>=0).
  - `max_amount` (number, required) — maximum loan amount (>=0; must be >= `min_amount`).
  - `interest_rate` (number, required) — decimal (0.0–100.0) representing proportion (e.g., 0.02 = 2%).
  - `min_term_months` (int, required) — minimum term in months (>=1).
  - `max_term_months` (int, required) — maximum term in months (>=1; must be >= `min_term_months`).
  - `required_documents` (list[string], optional) — document type keys from `documents.models.DOCUMENT_TYPES`.
  - `min_business_months` (int, optional) — required months in business.
  - `min_monthly_income` (number, optional).
  - `business_types` (list[string], optional).
  - `target_description` (string, optional).
  - `active` (boolean, optional).

Detailed request field reference for Officer endpoints:

- `GET /api/loans/officer/applications/` (query params)
  - `status` (string) — one of `pending`,`mine`,`submitted`,`under_review`,`approved`,`rejected`,`disbursed`,`all`.
  - `search` (string) — free text for customer/product/ID.
  - `min_amount` / `max_amount` (number) — amount range filters.
  - `start_date` / `end_date` (string, `YYYY-MM-DD`) — submission date range.
  - `risk_category` (string) — `low`|`medium`|`high`.
  - `page`, `page_size`, `sort_by` (`submitted_at`,`requested_amount`,`eligibility_score`,`created_at`), `sort_order` (`asc`|`desc`).

- `POST /api/loans/officer/applications/<id>/notes/` (ApplicationInternalNoteSerializer)
  - `note` (string, required, max_length=1000)

- `POST /api/loans/officer/applications/<id>/request-missing-documents/` (MissingDocumentsRequestSerializer)
  - `missing_documents` (list[string], required) — must be valid document type keys.
  - `reason` (string, optional)

- `PUT /api/loans/officer/applications/<id>/review/` (LoanReviewSerializer)
  - `action` (string, required) — `approve` or `reject`.
  - `approved_amount` (number, required if `action=='approve`) — must be <= requested amount and within product bounds.
  - `rejection_reason` (string, required if `action=='reject'`).
  - `notes` (string, optional)

- `POST /api/loans/officer/applications/<id>/disburse/` (DisburseView)
  - `amount` (number, required) — disbursement amount (>0).
  - `method` (string, required) — one of: `cash`, `gcash`, `bank_transfer`, `check`, `wallet`.
  - `reference` (string, optional) — officer/bank reference.
  - `external_reference` (string, optional)

- `POST /api/loans/officer/payments/` (RecordPaymentView)
  - `loan_id` (string, required)
  - `installment_number` (int, required)
  - `amount` (number, required)
  - `payment_method` (string, required) — officer manual recording accepts `cash` or `check` only.
  - `reference` / `external_reference` (string, optional)
  - `notes` (string, optional)

- `POST /api/loans/officer/applications/<id>/penalties/apply/`
  - `installment_number` (int, required)
  - `penalty_amount` (number, required, >0)
  - `reason` (string, optional)

- `POST /api/loans/officer/applications/<id>/penalties/waive/`
  - `installment_number` (int, required)
  - `reason` (string, optional)

## Quick reference: all request/body fields across the Loans API (alphabetical)

- `action` — (`approve`|`reject`) used in officer reviews.
- `amount` — numeric currency value in PHP. Context-specific (apply/request/disburse/payment).
- `approved_amount` — numeric (officer approval).
- `business_types` — list[string] for product creation.
- `code` — product code (admin).
- `disbursement_method` / `preferred_disbursement_method` — `cash|gcash|bank_transfer|check|wallet`.
- `external_reference` — optional string for bank/check refs.
- `installment_number` — integer >=1.
- `interest_rate` — decimal number for product (0.0–100.0).
- `loan_id` — application id / loan id string.
- `missing_documents` — list[string], document type keys.
- `min_amount` / `max_amount` — numeric filters or product bounds.
- `name` — product name.
- `notes` — free-text notes.
- `officer_id` — officer id string (ObjectId format expected).
- `page` / `page_size` — pagination ints.
- `payment_method` — string; allowed values depend on endpoint.
- `penalty_amount` — number when applying penalty.
- `product_id` — product id string.
- `purpose` — string, optional, max_length per serializer.
- `reference` — string reference for payments/disbursements.
- `requirements_scope` — `baseline`|`product`.
- `rejection_reason` — string (required on reject).
- `required_documents` — list[string] product-level field.
- `term_months` / `min_term_months` / `max_term_months` — integer months.
- `tx_hash` — ETH transaction hash (0x-prefixed, 66 chars).


## Smart Contract / Blockchain Notes
- ABIs and contract artifacts live under `loans/blockchain/abis/`.
- On-chain integration helpers are in `loans/blockchain/` and `loans/blockchain/sync.py`.
- For testing on a local chain, see `smartcontracts/docs/TESTNET_DEPLOYMENT_GUIDE.md` and `smartcontracts/docs/TESTING_GUIDE.md`.
- Admin endpoints expose blockchain transactions and sync status for reconciliation.

## Smoke Test Sequence
1. Create a product (admin) via `POST /api/loans/admin/products/` (or use existing product).
2. As a customer, `POST /api/loans/pre-qualify/` and inspect `eligible` response.
3. `POST /api/loans/apply/` to create an application and confirm `status: submitted`.
4. Officer: `GET /api/loans/officer/applications/?status=pending` to find application.
5. Officer: `PUT /api/loans/officer/applications/<id>/review/` to approve.
6. Officer: `POST /api/loans/officer/applications/<id>/disburse/` — if blockchain enabled, verify on-chain tx via `GET /api/loans/admin/blockchain/transactions/` or `GET /api/loans/officer/applications/<id>/blockchain/`.
7. Customer: `GET /api/loans/applications/<id>/schedule/` and `GET /api/loans/applications/<id>/payments/` to verify repayment schedule and history.

## Common Error Cases
- `400 Bad Request` — invalid payloads, invalid status transitions.
- `401 Unauthorized` — missing/invalid JWT.
- `403 Forbidden` — role or permission mismatch or ABAC scope violations.
- `404 Not Found` — application/product/record not found.
- `409 Conflict` — duplicate or already-processed operations (e.g., double disburse).

## Where to look in code
- URLs: `loans/urls.py`
- Views: `loans/views/` (customer/admin/officer split)
- Models: `loans/models/`
- Serializers: `loans/serializers/`
- Blockchain: `loans/blockchain/` and `smartcontracts/docs/`

## Notes for API tests
- Seed test data for products and application states; create minimal customer and officer accounts with JWTs.
- For blockchain-enabled tests, run a local testnet or mock the blockchain client in `loans/blockchain/client.py`.
- Use `page_size` small values to simplify assertions and verify pagination metadata.

