# Blockchain Function Table
## MSME Pathways — Smart Contract Integration Reference

This document maps every backend module to its corresponding smart contract transactions.

---

## System Architecture Overview

```
Django Backend (Python)         ←→         Ethereum Smart Contracts (Solidity)
────────────────────────────────────────────────────────────────────────────────
MongoDB (off-chain data)                    Blockchain (on-chain immutable records)
- Full loan details (encrypted)             - Loan state hashes
- Customer profiles                         - AI recommendation hashes
- Documents                                 - Payment hashes
- Chat history                              - Audit trail
```

---

## Smart Contracts Summary

| Contract File | Purpose | Deployed Pattern |
|---|---|---|
| `LoanAccessControl.sol` | Role-based access: who can do what | UUPS Upgradeable Proxy |
| `LoanCore.sol` | Loan lifecycle state machine | UUPS Upgradeable Proxy |
| `Disbursement.sol` | Fund release tracking | UUPS Upgradeable Proxy |
| `Repayment.sol` | Repayment schedules & payment recording | UUPS Upgradeable Proxy |
| `AuditRegistry.sol` | Immutable audit log for all actions | UUPS Upgradeable Proxy |

---

## Module-by-Module Blockchain Transaction Table

---

### 1. ACCOUNTS MODULE — User Registration

| Backend Action | Smart Contract | Function | Who Calls | Event Emitted |
|---|---|---|---|---|
| Loan officer account created | `LoanAccessControl` | `registerOfficer(address, bytes32)` | Admin | `OfficerRegistered` |
| Officer deactivated | `LoanAccessControl` | `deactivateOfficer(address)` | Admin | `OfficerDeactivated` |
| Officer reactivated | `LoanAccessControl` | `reactivateOfficer(address)` | Admin | `OfficerReactivated` |
| Customer account created | `LoanAccessControl` | `registerBorrower(address, bytes32)` | System | `BorrowerRegistered` |
| Emergency system pause | `LoanAccessControl` | `emergencyPause(string)` | Pauser Role | `EmergencyPaused` |
| System unpaused | `LoanAccessControl` | `unpause()` | Pauser Role | `Unpaused` |

**Data stored on-chain:** `keccak256` hash of employee ID / customer ID (no PII on-chain).

---

### 2. LOANS MODULE — Loan Lifecycle

| Backend Action | Backend Endpoint | Smart Contract | Function | Who Calls | Event Emitted |
|---|---|---|---|---|---|
| Customer applies for loan | `POST /api/loans/apply/` | `LoanCore` | `createLoan(loanId, productId, amount, term, interestBps)` | Borrower / System | `LoanCreated` |
| Loan submitted with AI score | `POST /api/loans/apply/` | `LoanCore` | `submitLoan(loanId, eligibilityScore, riskCategory, aiHash)` | Borrower / System | `LoanSubmitted` |
| Loan assigned to officer | `POST /api/loans/{id}/assign/` | `LoanCore` | `assignOfficer(loanId, officerAddress)` | Admin / System | `LoanAssigned` |
| Officer approves loan | `PUT /api/loans/{id}/review/` (approve) | `LoanCore` | `approveLoan(loanId, approvedAmount, notesHash)` | Loan Officer | `LoanApproved` |
| Officer rejects loan | `PUT /api/loans/{id}/review/` (reject) | `LoanCore` | `rejectLoan(loanId, rejectionReasonHash, notesHash)` | Loan Officer | `LoanRejected` |
| Loan cancelled | `DELETE /api/loans/{id}/` | `LoanCore` | `cancelLoan(loanId, reasonHash)` | Borrower / Admin | `LoanCancelled` |
| Loan marked disbursed | Called by `Disbursement.sol` | `LoanCore` | `markDisbursed(loanId, amount)` | Disbursement Contract | `LoanStatusChanged` |

**AI Integration:** The AI eligibility score (0–100), risk category (low/medium/high), and a `keccak256` hash of the full AI recommendation JSON are written permanently on-chain when the loan is submitted. This makes the AI's decision tamper-proof and auditable.

---

### 3. DISBURSEMENT — Fund Release

| Backend Action | Backend Endpoint | Smart Contract | Function | Who Calls | Event Emitted |
|---|---|---|---|---|---|
| Initiate disbursement | `POST /api/loans/{id}/disburse/` | `Disbursement` | `initiateDisbursement(loanId, amount, method)` | Loan Officer | `DisbursementInitiated` |
| Complete disbursement | `POST /api/loans/{id}/disburse/` | `Disbursement` | `completeDisbursement(disbursementId, referenceHash)` | Loan Officer | `DisbursementCompleted` |

**Disbursement Methods (on-chain enum):**
- `0` → Bank Transfer
- `1` → Cash
- `2` → GCash
- `3` → Maya
- `4` → Other

**Duplicate prevention:** A `referenceHash` mapping prevents the same external transaction reference from being recorded twice.

---

### 4. REPAYMENT — Payment Recording

