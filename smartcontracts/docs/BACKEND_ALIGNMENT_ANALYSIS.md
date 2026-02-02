# Backend & Smart Contract Alignment

## Contracts

| Contract | Backend Model | Purpose |
|----------|---------------|---------|
| `LoanAccessControl.sol` | `LoanOfficer`, `Customer` | Role management |
| `LoanCore.sol` | `LoanApplication` | Loan lifecycle |
| `Disbursement.sol` | `disburse()` method | Fund release tracking |
| `Repayment.sol` | `RepaymentSchedule`, `LoanPayment` | Payment recording |
| `AuditRegistry.sol` | `AuditLog` | Immutable audit trail |

---

## Status Mapping

### Loan Status

| Django | Smart Contract | Value |
|--------|---------------|-------|
| `draft` | `Draft` | 0 |
| `submitted` | `Submitted` | 1 |
| `under_review` | `UnderReview` | 2 |
| `approved` | `Approved` | 3 |
| `rejected` | `Rejected` | 4 |
| `disbursed` | `Disbursed` | 5 |
| `active` | `Active` | 6 |
| `completed` | `Completed` | 7 |
| `defaulted` | `Defaulted` | 8 |
| `cancelled` | `Cancelled` | 9 |

### Disbursement Status

| Django | Smart Contract | Value |
|--------|---------------|-------|
| Pending | `Pending` | 0 |
| Processing | `Processing` | 1 |
| Completed | `Completed` | 2 |

### Installment Status

| Django | Smart Contract | Value |
|--------|---------------|-------|
| `pending` | `Pending` | 0 |
| `paid` | `Paid` | 1 |
| `partial` | `Partial` | 2 |
| `overdue` | `Overdue` | 3 |

### Payment Methods

| Django | Smart Contract | Value |
|--------|---------------|-------|
| `cash` | `Cash` | 0 |
| `bank_transfer` | `BankTransfer` | 1 |
| `gcash` | `GCash` | 2 |
| `maya` | `Maya` | 3 |
| `other` | `Other` | 4 |

---

## Data Flow

```
Django Backend                    Smart Contracts
───────────────────────────────────────────────────────
POST /api/loans/apply/     →     LoanCore.createLoan()
PUT .../review/ (approve)  →     LoanCore.approveLoan()
PUT .../review/ (reject)   →     LoanCore.rejectLoan()
POST .../disburse/         →     Disbursement.initiateDisbursement()
                           →     Disbursement.completeDisbursement()
POST /api/loans/payment/   →     Repayment.recordPayment()
```

---

## Field Mapping

### LoanApplication → LoanCore

| Django Field | Smart Contract Field |
|--------------|---------------------|
| `id` | `loanId` (bytes32 hash) |
| `customer` | `borrower` (address) |
| `loan_product` | `productId` (bytes32 hash) |
| `requested_amount` | `requestedAmount` |
| `approved_amount` | `approvedAmount` |
| `term_months` | `termMonths` |
| `interest_rate` | `interestRateBps` |
| `status` | `status` (enum) |
| `assigned_officer` | `assignedOfficer` (address) |
| `eligibility_score` | `eligibilityScore` |
| `risk_category` | `riskCategory` |

### LoanPayment → Repayment

| Django Field | Smart Contract Field |
|--------------|---------------------|
| `loan_application` | `loanId` |
| `amount` | `amount` |
| `payment_method` | `method` (enum) |
| `reference_number` | `referenceHash` (bytes32) |
| `created_at` | `recordedAt` |

### LoanOfficer → LoanAccessControl

| Django Field | Smart Contract Field |
|--------------|---------------------|
| `user` | `officer` (address) |
| `employee_id` | `employeeIdHash` (bytes32) |
| `is_active` | `isActive` |

---

## Integration Pattern

```python
# Django service example
from web3 import Web3

class BlockchainService:
    def record_loan_approval(self, loan):
        loan_id = Web3.keccak(text=str(loan.id))
        
        tx = self.loan_core.functions.approveLoan(
            loan_id,
            int(loan.approved_amount * 10**18),
            Web3.keccak(text=loan.notes or "")
        ).build_transaction({...})
        
        return self.sign_and_send(tx)
    
    def record_payment(self, payment):
        loan_id = Web3.keccak(text=str(payment.loan_application.id))
        reference_hash = Web3.keccak(text=payment.reference_number)
        
        tx = self.repayment.functions.recordPayment(
            loan_id,
            payment.installment_number,
            int(payment.amount * 10**18),
            self.payment_method_to_enum(payment.payment_method),
            reference_hash
        ).build_transaction({...})
        
        return self.sign_and_send(tx)
```

---

## Test Status

```
100 passing (3s)
```

All contracts tested and aligned with backend functionality.
