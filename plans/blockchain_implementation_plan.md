# Blockchain Implementation Plan
**Project:** MSME Loan Platform  
**Date:** 2026-03-14  
**Phase:** 1 — Smart Contract Design & Implementation

---

## Overview

This plan breaks down all implementation tasks derived from the blockchain integration analysis. It is organized by sprint, with each task having a clear owner, acceptance criteria, and technical specification.

**Total Sprints:** 5  
**Estimated Duration:** 10 weeks  
**Prerequisite:** [`plans/blockchain_integration_analysis.md`](./blockchain_integration_analysis.md)

---

## Sprint 1 — Core Loan Contracts (Weeks 1–2)

### Goal
Separate the monolithic [`LoanCore.sol`](../smartcontracts/contracts/LoanCore.sol) into three focused contracts.

---

### Task 1.1 — Create `LoanApplication.sol`

**File:** `smartcontracts/contracts/core/LoanApplication.sol`  
**Responsibility:** Application creation and submission only  
**Replaces:** `LoanCore.createLoan()` + `LoanCore.submitLoan()`

**Functions to implement:**
```solidity
function createApplication(
    bytes32 loanId,
    bytes32 productId,
    uint256 requestedAmount,
    uint16 termMonths,
    uint16 interestRateBps
) external returns (bool)

function submitApplication(
    bytes32 loanId,
    uint8 eligibilityScore,
    RiskCategory riskCategory,
    bytes32 aiRecommendationHash
) external returns (bool)

function cancelApplication(bytes32 loanId, bytes32 reasonHash) external returns (bool)
```

**Events:**
- `ApplicationCreated(bytes32 loanId, address borrower, uint256 amount, uint256 timestamp)`
- `ApplicationSubmitted(bytes32 loanId, uint8 score, RiskCategory risk, uint256 timestamp)`
- `ApplicationCancelled(bytes32 loanId, address cancelledBy, uint256 timestamp)`

**Backend alignment:**
- [`loans/models/application.py:39`](../loans/models/application.py:39) — `__init__`
- [`loans/models/application.py:146`](../loans/models/application.py:146) — `submit()`

**Acceptance criteria:**
- [/] Contract compiles without warnings
- [/] Only borrowers (BORROWER_ROLE) can create/submit
- [/] Duplicate loanId reverts
- [/] AuditRegistry called on every state change
- [/] Unit tests pass (≥90% coverage)
- [/] Access control enforced
- [/] Reentrancy protection implemented
- [/] Pausable for emergencies
- [/] UUPS upgradeable
- [/] Events emitted for all state changes

---

### Task 1.2 — Create `LoanReview.sol`

**File:** `smartcontracts/contracts/core/LoanReview.sol`  
**Responsibility:** Officer assignment and review workflow  
**Replaces:** `LoanCore.assignOfficer()`

**Functions to implement:**
```solidity
function assignOfficer(bytes32 loanId, address officer) external returns (bool)

function reassignOfficer(bytes32 loanId, address newOfficer, bytes32 reasonHash) external returns (bool)

function requestDocuments(
    bytes32 loanId,
    bytes32[] calldata documentTypeHashes,
    bytes32 reasonHash
) external returns (bool)
```

**Events:**
- `OfficerAssigned(bytes32 loanId, address officer, address assignedBy, uint256 timestamp)`
- `OfficerReassigned(bytes32 loanId, address oldOfficer, address newOfficer, uint256 timestamp)`
- `DocumentsRequested(bytes32 loanId, bytes32[] documentTypes, address requestedBy, uint256 timestamp)`

**Backend alignment:**
- [`loans/models/application.py:152`](../loans/models/application.py:152) — `assign_officer()`
- [`loans/models/application.py:195`](../loans/models/application.py:195) — `request_missing_documents()`

