# Smart Contract Architecture for MSME Pathways Loan System

## ⚠️ Implementation Note

> **This document is the original design proposal.** After aligning with the Django backend, only the following contracts were implemented:
> 
> | Implemented ✅ | Removed ❌ |
> |---------------|-----------|
> | `LoanAccessControl.sol` | `PenaltyCalculator.sol` (no backend feature) |
> | `LoanCore.sol` | `LoanOracle.sol` (no backend feature) |
> | `Disbursement.sol` | `TokenDisbursement.sol` (no ERC20 in backend) |
> | `Repayment.sol` | `TokenRepayment.sol` (no ERC20 in backend) |
> | `AuditRegistry.sol` | `LoanToken.sol` (no ERC20 in backend) |
> 
> See [BACKEND_ALIGNMENT_ANALYSIS.md](docs/BACKEND_ALIGNMENT_ANALYSIS.md) for current implementation status.

---

## Executive Summary

This document provides a comprehensive analysis of the MSME Pathways backend system and proposes a production-grade smart contract architecture that mirrors the existing financial and operational flows. The design prioritizes **security**, **auditability**, **regulatory compliance**, and **upgrade paths**.

---

## 1. System Mapping: Transaction Flow Analysis

### 1.1 Core Transaction Flows Identified

| Flow ID | Transaction Type | Origin | Endpoints Involved | Database Collections |
|---------|-----------------|--------|-------------------|---------------------|
| TXN-001 | Loan Application Submission | Customer | `POST /api/loans/apply/` | `loan_applications` |
| TXN-002 | Application Assignment | Admin/Auto | `POST /api/loans/admin/applications/<id>/assign/` | `loan_applications`, `loan_officers` |
| TXN-003 | Loan Approval | Loan Officer | `PUT /api/loans/officer/applications/<id>/review/` | `loan_applications` |
| TXN-004 | Loan Rejection | Loan Officer | `PUT /api/loans/officer/applications/<id>/review/` | `loan_applications` |
| TXN-005 | Loan Disbursement | Loan Officer | `POST /api/loans/officer/applications/<id>/disburse/` | `loan_applications`, `repayment_schedules` |
| TXN-006 | Payment Recording | Loan Officer | `POST /api/loans/officer/payments/` | `loan_payments`, `repayment_schedules` |
| TXN-007 | Application Resubmission | Customer | `POST /api/loans/applications/<id>/resubmit/` | `loan_applications` |
| TXN-008 | Document Upload | Customer | `POST /api/documents/upload/` | `documents` |
| TXN-009 | Document Verification | Loan Officer | `POST /api/documents/<id>/verify/` | `documents` |
| TXN-010 | Product Creation | Admin | `POST /api/loans/admin/products/` | `loan_products` |
| TXN-011 | Loan Officer Creation | Admin | `POST /api/accounts/admin/loan-officers/` | `loan_officers` |
| TXN-012 | Consent Recording | Customer | `POST /api/accounts/consent/` | `consents` |

### 1.2 Transaction Classification

#### Financial (Value-Moving) Transactions
| Transaction | Description | On-Chain Priority |
|------------|-------------|-------------------|
| **TXN-005** | Loan Disbursement | **CRITICAL** - Must be immutable |
| **TXN-006** | Payment Recording | **CRITICAL** - Must be immutable |

#### State-Changing (Approval/Status) Transactions
| Transaction | Description | On-Chain Priority |
|------------|-------------|-------------------|
| **TXN-001** | Application Submission | HIGH - Creates binding agreement |
| **TXN-002** | Officer Assignment | MEDIUM - Audit trail |
| **TXN-003** | Loan Approval | **CRITICAL** - Authorizes disbursement |
| **TXN-004** | Loan Rejection | HIGH - Must be transparent |
| **TXN-007** | Resubmission | MEDIUM - State transition |
| **TXN-009** | Document Verification | HIGH - KYC compliance |

#### Audit-Only Transactions
| Transaction | Description | On-Chain Priority |
|------------|-------------|-------------------|
| **TXN-008** | Document Upload | LOW - Hash/proof only |
| **TXN-010** | Product Creation | LOW - Config, off-chain OK |
| **TXN-011** | Officer Creation | LOW - IAM, off-chain OK |
| **TXN-012** | Consent Recording | MEDIUM - Regulatory proof |

---

## 2. Transaction Classification Matrix

### 2.1 On-Chain Candidates (Must Be Immutable & Trustless)

| Transaction | Justification | Data to Store On-Chain |
|------------|---------------|----------------------|
| Loan Creation | Binding financial commitment | loan_id, borrower_id, amount, term, interest_rate, timestamp |
| Loan Approval | Authorization with conditions | loan_id, approver_id, approved_amount, conditions_hash |
| Disbursement | Value transfer proof | loan_id, amount, method, reference, disbursement_time |
| Payment | Value receipt proof | loan_id, installment_number, amount, payment_time |
| Repayment Schedule | Contractual obligation | loan_id, installments_hash, total_amount |

