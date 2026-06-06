# Loans API Testing Guide

## Scope

This guide documents the **Loans service API** under `/api/loans/` for API testing. It covers:

- All customer, admin, and loan officer endpoints
- Every request body field, query parameter, and key response field
- Smart contract / blockchain integration triggered by loan lifecycle actions

**Yes — the loans API is integrated with on-chain smart contracts.** When `BLOCKCHAIN_ENABLED=true`, key lifecycle events (submit, approve, reject, disburse, schedule, payment, penalty) are synced to Ethereum contracts in background threads via `loans/blockchain/sync.py`. Blockchain status can be queried through dedicated endpoints.

## Base URL and Auth

- **Base URL:** `http://localhost:8000/api/loans`
- **Required headers:**
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```
- **Roles:**
  - Customer endpoints → `customer` role JWT
  - Admin endpoints → `admin` role JWT (with specific permissions noted per endpoint)
  - Loan officer endpoints → `loan_officer` or `admin` role JWT

## Related Documentation

| Document | Purpose |
|----------|---------|
| `docs/BLOCKCHAIN_TESTING_GUIDE.md` | Blockchain integration testing |
| `docs/BLOCKCHAIN_SMART_CONTRACTS_GUIDE.md` | Smart contract overview |
| `smartcontracts/docs/TESTING_GUIDE.md` | On-chain contract unit tests |
| `smartcontracts/docs/TESTNET_DEPLOYMENT_GUIDE.md` | Local testnet setup |
| `docs/LOAN_LIFECYCLE_TESTING_GUIDE.md` | End-to-end loan lifecycle |
| `docs/PROFILES_API_TESTING_GUIDE.md` | Profile prerequisites for loan eligibility |

## Reference Values

### Application Statuses

`draft`, `submitted`, `under_review`, `approved`, `rejected`, `disbursed`, `cancelled`

Customer list filter alias: `pending` → matches `submitted` + `under_review`

### Disbursement / Payment Methods

`cash`, `gcash`, `bank_transfer`, `check`, `wallet`

### Document Types (for `required_documents` / `missing_documents`)

`valid_id`, `selfie_with_id`, `proof_of_address`, `business_permit`, `business_photo`, `income_proof`, `other`

### Risk Categories

`low`, `medium`, `high`

### Blockchain Transaction Actions (admin filter)

`submit`, `approve`, `reject`, `disburse`, `schedule`, `payment`

### Blockchain Transaction Statuses (admin filter)

`confirmed`, `pending`, `failed`

---

## Smart Contract Integration Map

When blockchain is enabled, these API actions trigger on-chain sync (non-blocking background thread):

| API Action | On-chain Action | Contract Area |
|------------|-----------------|---------------|
| `POST /apply/` | `submit` | LoanApplication |
| `PUT /officer/.../review/` (approve) | `approve` | LoanApproval |
| `PUT /officer/.../review/` (reject) | `reject` | LoanReview |
| `POST /officer/.../disburse/` | `disburse` + `schedule` | DisbursementExecution, Repayment |
| `POST .../payments/` (customer or officer) | `payment` | PaymentRecording |
| `POST /officer/.../penalties/apply/` | penalty apply | AuditRegistry |
| `POST /officer/.../penalties/waive/` | penalty waive | AuditRegistry |
| `POST .../wallet-payment/` | `payment` (after on-chain ETH verification) | PaymentRecording |

ABIs live in `loans/blockchain/abis/`. Solidity sources in `smartcontracts/contracts/`.

---

# Customer Endpoints

Auth: **customer only** for all endpoints below.

---

### 1. `GET /products/`

List active loan products.

**Query params (all optional):**

| Field | Type | Notes |
|-------|------|-------|
| `search` | string | Not implemented in view (reserved) |
| `page` | int | Not paginated in view — returns all active products |
| `page_size` | int | Not paginated in view |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `products` | array |
| `products[].id` | string |
| `products[].name` | string |
| `products[].code` | string |
| `products[].description` | string |
| `products[].min_amount` | number |
| `products[].max_amount` | number |
| `products[].interest_rate` | number (decimal, monthly) |
| `products[].interest_rate_unit` | string (`decimal`) |
| `products[].interest_rate_period` | string (`monthly`) |
| `products[].interest_rate_display` | string |
| `products[].min_term_months` | int |
| `products[].max_term_months` | int |
| `products[].required_documents` | array[string] |
| `products[].target_description` | string |
| `total` | int |

---

### 2. `GET /products/<product_id>/`

Product detail.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `product_id` | string | yes |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `name` | string |
| `code` | string |
| `description` | string |
| `min_amount` | number |
| `max_amount` | number |
| `interest_rate` | number |
| `interest_rate_unit` | string |
| `interest_rate_period` | string |
| `interest_rate_display` | string |
| `min_term_months` | int |
| `max_term_months` | int |
| `required_documents` | array[string] |
| `min_business_months` | int |
| `min_monthly_income` | number |
| `target_description` | string |

---

### 3. `POST /pre-qualify/`

AI-assisted eligibility check (rate-limited).

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `product_id` | string | **yes** | Must exist and be active |
| `amount` | number | **yes** | min 1000; within product min/max |
| `term_months` | int | no | default 12; min 1; within product min/max term |
| `purpose` | string | no | max 500 chars |
| `requirements_scope` | string | no | `baseline` or `product` (default `product`) |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `product.id` | string |
| `product.name` | string |
| `requested_amount` | number |
| `term_months` | int |
| `eligible` | boolean |
| `eligibility_score` | number |
| `risk_category` | string |
| `recommended_amount` | number |
| `interest_rate` | number |
| `interest_rate_unit` | string |
| `interest_rate_period` | string |
| `interest_rate_display` | string |
| `monthly_payment` | number |
| `total_interest` | number |
| `total_repayment` | number |
| `reasoning` | string |
| `strengths` | array |
| `concerns` | array |
| `missing_requirements` | array |
| `can_apply` | boolean |
| `requirements_scope` | string |
| `required_documents_resolved` | array |

---

### 4. `POST /apply/`

Submit a new loan application. Triggers blockchain `submit` sync when enabled.

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `product_id` | string | **yes** | Active product |
| `requested_amount` | number | **yes** | min 1000; within product min/max |
| `term_months` | int | **yes** | min 1; within product min/max |
| `purpose` | string | no | max 500 chars |
| `preferred_disbursement_method` | string | no | `cash`, `gcash`, `bank_transfer`, `check`, `wallet` |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `application_id` | string |
| `status` | string |
| `eligibility_score` | number |
| `recommended_amount` | number |
| `message` | string |

---

### 5. `GET /applications/`

List customer's own applications.

**Query params (all optional):**

| Field | Type | Validation |
|-------|------|------------|
| `status` | string | One of: `draft`, `submitted`, `under_review`, `approved`, `rejected`, `disbursed`, `cancelled`, `pending` |
| `search` | string | Case-insensitive product name search |
| `page` | int | min 1 (default 1) |
| `page_size` | int | min 1, max 100 (default 20) |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `applications` | array |
| `applications[].id` | string |
| `applications[].product_name` | string |
| `applications[].requested_amount` | number |
| `applications[].recommended_amount` | number |
| `applications[].approved_amount` | number |
| `applications[].term_months` | int |
| `applications[].status` | string |
| `applications[].eligibility_score` | number |
| `applications[].submitted_at` | ISO datetime |
| `applications[].created_at` | ISO datetime |
| `total` | int |
| `page` | int |
| `page_size` | int |
| `total_pages` | int |
| `has_next` | boolean |
| `has_previous` | boolean |

---

### 6. `GET /applications/<application_id>/`

Application detail (owner only).

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `product.id` | string |
| `product.name` | string |
| `requested_amount` | number |
| `recommended_amount` | number |
| `approved_amount` | number |
| `term_months` | int |
| `interest_rate` | number (monthly %) |
| `purpose` | string |
| `status` | string |
| `eligibility_score` | number |
| `risk_category` | string |
| `rejection_reason` | string |
| `submitted_at` | ISO datetime |
| `decision_date` | ISO datetime |
| `preferred_disbursement_method` | string |
| `disbursed_at` | ISO datetime |
| `created_at` | ISO datetime |

---

### 7. `PUT /applications/<application_id>/`

Edit and re-submit a **draft** application.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:** Same fields as `POST /apply/` (full body required by serializer)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `product_id` | string | **yes** | Must match original draft product (cannot change) |
| `requested_amount` | number | **yes** | min 1000 |
| `term_months` | int | **yes** | min 1 |
| `purpose` | string | no | max 500 |
| `preferred_disbursement_method` | string | no | disbursement method choices |

**Response fields:** Same as endpoint 6 (full application detail).

**Precondition:** `status` must be `draft`.

---

### 8. `GET /applications/<application_id>/schedule/`

Repayment schedule for a disbursed loan.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Precondition:** `status` must be `disbursed`.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `loan_id` | string |
| `principal` | number |
| `interest_rate` | number |
| `term_months` | int |
| `monthly_payment` | number |
| `total_amount` | number |
| `total_interest` | number |
| `paid_count` | int |
| `remaining_balance` | number |
| `next_payment` | object |
| `installments` | array |
| `installments[].number` | int |
| `installments[].due_date` | ISO datetime |
| `installments[].principal` | number |
| `installments[].interest` | number |
| `installments[].total_amount` | number |
| `installments[].status` | string |
| `installments[].paid_amount` | number |
| `installments[].penalty_status` | string |
| `installments[].penalty_amount` | number |
| `installments[].penalty_reason` | string |
| `installments[].penalty_applied_at` | ISO datetime |
| `installments[].penalty_applied_by` | string |
| `installments[].penalty_waived_at` | ISO datetime |
| `installments[].penalty_waived_by` | string |
| `installments[].penalty_waived_reason` | string |

---

### 9. `GET /applications/<application_id>/payments/`

Payment history.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `payments` | array |
| `payments[].id` | string |
| `payments[].amount` | number |
| `payments[].installment_number` | int |
| `payments[].payment_method` | string |
| `payments[].reference` | string |
| `payments[].recorded_at` | ISO datetime |
| `total_paid` | number |
| `count` | int |

---

### 10. `POST /applications/<application_id>/payments/`

Record a customer payment (non-cash/check). Triggers blockchain `payment` sync.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `installment_number` | int | **yes** | >= 1 |
| `amount` | number | **yes** | > 0; must not exceed remaining installment balance |
| `payment_method` | string | **yes** | `gcash`, `bank_transfer`, or `wallet` only (cash/check rejected) |
| `reference` | string | no | Auto-generated if omitted |
| `notes` | string | no | |

**Precondition:** `status` must be `disbursed`.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `payment_id` | string |
| `loan_id` | string |
| `installment_number` | int |
| `amount` | number |
| `payment_method` | string |
| `reference` | string |
| `recorded_at` | ISO datetime |
| `installment_status` | string |
| `remaining_balance` | number |
| `skipped_installments` | int |

---

### 11. `POST /applications/<application_id>/resubmit/`

Reset a rejected application to draft.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:** none

**Precondition:** `status` must be `rejected`.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `status` | string (`draft`) |
| `message` | string |

---

### 12. `GET /applications/<application_id>/feedback/`

AI-generated rejection feedback.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Precondition:** `status` must be `rejected`.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `rejection_reason` | string |
| `feedback` | string |
| `can_resubmit` | boolean |

---

### 13. `POST /applications/<application_id>/set-disbursement-method/`

Set preferred disbursement method after approval.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `disbursement_method` | string | **yes** | `cash`, `gcash`, `bank_transfer`, `check`, `wallet` |

**Allowed application statuses:** `submitted`, `under_review`, `approved` (and legacy `pending` if present)

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `status` | string |
| `preferred_disbursement_method` | string |

---

### 14. `GET /applications/<application_id>/blockchain/`

Blockchain transaction status for own application.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes (valid ObjectId) |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `application_id` | string |
| `blockchain_enabled` | boolean |
| `explorer_url` | string |
| `tx_hashes` | object (action → tx_hash map) |
| `transactions` | array (when blockchain enabled) |
| `transactions[].tx_hash` | string |
| `transactions[].contract_name` | string |
| `transactions[].method` | string |
| `transactions[].loan_id` | string |
| `transactions[].action` | string |
| `transactions[].status` | string |
| `transactions[].gas_used` | int |
| `transactions[].gas_price` | int |
| `transactions[].block_number` | int |
| `transactions[].error` | string |
| `transactions[].details` | object |
| `transactions[].created_at` | ISO datetime |
| `transactions[].completed_at` | ISO datetime |
| `audit_trail` | array (when blockchain enabled) |

---

### 15. `POST /applications/<application_id>/wallet-payment/`

Verify on-chain ETH payment and record installment. Triggers blockchain `payment` sync.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `tx_hash` | string | **yes** | `0x` prefix, exactly 66 chars |
| `installment_number` | int | **yes** | >= 1 |

**Preconditions:**
- `status` must be `disbursed`
- Customer profile must have `wallet_address` set
- ETH tx must be confirmed, sent from customer wallet to system wallet
- PHP equivalent must be within ±2% of installment amount (min ₱100)

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `status` | string (`verified`) |
| `payment_id` | string |
| `installment_number` | int |
| `installment_status` | string |
| `amount_php` | number |
| `amount_eth` | string |
| `eth_rate` | number |
| `tx_hash` | string |
| `block_number` | int |
| `remaining_balance` | number |
| `blockchain_sync_status` | string |
| `blockchain_sync_message` | string |

---

### 16. `GET /system-wallet/`

System wallet address and ETH/PHP rate for WalletConnect payments.

**Request body:** none

**Precondition:** `BLOCKCHAIN_ENABLED=true` and exchange rate available.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `wallet_address` | string |
| `chain_id` | int |
| `rpc_url` | string |
| `eth_php_rate` | number |
| `rate_source` | string |
| `rate_cached_at` | ISO datetime |
| `rate_updated_at` | ISO datetime |

---

# Admin Endpoints

Auth: **admin** role with specific permissions.

---

### 17. `GET /admin/products/`

List all loan products (including inactive).

**Permission:** `manage_system`

**Query params (all optional):**

| Field | Type | Validation |
|-------|------|------------|
| `active` | string | `true`, `false`, or `all` (default shows all) |
| `search` | string | Filter by name or code |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `products` | array |
| `products[].id` | string |
| `products[].name` | string |
| `products[].code` | string |
| `products[].description` | string |
| `products[].min_amount` | number |
| `products[].max_amount` | number |
| `products[].interest_rate` | number |
| `products[].min_term_months` | int |
| `products[].max_term_months` | int |
| `products[].required_documents` | array[string] |
| `products[].min_business_months` | int |
| `products[].min_monthly_income` | number |
| `products[].business_types` | array[string] |
| `products[].target_description` | string |
| `products[].active` | boolean |
| `products[].created_at` | ISO datetime |
| `total` | int |

---

### 18. `POST /admin/products/`

Create a loan product.

**Permission:** `manage_system`

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `name` | string | **yes** | max 100; unique among active products |
| `code` | string | **yes** | max 20; unique |
| `description` | string | no | max 1000 |
| `min_amount` | number | **yes** | >= 0 |
| `max_amount` | number | **yes** | >= min_amount |
| `interest_rate` | number | **yes** | 0.0–100.0 (decimal monthly rate, e.g. 0.02 = 2%) |
| `min_term_months` | int | **yes** | >= 1 |
| `max_term_months` | int | **yes** | >= min_term_months |
| `required_documents` | array[string] | no | Document type keys |
| `min_business_months` | int | no | >= 0 |
| `min_monthly_income` | number | no | >= 0 |
| `business_types` | array[string] | no | |
| `target_description` | string | no | |
| `active` | boolean | no | |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `code` | string |
| `name` | string |

---

### 19. `GET /admin/products/<product_id>/`

Get product by ID.

**Permission:** `manage_system`

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `product_id` | string | yes |

**Response fields:** Same as single item in endpoint 17.

---

### 20. `PUT /admin/products/<product_id>/`

Update product (partial update supported).

**Permission:** `manage_system`

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `product_id` | string | yes |

**Request body (all optional, at least one field):**

| Field | Type | Validation |
|-------|------|------------|
| `name` | string | max 100 |
| `description` | string | max 1000 |
| `min_amount` | number | >= 0 |
| `max_amount` | number | >= min_amount |
| `interest_rate` | number | 0.0–100.0 |
| `min_term_months` | int | >= 1 |
| `max_term_months` | int | >= min_term_months |
| `required_documents` | array[string] | |
| `min_business_months` | int | >= 0 |
| `min_monthly_income` | number | >= 0 |
| `business_types` | array[string] | |
| `target_description` | string | |
| `active` | boolean | |

**Note:** Cannot edit if product has active loan applications. `code` is not updatable.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |

---

### 21. `DELETE /admin/products/<product_id>/`

Soft-delete (deactivate) product.

**Permission:** `manage_system`

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `product_id` | string | yes |

**Precondition:** No active loans on product.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `code` | string |
| `active` | boolean |

---

### 22. `POST /admin/applications/<application_id>/assign/`

Manually assign application to a loan officer.

**Permission:** `manage_loan_officers`

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `officer_id` | string | **yes** | Valid MongoDB ObjectId |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `application_id` | string |
| `assigned_officer` | string |
| `officer_name` | string |
| `status` | string |

---

### 23. `POST /admin/applications/<application_id>/reassign/`

Reassign application to a different officer.

**Permission:** `manage_loan_officers`

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `officer_id` | string | **yes** | Valid MongoDB ObjectId |

**Response fields:** Same as endpoint 22.

---

### 24. `GET /admin/officers/workload/`

Officer workload, pending applications, and assigned applications.

**Permission:** `manage_loan_officers`

**Query params (all optional):**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `search` | string | | Officer name/email filter |
| `page` | int | 1 | >= 1 |
| `page_size` | int | 20 | 1–100 |
| `pending_search` | string | | Pending apps search |
| `pending_page` | int | 1 | >= 1 |
| `pending_page_size` | int | 20 | 1–100 |
| `assigned_search` | string | | Assigned apps search |
| `assigned_page` | int | 1 | >= 1 |
| `assigned_page_size` | int | 20 | 1–100 |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `officers` | array |
| `officers[].id` | string |
| `officers[].name` | string |
| `officers[].email` | string |
| `officers[].assigned_count` | int |
| `officers[].pending_count` | int |
| `total` | int |
| `page` | int |
| `page_size` | int |
| `total_pages` | int |
| `pending_applications` | array |
| `pending_applications[].id` | string |
| `pending_applications[].customer_id` | string |
| `pending_applications[].customer_name` | string |
| `pending_applications[].requested_amount` | number |
| `pending_applications[].term_months` | int |
| `pending_applications[].status` | string |
| `pending_applications[].eligibility_score` | number |
| `pending_applications[].risk_category` | string |
| `pending_applications[].assigned_officer` | string |
| `pending_applications[].assigned_officer_name` | string |
| `pending_applications[].submitted_at` | ISO datetime |
| `pending_applications[].internal_notes_count` | int |
| `pending_applications[].latest_internal_note` | object |
| `pending_count` | int |
| `pending_page` | int |
| `pending_page_size` | int |
| `pending_total_pages` | int |
| `assigned_applications` | array (same shape as pending) |
| `assigned_count` | int |
| `assigned_page` | int |
| `assigned_page_size` | int |
| `assigned_total_pages` | int |

---

### 25. `GET /admin/blockchain/transactions/`

Admin view of all blockchain transactions.

**Permission:** `view_logs`

**Query params (all optional):**

| Field | Type | Validation |
|-------|------|------------|
| `action` | string | `submit`, `approve`, `reject`, `disburse`, `schedule`, `payment` |
| `status` | string | `confirmed`, `pending`, `failed` |
| `search` | string | Search `tx_hash` or `loan_id` |
| `start_date` | string | `YYYY-MM-DD` |
| `end_date` | string | `YYYY-MM-DD` |
| `page` | int | default 1 |
| `page_size` | int | 1–100, default 20 |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `transactions` | array |
| `transactions[].id` | string |
| `transactions[].tx_hash` | string |
| `transactions[].contract_name` | string |
| `transactions[].method` | string |
| `transactions[].loan_id` | string |
| `transactions[].action` | string |
| `transactions[].status` | string |
| `transactions[].gas_used` | int |
| `transactions[].gas_price` | int |
| `transactions[].block_number` | int |
| `transactions[].error` | string |
| `transactions[].created_at` | ISO datetime |
| `transactions[].completed_at` | ISO datetime |
| `total` | int |
| `page` | int |
| `page_size` | int |
| `total_pages` | int |

---

# Loan Officer Endpoints

Auth: **loan_officer** or **admin**. Loan officers are ABAC-scoped to their assigned applications only.

---

### 26. `GET /officer/applications/`

List/search applications with advanced filters.

**Query params:**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `status` | string | `pending` | `pending`, `mine`, `submitted`, `under_review`, `approved`, `rejected`, `disbursed`, `all` |
| `search` | string | | Customer name/phone/email, product name, or app ID |
| `min_amount` | number | | |
| `max_amount` | number | | must be >= min_amount |
| `start_date` | string | | `YYYY-MM-DD` |
| `end_date` | string | | `YYYY-MM-DD` |
| `risk_category` | string | | `low`, `medium`, `high` |
| `page` | int | 1 | >= 1 |
| `page_size` | int | 20 | 1–100 |
| `sort_by` | string | `submitted_at` | `submitted_at`, `requested_amount`, `eligibility_score`, `created_at` |
| `sort_order` | string | `desc` | `asc`, `desc` |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `applications` | array |
| `applications[].id` | string |
| `applications[].customer_id` | string |
| `applications[].customer_name` | string |
| `applications[].product_name` | string |
| `applications[].requested_amount` | number |
| `applications[].recommended_amount` | number |
| `applications[].approved_amount` | number |
| `applications[].term_months` | int |
| `applications[].status` | string |
| `applications[].eligibility_score` | number |
| `applications[].risk_category` | string |
| `applications[].assigned_officer` | string |
| `applications[].assigned_officer_name` | string |
| `applications[].submitted_at` | ISO datetime |
| `applications[].decision_date` | ISO datetime |
| `applications[].internal_notes_count` | int |
| `applications[].latest_internal_note` | object |
| `total` | int |
| `page` | int |
| `page_size` | int |
| `total_pages` | int |

---

### 27. `GET /officer/applications/<application_id>/`

Full application detail with customer profiles and documents.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `customer_id` | string |
| `customer_name` | string |
| `product.id` | string |
| `product.name` | string |
| `product.code` | string |
| `product.required_documents` | array |
| `requested_amount` | number |
| `recommended_amount` | number |
| `approved_amount` | number |
| `term_months` | int |
| `purpose` | string |
| `status` | string |
| `eligibility_score` | number |
| `risk_category` | string |
| `ai_recommendation` | object |
| `assigned_officer` | string |
| `assigned_officer_name` | string |
| `officer_notes` | string |
| `rejection_reason` | string |
| `submitted_at` | ISO datetime |
| `decision_date` | ISO datetime |
| `disbursed_amount` | number |
| `preferred_disbursement_method` | string |
| `disbursement_method` | string |
| `disbursement_reference` | string |
| `disbursed_at` | ISO datetime |
| `eth_disbursement_tx_hash` | string |
| `eth_disbursement_amount` | string |
| `eth_disbursement_rate` | number |
| `eth_disbursement_recipient` | string |
| `internal_notes` | array |
| `internal_notes_count` | int |
| `latest_internal_note` | object |
| `missing_documents_requested` | array |
| `missing_documents_reason` | string |
| `missing_documents_requested_at` | ISO datetime |
| `customer.personal_profile` | object |
| `customer.business_profile` | object |
| `customer.alternative_data` | object |
| `documents` | array |
| `documents[].id` | string |
| `documents[].document_type` | string |
| `documents[].filename` | string |
| `documents[].file_url` | string |
| `documents[].file_size` | int |
| `documents[].status` | string |
| `documents[].verified` | boolean |
| `documents[].verified_at` | ISO datetime |
| `documents[].reupload_requested` | boolean |
| `documents[].reupload_reason` | string |
| `documents[].ai_analysis` | object |
| `documents[].uploaded_at` | ISO datetime |

---

### 28. `POST /officer/applications/<application_id>/notes/`

Add internal note.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `note` | string | **yes** | max 1000; non-empty after trim |

**Precondition:** Status not `draft` or `cancelled`.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `status` | string |
| `internal_notes_count` | int |
| `latest_internal_note.content` | string |
| `latest_internal_note.author_id` | string |
| `latest_internal_note.author_role` | string |
| `latest_internal_note.created_at` | ISO datetime |

---

### 29. `POST /officer/applications/<application_id>/request-missing-documents/`

Request documents not yet uploaded.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `missing_documents` | array[string] | **yes** | min 1 item; valid document type keys; must not already be uploaded |
| `reason` | string | no | max 1000 |

**Precondition:** Status `submitted` or `under_review`.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `status` | string |
| `missing_documents_requested` | array |
| `missing_documents_reason` | string |
| `missing_documents_requested_at` | ISO datetime |

---

### 30. `PUT /officer/applications/<application_id>/review/`

Approve or reject application. Triggers blockchain `approve` or `reject` sync.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `action` | string | **yes** | `approve` or `reject` |
| `approved_amount` | number | **yes if approve** | >= 0; must be <= requested_amount |
| `rejection_reason` | string | **yes if reject** | max 500 |
| `notes` | string | no | max 1000 |

**Precondition:** Status `submitted` or `under_review`.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `status` | string |
| `approved_amount` | number |

---

### 31. `POST /officer/applications/<application_id>/disburse/`

Disburse approved loan. Generates repayment schedule. Triggers blockchain `disburse` + `schedule` sync.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `amount` | number | no | Defaults to `approved_amount`; must be > 0 |
| `method` | string | no | `cash`, `gcash`, `bank_transfer`, `check`, `wallet` — **ignored if borrower already set `preferred_disbursement_method`** |
| `reference` | string | no | Auto-generated if omitted |
| `external_reference` | string | no | Bank/check number; used as reference if `reference` empty |

**Precondition:** Status must be `approved`.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `status` | string |
| `disbursed_amount` | number |
| `disbursement_method` | string |
| `disbursement_reference` | string |
| `disbursed_at` | ISO datetime |
| `eth_disbursement_tx_hash` | string |
| `eth_disbursement_amount` | string |
| `eth_disbursement_rate` | number |
| `eth_disbursement_recipient` | string |
| `schedule.monthly_payment` | number |
| `schedule.total_amount` | number |
| `schedule.term_months` | int |

---

### 32. `POST /officer/payments/`

Record cash/check payment on behalf of customer. Triggers blockchain `payment` sync.

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `loan_id` | string | **yes** | Application ID |
| `installment_number` | int | **yes** | >= 1 |
| `amount` | number | **yes** | > 0; must not exceed remaining balance |
| `payment_method` | string | **yes** | `cash` or `check` only |
| `reference` | string | no | Auto-generated if omitted |
| `external_reference` | string | no | Used as reference if `reference` empty |
| `notes` | string | no | |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `payment_id` | string |
| `loan_id` | string |
| `installment_number` | int |
| `amount` | number |
| `installment_status` | string |
| `remaining_balance` | number |
| `reference` | string |
| `skipped_installments` | int |

---

### 33. `GET /officer/payments/search/`

Search and filter all payments.

**Query params (all optional unless noted):**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `search` | string | | Customer name or reference |
| `loan_id` | string | | |
| `customer_id` | string | | |
| `disbursed_only` | boolean | `true` | `true`/`false` |
| `payment_status` | string | | `on_time`, `late` |
| `payment_method` | string | | `cash`, `gcash`, `bank_transfer`, `check`, `wallet` |
| `min_amount` | number | | |
| `max_amount` | number | | |
| `start_date` | string | | `YYYY-MM-DD` |
| `end_date` | string | | `YYYY-MM-DD` |
| `page` | int | 1 | >= 1 |
| `page_size` | int | 20 | 1–100 |
| `sort_by` | string | `recorded_at` | `recorded_at`, `amount`, `installment_number` |
| `sort_order` | string | `desc` | `asc`, `desc` |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `payments` | array |
| `payments[].id` | string |
| `payments[].loan_id` | string |
| `payments[].customer_id` | string |
| `payments[].customer_name` | string |
| `payments[].product_name` | string |
| `payments[].installment_number` | int |
| `payments[].due_date` | ISO datetime |
| `payments[].payment_status` | string |
| `payments[].amount` | number |
| `payments[].payment_method` | string |
| `payments[].reference` | string |
| `payments[].notes` | string |
| `payments[].recorded_by` | string |
| `payments[].recorded_at` | ISO datetime |
| `total` | int |
| `page` | int |
| `page_size` | int |
| `total_pages` | int |
| `summary.total_amount` | number |
| `summary.count` | int |

---

### 34. `GET /officer/active-loans/`

Active (disbursed) loans for payment recording.

**Query params:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `search` | string | one of search/customer_id | Customer name, phone, email, customer ID, or loan ID |
| `customer_id` | string | one of search/customer_id | Valid ObjectId |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `loans` | array |
| `loans[].loan_id` | string |
| `loans[].schedule_id` | string |
| `loans[].customer_id` | string |
| `loans[].customer_name` | string |
| `loans[].customer_phone` | string |
| `loans[].product_name` | string |
| `loans[].disbursed_amount` | number |
| `loans[].monthly_payment` | number |
| `loans[].remaining_balance` | number |
| `loans[].paid_installments` | int |
| `loans[].total_installments` | int |
| `loans[].next_due_installment` | int |
| `loans[].next_due_date` | ISO datetime |
| `loans[].next_due_amount` | number |
| `total` | int |

---

### 35. `GET /officer/applications/<application_id>/schedule/`

Officer view of repayment schedule (same shape as customer schedule, with dynamic overdue status).

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Precondition:** `status` must be `disbursed`.

**Response fields:** Same as endpoint 8.

---

### 36. `GET /officer/applications/<application_id>/payments/`

Officer payment history for an application.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `payments` | array |
| `payments[].id` | string |
| `payments[].amount` | number |
| `payments[].payment_method` | string |
| `payments[].reference` | string |
| `payments[].installment_number` | int |
| `payments[].notes` | string |
| `payments[].recorded_at` | ISO datetime |
| `total_paid` | number |
| `count` | int |

---

### 37. `POST /officer/applications/<application_id>/penalties/apply/`

Apply penalty to an installment. Triggers blockchain penalty sync.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `installment_number` | int | **yes** | >= 1 |
| `penalty_amount` | number | **yes** | > 0 |
| `reason` | string | no | |

**Precondition:** `status` must be `disbursed`; installment not paid; no existing applied penalty.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `loan_id` | string |
| `installment_number` | int |
| `penalty_status` | string (`applied`) |
| `penalty_amount` | number |
| `penalty_reason` | string |
| `penalty_applied_at` | ISO datetime |
| `penalty_applied_by` | string |

---

### 38. `POST /officer/applications/<application_id>/penalties/waive/`

Waive applied penalty. Triggers blockchain penalty sync.

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `installment_number` | int | **yes** | >= 1 |
| `reason` | string | no | |

**Precondition:** Penalty must be in `applied` status.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `loan_id` | string |
| `installment_number` | int |
| `penalty_status` | string (`waived`) |
| `penalty_amount` | number |
| `penalty_waived_at` | ISO datetime |
| `penalty_waived_by` | string |
| `penalty_waived_reason` | string |

---

### 39. `GET /officer/applications/<application_id>/blockchain/`

Officer blockchain status for application (same response as customer endpoint 14).

**Path params:**

| Field | Type | Required |
|-------|------|----------|
| `application_id` | string | yes |

---

### 40. `GET /officer/exchange-rate/`

Current ETH/PHP exchange rate.

**Request body:** none

**Precondition:** `BLOCKCHAIN_ENABLED=true`

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `eth_php_rate` | number |
| `rate_source` | string |
| `rate_cached_at` | ISO datetime |

---

## Complete URL Index (40 endpoints)

| # | Method | URL | Role |
|---|--------|-----|------|
| 1 | GET | `/api/loans/products/` | Customer |
| 2 | GET | `/api/loans/products/<product_id>/` | Customer |
| 3 | POST | `/api/loans/pre-qualify/` | Customer |
| 4 | POST | `/api/loans/apply/` | Customer |
| 5 | GET | `/api/loans/applications/` | Customer |
| 6 | GET | `/api/loans/applications/<application_id>/` | Customer |
| 7 | PUT | `/api/loans/applications/<application_id>/` | Customer |
| 8 | GET | `/api/loans/applications/<application_id>/schedule/` | Customer |
| 9 | GET | `/api/loans/applications/<application_id>/payments/` | Customer |
| 10 | POST | `/api/loans/applications/<application_id>/payments/` | Customer |
| 11 | POST | `/api/loans/applications/<application_id>/resubmit/` | Customer |
| 12 | GET | `/api/loans/applications/<application_id>/feedback/` | Customer |
| 13 | POST | `/api/loans/applications/<application_id>/set-disbursement-method/` | Customer |
| 14 | GET | `/api/loans/applications/<application_id>/blockchain/` | Customer |
| 15 | POST | `/api/loans/applications/<application_id>/wallet-payment/` | Customer |
| 16 | GET | `/api/loans/system-wallet/` | Customer |
| 17 | GET | `/api/loans/admin/products/` | Admin |
| 18 | POST | `/api/loans/admin/products/` | Admin |
| 19 | GET | `/api/loans/admin/products/<product_id>/` | Admin |
| 20 | PUT | `/api/loans/admin/products/<product_id>/` | Admin |
| 21 | DELETE | `/api/loans/admin/products/<product_id>/` | Admin |
| 22 | POST | `/api/loans/admin/applications/<application_id>/assign/` | Admin |
| 23 | POST | `/api/loans/admin/applications/<application_id>/reassign/` | Admin |
| 24 | GET | `/api/loans/admin/officers/workload/` | Admin |
| 25 | GET | `/api/loans/admin/blockchain/transactions/` | Admin |
| 26 | GET | `/api/loans/officer/applications/` | Officer |
| 27 | GET | `/api/loans/officer/applications/<application_id>/` | Officer |
| 28 | POST | `/api/loans/officer/applications/<application_id>/notes/` | Officer |
| 29 | POST | `/api/loans/officer/applications/<application_id>/request-missing-documents/` | Officer |
| 30 | PUT | `/api/loans/officer/applications/<application_id>/review/` | Officer |
| 31 | POST | `/api/loans/officer/applications/<application_id>/disburse/` | Officer |
| 32 | POST | `/api/loans/officer/payments/` | Officer |
| 33 | GET | `/api/loans/officer/payments/search/` | Officer |
| 34 | GET | `/api/loans/officer/active-loans/` | Officer |
| 35 | GET | `/api/loans/officer/applications/<application_id>/schedule/` | Officer |
| 36 | GET | `/api/loans/officer/applications/<application_id>/payments/` | Officer |
| 37 | POST | `/api/loans/officer/applications/<application_id>/penalties/apply/` | Officer |
| 38 | POST | `/api/loans/officer/applications/<application_id>/penalties/waive/` | Officer |
| 39 | GET | `/api/loans/officer/applications/<application_id>/blockchain/` | Officer |
| 40 | GET | `/api/loans/officer/exchange-rate/` | Officer |

---

## Smoke Test Sequence (Full Lifecycle)

### Prerequisites
1. Seed or create accounts: **admin**, **loan_officer**, **customer** (with JWTs).
2. Complete customer profile (`/api/profile/`) and upload/approve required documents (`/api/documents/`).
3. If testing wallet flows: set `wallet_address` on profile and ensure `BLOCKCHAIN_ENABLED=true`.

### Steps

| Step | Actor | Endpoint | Expected |
|------|-------|----------|----------|
| 1 | Admin | `POST /admin/products/` | 201, product `id` returned |
| 2 | Customer | `GET /products/` | Active product listed |
| 3 | Customer | `POST /pre-qualify/` | `eligible: true` or `missing_requirements` listed |
| 4 | Customer | `POST /apply/` | 201, `status: submitted` |
| 5 | Admin | `POST /admin/applications/<id>/assign/` | Officer assigned |
| 6 | Officer | `GET /officer/applications/?status=pending` | Application visible |
| 7 | Officer | `GET /officer/applications/<id>/` | Full customer + docs returned |
| 8 | Officer | `PUT /officer/applications/<id>/review/` `{action: approve}` | `status: approved` |
| 9 | Customer | `POST /applications/<id>/set-disbursement-method/` | Method saved |
| 10 | Officer | `POST /officer/applications/<id>/disburse/` | `status: disbursed`, schedule created |
| 11 | Customer | `GET /applications/<id>/schedule/` | Installments returned |
| 12 | Officer | `POST /officer/payments/` | Payment recorded |
| 13 | Customer | `GET /applications/<id>/payments/` | Payment in history |
| 14 | Admin | `GET /admin/blockchain/transactions/` | submit/approve/disburse/payment txs (if enabled) |
| 15 | Customer | `GET /applications/<id>/blockchain/` | On-chain audit trail |

### Rejection Path
1. Officer: `PUT /officer/applications/<id>/review/` with `{action: reject, rejection_reason: "..."}`
2. Customer: `GET /applications/<id>/feedback/`
3. Customer: `POST /applications/<id>/resubmit/`
4. Customer: `PUT /applications/<id>/` to update and re-submit

---

## Common Error Cases

| Code | When |
|------|------|
| `400 Bad Request` | Invalid payload, wrong status transition, amount out of range, invalid filters |
| `401 Unauthorized` | Missing or expired JWT |
| `403 Forbidden` | Wrong role, missing admin permission, ABAC scope violation (officer accessing unassigned app) |
| `404 Not Found` | Application/product/payment not found or not owned |
| `409 Conflict` | Duplicate operations (e.g., double disburse, duplicate tx_hash) |
| `503 Service Unavailable` | Blockchain disabled or ETH/PHP rate unavailable (`/system-wallet/`, `/exchange-rate/`) |

Standard error shape:
```json
{
  "status": "error",
  "message": "...",
  "errors": { }
}
```

---

## Where to Look in Code

| Area | Path |
|------|------|
| URL routing | `loans/urls.py` |
| Customer views | `loans/views/customer_views.py` |
| Admin views | `loans/views/admin_views.py` |
| Officer views | `loans/views/officer_views.py` |
| Serializers | `loans/serializers/loan_serializers.py` |
| Models | `loans/models/` |
| Blockchain sync | `loans/blockchain/sync.py` |
| Smart contract ABIs | `loans/blockchain/abis/` |
| Solidity contracts | `smartcontracts/contracts/` |
| Existing API stub tests | `tests/test_loans_api_stubs.py` |
| Blockchain smoke tests | `tests/test_loans_smoke.py`, `tests/blockchain/` |

---

## Notes for API Test Automation

1. Use role-specific JWTs; officer tests require the application to be assigned to that officer.
2. Customer `POST /payments/` rejects `cash` and `check` — use officer endpoint for those.
3. Officer `POST /payments/` accepts only `cash` and `check`.
4. `approved_amount` on approve must be <= `requested_amount` (smart contract enforces this on-chain).
5. Disbursement `method` is locked to customer's `preferred_disbursement_method` when set.
6. For blockchain tests: run local testnet per `smartcontracts/docs/TESTNET_DEPLOYMENT_GUIDE.md` or mock `loans/blockchain/client.py`.
7. Pre-qualify endpoint is rate-limited (`PreQualifyRateThrottle`).