**Acceptance criteria:**
- [/] Only ADMIN_ROLE or SYSTEM_ROLE can assign officers
- [/] Officer must be active in LoanAccessControl
- [/] Application must be in Submitted or UnderReview status
- [/] Unit tests pass (≥90% coverage)

---

### Task 1.3 — Create `LoanApproval.sol`

**File:** `smartcontracts/contracts/core/LoanApproval.sol`  
**Responsibility:** Approval and rejection decisions only  
**Replaces:** `LoanCore.approveLoan()` + `LoanCore.rejectLoan()`

**Functions to implement:**
```solidity
function approveLoan(
    bytes32 loanId,
    uint256 approvedAmount,
    bytes32 notesHash
) external returns (bool)

function rejectLoan(
    bytes32 loanId,
    bytes32 rejectionReasonHash,
    bytes32 notesHash
) external returns (bool)
```

**Events:**
- `LoanApproved(bytes32 loanId, address officer, uint256 approvedAmount, bytes32 notesHash, uint256 timestamp)`
- `LoanRejected(bytes32 loanId, address officer, bytes32 reasonHash, uint256 timestamp)`

**Backend alignment:**
- [`loans/models/application.py:158`](../loans/models/application.py:158) — `approve()`
- [`loans/models/application.py:167`](../loans/models/application.py:167) — `reject()`

**Acceptance criteria:**
- [/] Only assigned officer or ADMIN_ROLE can approve/reject
- [/] Approved amount cannot exceed requested amount
- [/] Rejection reason hash cannot be empty
- [/] AuditRegistry logs both approval and rejection
- [/] Unit tests pass (≥90% coverage)

---

### Task 1.4 — Create `interfaces/ILoanApplication.sol` ✅ COMPLETED

**File:** [`smartcontracts/contracts/interfaces/ILoanApplication.sol`](../smartcontracts/contracts/interfaces/ILoanApplication.sol)

**Status:** ✅ Completed (2026-03-14)

**Implementation:**
```solidity
interface ILoanApplication {
    enum LoanStatus { Draft, Submitted, UnderReview, Approved, Rejected, Disbursed, Cancelled }
    enum RiskCategory { Low, Medium, High }
    struct Application { ... }
    struct ApplicationData { ... } // Alias for cross-contract compatibility
    
    // Core functions
    function createApplication(...) external returns (bool);
    function submitApplication(...) external returns (bool);
    function cancelApplication(...) external returns (bool);
    function updateStatus(...) external returns (bool);
    
    // View functions
    function getApplication(bytes32 loanId) external view returns (Application memory);
    function getStatus(bytes32 loanId) external view returns (LoanStatus);
    function exists(bytes32 loanId) external view returns (bool);
    function getBorrowerApplications(address borrower) external view returns (bytes32[] memory);
}
```

**Acceptance criteria:**
- [x] Interface compiles without errors
- [x] Enums and structs properly defined
- [x] All core functions declared
- [x] View functions for cross-contract calls
- [x] Compatible with existing LoanApplication.sol implementation
- [x] NatSpec documentation complete

---

### Task 1.5 — Write Sprint 1 Tests ✅ COMPLETED

**Files:**
- [`smartcontracts/test/LoanApplication.test.js`](../smartcontracts/test/LoanApplication.test.js) — 138 tests
- [`smartcontracts/test/LoanReview.test.js`](../smartcontracts/test/LoanReview.test.js) — 60 tests
- [`smartcontracts/test/LoanApproval.test.js`](../smartcontracts/test/LoanApproval.test.js) — 60 tests

**Status:** ✅ Completed (2026-03-14) — All 258 tests passing

**Test coverage per contract:**

**LoanApplication.test.js:**
- [x] Happy path (create → submit → cancel lifecycle)
- [x] Access control violations (borrower-only operations)
- [x] Invalid status transitions (Draft → Submitted validation)
- [x] Duplicate ID handling (ApplicationAlreadyExists error)
- [x] AuditRegistry integration (all operations logged)
- [x] Gas optimization tests (< 600k create, < 450k submit)
- [x] Upgrade functionality (UUPS proxy)
- [x] Pause/unpause emergency controls