### 2.2 Off-Chain with On-Chain Proof/Reference

| Transaction | On-Chain Component | Off-Chain Component |
|------------|-------------------|-------------------|
| Application Submission | Application hash, submission_time | Full application data, AI analysis |
| Document Verification | Document hash, verification_status | Actual documents (IPFS/S3) |
| Consent | Consent hash, timestamp | Full consent text, IP address |
| AI Qualification | Score hash, risk_category | Full AI recommendation |

### 2.3 Fully Off-Chain (Compliance/PII/Internal)

| Transaction | Reason for Off-Chain |
|------------|---------------------|
| Customer Profile Data | PII regulations (GDPR-like), Philippine Data Privacy Act |
| Business Profile Data | Sensitive business information |
| Alternative Data | Credit scoring inputs are proprietary |
| Loan Officer Management | Internal HR/IAM operations |
| Admin Operations | Internal system management |
| Notifications | Non-financial, no audit requirement |

---

## 3. Smart Contract Design Strategy

### 3.1 Recommended Architecture: Domain-Separated Contracts

**I recommend using MULTIPLE DOMAIN CONTRACTS** rather than a single modular contract.

#### Justification:

| Factor | Single Contract | Multiple Contracts | Winner |
|--------|----------------|-------------------|--------|
| **Gas Efficiency** | Higher per-call due to size | Lower, targeted calls | Multiple |
| **Upgradeability** | Risk of breaking everything | Isolated upgrades per domain | Multiple |
| **Security Boundaries** | Single point of failure | Blast radius containment | Multiple |
| **Regulatory Compliance** | All-or-nothing audits | Targeted compliance audits | Multiple |
| **Development Velocity** | Blocked by monolith | Parallel development | Multiple |
| **Code Audit Cost** | Higher (full review) | Modular audits possible | Multiple |

### 3.2 Proposed Contract Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ACCESS CONTROL                            │
│                    (LoanAccessControl.sol)                       │
│  Roles: ADMIN, LOAN_OFFICER, BORROWER, ORACLE, SYSTEM           │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   LoanCore    │    │ Disbursement  │    │   Repayment   │
│    .sol       │◄───│    .sol       │───►│     .sol      │
│               │    │               │    │               │
│ - Create Loan │    │ - Disburse    │    │ - Record Pay  │
│ - Approve     │    │ - Escrow Hold │    │ - Track Due   │
│ - Reject      │    │ - Release     │    │ - Mark Paid   │
│ - Cancel      │    │               │    │ - Penalties   │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  PenaltyCalc  │    │ AuditRegistry │    │  LoanOracle   │
│    .sol       │    │     .sol      │    │    .sol       │
│               │    │               │    │               │
│ - Late Fees   │    │ - Event Logs  │    │ - Off-chain   │
│ - Penalties   │    │ - Hash Proofs │    │   data feed   │
│ - Grace Period│    │ - Timestamps  │    │ - AI scores   │
└───────────────┘    └───────────────┘    └───────────────┘
```

### 3.3 Contract Interaction Flow

```
Customer applies → LoanCore.createLoan()
                          │
                          ▼
Officer approves → LoanCore.approveLoan()
                          │
                          ▼
Disbursement → Disbursement.disburse() → Creates escrow
                          │
                          ▼
Funds released → Disbursement.releaseFunds()
                          │
                          ▼
Schedule created → Repayment.initializeSchedule()
                          │
                          ▼
Payment made → Repayment.recordPayment()
                          │
                          ▼
Overdue check → PenaltyCalc.calculatePenalty()
                          │
                          ▼
