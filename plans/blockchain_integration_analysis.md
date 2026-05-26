# Blockchain Integration Analysis & Architecture Plan

**Date:** 2026-03-14  
**Prepared by:** Senior Blockchain Architect  
**Project:** MSME Loan Platform - Blockchain Integration

---

## Executive Summary

This document provides a comprehensive analysis of the current backend transaction implementations, compares them with existing smart contracts, identifies gaps, and proposes a structured blockchain architecture based on separation of concerns principles.

### Key Findings

1. **Backend has 8 distinct transaction types** across the loan lifecycle
2. **Smart contracts cover 5 core operations** but lack granular separation
3. **3 critical transaction types are missing** from blockchain implementation
4. **Architecture needs restructuring** to align with separation of concerns

---

## 1. Backend Transaction Analysis

### 1.1 Loan Application Lifecycle Transactions

#### Transaction Type: Loan Application Creation
- **Location:** [`loans/models/application.py`](../loans/models/application.py:26)
- **Method:** `LoanApplication.__init__()` and `save()`
- **Status Flow:** `draft` → `submitted`
- **Key Operations:**
  - Create loan application record
  - Store customer ID, product ID, requested amount, term
  - AI eligibility scoring and risk categorization
  - Store AI recommendation data
- **Critical Data:**
  - `customer_id`, `product_id`
  - `requested_amount`, `term_months`
  - `eligibility_score`, `risk_category`
  - `ai_recommendation` (JSON object)

#### Transaction Type: Loan Submission
- **Location:** [`loans/models/application.py`](../loans/models/application.py:146)
- **Method:** `submit()`
- **Status Flow:** `draft` → `submitted`
- **Key Operations:**
  - Mark application as submitted
  - Record submission timestamp
  - Trigger notification to loan officers
- **Critical Data:**
  - `submitted_at` timestamp
  - Status change audit

#### Transaction Type: Officer Assignment
- **Location:** [`loans/models/application.py`](../loans/models/application.py:152)
- **Method:** `assign_officer(officer_id)`
- **Status Flow:** `submitted` → `under_review`
- **Key Operations:**
  - Assign loan officer to application
  - Change status to under review
- **Critical Data:**
  - `assigned_officer` ID
  - Assignment timestamp

#### Transaction Type: Loan Approval
- **Location:** [`loans/models/application.py`](../loans/models/application.py:158)
- **Method:** `approve(officer_id, approved_amount, notes)`
- **Status Flow:** `under_review` → `approved`
- **Key Operations:**
  - Approve loan application
  - Set approved amount (may differ from requested)
  - Record officer notes
  - Record decision timestamp
- **Critical Data:**
  - `approved_amount`
  - `officer_notes` (encrypted)
  - `decision_date`
  - Officer ID who approved

#### Transaction Type: Loan Rejection
- **Location:** [`loans/models/application.py`](../loans/models/application.py:167)
- **Method:** `reject(officer_id, reason, notes)`
- **Status Flow:** `under_review` → `rejected`
- **Key Operations:**
  - Reject loan application
  - Record rejection reason
  - Record officer notes
  - Record decision timestamp
- **Critical Data:**
  - `rejection_reason` (encrypted)
  - `officer_notes` (encrypted)
  - `decision_date`
  - Officer ID who rejected

### 1.2 Disbursement Transactions

#### Transaction Type: Loan Disbursement
- **Location:** [`loans/models/application.py`](../loans/models/application.py:239)
- **Method:** `disburse(amount, method, reference, processed_by)`
- **Status Flow:** `approved` → `disbursed`
- **Key Operations:**
  - Transfer funds to borrower
  - Record disbursement details
  - Generate repayment schedule
  - Update loan status
- **Critical Data:**
  - `disbursed_amount`
  - `disbursement_method` (bank_transfer, gcash, cash, etc.)
  - `disbursement_reference` (encrypted transaction reference)
  - `disbursed_at` timestamp
  - `disbursed_by` (officer/admin ID)
- **Financial Impact:** HIGH - Actual fund transfer

#### Transaction Type: Disbursement Method Selection
- **Location:** [`loans/models/application.py`](../loans/models/application.py:252)
- **Method:** `set_preferred_disbursement_method(method)`
- **Status Flow:** No status change (approved remains approved)
- **Key Operations:**
  - Borrower selects preferred disbursement method
  - Validates method (bank_transfer or gcash)
- **Critical Data:**
  - `preferred_disbursement_method`

### 1.3 Repayment Transactions

