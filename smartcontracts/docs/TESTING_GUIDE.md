# Smart Contract Testing Guide

## Quick Reference

| Command | Description |
|---------|-------------|
| `npm test` | Run all tests |
| `npm run test:coverage` | Run with coverage report |
| `npx hardhat test test/LoanCore.test.js` | Run single file |
| `npx hardhat test --grep "approval"` | Run matching tests |

---

## Running Tests

### All Tests

```bash
npm test
```

**Output:**
```
  AuditRegistry
    ✔ Should set correct version
    ✔ Should log audit entry
    ...

  Disbursement
    ✔ Should initiate disbursement
    ✔ Should complete disbursement
    ...

  LoanAccessControl
    ✔ Should register officer successfully
    ✔ Should register borrower
    ...

  LoanCore
    ✔ Should create loan
    ✔ Should approve loan
    ...

  Repayment
    ✔ Should create repayment schedule
    ✔ Should record payment
    ...

  100 passing (3s)
```

### Single Contract

```bash
npx hardhat test test/LoanCore.test.js
npx hardhat test test/Disbursement.test.js
npx hardhat test test/Repayment.test.js
npx hardhat test test/LoanAccessControl.test.js
npx hardhat test test/AuditRegistry.test.js
```

### Pattern Matching

```bash
npx hardhat test --grep "approval"
npx hardhat test --grep "disbursement"
npx hardhat test --grep "payment"
```

---

## Test Files

```
test/
├── AuditRegistry.test.js       # 26 tests
├── LoanAccessControl.test.js   # 24 tests
├── LoanCore.test.js            # 14 tests
├── Disbursement.test.js        # 14 tests
└── Repayment.test.js           # 22 tests
```

**Total: 100 tests**

---

## Test Categories

### AuditRegistry Tests

| Category | Tests |
|----------|-------|
| Deployment | Version, roles, permissions |
| Logger Management | Grant/revoke logger roles |
| Audit Logging | Entry creation, retrieval |
| State Verification | State hash validation |
| Batch Logging | Multiple entries |

**Functions Tested:**
- `log(resourceId, resourceType, action, dataHash, prevState, newState)`
- `logBatch(entries)`
- `getEntry(entryId)`
- `getEntriesByResource(resourceId)`
- `verifyStateTransition(resourceId, expectedState)`

### LoanAccessControl Tests

| Category | Tests |
|----------|-------|
| Officer Registration | Register, deactivate, reactivate |
| Borrower Registration | Register with ID hash |
| Pause Functionality | Emergency pause/unpause |
| Validation | `isActiveOfficer`, `isBorrower` |

**Functions Tested:**
- `registerOfficer(address, employeeIdHash)`
- `registerBorrower(address, customerIdHash)`
- `deactivateOfficer(address)`
- `reactivateOfficer(address)`
- `emergencyPause(reason)`

### LoanCore Tests

| Category | Tests |
|----------|-------|
| Loan Creation | Create with params |
| Loan Submission | Submit with AI scores |
| Officer Assignment | Assign to officer |
| Approval/Rejection | Approve or reject |
| Statistics | Track counts |

**Functions Tested:**
- `createLoan(loanId, productId, amount, termMonths, interestRateBps)`
- `submitLoan(loanId, eligibilityScore, riskCategory, aiRecommendationHash)`
- `assignOfficer(loanId, officerAddress)`
- `approveLoan(loanId, approvedAmount, notesHash)`
- `rejectLoan(loanId, rejectionReasonHash, notesHash)`

### Disbursement Tests

| Category | Tests |
|----------|-------|
| Initiate | Start disbursement |
| Complete | Mark completed |
| View | Query data |

**Functions Tested:**
- `initiateDisbursement(loanId, amount, method)`
- `completeDisbursement(disbursementId, referenceHash)`
- `getDisbursement(disbursementId)`

### Repayment Tests

| Category | Tests |
|----------|-------|
| Schedule Creation | Generate installments |
| Payment Recording | Record with reference |
| Installment Management | Track status |
| Loan Completion | Full repayment |

**Functions Tested:**
- `createSchedule(loanId, borrower, principal, interestRateBps, termMonths, startDate)`
- `recordPayment(loanId, installmentNumber, amount, method, referenceHash)`
- `getInstallment(scheduleId, installmentNumber)`

---

## Test Setup Pattern

Each test file uses `beforeEach` for fresh contracts:

```javascript
describe("LoanCore", function () {
  let loanCore, accessControl, auditRegistry;
  let admin, officer, borrower;

  beforeEach(async function () {
    [admin, officer, borrower] = await ethers.getSigners();

    // Deploy AuditRegistry
    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    auditRegistry = await upgrades.deployProxy(AuditRegistry, [admin.address], { kind: "uups" });

    // Deploy LoanAccessControl
    const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
    accessControl = await upgrades.deployProxy(LoanAccessControl, [admin.address], { kind: "uups" });

    // Deploy LoanCore
    const LoanCore = await ethers.getContractFactory("LoanCore");
    loanCore = await upgrades.deployProxy(
      LoanCore,
      [admin.address, await accessControl.getAddress(), await auditRegistry.getAddress()],
      { kind: "uups" }
    );

    // Setup
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());
    await accessControl.registerOfficer(officer.address, ethers.keccak256(ethers.toUtf8Bytes("EMP001")));
    await accessControl.registerBorrower(borrower.address, ethers.keccak256(ethers.toUtf8Bytes("CUST001")));
  });
});
```

### Setup Order

1. Deploy AuditRegistry
2. Deploy LoanAccessControl
3. Deploy LoanCore (needs AccessControl + AuditRegistry)
4. Deploy Disbursement (needs LoanCore + AuditRegistry)
5. Deploy Repayment (needs LoanCore + AuditRegistry)
6. Grant logger roles
7. Set contracts: `loanCore.setContracts(disbursement, repayment, ethers.ZeroAddress)`
8. Register officers and borrowers

---

## Adding Tests

### Example Test

```javascript
it("Should not allow duplicate loan IDs", async function () {
  const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
  const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT001"));
  
  // First loan succeeds
  await loanCore.connect(borrower).createLoan(
    loanId, productId, ethers.parseEther("1000"), 12, 150
  );
  
  // Duplicate fails
  await expect(
    loanCore.connect(borrower).createLoan(
      loanId, productId, ethers.parseEther("1000"), 12, 150
    )
  ).to.be.revertedWith("LoanCore: loan exists");
});
```

### Common Assertions

```javascript
// Event emission
await expect(contract.function())
  .to.emit(contract, "EventName")
  .withArgs(arg1, arg2);

// Revert with message
await expect(contract.function())
  .to.be.revertedWith("Error message");

// State value
const result = await contract.getValue();
expect(result).to.equal(expectedValue);

// BigInt (Ethers v6)
expect(await contract.getAmount()).to.equal(ethers.parseEther("1000"));
```

---

## Time Manipulation

```javascript
const { time } = require("@nomicfoundation/hardhat-network-helpers");

// Advance 1 day
await time.increase(86400);

// Advance to timestamp
await time.increaseTo(futureTimestamp);

// Get current time
const now = await time.latest();
```

---

## Coverage

```bash
npm run test:coverage
```

Generates report in `coverage/` directory.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Contract not deployed" | Check `beforeEach` deploys all contracts |
| "Not authorized" | Grant roles, register users, set contracts |
| "Invalid argument" | Use correct types (bytes32, uint256) |
| Tests timeout | Restart node, check for loops |

### Role Constants

```javascript
const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
const LOGGER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOGGER_ROLE"));
```