All events → AuditRegistry.log()
```

---

## 4. Data Model Translation

### 4.1 LoanCore Contract

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/security/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

interface ILoanCore {
    // ============ Enums ============
    enum LoanStatus {
        Draft,           // 0 - Created but not submitted
        Submitted,       // 1 - Awaiting review
        UnderReview,     // 2 - Assigned to officer
        Approved,        // 3 - Approved, awaiting disbursement
        Rejected,        // 4 - Rejected by officer
        Disbursed,       // 5 - Funds transferred
        Active,          // 6 - Repayment in progress
        Completed,       // 7 - Fully repaid
        Defaulted,       // 8 - Borrower defaulted
        Cancelled        // 9 - Cancelled by customer/admin
    }

    enum RiskCategory {
        Low,
        Medium,
        High
    }

    // ============ Structs ============
    struct Loan {
        bytes32 loanId;                  // Unique identifier (hash of off-chain ID)
        address borrower;                // Borrower's wallet address
        bytes32 productId;               // Loan product reference
        uint256 requestedAmount;         // Amount requested (in wei or stablecoin units)
        uint256 approvedAmount;          // Amount approved
        uint256 disbursedAmount;         // Amount actually disbursed
        uint16 termMonths;               // Loan term in months
        uint16 interestRateBps;          // Interest rate in basis points (150 = 1.5%)
        LoanStatus status;
        RiskCategory riskCategory;
        uint8 eligibilityScore;          // 0-100
        bytes32 aiRecommendationHash;    // Hash of off-chain AI analysis
        address assignedOfficer;
        bytes32 rejectionReasonHash;     // Hash of rejection reason
        uint256 submittedAt;
        uint256 approvedAt;
        uint256 disbursedAt;
        uint256 createdAt;
        uint256 updatedAt;
    }

    // ============ Events ============
    event LoanCreated(
        bytes32 indexed loanId,
        address indexed borrower,
        bytes32 indexed productId,
        uint256 requestedAmount,
        uint16 termMonths,
        uint256 timestamp
    );

    event LoanSubmitted(
        bytes32 indexed loanId,
        address indexed borrower,
        uint8 eligibilityScore,
        RiskCategory riskCategory,
        uint256 timestamp
    );

    event LoanAssigned(
        bytes32 indexed loanId,
        address indexed officer,
        uint256 timestamp
    );

    event LoanApproved(
        bytes32 indexed loanId,
        address indexed officer,
        uint256 approvedAmount,
        uint256 timestamp
    );

    event LoanRejected(
        bytes32 indexed loanId,
        address indexed officer,
        bytes32 rejectionReasonHash,
        uint256 timestamp
    );

    event LoanStatusChanged(
        bytes32 indexed loanId,
        LoanStatus oldStatus,
        LoanStatus newStatus,
        uint256 timestamp
    );

    // ============ Functions ============
    function createLoan(
        bytes32 loanId,
        bytes32 productId,
        uint256 requestedAmount,
        uint16 termMonths,
        uint16 interestRateBps
    ) external returns (bool);

    function submitLoan(
        bytes32 loanId,
        uint8 eligibilityScore,
        RiskCategory riskCategory,
        bytes32 aiRecommendationHash
    ) external returns (bool);

    function assignOfficer(bytes32 loanId, address officer) external returns (bool);

    function approveLoan(
        bytes32 loanId,
        uint256 approvedAmount,
        bytes32 notesHash
    ) external returns (bool);

    function rejectLoan(
        bytes32 loanId,
        bytes32 rejectionReasonHash,
        bytes32 notesHash
    ) external returns (bool);

    function getLoan(bytes32 loanId) external view returns (Loan memory);
    function getLoanStatus(bytes32 loanId) external view returns (LoanStatus);
}
```