#### Transaction Type: Repayment Schedule Generation
- **Location:** [`loans/models/repayment.py`](../loans/models/repayment.py:84)
- **Method:** `RepaymentSchedule.generate_for_loan(loan_application, product)`
- **Trigger:** Automatically after disbursement
- **Key Operations:**
  - Calculate monthly payment amounts
  - Generate installment schedule
  - Calculate total interest and repayment amount
  - Create installment records
- **Critical Data:**
  - `principal`, `interest_rate`, `term_months`
  - `monthly_payment`, `total_amount`, `total_interest`
  - `installments[]` array with due dates
  - `start_date` (disbursement date)

#### Transaction Type: Payment Recording
- **Location:** [`loans/models/repayment.py`](../loans/models/repayment.py:210)
- **Method:** `record_payment(installment_number, amount)`
- **Key Operations:**
  - Record payment against specific installment
  - Update installment status (pending → partial → paid)
  - Update total paid amount
  - Track payment timestamp
- **Critical Data:**
  - `installment_number`
  - `amount` paid
  - `paid_amount` (cumulative for installment)
  - `status` (pending/partial/paid)
  - `paid_at` timestamp
- **Financial Impact:** HIGH - Payment tracking

#### Transaction Type: Payment Record Creation
- **Location:** [`loans/models/payment.py`](../loans/models/payment.py:16)
- **Method:** `LoanPayment.__init__()` and `save()`
- **Key Operations:**
  - Create individual payment record
  - Link to loan and schedule
  - Record payment method and reference
  - Track who recorded the payment
- **Critical Data:**
  - `loan_id`, `schedule_id`, `customer_id`
  - `installment_number`
  - `amount`
  - `payment_method` (cash, bank_transfer, gcash, other)
  - `reference` (transaction reference)
  - `recorded_by` (officer ID)
  - `recorded_at` timestamp

---

## 2. Existing Smart Contract Analysis

### 2.1 Current Smart Contract Structure

The existing smart contracts are located in [`smartcontracts/contracts/`](../smartcontracts/contracts/)

#### Contract: LoanCore.sol
- **Purpose:** Core loan lifecycle management
- **Functions Covered:**
  - `createLoan()` - Create loan application
  - `submitLoan()` - Submit for review
  - `assignOfficer()` - Assign to loan officer
  - `approveLoan()` - Approve application
  - `rejectLoan()` - Reject application
  - `markDisbursed()` - Mark as disbursed (called by Disbursement contract)
- **Status Management:** Draft → Submitted → UnderReview → Approved/Rejected → Disbursed
- **Data Stored:**
  - Loan details (amounts, terms, interest rate)
  - Status and timestamps
  - Officer assignments
  - Hashes of sensitive data (AI recommendations, notes, reasons)

#### Contract: Disbursement.sol
- **Purpose:** Handles loan disbursement process
- **Functions Covered:**
  - `initiateDisbursement()` - Start disbursement process
  - `completeDisbursement()` - Complete with reference
- **Status Management:** Pending → Processing → Completed
- **Data Stored:**
  - Disbursement records
  - Amount, method, reference hash
  - Processing timestamps
  - Officer who processed

#### Contract: Repayment.sol
- **Purpose:** Manages repayment schedules and payments
- **Functions Covered:**
  - `createSchedule()` - Generate repayment schedule
  - `recordPayment()` - Record payment against installment
  - `markOverdue()` - Mark installments as overdue
- **Status Management:** Pending → Paid/Partial/Overdue
- **Data Stored:**
  - Schedule details (principal, interest, term)
  - Installment records with due dates
  - Payment records with methods and references
  - Total amounts and balances

#### Contract: LoanAccessControl.sol
- **Purpose:** Central access control and role management
- **Functions Covered:**
  - `registerOfficer()` - Register loan officer
  - `deactivateOfficer()` - Deactivate officer
  - `registerBorrower()` - Register borrower
  - `isActiveOfficer()` - Check officer status
- **Roles Managed:**
  - ADMIN_ROLE
  - LOAN_OFFICER_ROLE
  - BORROWER_ROLE
  - SYSTEM_ROLE

#### Contract: AuditRegistry.sol
- **Purpose:** Immutable audit trail for all transactions
- **Functions Covered:**
  - `log()` - Log audit entry
  - `logBatch()` - Batch logging
  - `getFullAuditTrail()` - Retrieve audit history
  - `verifyAuditTrail()` - Verify trail integrity
- **Data Stored:**
  - Action type, actor, timestamps
  - State transition hashes
  - Resource IDs and types

