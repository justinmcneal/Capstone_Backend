# Smart Contract Function Reference

Complete reference for all functions in the MSME Pathways smart contracts.

---

## LoanAccessControl

**Purpose:** Role-based access control for officers and borrowers

### Roles

| Role | Description |
|------|-------------|
| `ADMIN_ROLE` | Administrator |
| `LOAN_OFFICER_ROLE` | Loan officer |
| `SYSTEM_ROLE` | System/service role |
| `PAUSER_ROLE` | Can pause contract |
| `UPGRADER_ROLE` | Can upgrade contract |

### Functions

#### `registerOfficer(address officer, bytes32 employeeIdHash)`

Registers a loan officer.

| Parameter | Type | Description |
|-----------|------|-------------|
| `officer` | `address` | Officer's wallet address |
| `employeeIdHash` | `bytes32` | Hash of employee ID |

**Access:** `ADMIN_ROLE`  
**Emits:** `OfficerRegistered`

#### `registerBorrower(address borrower, bytes32 customerIdHash)`

Registers a borrower.

| Parameter | Type | Description |
|-----------|------|-------------|
| `borrower` | `address` | Borrower's wallet address |
| `customerIdHash` | `bytes32` | Hash of customer ID |

**Access:** `SYSTEM_ROLE`  
**Emits:** `BorrowerRegistered`

#### `deactivateOfficer(address officer)`

Deactivates an officer.

**Access:** `ADMIN_ROLE`  
**Emits:** `OfficerDeactivated`

#### `reactivateOfficer(address officer)`

Reactivates an officer.

**Access:** `ADMIN_ROLE`  
**Emits:** `OfficerReactivated`

#### `emergencyPause(string memory reason)`

Pauses all contract operations.

**Access:** `PAUSER_ROLE`

#### `unpause()`

Unpauses the contract.

**Access:** `PAUSER_ROLE`

#### View Functions

| Function | Returns | Description |
|----------|---------|-------------|
| `isActiveOfficer(address)` | `bool` | Check if officer is active |
| `isBorrower(address)` | `bool` | Check if address is borrower |
| `getOfficerInfo(address)` | struct | Get officer details |
| `getBorrowerInfo(address)` | struct | Get borrower details |

---

## AuditRegistry

**Purpose:** Immutable audit logging

### Audit Actions

```solidity
enum AuditAction {
    LoanCreated,
    LoanSubmitted,
    LoanAssigned,
    LoanApproved,
    LoanRejected,
    DisbursementInitiated,
    DisbursementCompleted,
    PaymentRecorded,
    ScheduleCreated,
    StatusChanged,
    RoleGranted,
    RoleRevoked,
    EmergencyPause
}
```

### Functions

#### `grantLoggerRole(address logger)`

Grants permission to write audit logs.

**Access:** `ADMIN_ROLE`

#### `log(bytes32 resourceId, string memory resourceType, AuditAction action, bytes32 dataHash, bytes32 prevState, bytes32 newState)`

Creates an audit log entry.

| Parameter | Type | Description |
|-----------|------|-------------|
| `resourceId` | `bytes32` | Resource identifier |
| `resourceType` | `string` | Type ("loan", "payment", etc.) |
| `action` | `AuditAction` | Action being logged |
| `dataHash` | `bytes32` | Hash of relevant data |
| `prevState` | `bytes32` | Previous state hash |
| `newState` | `bytes32` | New state hash |

**Returns:** `uint256` - Entry ID  
**Access:** `LOGGER_ROLE`  
**Emits:** `AuditEntryCreated`

#### `logBatch(AuditEntry[] memory entries)`

Creates multiple audit entries.

**Returns:** `uint256[]` - Entry IDs  
**Access:** `LOGGER_ROLE`

#### View Functions