### 4.2 Disbursement Contract

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IDisbursement {
    // ============ Enums ============
    enum DisbursementStatus {
        Pending,         // Awaiting disbursement
        Processing,      // In progress
        Completed,       // Successfully disbursed
        Failed,          // Disbursement failed
        Reversed         // Reversed/refunded
    }

    enum DisbursementMethod {
        BankTransfer,
        Cash,
        GCash,
        Maya,
        Other
    }

    // ============ Structs ============
    struct Disbursement {
        bytes32 disbursementId;
        bytes32 loanId;
        address borrower;
        uint256 amount;
        DisbursementMethod method;
        bytes32 referenceHash;           // Hash of external reference number
        DisbursementStatus status;
        address processedBy;             // Officer who processed
        uint256 processedAt;
        uint256 createdAt;
        bytes32 failureReasonHash;       // If failed
        uint256 reversedAt;              // If reversed
        address reversedBy;              // Who reversed
    }

    // ============ Events ============
    event DisbursementInitiated(
        bytes32 indexed disbursementId,
        bytes32 indexed loanId,
        address indexed borrower,
        uint256 amount,
        DisbursementMethod method,
        uint256 timestamp
    );

    event DisbursementCompleted(
        bytes32 indexed disbursementId,
        bytes32 indexed loanId,
        bytes32 referenceHash,
        uint256 timestamp
    );

    event DisbursementFailed(
        bytes32 indexed disbursementId,
        bytes32 indexed loanId,
        bytes32 failureReasonHash,
        uint256 timestamp
    );

    event DisbursementReversed(
        bytes32 indexed disbursementId,
        bytes32 indexed loanId,
        address indexed reversedBy,
        bytes32 reasonHash,
        uint256 timestamp
    );

    // ============ Functions ============
    function initiateDisbursement(
        bytes32 loanId,
        uint256 amount,
        DisbursementMethod method
    ) external returns (bytes32 disbursementId);

    function completeDisbursement(
        bytes32 disbursementId,
        bytes32 referenceHash
    ) external returns (bool);

    function failDisbursement(
        bytes32 disbursementId,
        bytes32 failureReasonHash
    ) external returns (bool);

    function reverseDisbursement(
        bytes32 disbursementId,
        bytes32 reasonHash
    ) external returns (bool);

    function getDisbursement(bytes32 disbursementId) external view returns (Disbursement memory);
}
```

### 4.3 Repayment Contract

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IRepayment {
    // ============ Enums ============
    enum InstallmentStatus {
        Pending,
        Paid,
        Partial,
        Overdue,
        Defaulted
    }

    enum PaymentMethod {
        Cash,
        BankTransfer,
        GCash,
        Maya,
        Other
    }

    // ============ Structs ============
    struct RepaymentSchedule {
        bytes32 scheduleId;
        bytes32 loanId;
        address borrower;
        uint256 principal;
        uint16 interestRateBps;
        uint16 termMonths;
        uint256 monthlyPayment;
        uint256 totalAmount;
        uint256 totalInterest;
        uint256 totalPaid;
        uint256 remainingBalance;
        uint256 startDate;
        uint256 createdAt;
        bool isActive;
    }

    struct Installment {
        uint16 number;
        uint256 dueDate;
        uint256 principalAmount;
        uint256 interestAmount;
        uint256 totalAmount;
        uint256 paidAmount;
        uint256 penaltyAmount;
        InstallmentStatus status;
        uint256 paidAt;
    }

    struct Payment {
        bytes32 paymentId;
        bytes32 loanId;
        bytes32 scheduleId;
        uint16 installmentNumber;
        uint256 amount;
        PaymentMethod method;
        bytes32 referenceHash;
        address recordedBy;
        uint256 recordedAt;
    }

    // ============ Events ============
    event ScheduleCreated(
        bytes32 indexed scheduleId,
        bytes32 indexed loanId,
        address indexed borrower,
        uint256 principal,
        uint16 termMonths,
        uint256 monthlyPayment,
        uint256 timestamp
    );

    event PaymentRecorded(
        bytes32 indexed paymentId,
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        uint256 amount,
        uint256 remainingBalance,
        uint256 timestamp
    );

    event InstallmentStatusChanged(
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        InstallmentStatus oldStatus,
        InstallmentStatus newStatus,
        uint256 timestamp
    );

    event LoanFullyRepaid(
        bytes32 indexed loanId,
        uint256 totalPaid,
        uint256 timestamp
    );

    event InstallmentOverdue(
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        uint256 daysOverdue,
        uint256 timestamp
    );

    // ============ Functions ============
    function createSchedule(
        bytes32 loanId,
        address borrower,
        uint256 principal,
        uint16 interestRateBps,
        uint16 termMonths,
        uint256 startDate
    ) external returns (bytes32 scheduleId);

    function recordPayment(
        bytes32 loanId,
        uint16 installmentNumber,
        uint256 amount,
        PaymentMethod method,
        bytes32 referenceHash
    ) external returns (bytes32 paymentId);

    function markOverdue(bytes32 loanId, uint16 installmentNumber) external returns (bool);

    function getSchedule(bytes32 loanId) external view returns (RepaymentSchedule memory);
    function getInstallment(bytes32 loanId, uint16 number) external view returns (Installment memory);
    function getRemainingBalance(bytes32 loanId) external view returns (uint256);
    function getNextPayment(bytes32 loanId) external view returns (Installment memory);
}
```