**LoanReview.test.js:**
- [x] Happy path (assign → reassign → request docs)
- [x] Access control violations (officer/admin authorization)
- [x] Invalid status transitions (UnderReview requirements)
- [x] Officer validation (active status checks)
- [x] AuditRegistry integration
- [x] Full lifecycle scenarios
- [x] Document request accumulation

**LoanApproval.test.js:**
- [x] Happy path (approve/reject flows)
- [x] Access control violations (assigned officer checks)
- [x] Invalid status transitions (prevent double approval/rejection)
- [x] Amount validation (approved ≤ requested)
- [x] AuditRegistry integration
- [x] Mixed decision scenarios (multiple loans)
- [x] Approval/rejection mutual exclusivity

**Test Results:**
```
258 passing (8s)
✓ All contracts compile successfully
✓ 100% test pass rate
✓ Comprehensive edge case coverage
✓ Security validations enforced
✓ Integration with AuditRegistry verified
```

---

## Sprint 2 — Disbursement Contracts (Weeks 3–4)

### Goal
Add missing disbursement method selection and refactor existing disbursement execution.

---

### Task 2.1 — Create `DisbursementMethod.sol` ⚠️ NEW (Currently Missing)

**File:** `smartcontracts/contracts/disbursement/DisbursementMethod.sol`  
**Responsibility:** Borrower's preferred disbursement method selection  
**Backend gap:** [`loans/models/application.py:252`](../loans/models/application.py:252) — `set_preferred_disbursement_method()`

**Functions to implement:**
```solidity
enum DisbursementMethod { BankTransfer, GCash, Cash, Maya, Other }

function setPreferredMethod(
    bytes32 loanId,
    DisbursementMethod method
) external returns (bool)

function getPreferredMethod(bytes32 loanId) external view returns (DisbursementMethod)

function hasPreferredMethod(bytes32 loanId) external view returns (bool)
```

**Events:**
- `DisbursementMethodSelected(bytes32 loanId, address borrower, DisbursementMethod method, uint256 timestamp)`

**Business rules:**
- Only the borrower of the loan can set the method
- Loan must be in Approved status
- Method can be updated before disbursement is initiated
- Once disbursement is initiated, method is locked

**Acceptance criteria:**
- [ ] Only borrower can call setPreferredMethod
- [ ] Reverts if loan not in Approved status
- [ ] Reverts if disbursement already initiated
- [ ] AuditRegistry logs method selection
- [ ] Unit tests pass (≥90% coverage)

---

### Task 2.2 — Refactor `Disbursement.sol` → `DisbursementExecution.sol`

**File:** `smartcontracts/contracts/disbursement/DisbursementExecution.sol`  
**Responsibility:** Actual disbursement execution only  
**Refactors:** [`smartcontracts/contracts/Disbursement.sol`](../smartcontracts/contracts/Disbursement.sol)

**Changes from existing contract:**
- Read preferred method from `DisbursementMethod.sol` instead of accepting as parameter
- Add `cancelDisbursement()` for failed transfers
- Emit richer events with method details

**Functions to implement:**
```solidity
function initiateDisbursement(
    bytes32 loanId,
    uint256 amount
) external returns (bytes32 disbursementId)

function completeDisbursement(
    bytes32 disbursementId,
    bytes32 referenceHash
) external returns (bool)

function cancelDisbursement(
    bytes32 disbursementId,
    bytes32 reasonHash
) external returns (bool)
```

**Events:**
- `DisbursementInitiated(bytes32 disbursementId, bytes32 loanId, address borrower, uint256 amount, DisbursementMethod method, uint256 timestamp)`
- `DisbursementCompleted(bytes32 disbursementId, bytes32 loanId, bytes32 referenceHash, uint256 timestamp)`
- `DisbursementCancelled(bytes32 disbursementId, bytes32 loanId, bytes32 reasonHash, uint256 timestamp)`