| Function | Returns | Description |
|----------|---------|-------------|
| `getEntry(uint256)` | `AuditEntry` | Get entry by ID |
| `getEntriesByResource(bytes32)` | `AuditEntry[]` | Get all entries for resource |
| `verifyStateTransition(bytes32, bytes32)` | `bool` | Verify state matches |
| `getLatestStateHash(bytes32)` | `bytes32` | Get latest state |

---

## LoanCore

**Purpose:** Loan lifecycle management

### Loan Status

```solidity
enum LoanStatus {
    Draft,        // 0
    Submitted,    // 1
    UnderReview,  // 2
    Approved,     // 3
    Rejected,     // 4
    Disbursed,    // 5
    Active,       // 6
    Completed,    // 7
    Defaulted,    // 8
    Cancelled     // 9
}
```

### Functions

#### `setContracts(address _disbursement, address _repayment, address _oracle)`

Sets related contract addresses.

| Parameter | Type | Description |
|-----------|------|-------------|
| `_disbursement` | `address` | Disbursement contract |
| `_repayment` | `address` | Repayment contract |
| `_oracle` | `address` | Set to `address(0)` |

**Access:** `ADMIN_ROLE`

#### `createLoan(bytes32 loanId, address borrower, bytes32 productId, uint256 requestedAmount, uint16 termMonths, uint16 interestRateBps)`

Creates a new loan application.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Unique loan identifier |
| `borrower` | `address` | Borrower address |
| `productId` | `bytes32` | Loan product identifier |
| `requestedAmount` | `uint256` | Amount requested |
| `termMonths` | `uint16` | Loan term in months |
| `interestRateBps` | `uint16` | Interest rate (150 = 1.5%) |

**Access:** `SYSTEM_ROLE`  
**Emits:** `LoanCreated`

#### `submitLoan(bytes32 loanId, uint8 eligibilityScore, uint8 riskCategory, bytes32 aiRecommendationHash)`

Submits loan for review.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `eligibilityScore` | `uint8` | AI score (0-100) |
| `riskCategory` | `uint8` | 0=Low, 1=Medium, 2=High |
| `aiRecommendationHash` | `bytes32` | Hash of AI recommendation |

**Access:** `SYSTEM_ROLE`  
**Emits:** `LoanSubmitted`

#### `assignOfficer(bytes32 loanId, address officer)`

Assigns officer to loan.

**Access:** `ADMIN_ROLE` or `SYSTEM_ROLE`  
**Emits:** `LoanAssigned`

#### `approveLoan(bytes32 loanId, uint256 approvedAmount, bytes32 notesHash)`

Approves loan.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `approvedAmount` | `uint256` | Approved amount (≤ requested) |
| `notesHash` | `bytes32` | Hash of notes |

**Access:** Assigned officer only  
**Emits:** `LoanApproved`

#### `rejectLoan(bytes32 loanId, bytes32 rejectionReasonHash, bytes32 notesHash)`

Rejects loan.

**Access:** Assigned officer only  
**Emits:** `LoanRejected`

#### View Functions

| Function | Returns | Description |
|----------|---------|-------------|
| `getLoan(bytes32)` | `Loan` struct | Get loan details |
| `getLoanStatus(bytes32)` | `LoanStatus` | Get status only |

---

## Disbursement

**Purpose:** Track fund disbursement

### Enums

```solidity
enum DisbursementStatus {
    Pending,     // 0
    Processing,  // 1
    Completed    // 2
}

enum DisbursementMethod {
    BankTransfer,  // 0
    Cash,          // 1
    GCash,         // 2
    Other          // 3
}
```

### Functions

#### `initiateDisbursement(bytes32 loanId, uint256 amount, uint8 method)`

Starts disbursement.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `amount` | `uint256` | Amount to disburse |
| `method` | `uint8` | Payment method |

**Returns:** `uint256` - Disbursement ID  
**Access:** `LOAN_OFFICER_ROLE` or `SYSTEM_ROLE`  
**Emits:** `DisbursementInitiated`

#### `completeDisbursement(uint256 disbursementId, bytes32 referenceHash)`