### 4.4 Penalty Calculator Contract

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IPenaltyCalculator {
    // ============ Structs ============
    struct PenaltyConfig {
        uint256 gracePeriodDays;         // Days before penalty applies
        uint16 lateFeePercentBps;        // Late fee in basis points
        uint16 dailyPenaltyBps;          // Daily penalty rate in bps
        uint256 maxPenaltyPercent;       // Maximum penalty cap (percentage)
        bool compoundPenalty;            // Whether penalty compounds
    }

    struct PenaltyRecord {
        bytes32 loanId;
        uint16 installmentNumber;
        uint256 originalAmount;
        uint256 penaltyAmount;
        uint256 daysOverdue;
        uint256 calculatedAt;
        bool waived;
        address waivedBy;
        bytes32 waiveReasonHash;
    }

    // ============ Events ============
    event PenaltyCalculated(
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        uint256 penaltyAmount,
        uint256 daysOverdue,
        uint256 timestamp
    );

    event PenaltyWaived(
        bytes32 indexed loanId,
        uint16 indexed installmentNumber,
        address indexed waivedBy,
        uint256 amount,
        bytes32 reasonHash,
        uint256 timestamp
    );

    event PenaltyConfigUpdated(
        uint256 gracePeriodDays,
        uint16 lateFeePercentBps,
        uint16 dailyPenaltyBps,
        uint256 timestamp
    );

    // ============ Functions ============
    function calculatePenalty(
        bytes32 loanId,
        uint16 installmentNumber,
        uint256 originalAmount,
        uint256 dueDate
    ) external view returns (uint256 penaltyAmount, uint256 daysOverdue);

    function recordPenalty(
        bytes32 loanId,
        uint16 installmentNumber,
        uint256 penaltyAmount
    ) external returns (bool);

    function waivePenalty(
        bytes32 loanId,
        uint16 installmentNumber,
        bytes32 reasonHash
    ) external returns (bool);

    function updateConfig(
        uint256 gracePeriodDays,
        uint16 lateFeePercentBps,
        uint16 dailyPenaltyBps,
        uint256 maxPenaltyPercent,
        bool compoundPenalty
    ) external returns (bool);

    function getConfig() external view returns (PenaltyConfig memory);
}
```

### 4.5 Audit Registry Contract

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IAuditRegistry {
    // ============ Enums ============
    enum AuditAction {
        LoanCreated,
        LoanSubmitted,
        LoanAssigned,
        LoanApproved,
        LoanRejected,
        LoanDisbursed,
        PaymentRecorded,
        PenaltyApplied,
        PenaltyWaived,
        DocumentVerified,
        ConsentRecorded,
        SystemConfigChanged
    }

    // ============ Structs ============
    struct AuditEntry {
        bytes32 entryId;
        bytes32 resourceId;              // Loan ID, Document ID, etc.
        string resourceType;             // "loan", "document", "consent"
        AuditAction action;
        address actor;                   // Who performed the action
        bytes32 detailsHash;             // Hash of detailed off-chain data
        bytes32 previousStateHash;       // Hash of previous state
        bytes32 newStateHash;            // Hash of new state
        uint256 timestamp;
        uint256 blockNumber;
    }

    // ============ Events ============
    event AuditLogged(
        bytes32 indexed entryId,
        bytes32 indexed resourceId,
        AuditAction indexed action,
        address actor,
        uint256 timestamp
    );

    // ============ Functions ============
    function log(
        bytes32 resourceId,
        string calldata resourceType,
        AuditAction action,
        bytes32 detailsHash,
        bytes32 previousStateHash,
        bytes32 newStateHash
    ) external returns (bytes32 entryId);

    function getEntry(bytes32 entryId) external view returns (AuditEntry memory);
    function getEntriesByResource(bytes32 resourceId) external view returns (bytes32[] memory);
    function getEntriesByActor(address actor, uint256 limit) external view returns (bytes32[] memory);
    function verifyStateTransition(bytes32 resourceId, bytes32 expectedStateHash) external view returns (bool);
}
```

### 4.6 Loan Access Control Contract

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface ILoanAccessControl {
    // ============ Role Definitions ============
    // bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    // bytes32 public constant LOAN_OFFICER_ROLE = keccak256("LOAN_OFFICER_ROLE");
    // bytes32 public constant BORROWER_ROLE = keccak256("BORROWER_ROLE");
    // bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");
    // bytes32 public constant SYSTEM_ROLE = keccak256("SYSTEM_ROLE");
    // bytes32 public constant UPGRADER_ROLE = keccak256("UPGRADER_ROLE");

    // ============ Events ============
    event OfficerRegistered(
        address indexed officer,
        bytes32 indexed employeeIdHash,
        uint256 timestamp
    );

    event OfficerDeactivated(
        address indexed officer,
        address indexed deactivatedBy,
        uint256 timestamp
    );

    event BorrowerRegistered(
        address indexed borrower,
        bytes32 indexed customerIdHash,
        uint256 timestamp
    );

    event EmergencyPaused(
        address indexed pausedBy,
        string reason,
        uint256 timestamp
    );

    // ============ Functions ============
    function registerOfficer(address officer, bytes32 employeeIdHash) external returns (bool);
    function deactivateOfficer(address officer) external returns (bool);
    function registerBorrower(address borrower, bytes32 customerIdHash) external returns (bool);
    function isActiveOfficer(address officer) external view returns (bool);
    function isBorrower(address account) external view returns (bool);
    function emergencyPause(string calldata reason) external returns (bool);
    function unpause() external returns (bool);
}
```

### 4.7 Loan Oracle Contract (Off-chain Data Bridge)

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface ILoanOracle {
    // ============ Structs ============
    struct AIScore {
        bytes32 loanId;
        uint8 eligibilityScore;          // 0-100
        uint8 riskCategory;              // 0=Low, 1=Medium, 2=High
        uint256 recommendedAmount;
        bytes32 analysisHash;            // Hash of full AI analysis
        uint256 timestamp;
        bool isValid;
    }

    struct ExternalPayment {
        bytes32 loanId;
        bytes32 externalReference;
        uint256 amount;
        uint256 confirmedAt;
        bool isConfirmed;
    }

    // ============ Events ============
    event AIScoreSubmitted(
        bytes32 indexed loanId,
        uint8 eligibilityScore,
        uint8 riskCategory,
        uint256 recommendedAmount,
        uint256 timestamp
    );

    event PaymentConfirmed(
        bytes32 indexed loanId,
        bytes32 indexed externalReference,
        uint256 amount,
        uint256 timestamp
    );

    event OracleUpdated(
        address indexed oldOracle,
        address indexed newOracle,
        uint256 timestamp
    );

    // ============ Functions ============
    function submitAIScore(
        bytes32 loanId,
        uint8 eligibilityScore,
        uint8 riskCategory,
        uint256 recommendedAmount,
        bytes32 analysisHash
    ) external returns (bool);

    function confirmExternalPayment(
        bytes32 loanId,
        bytes32 externalReference,
        uint256 amount
    ) external returns (bool);

    function getAIScore(bytes32 loanId) external view returns (AIScore memory);
    function isPaymentConfirmed(bytes32 loanId, bytes32 reference) external view returns (bool);
}
```