**Backend alignment:**
- [`loans/models/application.py:239`](../loans/models/application.py:239) — `disburse()`
- [`loans/views/officer_views.py:868`](../loans/views/officer_views.py:868) — `OfficerDisburseLoanView`

**Acceptance criteria:**
- [ ] Reads preferred method from DisbursementMethod contract
- [ ] Reverts if no preferred method set
- [ ] Reverts if loan not in Approved status
- [ ] Calls LoanApplication.markDisbursed() on completion
- [ ] Duplicate reference hash reverts
- [ ] Unit tests pass (≥90% coverage)

---

### Task 2.3 — Write Sprint 2 Tests

**Files:**
- `smartcontracts/test/DisbursementMethod.test.js`
- `smartcontracts/test/DisbursementExecution.test.js`

**Test scenarios:**
- Method selection before/after approval
- Method lock after disbursement initiation
- Disbursement with and without preferred method
- Cancellation flow
- Duplicate reference prevention

---

## Sprint 3 — Repayment Contracts (Weeks 5–6)

### Goal
Separate the monolithic [`Repayment.sol`](../smartcontracts/contracts/Repayment.sol) into schedule management and payment recording.

---

### Task 3.1 — Create `RepaymentSchedule.sol`

**File:** `smartcontracts/contracts/repayment/RepaymentSchedule.sol`  
**Responsibility:** Schedule generation and structure only  
**Refactors:** `Repayment.createSchedule()` from [`Repayment.sol`](../smartcontracts/contracts/Repayment.sol)

**Functions to implement:**
```solidity
function createSchedule(
    bytes32 loanId,
    address borrower,
    uint256 principal,
    uint16 interestRateBps,
    uint16 termMonths,
    uint256 startDate
) external returns (bytes32 scheduleId)

function getSchedule(bytes32 loanId) external view returns (RepaymentSchedule memory)

function getInstallment(bytes32 loanId, uint16 number) external view returns (Installment memory)

function getAllInstallments(bytes32 loanId) external view returns (Installment[] memory)

function getRemainingBalance(bytes32 loanId) external view returns (uint256)
```

**Events:**
- `ScheduleCreated(bytes32 scheduleId, bytes32 loanId, address borrower, uint256 principal, uint16 termMonths, uint256 monthlyPayment, uint256 timestamp)`

**Backend alignment:**
- [`loans/models/repayment.py:84`](../loans/models/repayment.py:84) — `generate_for_loan()`

**Acceptance criteria:**
- [ ] Schedule can only be created once per loan
- [ ] Loan must be in Disbursed status
- [ ] Installment due dates calculated correctly (30-day months)
- [ ] Total amount = principal + (principal × rate × term)
- [ ] Unit tests pass (≥90% coverage)

---

### Task 3.2 — Create `PaymentRecording.sol`

**File:** `smartcontracts/contracts/repayment/PaymentRecording.sol`  
**Responsibility:** Payment recording and installment status updates  
**Refactors:** `Repayment.recordPayment()` + `Repayment.markOverdue()`

**Functions to implement:**
```solidity
function recordPayment(
    bytes32 loanId,
    uint16 installmentNumber,
    uint256 amount,
    PaymentMethod method,
    bytes32 referenceHash
) external returns (bytes32 paymentId)

function markOverdue(bytes32 loanId, uint16 installmentNumber) external returns (bool)

function getPaymentHistory(bytes32 loanId) external view returns (Payment[] memory)

function getPayment(bytes32 paymentId) external view returns (Payment memory)
```