---

## 3. Gap Analysis: Backend vs Smart Contracts

### 3.1 Transaction Coverage Matrix

| Backend Transaction | Smart Contract | Status | Notes |
|---------------------|----------------|--------|-------|
| Loan Application Creation | LoanCore.createLoan() | ✅ COVERED | Well aligned |
| Loan Submission | LoanCore.submitLoan() | ✅ COVERED | Well aligned |
| Officer Assignment | LoanCore.assignOfficer() | ✅ COVERED | Well aligned |
| Loan Approval | LoanCore.approveLoan() | ✅ COVERED | Well aligned |
| Loan Rejection | LoanCore.rejectLoan() | ✅ COVERED | Well aligned |
| Disbursement Method Selection | **MISSING** | ❌ GAP | No smart contract |
| Loan Disbursement | Disbursement.initiateDisbursement() + completeDisbursement() | ⚠️ PARTIAL | Two-step process, needs alignment |
| Repayment Schedule Generation | Repayment.createSchedule() | ✅ COVERED | Well aligned |
| Payment Recording | Repayment.recordPayment() | ✅ COVERED | Well aligned |
| Payment Record Creation | **MISSING** | ❌ GAP | Merged into recordPayment() |

### 3.2 Identified Gaps

#### Gap 1: Disbursement Method Selection (MISSING)
- **Backend Implementation:** [`loans/models/application.py:252`](../loans/models/application.py:252)
- **Smart Contract:** None
- **Impact:** Medium
- **Recommendation:** Create separate contract or add to Disbursement.sol
- **Rationale:** Borrower preference should be recorded on-chain for transparency

#### Gap 2: Granular Payment Record Tracking (MISSING)
- **Backend Implementation:** [`loans/models/payment.py`](../loans/models/payment.py:16)
- **Smart Contract:** Merged into Repayment.recordPayment()
- **Impact:** Low
- **Recommendation:** Current implementation acceptable, but consider separation
- **Rationale:** Backend maintains separate payment records for detailed tracking

#### Gap 3: Internal Notes and Document Requests (MISSING)
- **Backend Implementation:** 
  - [`loans/models/application.py:176`](../loans/models/application.py:176) - `add_internal_note()`
  - [`loans/models/application.py:195`](../loans/models/application.py:195) - `request_missing_documents()`
- **Smart Contract:** None
- **Impact:** Low
- **Recommendation:** Keep off-chain (privacy concerns)
- **Rationale:** Internal operational data, not critical for blockchain

---

## 4. Separation of Concerns Analysis

### 4.1 Current Architecture Issues

The existing smart contract architecture has good separation but can be improved:

**Current Structure:**
```
LoanCore.sol (500+ lines)
├── Loan lifecycle (create, submit, assign, approve, reject)
├── Status management
└── Disbursement marking

Disbursement.sol (324 lines)
├── Disbursement initiation
└── Disbursement completion

Repayment.sol (579 lines)
├── Schedule creation
├── Payment recording
└── Overdue marking
```

**Issues:**
1. LoanCore handles too many responsibilities
2. Disbursement is split into two steps but lacks method selection
3. No clear separation between schedule management and payment recording

### 4.2 Recommended Architecture (Separation of Concerns)

```
smartcontracts/contracts/
├── core/
│   ├── LoanApplication.sol          [NEW - Separated]
│   ├── LoanReview.sol                [NEW - Separated]
│   └── LoanApproval.sol              [NEW - Separated]
├── disbursement/
│   ├── DisbursementMethod.sol        [NEW - Missing]
│   └── DisbursementExecution.sol     [REFACTOR from Disbursement.sol]
├── repayment/
│   ├── RepaymentSchedule.sol         [NEW - Separated]
│   └── PaymentRecording.sol          [NEW - Separated]
├── access/
│   └── LoanAccessControl.sol         [KEEP - Already good]
└── audit/
    └── AuditRegistry.sol             [KEEP - Already good]
```

---

## 5. Proposed Smart Contract Architecture

### 5.1 Core Loan Contracts (Separated)

#### Contract: LoanApplication.sol
**Responsibility:** Loan application creation and submission only

**Functions:**
- `createApplication(bytes32 loanId, bytes32 productId, uint256 requestedAmount, uint16 termMonths, uint16 interestRateBps)`
- `submitApplication(bytes32 loanId, uint8 eligibilityScore, RiskCategory riskCategory, bytes32 aiRecommendationHash)`
- `cancelApplication(bytes32 loanId)` - Borrower cancellation