---

## 5. Access Control Rules

### 5.1 Role-Based Permissions Matrix

| Function | ADMIN | LOAN_OFFICER | BORROWER | ORACLE | SYSTEM |
|----------|-------|--------------|----------|--------|--------|
| `createLoan` | ❌ | ❌ | ✅ | ❌ | ✅ |
| `submitLoan` | ❌ | ❌ | ✅ | ❌ | ✅ |
| `assignOfficer` | ✅ | ❌ | ❌ | ❌ | ✅ |
| `approveLoan` | ❌ | ✅ | ❌ | ❌ | ❌ |
| `rejectLoan` | ❌ | ✅ | ❌ | ❌ | ❌ |
| `initiateDisbursement` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `completeDisbursement` | ✅ | ✅ | ❌ | ❌ | ✅ |
| `reverseDisbursement` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `recordPayment` | ❌ | ✅ | ❌ | ✅ | ✅ |
| `waivePenalty` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `submitAIScore` | ❌ | ❌ | ❌ | ✅ | ✅ |
| `updateConfig` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `emergencyPause` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `upgrade` | ✅ (UPGRADER) | ❌ | ❌ | ❌ | ❌ |

### 5.2 Contract Invariants (Must NEVER Be Violated)

```solidity
// CRITICAL INVARIANTS - Enforced on-chain

// 1. Loan State Machine
invariant "Loan cannot skip states"
    loan.status transitions must follow: Draft → Submitted → UnderReview → Approved/Rejected
    Approved → Disbursed → Active → Completed/Defaulted

// 2. Financial Integrity
invariant "Disbursed amount cannot exceed approved amount"
    disbursement.amount <= loan.approvedAmount

invariant "Total payments cannot exceed total loan amount + penalties"
    schedule.totalPaid <= schedule.totalAmount + totalPenalties

invariant "Payment amount must be positive"
    payment.amount > 0

// 3. Authorization
invariant "Only assigned officer can approve/reject"
    msg.sender == loan.assignedOfficer || hasRole(ADMIN_ROLE, msg.sender)

invariant "Only borrower can create their loan"
    loan.borrower == msg.sender || hasRole(SYSTEM_ROLE, msg.sender)

// 4. Temporal
invariant "Disbursement must happen after approval"
    disbursement.timestamp > loan.approvedAt

invariant "Payment cannot be recorded for future installments"
    installment.dueDate <= block.timestamp + GRACE_PERIOD

// 5. Immutability
invariant "Completed loans cannot be modified"
    loan.status != Completed && loan.status != Defaulted

invariant "Disbursement reference cannot change after completion"
    disbursement.status == Completed => disbursement.referenceHash immutable
```

---

## 6. Edge Cases & Risk Mitigation

### 6.1 Partial Payments

**Scenario:** Customer pays less than the full installment amount.

**Solution:**
```solidity
function recordPayment(bytes32 loanId, uint16 installmentNumber, uint256 amount) {
    Installment storage inst = installments[loanId][installmentNumber];
    
    inst.paidAmount += amount;
    
    if (inst.paidAmount >= inst.totalAmount) {
        inst.status = InstallmentStatus.Paid;
        inst.paidAt = block.timestamp;
    } else if (inst.paidAmount > 0) {
        inst.status = InstallmentStatus.Partial;
    }
    
    // Apply excess to next installment or hold
    if (inst.paidAmount > inst.totalAmount) {
        uint256 excess = inst.paidAmount - inst.totalAmount;
        _applyExcessPayment(loanId, installmentNumber, excess);
    }
}
```

### 6.2 Failed Disbursements

**Scenario:** Bank transfer fails after being initiated on-chain.

**Solution:**
```solidity
function failDisbursement(bytes32 disbursementId, bytes32 failureReasonHash) external {
    require(hasRole(LOAN_OFFICER_ROLE, msg.sender) || hasRole(SYSTEM_ROLE, msg.sender));
    
    Disbursement storage d = disbursements[disbursementId];
    require(d.status == DisbursementStatus.Processing, "Invalid status");
    
    d.status = DisbursementStatus.Failed;
    d.failureReasonHash = failureReasonHash;
    
    // Revert loan status to Approved for retry
    ILoanCore(loanCoreAddress).revertToApproved(d.loanId);
    
    emit DisbursementFailed(disbursementId, d.loanId, failureReasonHash, block.timestamp);
}
```

