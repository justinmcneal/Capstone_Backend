# Smart Contracts Overview

> Blockchain-based audit trail and loan verification for MSME Pathways

---

## Overview

The `/smartcontracts/` directory contains 5 Solidity smart contracts that provide immutable, auditable record-keeping for the loan management system.

```
┌─────────────────────────────────────────────────────────────┐
│                    SMART CONTRACTS                           │
├─────────────────────────────────────────────────────────────┤
│  LoanAccessControl  →  Role-based permissions               │
│  AuditRegistry      →  Immutable audit logs                 │
│  LoanCore           →  Loan lifecycle management            │
│  Disbursement       →  Fund release tracking                │
│  Repayment          →  Payment recording                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Contract Summary

| Contract | Purpose | Key Functions |
|----------|---------|---------------|
| `LoanAccessControl.sol` | Role management (officer, borrower) | `registerOfficer()`, `registerBorrower()` |
| `AuditRegistry.sol` | Immutable event logging | `logEvent()`, `getEventsByLoan()` |
| `LoanCore.sol` | Loan CRUD and status transitions | `createLoan()`, `approveLoan()`, `rejectLoan()` |
| `Disbursement.sol` | Disbursement tracking | `initiateDisbursement()`, `completeDisbursement()` |
| `Repayment.sol` | Payment schedules and recording | `createSchedule()`, `recordPayment()` |

---

## Status Mapping (Django ↔ Smart Contract)

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

## Integration Status

| Component | Status |
|-----------|--------|
| Smart Contracts | ✅ Developed |
| Local Testing | ✅ Hardhat node |
| Testnet Deployment | ⚠️ Optional |
| **Django Integration** | ❌ **Not Implemented** |

> **Important:** The smart contracts are fully functional but the Django backend does not currently call them. A `BlockchainService` bridge needs to be implemented using `web3.py`.

---

## Local Development

### Prerequisites

```bash
cd smartcontracts
npm install
```

### Start Local Blockchain

```bash
npm run node
```

### Deploy Contracts

```bash
npm run deploy:local
```

### Run Tests

```bash
npm test
```

---

## Future Integration

When implementing Django ↔ Smart Contract integration:

```python
# Example: loans/services/blockchain_service.py
from web3 import Web3

class BlockchainService:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(
            os.getenv('BLOCKCHAIN_RPC_URL', 'http://127.0.0.1:8545')
        ))
    
    def create_loan_on_chain(self, loan):
        loan_id = Web3.keccak(text=str(loan.id))
        # Call LoanCore.createLoan(...)
        
    def record_payment_on_chain(self, payment):
        loan_id = Web3.keccak(text=str(payment.loan_application.id))
        # Call Repayment.recordPayment(...)
```

---

## Related Documentation

- [smartcontracts/README.md](../smartcontracts/README.md) — Full contract documentation
- [smartcontracts/docs/](../smartcontracts/docs/) — Detailed testing guides