**Events:**
- `PaymentRecorded(bytes32 paymentId, bytes32 loanId, uint16 installmentNumber, uint256 amount, uint256 remainingBalance, address recordedBy, uint256 timestamp)`
- `InstallmentStatusChanged(bytes32 loanId, uint16 number, InstallmentStatus oldStatus, InstallmentStatus newStatus, uint256 timestamp)`
- `InstallmentOverdue(bytes32 loanId, uint16 number, uint256 daysOverdue, uint256 timestamp)`
- `LoanFullyRepaid(bytes32 loanId, uint256 totalPaid, uint256 timestamp)`

**Backend alignment:**
- [`loans/models/repayment.py:210`](../loans/models/repayment.py:210) — `record_payment()`
- [`loans/models/payment.py:16`](../loans/models/payment.py:16) — `LoanPayment`
- [`loans/views/officer_views.py:1026`](../loans/views/officer_views.py:1026) — `OfficerRecordPaymentView`

**Acceptance criteria:**
- [ ] Only LOAN_OFFICER_ROLE or SYSTEM_ROLE can record payments
- [ ] Duplicate reference hash reverts
- [ ] Cannot pay already-paid installment
- [ ] Partial payments update status to Partial
- [ ] Full payment triggers LoanFullyRepaid if last installment
- [ ] markOverdue only works past due date
- [ ] Unit tests pass (≥90% coverage)

---

### Task 3.3 — Write Sprint 3 Tests

**Files:**
- `smartcontracts/test/RepaymentSchedule.test.js`
- `smartcontracts/test/PaymentRecording.test.js`

**Test scenarios:**
- Schedule generation with various terms
- Installment due date accuracy
- Partial payment tracking
- Full payment and loan completion
- Overdue marking
- Payment history retrieval

---

## Sprint 4 — Testing, Security & Optimization (Weeks 7–8)

### Goal
Ensure all contracts are production-ready before integration.

---

### Task 4.1 — Integration Tests

**File:** `smartcontracts/test/integration/FullLoanLifecycle.test.js`

Test the complete loan lifecycle across all contracts:
1. Register borrower → `LoanAccessControl.registerBorrower()`
2. Create application → `LoanApplication.createApplication()`
3. Submit application → `LoanApplication.submitApplication()`
4. Assign officer → `LoanReview.assignOfficer()`
5. Approve loan → `LoanApproval.approveLoan()`
6. Set disbursement method → `DisbursementMethod.setPreferredMethod()`
7. Initiate disbursement → `DisbursementExecution.initiateDisbursement()`
8. Complete disbursement → `DisbursementExecution.completeDisbursement()`
9. Create schedule → `RepaymentSchedule.createSchedule()`
10. Record payments → `PaymentRecording.recordPayment()` (all installments)
11. Verify full repayment → `LoanFullyRepaid` event emitted
12. Verify audit trail → `AuditRegistry.getFullAuditTrail()`

---

### Task 4.2 — Gas Optimization

For each contract, measure and optimize:
- Storage layout (pack structs)
- Use `bytes32` over `string` where possible
- Minimize on-chain data (store hashes, not raw data)
- Use events for historical data instead of storage arrays

**Target gas costs:**
| Operation | Target Gas |
|-----------|-----------|
| createApplication | < 150,000 |
| submitApplication | < 80,000 |
| approveLoan | < 80,000 |
| initiateDisbursement | < 100,000 |
| completeDisbursement | < 80,000 |
| createSchedule (12 months) | < 500,000 |
| recordPayment | < 100,000 |

---

### Task 4.3 — Security Checklist

For each contract, verify:
- [ ] Reentrancy guards on all state-changing functions
- [ ] Access control on every external function
- [ ] Input validation (zero amounts, zero addresses, empty hashes)
- [ ] Integer overflow protection (Solidity 0.8.x built-in)
- [ ] No `tx.origin` usage
- [ ] No unchecked external calls
- [ ] UUPS upgrade authorization locked to UPGRADER_ROLE
- [ ] Pausable pattern implemented for emergency stops

---

### Task 4.4 — Update Deployment Scripts

**File:** `smartcontracts/scripts/deploy-v2.js`