### 6.3 Rollbacks / Reversals

**Scenario:** Admin needs to reverse a disbursement due to fraud detection.

**Solution:**
```solidity
function reverseDisbursement(bytes32 disbursementId, bytes32 reasonHash) external {
    require(hasRole(ADMIN_ROLE, msg.sender), "Admin only");
    
    Disbursement storage d = disbursements[disbursementId];
    require(d.status == DisbursementStatus.Completed, "Can only reverse completed");
    
    // Check time limit (e.g., 72 hours)
    require(block.timestamp <= d.processedAt + REVERSAL_WINDOW, "Reversal window expired");
    
    d.status = DisbursementStatus.Reversed;
    d.reversedAt = block.timestamp;
    d.reversedBy = msg.sender;
    
    // Update loan status
    ILoanCore(loanCoreAddress).markReversed(d.loanId);
    
    // Log audit
    IAuditRegistry(auditAddress).log(
        disbursementId,
        "disbursement",
        AuditAction.DisbursementReversed,
        keccak256(abi.encodePacked(msg.sender, reasonHash)),
        bytes32(uint256(DisbursementStatus.Completed)),
        bytes32(uint256(DisbursementStatus.Reversed))
    );
    
    emit DisbursementReversed(disbursementId, d.loanId, msg.sender, reasonHash, block.timestamp);
}
```

### 6.4 Late Fees and Penalties

**Scenario:** Installment becomes overdue, penalties must be calculated.

**Solution:**
```solidity
function calculatePenalty(
    bytes32 loanId,
    uint16 installmentNumber,
    uint256 originalAmount,
    uint256 dueDate
) external view returns (uint256 penaltyAmount, uint256 daysOverdue) {
    if (block.timestamp <= dueDate + (config.gracePeriodDays * 1 days)) {
        return (0, 0);
    }
    
    daysOverdue = (block.timestamp - dueDate) / 1 days;
    
    // Late fee (one-time)
    uint256 lateFee = (originalAmount * config.lateFeePercentBps) / 10000;
    
    // Daily penalty
    uint256 dailyPenalty = (originalAmount * config.dailyPenaltyBps * daysOverdue) / 10000;
    
    penaltyAmount = lateFee + dailyPenalty;
    
    // Cap at maximum
    uint256 maxPenalty = (originalAmount * config.maxPenaltyPercent) / 100;
    if (penaltyAmount > maxPenalty) {
        penaltyAmount = maxPenalty;
    }
    
    return (penaltyAmount, daysOverdue);
}
```

### 6.5 Oracle Failures

**Scenario:** AI scoring oracle becomes unavailable.

**Solution:**
```solidity
// In LoanCore.sol
function submitLoan(bytes32 loanId, ...) external {
    Loan storage loan = loans[loanId];
    
    // Try to get AI score from oracle
    try ILoanOracle(oracleAddress).getAIScore(loanId) returns (AIScore memory score) {
        if (score.isValid && block.timestamp - score.timestamp < SCORE_VALIDITY_PERIOD) {
            loan.eligibilityScore = score.eligibilityScore;
            loan.riskCategory = RiskCategory(score.riskCategory);
            loan.aiRecommendationHash = score.analysisHash;
        } else {
            // Fallback: Mark as pending manual review
            loan.eligibilityScore = 0;
            loan.riskCategory = RiskCategory.High;  // Conservative default
            emit ManualReviewRequired(loanId, "Oracle score invalid or expired");
        }
    } catch {
        // Oracle unavailable: Queue for manual review
        loan.eligibilityScore = 0;
        loan.riskCategory = RiskCategory.High;
        emit ManualReviewRequired(loanId, "Oracle unavailable");
    }
    
    loan.status = LoanStatus.Submitted;
}
```

### 6.6 Reentrancy and Double-Spend Risks

**Mitigations:**
```solidity
// 1. Use ReentrancyGuard on all value-moving functions
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

function recordPayment(...) external nonReentrant {
    // ...
}

// 2. Check-Effects-Interactions pattern
function disburseFunds(bytes32 disbursementId) external nonReentrant {
    Disbursement storage d = disbursements[disbursementId];
    
    // CHECKS
    require(d.status == DisbursementStatus.Processing, "Invalid status");
    require(d.amount > 0, "Invalid amount");
    
    // EFFECTS (update state BEFORE external call)
    d.status = DisbursementStatus.Completed;
    d.processedAt = block.timestamp;
    
    // INTERACTIONS (external call last)
    // If using actual token transfer:
    // IERC20(stablecoin).transfer(d.borrower, d.amount);
    
    emit DisbursementCompleted(disbursementId, d.loanId, d.referenceHash, block.timestamp);
}

// 3. Use nonces for payment deduplication
mapping(bytes32 => bool) public usedPaymentReferences;

function recordPayment(..., bytes32 referenceHash) external {
    require(!usedPaymentReferences[referenceHash], "Duplicate payment reference");
    usedPaymentReferences[referenceHash] = true;
    // ...
}
```