**Events:**
- `ApplicationCreated`
- `ApplicationSubmitted`
- `ApplicationCancelled`

**Rationale:** Separates application creation from review process

#### Contract: LoanReview.sol
**Responsibility:** Officer assignment and review process

**Functions:**
- `assignOfficer(bytes32 loanId, address officer)`
- `reassignOfficer(bytes32 loanId, address newOfficer)`
- `requestDocuments(bytes32 loanId, bytes32[] documentTypes, bytes32 reasonHash)`

**Events:**
- `OfficerAssigned`
- `OfficerReassigned`
- `DocumentsRequested`

**Rationale:** Separates review workflow from approval decisions

#### Contract: LoanApproval.sol
**Responsibility:** Approval and rejection decisions only

**Functions:**
- `approveLoan(bytes32 loanId, uint256 approvedAmount, bytes32 notesHash)`
- `rejectLoan(bytes32 loanId, bytes32 rejectionReasonHash, bytes32 notesHash)`

**Events:**
- `LoanApproved`
- `LoanRejected`

**Rationale:** Critical financial decisions in dedicated contract

### 5.2 Disbursement Contracts (Separated)

#### Contract: DisbursementMethod.sol [NEW]
**Responsibility:** Borrower disbursement method selection

**Functions:**
- `setPreferredMethod(bytes32 loanId, DisbursementMethod method)`
- `getPreferredMethod(bytes32 loanId) returns (DisbursementMethod)`

**Events:**
- `DisbursementMethodSelected`

**Rationale:** Borrower preference should be recorded on-chain

#### Contract: DisbursementExecution.sol [REFACTOR]
**Responsibility:** Actual disbursement execution

**Functions:**
- `initiateDisbursement(bytes32 loanId, uint256 amount, DisbursementMethod method)`
- `completeDisbursement(bytes32 disbursementId, bytes32 referenceHash)`
- `cancelDisbursement(bytes32 disbursementId, bytes32 reasonHash)` - For failed transfers

**Events:**
- `DisbursementInitiated`
- `DisbursementCompleted`
- `DisbursementCancelled`

**Rationale:** Separates method selection from execution

### 5.3 Repayment Contracts (Separated)

#### Contract: RepaymentSchedule.sol [NEW]
**Responsibility:** Schedule generation and management only

**Functions:**
- `createSchedule(bytes32 loanId, address borrower, uint256 principal, uint16 interestRateBps, uint16 termMonths, uint256 startDate)`
- `getSchedule(bytes32 loanId) returns (RepaymentSchedule)`
- `getInstallment(bytes32 loanId, uint16 number) returns (Installment)`
- `getAllInstallments(bytes32 loanId) returns (Installment[])`

**Events:**
- `ScheduleCreated`

**Rationale:** Schedule is immutable once created, separate from payments

#### Contract: PaymentRecording.sol [NEW]
**Responsibility:** Payment recording and tracking only

**Functions:**
- `recordPayment(bytes32 loanId, uint16 installmentNumber, uint256 amount, PaymentMethod method, bytes32 referenceHash)`
- `markOverdue(bytes32 loanId, uint16 installmentNumber)`
- `getPaymentHistory(bytes32 loanId) returns (Payment[])`
- `getRemainingBalance(bytes32 loanId) returns (uint256)`

**Events:**
- `PaymentRecorded`
- `InstallmentPaid`
- `InstallmentOverdue`
- `LoanFullyRepaid`

**Rationale:** Payment operations separate from schedule structure

---

## 6. Phase 1: Smart Contract Design & Implementation

### 6.1 Objectives

1. Finalize all smart contract designs with separation of concerns
2. Implement missing smart contracts
3. Refactor existing contracts for better separation
4. Complete testing and security audits
5. Deploy to testnet for validation

### 6.2 Deliverables

#### Deliverable 1: New Smart Contracts
- [x] `LoanApplication.sol` - Application creation and submission
- [x] `LoanReview.sol` - Officer assignment and review
- [x] `LoanApproval.sol` - Approval/rejection decisions
- [x] `DisbursementMethod.sol` - Method selection
- [x] `RepaymentSchedule.sol` - Schedule management
- [x] `PaymentRecording.sol` - Payment tracking

#### Deliverable 2: Refactored Contracts
- [x] Refactor `LoanCore.sol` → Split into Application, Review, Approval
- [x] Refactor `Disbursement.sol` → DisbursementExecution.sol
- [x] Refactor `Repayment.sol` → RepaymentSchedule.sol + PaymentRecording.sol

