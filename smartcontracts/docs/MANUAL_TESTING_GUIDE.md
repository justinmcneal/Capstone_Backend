# Manual Testing Guide

Step-by-step guide to manually test the smart contracts using Hardhat Console.

---

## Prerequisites

```bash
cd smartcontracts
npm install
npm run compile
```

---

## Phase 1: Start Local Blockchain

**Terminal 1:**
```bash
npm run node
```

Leave running. You'll see 20 test accounts with 10,000 ETH each.

---

## Phase 2: Deploy Contracts

**Terminal 2:**
```bash
npm run deploy:local
```

**Output:**
```
1. Deploying LoanAccessControl...
   LoanAccessControl deployed to: 0x5FbDB2315678afecb367f032d93F642f64180aa3

2. Deploying AuditRegistry...
   AuditRegistry deployed to: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512

3. Deploying LoanCore...
   LoanCore deployed to: 0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0

4. Deploying Disbursement...
   Disbursement deployed to: 0xCf7Ed3AccA5a467e9e704C703E8D87F634fB0Fc9

5. Deploying Repayment...
   Repayment deployed to: 0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9
```

Copy these addresses for the next steps.

---

## Phase 3: Interactive Testing

**Open Hardhat Console:**
```bash
npx hardhat console --network localhost
```

### Setup

```javascript
// Get accounts
const [admin, officer, borrower] = await ethers.getSigners();

// Contract addresses (from deployment)
const ACCESS_ADDR = "0x5FbDB2315678afecb367f032d93F642f64180aa3";
const AUDIT_ADDR = "0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512";
const CORE_ADDR = "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0";
const DISB_ADDR = "0xCf7Ed3AccA5a467e9e704C703E8D87F634fB0Fc9";
const REPAY_ADDR = "0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9";

// Connect to contracts
const accessControl = await ethers.getContractAt("LoanAccessControl", ACCESS_ADDR);
const auditRegistry = await ethers.getContractAt("AuditRegistry", AUDIT_ADDR);
const loanCore = await ethers.getContractAt("LoanCore", CORE_ADDR);
const disbursement = await ethers.getContractAt("Disbursement", DISB_ADDR);
const repayment = await ethers.getContractAt("Repayment", REPAY_ADDR);

// Role constants
const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
```

### Register Users

```javascript
// Register officer
await accessControl.registerOfficer(officer.address, ethers.keccak256(ethers.toUtf8Bytes("EMP001")));
await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address);
await disbursement.grantRole(LOAN_OFFICER_ROLE, officer.address);
await repayment.grantRole(LOAN_OFFICER_ROLE, officer.address);

// Register borrower
await accessControl.grantRole(SYSTEM_ROLE, admin.address);
await accessControl.registerBorrower(borrower.address, ethers.keccak256(ethers.toUtf8Bytes("CUST001")));
```

### Create Loan

```javascript
const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN-001"));
const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT-001"));
const amount = ethers.parseEther("10000");

await loanCore.grantRole(SYSTEM_ROLE, admin.address);
await loanCore.createLoan(loanId, borrower.address, productId, amount, 12, 150);

// Check loan
const loan = await loanCore.getLoan(loanId);
console.log("Status:", loan.status); // 0 = Draft
```

### Submit Loan

```javascript
await loanCore.submitLoan(loanId, 85, 1, ethers.keccak256(ethers.toUtf8Bytes("AI_OK")));

const loan = await loanCore.getLoan(loanId);
console.log("Status:", loan.status); // 1 = Submitted
```

### Assign Officer & Approve

```javascript
await loanCore.assignOfficer(loanId, officer.address);

const approvedAmount = ethers.parseEther("8000");
await loanCore.connect(officer).approveLoan(loanId, approvedAmount, ethers.ZeroHash);

const loan = await loanCore.getLoan(loanId);
console.log("Status:", loan.status); // 3 = Approved
```

### Disburse

```javascript
await disbursement.connect(officer).initiateDisbursement(loanId, approvedAmount, 1);
const disbId = await disbursement.loanToDisbursement(loanId);

await disbursement.connect(officer).completeDisbursement(disbId, ethers.keccak256(ethers.toUtf8Bytes("REF-001")));

const loan = await loanCore.getLoan(loanId);
console.log("Status:", loan.status); // 5 = Disbursed
```

### Create Repayment Schedule

```javascript
const startDate = Math.floor(Date.now() / 1000);
await repayment.grantRole(SYSTEM_ROLE, admin.address);
await repayment.createSchedule(loanId, borrower.address, approvedAmount, 150, 12, startDate);

const scheduleId = await repayment.loanToSchedule(loanId);
const schedule = await repayment.schedules(scheduleId);
console.log("Monthly Payment:", ethers.formatEther(schedule.monthlyPayment));
```

### Record Payment

```javascript
const installment = await repayment.installments(scheduleId, 1);
await repayment.connect(officer).recordPayment(
    loanId, 1, installment.totalAmount, 0, ethers.keccak256(ethers.toUtf8Bytes("RECEIPT-001"))
);

const paid = await repayment.installments(scheduleId, 1);
console.log("Status:", paid.status); // 1 = Paid
```

---

## Status Values

### Loan Status

| Value | Status |
|-------|--------|
| 0 | Draft |
| 1 | Submitted |
| 2 | UnderReview |
| 3 | Approved |
| 4 | Rejected |
| 5 | Disbursed |
| 6 | Cancelled |

### Installment Status

| Value | Status |
|-------|--------|
| 0 | Pending |
| 1 | Paid |
| 2 | Partial |
| 3 | Overdue |

### Payment Method

| Value | Method |
|-------|--------|
| 0 | Cash |
| 1 | BankTransfer |
| 2 | GCash |
| 3 | Maya |
| 4 | Other |

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| "execution reverted" | Check permissions and parameters |
| "contract not found" | Verify addresses from deployment |
| "nonce too high" | Restart blockchain node |
| "not authorized" | Grant required role |

### Reset

```bash
# Stop node (Ctrl+C), restart
npm run node

# Redeploy
npm run deploy:local
```