---

## 7. Transaction → Smart Contract Mapping Table

| Backend Transaction | Smart Contract | Function | Events Emitted |
|-------------------|----------------|----------|----------------|
| `LoanApplication.save()` (create) | `LoanCore` | `createLoan()` | `LoanCreated` |
| `LoanApplication.submit()` | `LoanCore` | `submitLoan()` | `LoanSubmitted` |
| `LoanApplication.assign_officer()` | `LoanCore` | `assignOfficer()` | `LoanAssigned` |
| `LoanApplication.approve()` | `LoanCore` | `approveLoan()` | `LoanApproved`, `LoanStatusChanged` |
| `LoanApplication.reject()` | `LoanCore` | `rejectLoan()` | `LoanRejected`, `LoanStatusChanged` |
| `LoanApplication.disburse()` | `Disbursement` | `initiateDisbursement()`, `completeDisbursement()` | `DisbursementInitiated`, `DisbursementCompleted` |
| `RepaymentSchedule.generate_for_loan()` | `Repayment` | `createSchedule()` | `ScheduleCreated` |
| `RepaymentSchedule.record_payment()` | `Repayment` | `recordPayment()` | `PaymentRecorded`, `InstallmentStatusChanged` |
| `LoanPayment.save()` | `Repayment` | `recordPayment()` | `PaymentRecorded` |
| Overdue check (cron) | `Repayment` + `PenaltyCalc` | `markOverdue()`, `calculatePenalty()` | `InstallmentOverdue`, `PenaltyCalculated` |
| `Document.save()` (verified) | `AuditRegistry` | `log()` | `AuditLogged` |
| `Consent.save()` | `AuditRegistry` | `log()` | `AuditLogged` |
| AI Qualification | `LoanOracle` | `submitAIScore()` | `AIScoreSubmitted` |
| Admin actions | `AuditRegistry` | `log()` | `AuditLogged` |

---

## 8. Deployment & Upgrade Strategy

### 8.1 Deployment Order

```
1. Deploy LoanAccessControl (proxy)
   ↓
2. Deploy AuditRegistry (proxy) - needs AccessControl
   ↓
3. Deploy LoanOracle (proxy) - needs AccessControl
   ↓
4. Deploy PenaltyCalculator (proxy) - needs AccessControl
   ↓
5. Deploy Repayment (proxy) - needs AccessControl, PenaltyCalc, AuditRegistry
   ↓
6. Deploy Disbursement (proxy) - needs AccessControl, AuditRegistry
   ↓
7. Deploy LoanCore (proxy) - needs AccessControl, Disbursement, Repayment, Oracle, AuditRegistry
   ↓
8. Configure cross-contract references
   ↓
9. Set up roles (Admin, initial officers)
```

### 8.2 Upgrade Pattern (UUPS)

```solidity
// All contracts use UUPS upgradeable pattern
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

contract LoanCore is 
    Initializable,
    UUPSUpgradeable,
    AccessControlUpgradeable,
    ReentrancyGuardUpgradeable 
{
    function _authorizeUpgrade(address newImplementation) internal override {
        require(hasRole(UPGRADER_ROLE, msg.sender), "Not authorized to upgrade");
    }
    
    // Version tracking for migrations
    uint256 public constant VERSION = 1;
}
```

---

## 9. Gas Optimization Notes

1. **Use `bytes32` instead of `string`** for fixed-length data (IDs, hashes)
2. **Pack structs** to minimize storage slots
3. **Use events** for data that doesn't need on-chain querying
4. **Batch operations** where possible (e.g., mark multiple installments overdue)
5. **Off-chain computation** with on-chain verification for complex calculations

---

## 10. Regulatory Considerations

| Regulation | Smart Contract Compliance |
|-----------|--------------------------|
| **Philippine Data Privacy Act** | PII stored off-chain, only hashes on-chain |
| **BSP Lending Regulations** | Full audit trail, transparent interest calculations |
| **Anti-Money Laundering** | Audit logs for all value transfers, officer identification |
| **Consumer Protection** | Immutable loan terms once approved, penalty caps |

---

## 11. Next Steps

1. **Review this architecture** with your team
2. **Decide on blockchain** (Ethereum L2, Polygon, BSC, or private chain)
3. **Implement AccessControl** first as foundation
4. **Create test suite** with edge case scenarios
5. **Security audit** before mainnet deployment
6. **Integrate with backend** via Web3 service layer

---

*Document Version: 1.0*  
*Generated: February 2, 2026*  
*For: MSME Pathways Loan Management System*
