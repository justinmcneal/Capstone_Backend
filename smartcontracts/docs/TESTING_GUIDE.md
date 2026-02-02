# Smart Contract Testing Guide

## 🎯 Overview

This guide explains how to run, understand, and extend the smart contract test suite for the MSME Pathways Loan Management System.

---

## 📋 Quick Reference

| Command | Description |
|---------|-------------|
| `npm test` | Run all tests |
| `npm run test:coverage` | Run tests with coverage report |
| `npx hardhat test test/LoanCore.test.js` | Run single test file |
| `npx hardhat test --grep "approval"` | Run tests matching pattern |

---

## 🚀 Running Tests

### Basic Test Run

```bash
cd smartcontracts
npm test
```

**Expected Output:**
```
  AuditRegistry
    Deployment
      ✔ Should set correct version
      ✔ Should set admin role
      ...
  
  166 passing (4s)
```

### Test a Specific Contract

```bash
npx hardhat test test/LoanCore.test.js
npx hardhat test test/Disbursement.test.js
npx hardhat test test/Repayment.test.js
```

### Test with Verbose Output

```bash
npx hardhat test --verbose
```

### Run Tests Matching a Pattern

```bash
# Run all tests containing "approval"
npx hardhat test --grep "approval"

# Run all tests containing "disbursement"
npx hardhat test --grep "disbursement"
```

---

## 📁 Test Files Structure

```
test/
├── AuditRegistry.test.js       # Audit logging tests (26 tests)
├── LoanAccessControl.test.js   # Role management tests (~24 tests)
├── LoanCore.test.js            # Loan lifecycle tests (14 tests)
├── LoanOracle.test.js          # Oracle & AI score tests (~24 tests)
├── PenaltyCalculator.test.js   # Penalty calculation tests (~24 tests)
├── Disbursement.test.js        # Disbursement flow tests (~20 tests)
└── Repayment.test.js           # Repayment & schedule tests (~24 tests)
```

---

## 🧪 Test Categories

### 1. AuditRegistry Tests

Tests the immutable audit logging system.

| Test Category | What It Tests |
|---------------|---------------|
| Deployment | Version, roles, permissions |
| Logger Management | Granting/revoking logger roles |
| Audit Logging | Entry creation, retrieval |
| State Verification | State hash validation |
| Batch Logging | Multiple entries at once |
| Entry Retrieval | Querying by resource, actor |

**Key Functions Tested:**
- `log(resourceId, resourceType, action, dataHash, prevState, newState)`
- `logBatch(entries)`
- `getEntry(entryId)`
- `getEntriesByResource(resourceId)`
- `verifyStateTransition(resourceId, expectedState)`

### 2. LoanAccessControl Tests

Tests role-based access control.

| Test Category | What It Tests |
|---------------|---------------|
| Officer Registration | Register, deactivate, reactivate |
| Borrower Registration | Register with customer ID hash |
| Pause Functionality | Emergency pause/unpause |
| Validation Functions | `isActiveOfficer`, `isBorrower` |
| Role Management | Grant/revoke roles |

**Key Functions Tested:**
- `registerOfficer(address, employeeIdHash)`
- `registerBorrower(address, customerIdHash)`
- `deactivateOfficer(address)`
- `reactivateOfficer(address)`
- `emergencyPause(reason)`
- `unpause()`

### 3. LoanCore Tests

Tests the main loan lifecycle.

| Test Category | What It Tests |
|---------------|---------------|
| Loan Creation | Create with proper params |
| Loan Submission | Submit with AI scores |
| Officer Assignment | Assign to registered officer |
| Approval/Rejection | Approve or reject with notes |
| Statistics | Track loan counts |

**Key Functions Tested:**
- `createLoan(loanId, productId, amount, termMonths, interestRateBps)`
- `submitLoan(loanId, eligibilityScore, riskCategory, aiRecommendationHash)`
- `assignOfficer(loanId, officerAddress)`
- `approveLoan(loanId, approvedAmount, notesHash)`
- `rejectLoan(loanId, rejectionReasonHash, notesHash)`

### 4. Disbursement Tests

Tests fund release tracking.

| Test Category | What It Tests |
|---------------|---------------|
| Initiate Disbursement | Start disbursement process |
| Complete Disbursement | Mark as completed with reference |
| Failed Disbursement | Handle failures, allow retry |
| Disbursement Reversal | Reverse within time window |
| View Functions | Query disbursement data |

**Key Functions Tested:**
- `initiateDisbursement(loanId, amount, method)`
- `completeDisbursement(disbursementId, referenceHash)`
- `failDisbursement(disbursementId, reasonHash)`
- `reverseDisbursement(disbursementId, reasonHash)`

### 5. Repayment Tests

Tests payment recording and schedules.

| Test Category | What It Tests |
|---------------|---------------|
| Schedule Creation | Generate installment schedule |
| Payment Recording | Record payments with reference |
| Installment Management | Track paid/partial/overdue |
| Loan Completion | Handle full repayment |
| Penalty Calculator | Set penalty calculator |

**Key Functions Tested:**
- `createSchedule(loanId, borrower, principal, interestRateBps, termMonths, startDate)`
- `recordPayment(loanId, installmentNumber, amount, method, referenceHash)`
- `getInstallment(scheduleId, installmentNumber)`

### 6. PenaltyCalculator Tests

Tests penalty computation.

