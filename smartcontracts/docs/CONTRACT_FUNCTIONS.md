# Smart Contract Function Reference

Complete reference for all smart contract functions in the MSME Pathways Loan Management System.

---

## Table of Contents

1. [LoanAccessControl](#loanaccesscontrol)
2. [AuditRegistry](#auditregistry)
3. [LoanCore](#loancore)
4. [Disbursement](#disbursement)
5. [Repayment](#repayment)

---

## LoanAccessControl

**Contract:** `contracts/LoanAccessControl.sol`  
**Purpose:** Role-based access control for officers and borrowers

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `VERSION` | `1` | Contract version |
| `ADMIN_ROLE` | `keccak256("ADMIN_ROLE")` | Administrator role |
| `LOAN_OFFICER_ROLE` | `keccak256("LOAN_OFFICER_ROLE")` | Loan officer role |
| `SYSTEM_ROLE` | `keccak256("SYSTEM_ROLE")` | System/service role |
| `PAUSER_ROLE` | `keccak256("PAUSER_ROLE")` | Can pause contract |
| `UPGRADER_ROLE` | `keccak256("UPGRADER_ROLE")` | Can upgrade contract |

### Functions

#### `initialize(address admin)`

Initializes the contract with an admin address.

| Parameter | Type | Description |
|-----------|------|-------------|
| `admin` | `address` | Initial admin address |

**Emits:** None  
**Access:** Called once during deployment

---

#### `registerOfficer(address officer, bytes32 employeeIdHash)`

Registers a new loan officer.

| Parameter | Type | Description |
|-----------|------|-------------|
| `officer` | `address` | Officer's wallet address |
| `employeeIdHash` | `bytes32` | Hash of employee ID (for privacy) |

**Returns:** `bool` - Success status  
**Emits:** `OfficerRegistered(officer, employeeIdHash, timestamp)`  
**Access:** `ADMIN_ROLE` only  
**Reverts:**
- `"LoanAccessControl: zero address"` - If officer is zero address
- `"LoanAccessControl: empty employee ID"` - If employeeIdHash is empty
- `"LoanAccessControl: already registered"` - If officer already registered

**Example:**
```javascript
const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));
await accessControl.registerOfficer(officerAddress, employeeIdHash);
```

---

#### `registerBorrower(address borrower, bytes32 customerIdHash)`

Registers a borrower in the system.

| Parameter | Type | Description |
|-----------|------|-------------|
| `borrower` | `address` | Borrower's wallet address |
| `customerIdHash` | `bytes32` | Hash of customer ID (for privacy) |

**Returns:** `bool` - Success status  
**Emits:** `BorrowerRegistered(borrower, customerIdHash, timestamp)`  
**Access:** `SYSTEM_ROLE` only  
**Reverts:**
- `"LoanAccessControl: zero address"` - If borrower is zero address
- `"LoanAccessControl: already registered"` - If borrower already registered

**Example:**
```javascript
const customerIdHash = ethers.keccak256(ethers.toUtf8Bytes("CUST001"));
await accessControl.connect(systemAccount).registerBorrower(borrowerAddress, customerIdHash);
```

---

#### `deactivateOfficer(address officer)`

Deactivates an officer (cannot process loans).

| Parameter | Type | Description |
|-----------|------|-------------|
| `officer` | `address` | Officer's wallet address |

**Returns:** `bool` - Success status  
**Emits:** `OfficerDeactivated(officer, timestamp)`  
**Access:** `ADMIN_ROLE` only

---

#### `reactivateOfficer(address officer)`

Reactivates a previously deactivated officer.

| Parameter | Type | Description |
|-----------|------|-------------|
| `officer` | `address` | Officer's wallet address |

**Returns:** `bool` - Success status  
**Emits:** `OfficerReactivated(officer, timestamp)`  
**Access:** `ADMIN_ROLE` only

---

#### `emergencyPause(string memory reason)`

Pauses all contract operations (emergency use).

| Parameter | Type | Description |
|-----------|------|-------------|
| `reason` | `string` | Reason for pausing |

**Emits:** `Paused(address)` (from OpenZeppelin)  
**Access:** `PAUSER_ROLE` only

---

#### `unpause()`

Unpauses the contract.

**Emits:** `Unpaused(address)` (from OpenZeppelin)  
**Access:** `PAUSER_ROLE` only

---

#### `isActiveOfficer(address officer)` (view)

Checks if an officer is active.

| Parameter | Type | Description |
|-----------|------|-------------|
| `officer` | `address` | Officer's wallet address |

**Returns:** `bool` - True if officer is registered and active

---

#### `isBorrower(address borrower)` (view)

Checks if an address is a registered borrower.

| Parameter | Type | Description |
|-----------|------|-------------|
| `borrower` | `address` | Address to check |

**Returns:** `bool` - True if registered as borrower

---

#### `getOfficerInfo(address officer)` (view)

Gets officer information.

| Parameter | Type | Description |
|-----------|------|-------------|
| `officer` | `address` | Officer's wallet address |

**Returns:**
- `employeeIdHash` - Hash of employee ID
- `isActive` - Active status
- `registeredAt` - Registration timestamp

---

#### `getBorrowerInfo(address borrower)` (view)

Gets borrower information.

| Parameter | Type | Description |
|-----------|------|-------------|
| `borrower` | `address` | Borrower's wallet address |

**Returns:**
- `customerIdHash` - Hash of customer ID
- `registeredAt` - Registration timestamp

---

## AuditRegistry

**Contract:** `contracts/AuditRegistry.sol`  
**Purpose:** Immutable audit logging for all contract operations

### Enums

```solidity
enum AuditAction {
    LoanCreated,
    LoanSubmitted,
    LoanAssigned,
    LoanApproved,
    LoanRejected,
    DisbursementInitiated,
    DisbursementCompleted,
    DisbursementFailed,
    DisbursementReversed,
    PaymentRecorded,
    ScheduleCreated,
    PenaltyApplied,
    PenaltyWaived,
    AIScoreSubmitted,
    ExternalPaymentConfirmed,
    StatusChanged,
    ConfigUpdated,
    RoleGranted,
    RoleRevoked,
    EmergencyPause,
    ContractUpgraded
}
```

### Functions

#### `initialize(address admin)`

Initializes the audit registry.

| Parameter | Type | Description |
|-----------|------|-------------|
| `admin` | `address` | Initial admin address |

---

#### `grantLoggerRole(address logger)`

Grants permission to write audit logs.

| Parameter | Type | Description |
|-----------|------|-------------|
| `logger` | `address` | Address to grant logger role |

**Access:** `ADMIN_ROLE` only

---

#### `log(bytes32 resourceId, string memory resourceType, AuditAction action, bytes32 dataHash, bytes32 prevState, bytes32 newState)`

Creates an audit log entry.

| Parameter | Type | Description |
|-----------|------|-------------|
| `resourceId` | `bytes32` | Resource identifier (e.g., loan ID) |
| `resourceType` | `string` | Type of resource ("loan", "payment", etc.) |
| `action` | `AuditAction` | Action being logged |
| `dataHash` | `bytes32` | Hash of relevant data |
| `prevState` | `bytes32` | Previous state hash |
| `newState` | `bytes32` | New state hash |

**Returns:** `uint256` - Entry ID  
**Emits:** `AuditEntryCreated(entryId, resourceId, action, actor, timestamp)`  
**Access:** `LOGGER_ROLE` only

**Example:**
```javascript
await auditRegistry.log(
  loanId,
  "loan",
  0, // AuditAction.LoanCreated
  ethers.keccak256(ethers.toUtf8Bytes("data")),
  ethers.ZeroHash,
  ethers.keccak256(ethers.toUtf8Bytes("new state"))
);
```

---

#### `logBatch(AuditEntry[] memory entries)`

Creates multiple audit entries in one transaction.

| Parameter | Type | Description |
|-----------|------|-------------|
| `entries` | `AuditEntry[]` | Array of entry data |

**Returns:** `uint256[]` - Array of entry IDs  
**Access:** `LOGGER_ROLE` only

---

#### `getEntry(uint256 entryId)` (view)

Retrieves an audit entry by ID.

| Parameter | Type | Description |
|-----------|------|-------------|
| `entryId` | `uint256` | Entry ID to retrieve |

**Returns:** Full `AuditEntry` struct

---

#### `getEntriesByResource(bytes32 resourceId)` (view)

Gets all entries for a resource.

| Parameter | Type | Description |
|-----------|------|-------------|
| `resourceId` | `bytes32` | Resource identifier |

**Returns:** `AuditEntry[]` - Array of entries

---

#### `verifyStateTransition(bytes32 resourceId, bytes32 expectedState)` (view)

Verifies the current state matches expected.

| Parameter | Type | Description |
|-----------|------|-------------|
| `resourceId` | `bytes32` | Resource identifier |
| `expectedState` | `bytes32` | Expected current state hash |

**Returns:** `bool` - True if state matches

---

#### `getLatestStateHash(bytes32 resourceId)` (view)

Gets the most recent state hash for a resource.

| Parameter | Type | Description |
|-----------|------|-------------|
| `resourceId` | `bytes32` | Resource identifier |

**Returns:** `bytes32` - Latest state hash

---

## LoanCore

**Contract:** `contracts/LoanCore.sol`  
**Purpose:** Main loan lifecycle management

### Enums

```solidity
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
```

### Functions

#### `initialize(address _accessControl, address _auditRegistry, address admin)`

Initializes the loan core contract.

| Parameter | Type | Description |
|-----------|------|-------------|
| `_accessControl` | `address` | LoanAccessControl contract |
| `_auditRegistry` | `address` | AuditRegistry contract |
| `admin` | `address` | Admin address |

---

#### `setContracts(address _disbursement, address _repayment, address _oracle)`

Sets related contract addresses.

| Parameter | Type | Description |
|-----------|------|-------------|
| `_disbursement` | `address` | Disbursement contract |
| `_repayment` | `address` | Repayment contract |
| `_oracle` | `address` | Oracle contract (set to `address(0)` - not used) |

**Access:** `ADMIN_ROLE` only

> **Note:** In the current backend-aligned implementation, the `_oracle` parameter should be set to `address(0)` as LoanOracle was removed.

---

#### `createLoan(bytes32 loanId, bytes32 productId, uint256 requestedAmount, uint16 termMonths, uint16 interestRateBps)`

Creates a new loan application.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Unique loan identifier (hash of off-chain ID) |
| `productId` | `bytes32` | Loan product identifier |
| `requestedAmount` | `uint256` | Amount requested in smallest unit |
| `termMonths` | `uint16` | Loan term in months |
| `interestRateBps` | `uint16` | Interest rate in basis points (150 = 1.5%) |

**Returns:** `bool` - Success status  
**Emits:** `LoanCreated(loanId, borrower, amount, termMonths, interestRateBps, timestamp)`  
**Access:** Any registered borrower  
**Reverts:**
- `"LoanCore: loan exists"` - If loan ID already used
- `"LoanCore: amount must be positive"` - If amount is zero
- `"LoanCore: invalid term"` - If term is 0 or > 120 months

**Example:**
```javascript
const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
const productId = ethers.keccak256(ethers.toUtf8Bytes("MSME_BASIC"));

await loanCore.connect(borrower).createLoan(
  loanId,
  productId,
  ethers.parseEther("10000"),  // 10,000 PHP
  12,                          // 12 months
  150                          // 1.5% monthly interest
);
```

---

#### `submitLoan(bytes32 loanId, uint8 eligibilityScore, RiskCategory riskCategory, bytes32 aiRecommendationHash)`

Submits a loan for review with AI assessment.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `eligibilityScore` | `uint8` | AI-generated score (0-100) |
| `riskCategory` | `RiskCategory` | Low=0, Medium=1, High=2 |
| `aiRecommendationHash` | `bytes32` | Hash of AI recommendation |

**Returns:** `bool` - Success status  
**Emits:** `LoanSubmitted(loanId, eligibilityScore, riskCategory, timestamp)`  
**Access:** Only the loan's borrower  
**Reverts:**
- `"LoanCore: invalid score"` - If score > 100
- `"LoanCore: invalid status"` - If not in Draft status

**Example:**
```javascript
const aiRecHash = ethers.keccak256(ethers.toUtf8Bytes("AI_RECOMMENDATION_DATA"));

await loanCore.connect(borrower).submitLoan(
  loanId,
  85,     // eligibility score
  0,      // RiskCategory.Low
  aiRecHash
);
```

---

#### `assignOfficer(bytes32 loanId, address officer)`

Assigns a loan officer to review the loan.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `officer` | `address` | Officer's wallet address |

**Returns:** `bool` - Success status  
**Emits:** `LoanAssigned(loanId, officer, assignedBy, timestamp)`  
**Access:** `ADMIN_ROLE` or `SYSTEM_ROLE`  
**Reverts:**
- `"LoanCore: invalid officer"` - If officer not active in LoanAccessControl
- `"LoanCore: invalid status for assignment"` - If not Submitted or UnderReview

---

#### `approveLoan(bytes32 loanId, uint256 approvedAmount, bytes32 notesHash)`

Approves a loan with specified amount.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `approvedAmount` | `uint256` | Amount approved (≤ requested) |
| `notesHash` | `bytes32` | Hash of approval notes |

**Returns:** `bool` - Success status  
**Emits:** `LoanApproved(loanId, officer, approvedAmount, notesHash, timestamp)`  
**Access:** Only the assigned officer  
**Reverts:**
- `"LoanCore: amount must be positive"` - If amount is zero
- `"LoanCore: exceeds requested"` - If > requested amount
- `"LoanCore: invalid status"` - If not UnderReview

---

#### `rejectLoan(bytes32 loanId, bytes32 rejectionReasonHash, bytes32 notesHash)`

Rejects a loan application.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `rejectionReasonHash` | `bytes32` | Hash of rejection reason |
| `notesHash` | `bytes32` | Hash of notes |

**Returns:** `bool` - Success status  
**Emits:** `LoanRejected(loanId, officer, rejectionReasonHash, timestamp)`  
**Access:** Only the assigned officer

---

#### `markDisbursed(bytes32 loanId, uint256 amount)`

Marks loan as disbursed (called by Disbursement contract).

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `amount` | `uint256` | Disbursed amount |

**Returns:** `bool` - Success status  
**Access:** Disbursement contract or `ADMIN_ROLE`

---

#### `getLoan(bytes32 loanId)` (view)

Gets full loan details.

**Returns:** `Loan` struct with all loan data

---

#### `getLoanStatus(bytes32 loanId)` (view)

Gets only the loan status.

**Returns:** `LoanStatus` enum value

---

## Disbursement

**Contract:** `contracts/Disbursement.sol`  
**Purpose:** Track fund disbursement to borrowers

### Enums

```solidity
enum DisbursementStatus {
    Pending,     // 0 - Awaiting processing
    Processing,  // 1 - In progress
    Completed    // 2 - Successfully disbursed
}

enum DisbursementMethod {
    BankTransfer,  // 0
    Cash,          // 1
    GCash,         // 2
    Maya,          // 3
    Other          // 4
}
```

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `VERSION` | `1` | Contract version |

### Functions

#### `initialize(address _loanCore, address _auditRegistry, address admin)`

Initializes the disbursement contract.

---

#### `initiateDisbursement(bytes32 loanId, uint256 amount, DisbursementMethod method)`

Starts disbursement process.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `amount` | `uint256` | Amount to disburse |
| `method` | `DisbursementMethod` | Payment method |

**Returns:** `uint256` - Disbursement ID  
**Emits:** `DisbursementInitiated(disbursementId, loanId, amount, method, timestamp)`  
**Access:** `LOAN_OFFICER_ROLE` or `SYSTEM_ROLE`  
**Reverts:**
- `"Disbursement: exceeds approved"` - If amount > approved amount

**Example:**
```javascript
const disbursementId = await disbursement.connect(officer).initiateDisbursement(
  loanId,
  ethers.parseEther("8000"),
  0  // DisbursementMethod.BankTransfer
);
```

---

#### `completeDisbursement(uint256 disbursementId, bytes32 referenceHash)`

Marks disbursement as completed.

| Parameter | Type | Description |
|-----------|------|-------------|
| `disbursementId` | `uint256` | Disbursement ID |
| `referenceHash` | `bytes32` | Hash of payment reference |

**Returns:** `bool` - Success status  
**Emits:** `DisbursementCompleted(disbursementId, referenceHash, timestamp)`  
**Access:** `LOAN_OFFICER_ROLE` or `SYSTEM_ROLE`

---

#### `getDisbursement(bytes32 disbursementId)` (view)

Gets disbursement details.

---

#### `loanToDisbursement(bytes32 loanId)` (view)

Gets disbursement ID for a loan.

---

## Repayment

**Contract:** `contracts/Repayment.sol`  
**Purpose:** Track loan repayments and schedules

### Enums

```solidity
enum PaymentMethod {
    Cash,          // 0
    BankTransfer,  // 1
    GCash,         // 2
    Maya,          // 3
    Other          // 4
}

enum InstallmentStatus {
    Pending,   // 0 - Not yet due
    Paid,      // 1 - Fully paid
    Partial,   // 2 - Partially paid
    Overdue    // 3 - Past due date
}
```

### Functions

#### `initialize(address _loanCore, address _auditRegistry, address admin)`

Initializes the repayment contract.

---

#### `createSchedule(bytes32 loanId, address borrower, uint256 principal, uint16 interestRateBps, uint16 termMonths, uint256 startDate)`

Creates repayment schedule with installments.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `borrower` | `address` | Borrower's address |
| `principal` | `uint256` | Total principal amount |
| `interestRateBps` | `uint16` | Monthly interest rate in basis points |
| `termMonths` | `uint16` | Number of installments |
| `startDate` | `uint256` | Unix timestamp for first due date |

**Returns:** `uint256` - Schedule ID  
**Emits:** `ScheduleCreated(scheduleId, loanId, termMonths, monthlyAmount)`  
**Access:** `ADMIN_ROLE` or `SYSTEM_ROLE`

**Example:**
```javascript
const startDate = Math.floor(Date.now() / 1000);

await repayment.createSchedule(
  loanId,
  borrowerAddress,
  ethers.parseEther("12000"),
  150,     // 1.5% monthly
  12,      // 12 installments
  startDate
);
```

---

#### `recordPayment(bytes32 loanId, uint16 installmentNumber, uint256 amount, PaymentMethod method, bytes32 referenceHash)`

Records a payment against an installment.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `installmentNumber` | `uint16` | Installment to pay (1-based) |
| `amount` | `uint256` | Payment amount |
| `method` | `PaymentMethod` | Payment method |
| `referenceHash` | `bytes32` | Hash of payment reference |

**Returns:** `bool` - Success status  
**Emits:** `PaymentRecorded(loanId, installmentNumber, amount, method, referenceHash)`  
**Access:** `LOAN_OFFICER_ROLE` or `SYSTEM_ROLE`  
**Reverts:**
- `"Repayment: amount must be positive"` - If amount is 0
- `"Repayment: duplicate reference"` - If referenceHash already used

---

#### `getInstallment(uint256 scheduleId, uint16 installmentNumber)` (view)

Gets installment details.

**Returns:**
- `dueDate` - Unix timestamp
- `totalAmount` - Amount due
- `paidAmount` - Amount paid
- `status` - InstallmentStatus

---

## Common Patterns

### Converting Strings to bytes32

```javascript
// For IDs and hashes
const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
const productId = ethers.keccak256(ethers.toUtf8Bytes("MSME_BASIC"));
const notesHash = ethers.keccak256(ethers.toUtf8Bytes("Approved with conditions"));
```

### Working with Amounts

```javascript
// Convert to smallest unit (wei-like)
const amount = ethers.parseEther("10000");  // 10,000 with 18 decimals

// Convert from smallest unit to readable
const readable = ethers.formatEther(amount);
console.log(readable);  // "10000.0"
```

### Role Hashes

```javascript
const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
const LOGGER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOGGER_ROLE"));
```

---

## Events Reference

### LoanCore Events

| Event | Parameters |
|-------|------------|
| `LoanCreated` | loanId, borrower, amount, termMonths, interestRateBps, timestamp |
| `LoanSubmitted` | loanId, eligibilityScore, riskCategory, timestamp |
| `LoanAssigned` | loanId, officer, assignedBy, timestamp |
| `LoanApproved` | loanId, officer, approvedAmount, notesHash, timestamp |
| `LoanRejected` | loanId, officer, rejectionReasonHash, timestamp |
| `LoanStatusChanged` | loanId, oldStatus, newStatus, timestamp |

### Disbursement Events

| Event | Parameters |
|-------|------------|
| `DisbursementInitiated` | disbursementId, loanId, amount, method, timestamp |
| `DisbursementCompleted` | disbursementId, referenceHash, timestamp |

### Repayment Events

| Event | Parameters |
|-------|------------|
| `ScheduleCreated` | scheduleId, loanId, termMonths, monthlyAmount |
| `PaymentRecorded` | loanId, installmentNumber, amount, method, referenceHash |
| `InstallmentStatusChanged` | scheduleId, installmentNumber, oldStatus, newStatus |
| `LoanFullyRepaid` | loanId, scheduleId, timestamp |