Deployment order (dependency-aware):
1. `AuditRegistry`
2. `LoanAccessControl`
3. `LoanApplication` (depends on AccessControl + AuditRegistry)
4. `LoanReview` (depends on LoanApplication)
5. `LoanApproval` (depends on LoanApplication)
6. `DisbursementMethod` (depends on LoanApplication)
7. `DisbursementExecution` (depends on LoanApproval + DisbursementMethod)
8. `RepaymentSchedule` (depends on LoanApplication)
9. `PaymentRecording` (depends on RepaymentSchedule)
10. Grant LOGGER_ROLE to all contracts on AuditRegistry
11. Grant SYSTEM_ROLE to backend service wallet

---

### Task 4.5 — Testnet Deployment & Validation

- Deploy all contracts to Polygon Mumbai or Sepolia testnet
- Run full lifecycle integration test on testnet
- Verify all events are emitted correctly
- Verify AuditRegistry trail is complete and verifiable
- Document deployed contract addresses

---

## Sprint 5 — Phase 2 Integration (Weeks 9–10)

> **Gate:** All Phase 1 contracts must be deployed and validated on testnet before Sprint 5 begins.

---

### Task 5.1 — Backend Blockchain Service Layer

**Files to create:**
```
loans/blockchain/
├── __init__.py
├── client.py              # Web3 connection and contract loading
├── services/
│   ├── application_service.py   # Calls LoanApplication contract
│   ├── review_service.py        # Calls LoanReview contract
│   ├── approval_service.py      # Calls LoanApproval contract
│   ├── disbursement_service.py  # Calls DisbursementMethod + DisbursementExecution
│   └── repayment_service.py     # Calls RepaymentSchedule + PaymentRecording
├── event_listener.py            # Listens for contract events
└── models/
    └── blockchain_tx.py         # Stores tx hashes linked to DB records
```

**Key integration points:**
- After `LoanApplication.submit()` in backend → call `LoanApplication.submitApplication()` on-chain
- After `LoanApplication.approve()` in backend → call `LoanApproval.approveLoan()` on-chain
- After `LoanApplication.disburse()` in backend → call `DisbursementExecution.completeDisbursement()` on-chain
- After `RepaymentSchedule.generate_for_loan()` → call `RepaymentSchedule.createSchedule()` on-chain
- After `RepaymentSchedule.record_payment()` → call `PaymentRecording.recordPayment()` on-chain

---

### Task 5.2 — Web Application Integration

**Files to create in `Capstone-Web/src/blockchain/`:**
```
hooks/
├── useWallet.ts           # Wallet connection (MetaMask/WalletConnect)
├── useContract.ts         # Contract instance management
└── useTransaction.ts      # Transaction submission and status

services/
├── contractService.ts     # ABI loading and contract calls
└── walletService.ts       # Wallet management

components/
├── TransactionStatus.tsx  # Show pending/confirmed/failed
├── BlockchainBadge.tsx    # Show "Verified on blockchain" badge
└── AuditTrail.tsx         # Display full audit trail for a loan
```

---

### Task 5.3 — Mobile Application Integration

**Files to create in `MSME-Pathways-Mobile/src/blockchain/`:**
```
services/
├── walletService.ts       # Mobile wallet (WalletConnect v2)
└── contractService.ts     # Contract interaction

components/
├── TransactionModal.tsx   # Confirm transaction modal
└── AuditTrail.tsx         # Audit trail display
```

---

## Contract Dependency Map

```
AuditRegistry ◄─────────────────────────────────────────────────────┐
LoanAccessControl ◄──────────────────────────────────────────────┐  │
                                                                  │  │
LoanApplication ──────────────────────────────────────────────►  │  │
    │                                                             │  │
    ├──► LoanReview ──────────────────────────────────────────►  │  │
    │                                                             │  │
    ├──► LoanApproval ────────────────────────────────────────►  │  │
    │        │                                                    │  │
    │        ▼                                                    │  │
    ├──► DisbursementMethod ──────────────────────────────────►  │  │
    │        │                                                    │  │
    │        ▼                                                    │  │
    │    DisbursementExecution ───────────────────────────────►  │  │
    │        │                                                    │  │
    │        ▼                                                    │  │
    └──► RepaymentSchedule ───────────────────────────────────►  │  │
              │                                                   │  │
              ▼                                                   │  │
          PaymentRecording ──────────────────────────────────►   │  │
```