#### Deliverable 3: Interface Contracts
- [x] `ILoanApplication.sol`
- [ ] `ILoanReview.sol`
- [ ] `ILoanApproval.sol`
- [ ] `IDisbursementMethod.sol`
- [ ] `IDisbursementExecution.sol`
- [ ] `IRepaymentSchedule.sol`
- [ ] `IPaymentRecording.sol`
- [x] `ILoanReview.sol`
- [x] `ILoanApproval.sol`
- [x] `IDisbursementMethod.sol`
- [x] `IDisbursementExecution.sol`
- [x] `IRepaymentSchedule.sol`
- [x] `IPaymentRecording.sol`

#### Deliverable 4: Testing Suite
- [x] Unit tests for each contract
- [x] Integration tests for contract interactions
- [x] Gas optimization tests
- [x] Security audit preparation

#### Deliverable 5: Documentation
- [ ] Contract architecture diagrams
- [x] Function reference documentation
- [x] Deployment guide
- [ ] Security considerations document
- [x] Contract architecture diagrams
- [x] Function reference documentation
- [x] Deployment guide
- [x] Security considerations document

### 6.3 Success Criteria

- All contracts follow single responsibility principle
- Each transaction type has dedicated contract
- All backend transactions have blockchain equivalents
- Contracts pass security audit
- Gas costs are optimized
- Testnet deployment successful

---

## 7. Phase 2: System Integration

### 7.1 Integration Points

#### Backend Integration
- [x] Update Django models to interact with new contracts
- [x] Create blockchain service layer
- [x] Implement transaction signing and submission
- [ ] Add blockchain event listeners
- [x] Sync on-chain and off-chain data
- [x] Create blockchain service layer
- [x] Implement transaction signing and submission
- [x] Add blockchain event listeners
- [x] Sync on-chain and off-chain data

#### Web Application Integration
- [ ] Connect Web3 wallet (MetaMask, WalletConnect)
- [ ] Display blockchain transaction status
- [ ] Show gas estimates
- [ ] Handle transaction confirmations
- [ ] Display audit trail from blockchain

#### Mobile Application Integration
- [ ] Integrate mobile wallet support
- [ ] Implement transaction signing on mobile
- [ ] Display blockchain confirmations
- [ ] Handle network switching
- [ ] Offline transaction queuing

### 7.2 Integration Architecture

```
Backend (Django)
├── blockchain/
│   ├── services/
│   │   ├── contract_service.py       [Contract interaction]
│   │   ├── transaction_service.py    [Transaction management]
│   │   └── event_listener.py         [Event monitoring]
│   ├── models/
│   │   ├── blockchain_transaction.py [Transaction records]
│   │   └── contract_state.py         [State sync]
│   └── utils/
│       ├── web3_client.py            [Web3 connection]
│       └── abi_loader.py             [Contract ABIs]

Web Application (React)
├── blockchain/
│   ├── hooks/
│   │   ├── useContract.ts            [Contract hooks]
│   │   ├── useTransaction.ts         [Transaction hooks]
│   │   └── useWallet.ts              [Wallet connection]
│   ├── services/
│   │   ├── contractService.ts        [Contract calls]
│   │   └── walletService.ts          [Wallet management]
│   └── components/
│       ├── TransactionStatus.tsx     [TX status display]
│       └── BlockchainAudit.tsx       [Audit trail]

Mobile Application (React Native)
├── blockchain/
│   ├── services/
│   │   ├── walletService.ts          [Mobile wallet]
│   │   └── contractService.ts        [Contract interaction]
│   └── components/
│       ├── TransactionModal.tsx      [TX confirmation]
│       └── AuditTrail.tsx            [Audit display]
```

### 7.3 Data Synchronization Strategy

**Hybrid Approach:**
- Critical financial transactions → Blockchain (source of truth)
- Operational data → Database (performance)
- Audit trail → Both (redundancy)

**Sync Flow:**
1. User initiates action in UI
2. Backend validates and prepares transaction
3. Transaction sent to blockchain
4. Event listener captures confirmation
5. Database updated with blockchain reference
6. UI updated with confirmation

---

## 8. Recommendations

### 8.1 Immediate Actions

1. **Approve Architecture:** Review and approve the proposed separation of concerns architecture
2. **Prioritize Contracts:** Start with critical path contracts (Application → Approval → Disbursement → Payment)
3. **Set Up Development Environment:** Configure Hardhat, testing framework, and testnet access
4. **Create Contract Templates:** Establish coding standards and templates