| Backend Action | Backend Endpoint | Smart Contract | Function | Who Calls | Event Emitted |
|---|---|---|---|---|---|
| Create repayment schedule | After disbursement | `Repayment` | `createSchedule(loanId, principal, interestBps, termMonths, startDate)` | System | `ScheduleCreated` |
| Record a payment | `POST /api/loans/payment/` | `Repayment` | `recordPayment(loanId, installmentNumber, amount, method, referenceHash)` | Loan Officer / System | `PaymentRecorded` |
| Installment marked overdue | `check_overdue_installments_task` (Celery) | `Repayment` | `markOverdue(loanId, installmentNumber)` | System | `InstallmentOverdue` |
| Loan fully repaid | Auto-triggered on last payment | `Repayment` | *(auto-emitted when `totalPaid >= totalAmount`)* | — | `LoanFullyRepaid` |

**Installment Statuses (on-chain):** `Pending → Partial → Paid` or `Pending → Overdue`

**Payment Methods (on-chain enum):**
- `0` → Cash
- `1` → Bank Transfer
- `2` → GCash
- `3` → Maya
- `4` → Other

---

### 5. AUDIT REGISTRY — Immutable Audit Trail

Every state-changing transaction above automatically writes an entry to `AuditRegistry`. This is called internally by `LoanCore`, `Disbursement`, and `Repayment` — no manual action needed.

| Audit Action (enum) | Triggered By |
|---|---|
| `LoanCreated` | `LoanCore.createLoan()` |
| `LoanSubmitted` | `LoanCore.submitLoan()` |
| `LoanAssigned` | `LoanCore.assignOfficer()` |
| `LoanApproved` | `LoanCore.approveLoan()` |
| `LoanRejected` | `LoanCore.rejectLoan()` |
| `LoanDisbursed` | `Disbursement.completeDisbursement()` |
| `PaymentRecorded` | `Repayment.recordPayment()` |
| `PenaltyApplied` | Backend → `AuditRegistry.log()` |
| `PenaltyWaived` | Backend → `AuditRegistry.log()` |
| `DocumentVerified` | Backend → `AuditRegistry.log()` |
| `ConsentRecorded` | Backend → `AuditRegistry.log()` |
| `SystemConfigChanged` | Admin → `AuditRegistry.log()` |

Each audit entry stores:
- `resourceId` — keccak256 of the loan/payment ID
- `actor` — wallet address of who performed the action
- `previousStateHash` — state before the transaction
- `newStateHash` — state after the transaction
- `blockNumber` + `timestamp` — permanent blockchain timestamp

---

## Full Loan Flow: Blockchain Transaction Sequence

```
Customer                Backend               Smart Contracts          Blockchain
   │                       │                        │                      │
   │── Apply for loan ────→│                        │                      │
   │                       │── createLoan() ───────→│ LoanCore             │
   │                       │── submitLoan()         │  + AuditRegistry ──→ │ tx1
   │                       │   (with AI score hash) │                      │
   │                       │                        │                      │
   │                       │← Assign officer        │                      │
   │                       │── assignOfficer() ────→│ LoanCore             │
   │                       │                        │  + AuditRegistry ──→ │ tx2
   │                       │                        │                      │
   │              Officer reviews                   │                      │
   │                       │── approveLoan() ──────→│ LoanCore             │
   │                       │                        │  + AuditRegistry ──→ │ tx3
   │                       │                        │                      │
   │                       │── initiateDisbursement()→ Disbursement        │
   │                       │── completeDisbursement()│  + LoanCore         │
   │                       │                        │  + AuditRegistry ──→ │ tx4
   │                       │                        │                      │
   │                       │── createSchedule() ───→│ Repayment            │
   │                       │                        │  + AuditRegistry ──→ │ tx5
   │                       │                        │                      │
   │── Make payment ──────→│                        │                      │
   │                       │── recordPayment() ────→│ Repayment            │
   │                       │                        │  + AuditRegistry ──→ │ tx6
   │                       │                        │                      │
   │                       │                   (repeat per installment)    │
   │                       │                        │                      │
   │                       │              LoanFullyRepaid event ─────────→ │ txN
```

---

## Off-Chain vs On-Chain Data Split

| Data | Where Stored | Why |
|---|---|---|
| Customer name, address, income | MongoDB (encrypted) | Privacy — PII must not be public |
| Document files (ID, selfie, etc.) | Encrypted file storage | File size — too large for chain |
| AI recommendation full JSON | MongoDB | Size; hashed version on-chain |
| Loan status | Both | MongoDB for queries, chain for integrity |
| Approval/rejection notes | MongoDB (encrypted) | Privacy; hash on-chain for verification |
| Payment amounts | Both | MongoDB for display, chain for audit |
| Audit trail | Both | MongoDB for fast queries, chain as tamper-proof record |

---

## Role Permissions Summary

| Role | Contract | Can Do |
|---|---|---|
| `ADMIN_ROLE` | All contracts | Register/deactivate officers, upgrade contracts, pause system |
| `LOAN_OFFICER_ROLE` | `LoanCore`, `Disbursement`, `Repayment` | Approve/reject loans, disburse, record payments |
| `BORROWER_ROLE` | `LoanCore` | Create and submit loan applications |
| `SYSTEM_ROLE` | `LoanCore`, `LoanAccessControl` | Register borrowers, assign officers (automated backend calls) |
| `LOGGER_ROLE` | `AuditRegistry` | Write audit entries (granted to other contracts) |
| `UPGRADER_ROLE` | All contracts | Deploy contract upgrades |
| `PAUSER_ROLE` | `LoanAccessControl` | Emergency pause/unpause all operations |