| Test Category | What It Tests |
|---------------|---------------|
| Configuration | Default config, updates |
| Penalty Calculation | Grace period, daily rate, cap |
| Penalty Recording | Store penalty records |
| Penalty Waiver | Admin/officer can waive |
| Edge Cases | Same-day, grace period end |

**Key Functions Tested:**
- `calculatePenalty(loanId, installmentNumber, amount, dueDate)`
- `updateConfig(gracePeriod, lateFeePercent, dailyPenaltyPercent, maxPenaltyPercent)`
- `recordPenalty(loanId, installmentNumber, amount)`
- `waivePenalty(loanId, installmentNumber, reasonHash)`

### 7. LoanOracle Tests

Tests external data bridging.

| Test Category | What It Tests |
|---------------|---------------|
| AI Score Submission | Submit, store, validate scores |
| Score Invalidation | Admin can invalidate |
| Score Validity | Check expiration |
| External Payments | Confirm off-chain payments |
| Batch Operations | Multiple confirmations |
| Oracle Management | Add/remove oracles |

**Key Functions Tested:**
- `submitAIScore(loanId, score, riskCategory, factors)`
- `invalidateScore(loanId)`
- `isScoreValid(loanId)`
- `confirmExternalPayment(loanId, amount, referenceHash)`
- `confirmExternalPaymentsBatch(loanIds, amounts, referenceHashes)`

---

## 🔧 Understanding Test Setup

### beforeEach Pattern

Each test file uses a `beforeEach` hook to set up fresh contracts:

```javascript
describe("LoanCore", function () {
  let loanCore, accessControl, auditRegistry;
  let admin, officer, borrower;

  beforeEach(async function () {
    // Get test accounts
    [admin, officer, borrower] = await ethers.getSigners();

    // Deploy contracts
    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    auditRegistry = await upgrades.deployProxy(
      AuditRegistry,
      [admin.address],
      { kind: "uups" }
    );
    await auditRegistry.waitForDeployment();

    // ... deploy other contracts

    // Setup permissions
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());
  });
});
```

### Important Setup Steps

1. **Deploy in order**: AuditRegistry → LoanAccessControl → LoanCore → Disbursement/Repayment
2. **Grant logger roles** to contracts that need to write audit logs
3. **Register contracts**: Call `loanCore.setContracts(disbursement, repayment, oracle)`
4. **Register users**: Register officers and borrowers in LoanAccessControl

### Role Constants

Tests use consistent role constants:

```javascript
const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
const LOGGER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOGGER_ROLE"));
```

---

## 🆕 Adding New Tests

### Example: Adding a Test Case

```javascript
it("Should not allow duplicate loan IDs", async function () {
  const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
  const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT001"));
  
  // First loan should succeed
  await loanCore.connect(borrower).createLoan(
    loanId, productId, ethers.parseEther("1000"), 12, 150
  );
  
  // Duplicate should fail
  await expect(
    loanCore.connect(borrower).createLoan(
      loanId, productId, ethers.parseEther("1000"), 12, 150
    )
  ).to.be.revertedWith("LoanCore: loan exists");
});
```

### Test Assertions

Common assertion patterns:

```javascript
// Check event emission
await expect(contract.function())
  .to.emit(contract, "EventName")
  .withArgs(arg1, arg2);

// Check revert with message
await expect(contract.function())
  .to.be.revertedWith("Error message");

// Check state change
const result = await contract.getValue();
expect(result).to.equal(expectedValue);

// Check BigInt values (Ethers v6)
expect(await contract.getAmount()).to.equal(ethers.parseEther("1000"));
```

---

## 🔍 Debugging Tests

### Enable Verbose Logging

Add `console.log` in contracts:

```solidity
// In contract
import "hardhat/console.sol";

function createLoan(...) {
    console.log("Creating loan:", loanId);
    console.log("Borrower:", msg.sender);
}
```

### Check Transaction Details

```javascript
const tx = await contract.function();
const receipt = await tx.wait();
console.log("Gas used:", receipt.gasUsed);
console.log("Events:", receipt.events);
```

### Time Manipulation

```javascript
const { time } = require("@nomicfoundation/hardhat-network-helpers");

// Advance time by 1 day
await time.increase(86400);

// Advance to specific timestamp
await time.increaseTo(futureTimestamp);

// Get current block time
const now = await time.latest();
```

---

## 📊 Test Coverage

Run tests with coverage analysis:

```bash
npm run test:coverage
```

This generates a coverage report in `coverage/` directory.

---

## ❓ Troubleshooting

### "Contract not deployed"
- Ensure `beforeEach` deploys all required contracts
- Check that `waitForDeployment()` is called

### "Not authorized" errors
- Grant proper roles: `await contract.grantRole(ROLE, address)`
- Register users: `await accessControl.registerOfficer(...)` 
- Set contracts: `await loanCore.setContracts(...)`

### "Invalid argument" errors
- Check parameter types (bytes32 vs address vs uint256)
- Use `ethers.keccak256(ethers.toUtf8Bytes("string"))` for bytes32 IDs
- Use `ethers.parseEther("1000")` for amounts

### Tests timing out
- Hardhat local node may need restart: `Ctrl+C` and `npm run node`
- Check for infinite loops in contract logic

---

## 🎉 Summary

- **166 tests** covering all 7 main contracts
- Tests run in **~4 seconds** using Hardhat's in-memory blockchain
- No wallet or real ETH needed for testing
- Use `npm test` for quick validation
- Use `npx hardhat test --grep "pattern"` for specific tests