### 8.2 Development Sequence

**Sprint 1: Core Loan Contracts**
- LoanApplication.sol
- LoanReview.sol
- LoanApproval.sol

**Sprint 2: Disbursement Contracts**
- DisbursementMethod.sol
- DisbursementExecution.sol (refactored)

**Sprint 3: Repayment Contracts**
- RepaymentSchedule.sol
- PaymentRecording.sol

**Sprint 4: Testing & Security**
- Comprehensive testing
- Security audit
- Gas optimization

**Sprint 5: Integration**
- Backend integration
- Web app integration
- Mobile app integration

### 8.3 Risk Mitigation

**Technical Risks:**
- Gas costs too high → Optimize storage, use events
- Contract size limits → Modular design already addresses this
- Upgrade complexity → Use UUPS proxy pattern (already in place)

**Business Risks:**
- Blockchain downtime → Maintain database fallback
- Transaction failures → Implement retry mechanism
- User adoption → Gradual rollout, optional blockchain features initially

---

## 9. Conclusion

The current backend has a well-structured transaction system with 8 distinct transaction types. The existing smart contracts cover the core functionality but lack the granular separation needed for optimal blockchain architecture.

**Key Takeaways:**

1. **3 Missing Smart Contracts** need to be created (DisbursementMethod, RepaymentSchedule, PaymentRecording)
2. **3 Existing Contracts** need refactoring for better separation (LoanCore → 3 contracts, Disbursement → 1 contract, Repayment → 2 contracts)
3. **Phase 1 Focus:** Complete all smart contract design and implementation before integration
4. **Phase 2 Focus:** Integrate finalized contracts with backend, web, and mobile applications

**Next Steps:**

1. Review and approve this architecture plan
2. Begin Phase 1 development with LoanApplication.sol
3. Establish testing and security audit processes
4. Plan Phase 2 integration timeline

---

## Appendices

### Appendix A: Contract Function Mapping

| Backend Function | Current Smart Contract | Proposed Smart Contract |
|------------------|------------------------|-------------------------|
| `LoanApplication.save()` | `LoanCore.createLoan()` | `LoanApplication.createApplication()` |
| `LoanApplication.submit()` | `LoanCore.submitLoan()` | `LoanApplication.submitApplication()` |
| `LoanApplication.assign_officer()` | `LoanCore.assignOfficer()` | `LoanReview.assignOfficer()` |
| `LoanApplication.approve()` | `LoanCore.approveLoan()` | `LoanApproval.approveLoan()` |
| `LoanApplication.reject()` | `LoanCore.rejectLoan()` | `LoanApproval.rejectLoan()` |
| `LoanApplication.set_preferred_disbursement_method()` | None | `DisbursementMethod.setPreferredMethod()` |
| `LoanApplication.disburse()` | `Disbursement.initiateDisbursement()` + `completeDisbursement()` | `DisbursementExecution.initiateDisbursement()` + `completeDisbursement()` |
| `RepaymentSchedule.generate_for_loan()` | `Repayment.createSchedule()` | `RepaymentSchedule.createSchedule()` |
| `RepaymentSchedule.record_payment()` | `Repayment.recordPayment()` | `PaymentRecording.recordPayment()` |

### Appendix B: File Structure Reference

**Backend Files:**
- [`loans/models/application.py`](../loans/models/application.py) - Loan application model
- [`loans/models/payment.py`](../loans/models/payment.py) - Payment records
- [`loans/models/repayment.py`](../loans/models/repayment.py) - Repayment schedules
- [`loans/views/officer_views.py`](../loans/views/officer_views.py) - Officer operations
- [`loans/views/customer_views.py`](../loans/views/customer_views.py) - Customer operations

**Smart Contract Files:**
- [`smartcontracts/contracts/LoanCore.sol`](../smartcontracts/contracts/LoanCore.sol)
- [`smartcontracts/contracts/Disbursement.sol`](../smartcontracts/contracts/Disbursement.sol)
- [`smartcontracts/contracts/Repayment.sol`](../smartcontracts/contracts/Repayment.sol)
- [`smartcontracts/contracts/LoanAccessControl.sol`](../smartcontracts/contracts/LoanAccessControl.sol)
- [`smartcontracts/contracts/AuditRegistry.sol`](../smartcontracts/contracts/AuditRegistry.sol)

---

**Document Version:** 1.0  
**Last Updated:** 2026-03-14  
**Status:** Draft for Review