---

## File Structure (Final)

```
smartcontracts/contracts/
├── core/
│   ├── LoanApplication.sol       [NEW - Sprint 1]
│   ├── LoanReview.sol            [NEW - Sprint 1]
│   └── LoanApproval.sol          [NEW - Sprint 1]
├── disbursement/
│   ├── DisbursementMethod.sol    [NEW - Sprint 2]
│   └── DisbursementExecution.sol [REFACTOR - Sprint 2]
├── repayment/
│   ├── RepaymentSchedule.sol     [NEW - Sprint 3]
│   └── PaymentRecording.sol      [NEW - Sprint 3]
├── access/
│   └── LoanAccessControl.sol     [KEEP - no changes]
├── audit/
│   └── AuditRegistry.sol         [KEEP - no changes]
├── interfaces/
│   ├── ILoanApplication.sol      [NEW - Sprint 1]
│   ├── ILoanReview.sol           [NEW - Sprint 1]
│   ├── ILoanApproval.sol         [NEW - Sprint 1]
│   ├── IDisbursementMethod.sol   [NEW - Sprint 2]
│   ├── IDisbursementExecution.sol[NEW - Sprint 2]
│   ├── IRepaymentSchedule.sol    [NEW - Sprint 3]
│   ├── IPaymentRecording.sol     [NEW - Sprint 3]
│   ├── ILoanCore.sol             [KEEP]
│   ├── ILoanAccessControl.sol    [KEEP]
│   └── IAuditRegistry.sol        [KEEP]
└── legacy/
    ├── LoanCore.sol              [DEPRECATED after Sprint 1]
    ├── Disbursement.sol          [DEPRECATED after Sprint 2]
    └── Repayment.sol             [DEPRECATED after Sprint 3]
```

---

## Task Summary Table

| Task | Contract | Sprint | Priority | Status |
|------|----------|--------|----------|--------|
| 1.1 | LoanApplication.sol | 1 | HIGH | Pending |
| 1.2 | LoanReview.sol | 1 | HIGH | Pending |
| 1.3 | LoanApproval.sol | 1 | HIGH | Pending |
| 1.4 | ILoanApplication.sol | 1 | HIGH | Pending |
| 1.5 | Sprint 1 Tests | 1 | HIGH | Pending |
| 2.1 | DisbursementMethod.sol | 2 | HIGH | Pending |
| 2.2 | DisbursementExecution.sol | 2 | HIGH | Pending |
| 2.3 | Sprint 2 Tests | 2 | HIGH | Pending |
| 3.1 | RepaymentSchedule.sol | 3 | HIGH | Pending |
| 3.2 | PaymentRecording.sol | 3 | HIGH | Pending |
| 3.3 | Sprint 3 Tests | 3 | HIGH | Pending |
| 4.1 | Integration Tests | 4 | HIGH | Pending |
| 4.2 | Gas Optimization | 4 | MEDIUM | Pending |
| 4.3 | Security Checklist | 4 | HIGH | Pending |
| 4.4 | Deploy Scripts | 4 | HIGH | Pending |
| 4.5 | Testnet Deployment | 4 | HIGH | Pending |
| 5.1 | Backend Service Layer | 5 | HIGH | Pending |
| 5.2 | Web App Integration | 5 | MEDIUM | Pending |
| 5.3 | Mobile App Integration | 5 | MEDIUM | Pending |

---

**Document Version:** 1.0  
**Status:** Ready for Development
