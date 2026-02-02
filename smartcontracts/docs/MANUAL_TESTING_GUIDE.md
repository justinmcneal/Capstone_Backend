# 📋 Manual Testing Guide for Smart Contracts

A complete, beginner-friendly guide to manually test the MSME Pathways Smart Contracts using Hardhat Console.

---

## 📌 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Understanding the Basics](#understanding-the-basics)
4. [Step-by-Step Testing](#step-by-step-testing)
   - [Phase 1: Start Local Blockchain](#phase-1-start-local-blockchain)
   - [Phase 2: Deploy Contracts](#phase-2-deploy-contracts)
   - [Phase 3: Test Loan Lifecycle](#phase-3-test-loan-lifecycle)
   - [Phase 4: Test Disbursement](#phase-4-test-disbursement)
   - [Phase 5: Test Repayment](#phase-5-test-repayment)
5. [Complete Test Script](#complete-test-script)
6. [Troubleshooting](#troubleshooting)
7. [Glossary](#glossary)

---

## Prerequisites

### What You Need
- ✅ Node.js installed (v18 or higher)
- ✅ Smart contracts folder set up
- ✅ Dependencies installed (`npm install`)
- ✅ Contracts compiled (`npm run compile`)

### Verify Your Setup
```bash
# Navigate to the smart contracts folder
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts

# Check Node.js version
node --version  # Should show v18+ (v25.2.1 works but shows warning)

# Verify contracts compile
npm run compile
# Should say: "Compiled X Solidity files successfully"
```

---

## Quick Start

**Want to just run tests?** Use this:
```bash
npm test
```

**Want to manually interact with contracts?** Follow the full guide below.

---

## Understanding the Basics

### What is a Local Blockchain?
When you run `npm run node`, Hardhat creates a **temporary blockchain** on your computer. It:
- Gives you **20 test accounts** with 10,000 fake ETH each
- Runs at `http://127.0.0.1:8545`
- Resets when you stop it

### What are the Test Accounts?
```
Account #0: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 (Admin)
Account #1: 0x70997970C51812dc3A010C7d01b50e0d17dc79C8 (Loan Officer)
Account #2: 0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC (Borrower)
Account #3: 0x90F79bf6EB2c4f870365E785982E1f101E93b906 (Other)
...
```

### Key Concepts
| Term | Meaning |
|------|---------|
| `bytes32` | A 32-byte identifier (like a unique ID) |
| `wei` | Smallest unit of ETH (1 ETH = 10^18 wei) |
| `parseEther("100")` | Converts "100" to wei |
| `formatEther(wei)` | Converts wei back to readable ETH |
| `keccak256` | Hash function (creates unique IDs) |

---

## Step-by-Step Testing

### Phase 1: Start Local Blockchain

**Terminal 1 - Start the blockchain:**
```bash
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts
npm run node
```

You'll see:
```
Started HTTP and WebSocket JSON-RPC server at http://127.0.0.1:8545/

Accounts
========
Account #0: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 (10000 ETH)
Private Key: 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
...
```

**⚠️ Leave this terminal running!** Open a new terminal for the next steps.

---

### Phase 2: Deploy Contracts

**Terminal 2 - Deploy contracts:**
```bash
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts
npm run deploy:local
```

You'll see:
```
Deploying contracts with account: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266

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

✅ DEPLOYMENT COMPLETE!
```

**📝 Copy these addresses!** You'll need them for the next steps.

---

### Phase 3: Test Loan Lifecycle

**Open Hardhat Console:**
```bash
npx hardhat console --network localhost
```

Now you're in an interactive JavaScript environment. Type these commands one at a time:

#### Step 3.1: Setup Variables
```javascript
// Get test accounts
const [admin, officer, borrower] = await ethers.getSigners();
console.log("Admin:", admin.address);
console.log("Officer:", officer.address);
console.log("Borrower:", borrower.address);

// Contract addresses (use the ones from your deployment!)
const ACCESS_CONTROL_ADDR = "0x5FbDB2315678afecb367f032d93F642f64180aa3";
const AUDIT_REGISTRY_ADDR = "0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512";
const LOAN_CORE_ADDR = "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0";
const DISBURSEMENT_ADDR = "0xCf7Ed3AccA5a467e9e704C703E8D87F634fB0Fc9";
const REPAYMENT_ADDR = "0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9";

// Connect to contracts
const accessControl = await ethers.getContractAt("LoanAccessControl", ACCESS_CONTROL_ADDR);
const auditRegistry = await ethers.getContractAt("AuditRegistry", AUDIT_REGISTRY_ADDR);
const loanCore = await ethers.getContractAt("LoanCore", LOAN_CORE_ADDR);
const disbursement = await ethers.getContractAt("Disbursement", DISBURSEMENT_ADDR);
const repayment = await ethers.getContractAt("Repayment", REPAYMENT_ADDR);

console.log("✅ Contracts connected!");
```

#### Step 3.2: Register Officer and Borrower
```javascript
// Define role hashes
const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

// Register the loan officer
const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));
await accessControl.connect(admin).registerOfficer(officer.address, employeeIdHash);
console.log("✅ Officer registered:", officer.address);

// Grant roles to officer on all contracts
await loanCore.connect(admin).grantRole(LOAN_OFFICER_ROLE, officer.address);
await disbursement.connect(admin).grantRole(LOAN_OFFICER_ROLE, officer.address);
await repayment.connect(admin).grantRole(LOAN_OFFICER_ROLE, officer.address);
console.log("✅ Officer roles granted!");

// Register the borrower
const customerIdHash = ethers.keccak256(ethers.toUtf8Bytes("CUST001"));
await accessControl.connect(admin).grantRole(SYSTEM_ROLE, admin.address);
await accessControl.connect(admin).registerBorrower(borrower.address, customerIdHash);
console.log("✅ Borrower registered:", borrower.address);
```

#### Step 3.3: Create a Loan
```javascript
// Create loan identifiers
const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN-2024-001"));
const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT-MSME-STANDARD"));
const requestedAmount = ethers.parseEther("10000"); // 10,000 PHP equivalent
const termMonths = 12;
const interestRateBps = 150; // 1.5% monthly

// Create the loan application
await loanCore.connect(admin).grantRole(SYSTEM_ROLE, admin.address);
const tx1 = await loanCore.connect(admin).createLoan(
    loanId,
    borrower.address,
    productId,
    requestedAmount,
    termMonths,
    interestRateBps
);
await tx1.wait();
console.log("✅ Loan created!");

// Check loan status
const loan = await loanCore.getLoan(loanId);
console.log("Loan Status:", loan.status); // 0 = Draft
console.log("Requested Amount:", ethers.formatEther(loan.requestedAmount), "ETH");
```

#### Step 3.4: Submit the Loan
```javascript
// AI qualification data
const eligibilityScore = 85; // 0-100
const riskCategory = 1; // 0=Low, 1=Medium, 2=High
const aiRecommendationHash = ethers.keccak256(ethers.toUtf8Bytes("AI_RECOMMENDS_APPROVE"));

// Submit the loan
const tx2 = await loanCore.connect(admin).submitLoan(
    loanId,
    eligibilityScore,
    riskCategory,
    aiRecommendationHash
);
await tx2.wait();
console.log("✅ Loan submitted!");

// Check new status
const loanAfterSubmit = await loanCore.getLoan(loanId);
console.log("Loan Status:", loanAfterSubmit.status); // 1 = Submitted
```

#### Step 3.5: Assign Officer and Review
```javascript
// Assign officer to loan
await loanCore.connect(admin).assignOfficer(loanId, officer.address);
console.log("✅ Officer assigned!");

// Check loan is now under review
const loanAfterAssign = await loanCore.getLoan(loanId);
console.log("Loan Status:", loanAfterAssign.status); // 2 = UnderReview
console.log("Assigned Officer:", loanAfterAssign.assignedOfficer);
```

#### Step 3.6: Approve the Loan
```javascript
// Approve the loan
const approvedAmount = ethers.parseEther("8000"); // Approve 8,000 (less than requested)
const notesHash = ethers.keccak256(ethers.toUtf8Bytes("Good credit history, approved for lower amount"));

const tx3 = await loanCore.connect(officer).approveLoan(loanId, approvedAmount, notesHash);
await tx3.wait();
console.log("✅ Loan approved!");

// Check final status
const approvedLoan = await loanCore.getLoan(loanId);
console.log("Loan Status:", approvedLoan.status); // 3 = Approved
console.log("Approved Amount:", ethers.formatEther(approvedLoan.approvedAmount), "ETH");
```

---

### Phase 4: Test Disbursement

#### Step 4.1: Initiate Disbursement
```javascript
// DisbursementMethod: 0=BankTransfer, 1=Cash, 2=GCash, 3=Maya, 4=Other
const disbursementMethod = 1; // Cash

const tx4 = await disbursement.connect(officer).initiateDisbursement(
    loanId,
    approvedAmount,
    disbursementMethod
);
await tx4.wait();
console.log("✅ Disbursement initiated!");

// Get disbursement ID
const disbursementId = await disbursement.loanToDisbursement(loanId);
console.log("Disbursement ID:", disbursementId);

// Check disbursement status
const disbRecord = await disbursement.disbursements(disbursementId);
console.log("Disbursement Status:", disbRecord.status); // 0 = Pending
```

#### Step 4.2: Complete Disbursement
```javascript
// Reference number from bank/payment processor
const referenceHash = ethers.keccak256(ethers.toUtf8Bytes("BANK-REF-2024-001-ABC"));

const tx5 = await disbursement.connect(officer).completeDisbursement(
    disbursementId,
    referenceHash
);
await tx5.wait();
console.log("✅ Disbursement completed!");

// Check loan is now disbursed
const disbursedLoan = await loanCore.getLoan(loanId);
console.log("Loan Status:", disbursedLoan.status); // 5 = Disbursed
console.log("Disbursed Amount:", ethers.formatEther(disbursedLoan.disbursedAmount), "ETH");
```

---

### Phase 5: Test Repayment

#### Step 5.1: Create Repayment Schedule
```javascript
// Get current timestamp for start date
const startDate = Math.floor(Date.now() / 1000);

// Create schedule
await repayment.connect(admin).grantRole(SYSTEM_ROLE, admin.address);
const tx6 = await repayment.connect(admin).createSchedule(
    loanId,
    borrower.address,
    approvedAmount,  // Principal
    interestRateBps, // 1.5% monthly
    termMonths,      // 12 months
    startDate
);
await tx6.wait();
console.log("✅ Repayment schedule created!");

// Get schedule details
const scheduleId = await repayment.loanToSchedule(loanId);
const schedule = await repayment.schedules(scheduleId);
console.log("Schedule ID:", scheduleId);
console.log("Term Months:", schedule.termMonths);
console.log("Monthly Payment:", ethers.formatEther(schedule.monthlyPayment), "ETH");
console.log("Total Amount:", ethers.formatEther(schedule.totalAmount), "ETH");
```

#### Step 5.2: Check Installments
```javascript
// Get first installment
const installment1 = await repayment.installments(scheduleId, 1);
console.log("\n📅 Installment 1:");
console.log("  Due Date:", new Date(Number(installment1.dueDate) * 1000).toLocaleDateString());
console.log("  Principal:", ethers.formatEther(installment1.principalAmount), "ETH");
console.log("  Interest:", ethers.formatEther(installment1.interestAmount), "ETH");
console.log("  Total:", ethers.formatEther(installment1.totalAmount), "ETH");
console.log("  Status:", installment1.status); // 0 = Pending

// Get second installment
const installment2 = await repayment.installments(scheduleId, 2);
console.log("\n📅 Installment 2:");
console.log("  Due Date:", new Date(Number(installment2.dueDate) * 1000).toLocaleDateString());
console.log("  Total:", ethers.formatEther(installment2.totalAmount), "ETH");
```

#### Step 5.3: Record a Payment
```javascript
// Payment details
const installmentNumber = 1;
const paymentAmount = installment1.totalAmount; // Full payment
const paymentMethod = 0; // Cash
const paymentRefHash = ethers.keccak256(ethers.toUtf8Bytes("RECEIPT-001"));

// Record the payment
const tx7 = await repayment.connect(officer).recordPayment(
    loanId,
    installmentNumber,
    paymentAmount,
    paymentMethod,
    paymentRefHash
);
await tx7.wait();
console.log("✅ Payment recorded!");

// Check installment status
const paidInstallment = await repayment.installments(scheduleId, 1);
console.log("Installment Status:", paidInstallment.status); // 1 = Paid
console.log("Paid Amount:", ethers.formatEther(paidInstallment.paidAmount), "ETH");
console.log("Paid At:", new Date(Number(paidInstallment.paidAt) * 1000).toLocaleString());

// Check schedule totals
const updatedSchedule = await repayment.schedules(scheduleId);
console.log("Total Paid:", ethers.formatEther(updatedSchedule.totalPaid), "ETH");
```

#### Step 5.4: Make a Partial Payment
```javascript
// Partial payment on installment 2
const partialAmount = ethers.parseEther("300"); // Less than full amount
const partialRefHash = ethers.keccak256(ethers.toUtf8Bytes("RECEIPT-002"));

const tx8 = await repayment.connect(officer).recordPayment(
    loanId,
    2, // Installment 2
    partialAmount,
    paymentMethod,
    partialRefHash
);
await tx8.wait();
console.log("✅ Partial payment recorded!");

// Check status
const partialInstallment = await repayment.installments(scheduleId, 2);
console.log("Installment 2 Status:", partialInstallment.status); // 2 = Partial
console.log("Paid Amount:", ethers.formatEther(partialInstallment.paidAmount), "ETH");
```

---

## Complete Test Script

Save this as `scripts/manual-test.js` and run with `npx hardhat run scripts/manual-test.js --network localhost`:

```javascript
const { ethers } = require("hardhat");

async function main() {
    console.log("\n🚀 Starting Manual Test...\n");
    
    // Get signers
    const [admin, officer, borrower] = await ethers.getSigners();
    console.log("Admin:", admin.address);
    console.log("Officer:", officer.address);
    console.log("Borrower:", borrower.address);

    // Role definitions
    const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
    const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

    // ============ DEPLOY CONTRACTS ============
    console.log("\n📦 Deploying contracts...");
    
    // Deploy AccessControl
    const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
    const accessControl = await (await ethers.upgrades.deployProxy(
        LoanAccessControl,
        [admin.address],
        { kind: "uups" }
    )).waitForDeployment();
    console.log("  AccessControl:", await accessControl.getAddress());

    // Deploy AuditRegistry
    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    const auditRegistry = await (await ethers.upgrades.deployProxy(
        AuditRegistry,
        [admin.address],
        { kind: "uups" }
    )).waitForDeployment();
    console.log("  AuditRegistry:", await auditRegistry.getAddress());

    // Deploy LoanCore
    const LoanCore = await ethers.getContractFactory("LoanCore");
    const loanCore = await (await ethers.upgrades.deployProxy(
        LoanCore,
        [
            await accessControl.getAddress(),
            await auditRegistry.getAddress(),
            admin.address
        ],
        { kind: "uups" }
    )).waitForDeployment();
    console.log("  LoanCore:", await loanCore.getAddress());

    // Deploy Disbursement
    const Disbursement = await ethers.getContractFactory("Disbursement");
    const disbursement = await (await ethers.upgrades.deployProxy(
        Disbursement,
        [
            await loanCore.getAddress(),
            await auditRegistry.getAddress(),
            admin.address
        ],
        { kind: "uups" }
    )).waitForDeployment();
    console.log("  Disbursement:", await disbursement.getAddress());

    // Deploy Repayment
    const Repayment = await ethers.getContractFactory("Repayment");
    const repayment = await (await ethers.upgrades.deployProxy(
        Repayment,
        [
            await loanCore.getAddress(),
            await auditRegistry.getAddress(),
            admin.address
        ],
        { kind: "uups" }
    )).waitForDeployment();
    console.log("  Repayment:", await repayment.getAddress());

    // Configure cross-references
    await loanCore.setContracts(
        await disbursement.getAddress(),
        await repayment.getAddress(),
        ethers.ZeroAddress
    );
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());
    await auditRegistry.grantLoggerRole(await disbursement.getAddress());
    await auditRegistry.grantLoggerRole(await repayment.getAddress());

    // ============ SETUP ROLES ============
    console.log("\n👤 Setting up roles...");
    
    // Register officer
    const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));
    await accessControl.registerOfficer(officer.address, employeeIdHash);
    await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await disbursement.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await repayment.grantRole(LOAN_OFFICER_ROLE, officer.address);
    console.log("  ✅ Officer registered and granted roles");

    // Register borrower
    await accessControl.grantRole(SYSTEM_ROLE, admin.address);
    const customerIdHash = ethers.keccak256(ethers.toUtf8Bytes("CUST001"));
    await accessControl.registerBorrower(borrower.address, customerIdHash);
    console.log("  ✅ Borrower registered");

    // ============ CREATE LOAN ============
    console.log("\n📝 Creating loan application...");
    
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN-2024-001"));
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT-MSME"));
    const requestedAmount = ethers.parseEther("10000");
    const termMonths = 12;
    const interestRateBps = 150;

    await loanCore.grantRole(SYSTEM_ROLE, admin.address);
    await loanCore.createLoan(loanId, borrower.address, productId, requestedAmount, termMonths, interestRateBps);
    console.log("  ✅ Loan created (status: Draft)");

    // ============ SUBMIT LOAN ============
    await loanCore.submitLoan(loanId, 85, 1, ethers.keccak256(ethers.toUtf8Bytes("AI_OK")));
    console.log("  ✅ Loan submitted (status: Submitted)");

    // ============ ASSIGN & APPROVE ============
    await loanCore.assignOfficer(loanId, officer.address);
    console.log("  ✅ Officer assigned (status: UnderReview)");

    const approvedAmount = ethers.parseEther("8000");
    await loanCore.connect(officer).approveLoan(loanId, approvedAmount, ethers.ZeroHash);
    console.log("  ✅ Loan approved (status: Approved)");

    // ============ DISBURSE ============
    console.log("\n💰 Processing disbursement...");
    
    await disbursement.connect(officer).initiateDisbursement(loanId, approvedAmount, 1);
    const disbursementId = await disbursement.loanToDisbursement(loanId);
    console.log("  ✅ Disbursement initiated");

    await disbursement.connect(officer).completeDisbursement(
        disbursementId,
        ethers.keccak256(ethers.toUtf8Bytes("BANK-REF-001"))
    );
    console.log("  ✅ Disbursement completed (loan status: Disbursed)");

    // ============ CREATE REPAYMENT SCHEDULE ============
    console.log("\n📅 Creating repayment schedule...");
    
    const startDate = Math.floor(Date.now() / 1000);
    await repayment.grantRole(SYSTEM_ROLE, admin.address);
    await repayment.createSchedule(loanId, borrower.address, approvedAmount, interestRateBps, termMonths, startDate);
    
    const scheduleId = await repayment.loanToSchedule(loanId);
    const schedule = await repayment.schedules(scheduleId);
    console.log("  ✅ Schedule created");
    console.log("    Monthly Payment:", ethers.formatEther(schedule.monthlyPayment), "ETH");
    console.log("    Total Amount:", ethers.formatEther(schedule.totalAmount), "ETH");

    // ============ RECORD PAYMENT ============
    console.log("\n💳 Recording payment...");
    
    const installment1 = await repayment.installments(scheduleId, 1);
    await repayment.connect(officer).recordPayment(
        loanId,
        1,
        installment1.totalAmount,
        0,
        ethers.keccak256(ethers.toUtf8Bytes("RECEIPT-001"))
    );
    console.log("  ✅ Payment recorded for installment 1");

    const paidInstallment = await repayment.installments(scheduleId, 1);
    console.log("    Status:", paidInstallment.status == 1 ? "Paid" : "Other");
    console.log("    Paid Amount:", ethers.formatEther(paidInstallment.paidAmount), "ETH");

    // ============ FINAL STATUS ============
    console.log("\n📊 Final Loan Status:");
    const finalLoan = await loanCore.getLoan(loanId);
    console.log("  Status:", ["Draft", "Submitted", "UnderReview", "Approved", "Rejected", "Disbursed", "Cancelled"][finalLoan.status]);
    console.log("  Requested:", ethers.formatEther(finalLoan.requestedAmount), "ETH");
    console.log("  Approved:", ethers.formatEther(finalLoan.approvedAmount), "ETH");
    console.log("  Disbursed:", ethers.formatEther(finalLoan.disbursedAmount), "ETH");

    const finalSchedule = await repayment.schedules(scheduleId);
    console.log("  Total Paid:", ethers.formatEther(finalSchedule.totalPaid), "ETH");

    console.log("\n✅ ALL TESTS COMPLETED SUCCESSFULLY!\n");
}

main()
    .then(() => process.exit(0))
    .catch((error) => {
        console.error(error);
        process.exit(1);
    });
```

Run it:
```bash
npx hardhat run scripts/manual-test.js --network localhost
```

---

## Troubleshooting

### Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `"execution reverted"` | Transaction failed | Check role permissions and parameters |
| `"contract not found"` | Wrong address | Verify contract addresses from deployment |
| `"insufficient funds"` | No test ETH | Restart blockchain node |
| `"nonce too high"` | State out of sync | Restart blockchain node |
| `"not authorized"` | Missing role | Grant required role before calling |

### Reset Everything
```bash
# Stop the node (Ctrl+C)
# Restart it
npm run node

# Redeploy
npm run deploy:local
```

### Check Contract State
```javascript
// In Hardhat console
const loan = await loanCore.getLoan(loanId);
console.log("Loan:", loan);

const hasRole = await loanCore.hasRole(LOAN_OFFICER_ROLE, officer.address);
console.log("Officer has role:", hasRole);
```

---

## Glossary

| Term | Description |
|------|-------------|
| **bytes32** | A 32-byte value, often used for IDs and hashes |
| **keccak256** | Cryptographic hash function used in Ethereum |
| **wei** | Smallest unit of ETH (10^18 wei = 1 ETH) |
| **parseEther** | Converts human-readable ETH to wei |
| **formatEther** | Converts wei to human-readable ETH |
| **Signer** | An account that can sign transactions |
| **Contract Instance** | A JavaScript object representing a deployed contract |
| **UUPS Proxy** | Upgradeable contract pattern |
| **Role** | Permission level (ADMIN, LOAN_OFFICER, etc.) |

---

## Loan Status Values

| Value | Status | Description |
|-------|--------|-------------|
| 0 | Draft | Created but not submitted |
| 1 | Submitted | Submitted for review |
| 2 | UnderReview | Assigned to officer |
| 3 | Approved | Officer approved |
| 4 | Rejected | Officer rejected |
| 5 | Disbursed | Funds released |
| 6 | Cancelled | Cancelled by user/admin |

## Installment Status Values

| Value | Status | Description |
|-------|--------|-------------|
| 0 | Pending | Not yet due |
| 1 | Paid | Fully paid |
| 2 | Partial | Partially paid |
| 3 | Overdue | Past due date |

## Payment Method Values

| Value | Method |
|-------|--------|
| 0 | Cash |
| 1 | BankTransfer |
| 2 | GCash |
| 3 | Maya |
| 4 | Other |

---

## Next Steps

1. ✅ Complete basic testing with this guide
2. 📚 Read [CONTRACT_FUNCTIONS.md](CONTRACT_FUNCTIONS.md) for full API reference
3. 🔗 Integrate with Django backend using Web3.py
4. 🚀 Deploy to testnet when ready

---

*Last Updated: February 2, 2026*
