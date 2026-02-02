# Smart Contract Architecture

## Overview

The MSME Pathways smart contract system provides immutable record-keeping for the loan management system. It consists of 5 contracts that mirror the Django backend's financial flows.

---

## Contract Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    LoanAccessControl                         │
│              (Roles: Admin, Officer, Borrower)               │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                       LoanCore                               │
│         (Loan lifecycle: create → approve → disburse)        │
└──────┬─────────────────────────────────────────┬────────────┘
       │                                         │
       ▼                                         ▼
┌─────────────────┐                   ┌─────────────────────┐
│   Disbursement  │                   │     Repayment       │
│  (Fund release) │                   │  (Payments/Schedule)│
└────────┬────────┘                   └──────────┬──────────┘
         │                                       │
         └───────────────┬───────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                     AuditRegistry                            │
│                (Immutable audit logging)                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Contracts

### LoanAccessControl

**Purpose:** Role-based access control

**Roles:**
- `ADMIN_ROLE` - Contract administration
- `LOAN_OFFICER_ROLE` - Process loans and payments
- `SYSTEM_ROLE` - Backend service account
- `PAUSER_ROLE` - Emergency pause
- `UPGRADER_ROLE` - Contract upgrades

**Key Features:**
- Officer registration with employee ID hash
- Borrower registration with customer ID hash
- Officer activation/deactivation
- Emergency pause capability

### LoanCore

**Purpose:** Loan lifecycle management

**Status Flow:**
```
Draft → Submitted → UnderReview → Approved → Disbursed → Active → Completed
                               → Rejected
```

**Key Features:**
- Loan creation with product and terms
- AI qualification data recording
- Officer assignment
- Approval/rejection by assigned officer
- Integration with Disbursement and Repayment contracts

### Disbursement

**Purpose:** Track fund release to borrowers

**Status Flow:**
```
Pending → Processing → Completed
```

**Key Features:**
- Disbursement initiation with method
- Completion with reference hash
- Updates LoanCore status automatically

### Repayment

**Purpose:** Payment recording and schedule management

**Key Features:**
- Schedule creation with calculated installments
- Payment recording with reference
- Installment status tracking (Pending, Paid, Partial, Overdue)
- Duplicate payment prevention

### AuditRegistry

**Purpose:** Immutable audit trail

**Key Features:**
- Audit entry logging with state hashes
- Batch logging support
- State verification
- Entry retrieval by resource

---

## Data Model

### Loan Structure

```solidity
struct Loan {
    bytes32 loanId;
    address borrower;
    bytes32 productId;
    uint256 requestedAmount;
    uint256 approvedAmount;
    uint256 disbursedAmount;
    uint16 termMonths;
    uint16 interestRateBps;
    LoanStatus status;
    address assignedOfficer;
    uint8 eligibilityScore;
    RiskCategory riskCategory;
    uint256 createdAt;
    uint256 submittedAt;
    uint256 approvedAt;
    uint256 disbursedAt;
}
```

### Schedule Structure

```solidity
struct Schedule {
    bytes32 scheduleId;
    bytes32 loanId;
    address borrower;
    uint256 principal;
    uint16 interestRateBps;
    uint16 termMonths;
    uint256 monthlyPayment;
    uint256 totalAmount;
    uint256 totalPaid;
    uint256 startDate;
    uint256 createdAt;
}
```

### Installment Structure

```solidity
struct Installment {
    uint16 number;
    uint256 dueDate;
    uint256 principalAmount;
    uint256 interestAmount;
    uint256 totalAmount;
    uint256 paidAmount;
    InstallmentStatus status;
    uint256 paidAt;
}
```

---

## Security Features

### OpenZeppelin Standards

| Pattern | Purpose |
|---------|---------|
| **UUPS Proxy** | Upgradeable contracts |
| **AccessControl** | Role-based permissions |
| **ReentrancyGuard** | Prevent reentrancy attacks |
| **Pausable** | Emergency stop |

### Access Control Matrix

| Function | Admin | Officer | System | Borrower |
|----------|-------|---------|--------|----------|
| `registerOfficer` | ✓ | | | |
| `registerBorrower` | | | ✓ | |
| `createLoan` | | | ✓ | |
| `submitLoan` | | | ✓ | |
| `assignOfficer` | ✓ | | ✓ | |
| `approveLoan` | | ✓* | | |
| `rejectLoan` | | ✓* | | |
| `initiateDisbursement` | | ✓ | ✓ | |
| `completeDisbursement` | | ✓ | ✓ | |
| `createSchedule` | ✓ | | ✓ | |
| `recordPayment` | | ✓ | ✓ | |

*Only assigned officer

---

## Deployment Order

1. **LoanAccessControl** - No dependencies
2. **AuditRegistry** - No dependencies
3. **LoanCore** - Requires AccessControl, AuditRegistry
4. **Disbursement** - Requires LoanCore, AuditRegistry
5. **Repayment** - Requires LoanCore, AuditRegistry

### Post-Deployment Setup

```javascript
// Grant logger roles
await auditRegistry.grantLoggerRole(loanCore.address);
await auditRegistry.grantLoggerRole(disbursement.address);
await auditRegistry.grantLoggerRole(repayment.address);

// Set contract references
await loanCore.setContracts(disbursement.address, repayment.address, ethers.ZeroAddress);
```

---

## Events

### LoanCore Events

| Event | When Emitted |
|-------|-------------|
| `LoanCreated` | New loan created |
| `LoanSubmitted` | Loan submitted for review |
| `LoanAssigned` | Officer assigned |
| `LoanApproved` | Loan approved |
| `LoanRejected` | Loan rejected |
| `LoanStatusChanged` | Any status change |

### Disbursement Events

| Event | When Emitted |
|-------|-------------|
| `DisbursementInitiated` | Disbursement started |
| `DisbursementCompleted` | Disbursement completed |

### Repayment Events

| Event | When Emitted |
|-------|-------------|
| `ScheduleCreated` | Schedule created |
| `PaymentRecorded` | Payment recorded |
| `InstallmentStatusChanged` | Installment status changed |
| `LoanFullyRepaid` | All installments paid |

---

## Integration Points

### Django Backend → Smart Contracts

```
POST /api/loans/apply/          →  LoanCore.createLoan()
                                   LoanCore.submitLoan()
                                   
PUT /api/loans/.../review/      →  LoanCore.assignOfficer()
    (approve)                      LoanCore.approveLoan()
    (reject)                       LoanCore.rejectLoan()
    
POST /api/loans/.../disburse/   →  Disbursement.initiateDisbursement()
                                   Disbursement.completeDisbursement()
                                   
POST /api/loans/payment/        →  Repayment.recordPayment()
```

### Smart Contracts → AuditRegistry

All state changes automatically log to AuditRegistry via internal calls.

---

## Gas Optimization

| Operation | Estimated Gas |
|-----------|---------------|
| Create Loan | ~200,000 |
| Submit Loan | ~100,000 |
| Approve Loan | ~150,000 |
| Initiate Disbursement | ~120,000 |
| Complete Disbursement | ~100,000 |
| Create Schedule | ~250,000 |
| Record Payment | ~80,000 |

---

## Upgrade Strategy

All contracts use UUPS proxy pattern:

```solidity
function _authorizeUpgrade(address newImplementation)
    internal
    override
    onlyRole(UPGRADER_ROLE)
{}
```

Upgrade process:
1. Deploy new implementation
2. Call `upgradeToAndCall()` on proxy
3. State is preserved, logic is updated