Marks disbursement completed.

| Parameter | Type | Description |
|-----------|------|-------------|
| `disbursementId` | `uint256` | Disbursement ID |
| `referenceHash` | `bytes32` | Payment reference hash |

**Access:** `LOAN_OFFICER_ROLE` or `SYSTEM_ROLE`  
**Emits:** `DisbursementCompleted`

#### View Functions

| Function | Returns | Description |
|----------|---------|-------------|
| `getDisbursement(uint256)` | struct | Get disbursement |
| `loanToDisbursement(bytes32)` | `uint256` | Get disbursement ID for loan |

---

## Repayment

**Purpose:** Track repayments and schedules

### Enums

```solidity
enum PaymentMethod {
    Cash,          // 0
    BankTransfer,  // 1
    GCash,         // 2
    Other          // 3
}

enum InstallmentStatus {
    Pending,   // 0
    Paid,      // 1
    Partial,   // 2
    Overdue    // 3
}
```

### Functions

#### `createSchedule(bytes32 loanId, address borrower, uint256 principal, uint16 interestRateBps, uint16 termMonths, uint256 startDate)`

Creates repayment schedule.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `borrower` | `address` | Borrower address |
| `principal` | `uint256` | Principal amount |
| `interestRateBps` | `uint16` | Interest rate (150 = 1.5%) |
| `termMonths` | `uint16` | Number of installments |
| `startDate` | `uint256` | Unix timestamp |

**Returns:** `uint256` - Schedule ID  
**Access:** `ADMIN_ROLE` or `SYSTEM_ROLE`  
**Emits:** `ScheduleCreated`

#### `recordPayment(bytes32 loanId, uint16 installmentNumber, uint256 amount, uint8 method, bytes32 referenceHash)`

Records a payment.

| Parameter | Type | Description |
|-----------|------|-------------|
| `loanId` | `bytes32` | Loan identifier |
| `installmentNumber` | `uint16` | Installment (1-based) |
| `amount` | `uint256` | Payment amount |
| `method` | `uint8` | Payment method |
| `referenceHash` | `bytes32` | Reference hash |

**Access:** `LOAN_OFFICER_ROLE` or `SYSTEM_ROLE`  
**Emits:** `PaymentRecorded`

#### View Functions

| Function | Returns | Description |
|----------|---------|-------------|
| `getSchedule(uint256)` | struct | Get schedule details |
| `getInstallment(uint256, uint16)` | struct | Get installment |
| `loanToSchedule(bytes32)` | `uint256` | Get schedule ID for loan |

---

## Common Patterns

### Converting Strings to bytes32

```javascript
const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
const notesHash = ethers.keccak256(ethers.toUtf8Bytes("Approved"));
```

### Working with Amounts

```javascript
const amount = ethers.parseEther("10000");  // 10,000 with 18 decimals
const readable = ethers.formatEther(amount);  // "10000.0"
```

### Role Hashes

```javascript
const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
const LOGGER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOGGER_ROLE"));
```

---

## Events

### LoanCore

| Event | Parameters |
|-------|------------|
| `LoanCreated` | loanId, borrower, amount, termMonths, interestRateBps |
| `LoanSubmitted` | loanId, eligibilityScore, riskCategory |
| `LoanAssigned` | loanId, officer, assignedBy |
| `LoanApproved` | loanId, officer, approvedAmount |
| `LoanRejected` | loanId, officer, rejectionReasonHash |

### Disbursement

| Event | Parameters |
|-------|------------|
| `DisbursementInitiated` | disbursementId, loanId, amount, method |
| `DisbursementCompleted` | disbursementId, referenceHash |

### Repayment

| Event | Parameters |
|-------|------------|
| `ScheduleCreated` | scheduleId, loanId, termMonths, monthlyAmount |
| `PaymentRecorded` | loanId, installmentNumber, amount, method |
| `LoanFullyRepaid` | loanId, scheduleId |
