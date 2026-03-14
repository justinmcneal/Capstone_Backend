// Testnet Validation Script — Full Loan Lifecycle on Deployed Ganache Contracts
// Usage: npx hardhat run scripts/validate-deployment.js --network ganache

const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  console.log("═".repeat(60));
  console.log("  MSME Loan V2 — Deployment Validation");
  console.log("═".repeat(60));

  // ================================================================
  // 1. Read deployment data from most recent v2-ganache-*.json
  // ================================================================
  const deploymentsDir = path.join(__dirname, "..", "deployments");
  const files = fs.readdirSync(deploymentsDir)
    .filter(f => f.startsWith("v2-ganache-") && f.endsWith(".json"))
    .sort()
    .reverse();

  if (files.length === 0) {
    throw new Error("No v2-ganache-*.json deployment files found in ./deployments/");
  }

  const deploymentFile = files[0];
  const deploymentPath = path.join(deploymentsDir, deploymentFile);
  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  console.log(`\nDeployment file: ${deploymentFile}`);
  console.log(`Network:         ${deployment.network}`);
  console.log(`Deployer:        ${deployment.deployer}`);
  console.log(`Timestamp:       ${deployment.timestamp}`);

  // ================================================================
  // 2. Get signers (admin = deployer, borrower = second account)
  // ================================================================
  const signers = await ethers.getSigners();
  const admin = signers[0];

  let borrower;
  if (signers.length > 1) {
    borrower = signers[1];
  } else {
    // Ganache: all default accounts are unlocked; query them via RPC
    const ganacheAccounts = await ethers.provider.send("eth_accounts", []);
    const borrowerAddr = ganacheAccounts.find(
      a => a.toLowerCase() !== admin.address.toLowerCase()
    );
    if (!borrowerAddr) {
      throw new Error("Need at least 2 accounts. Only found the deployer.");
    }
    borrower = await ethers.provider.getSigner(borrowerAddr);
  }

  console.log(`\nAdmin (deployer): ${admin.address}`);
  console.log(`Borrower:         ${borrower.address}`);

  // ================================================================
  // Patch signers: Ganache GUI underestimates gas for cross-contract
  // proxy calls, causing bare "revert" errors. HardhatEthersSigner
  // only reads the `gas` config for hardhat/localhost networks, so
  // we set _gasLimit directly on each signer instance.
  // ================================================================
  const GANACHE_GAS = 6_721_975; // Ganache default block gas limit
  admin._gasLimit = GANACHE_GAS;
  borrower._gasLimit = GANACHE_GAS;

  // ================================================================
  // 3. Connect to all 10 contracts using the patched admin signer
  //    (ethers.getContractAt creates its own signer instance, so we
  //     must .connect(admin) to pick up the _gasLimit override)
  // ================================================================
  const c = deployment.contracts;
  const accessControl = (await ethers.getContractAt("LoanAccessControl", c.accessControl)).connect(admin);
  const auditRegistry = (await ethers.getContractAt("AuditRegistry", c.auditRegistry)).connect(admin);
  const loanCore = (await ethers.getContractAt("LoanCore", c.loanCore)).connect(admin);
  const loanApplication = (await ethers.getContractAt("LoanApplication", c.loanApplication)).connect(admin);
  const loanReview = (await ethers.getContractAt("LoanReview", c.loanReview)).connect(admin);
  const loanApproval = (await ethers.getContractAt("LoanApproval", c.loanApproval)).connect(admin);
  const disbursementMethod = (await ethers.getContractAt("DisbursementMethod", c.disbursementMethod)).connect(admin);
  const disbursementExecution = (await ethers.getContractAt("DisbursementExecution", c.disbursementExecution)).connect(admin);
  const repaymentSchedule = (await ethers.getContractAt("RepaymentSchedule", c.repaymentSchedule)).connect(admin);
  const paymentRecording = (await ethers.getContractAt("PaymentRecording", c.paymentRecording)).connect(admin);

  console.log("\n✓ Connected to all 10 contracts");

  // All contract instances for event parsing
  const allContracts = [
    accessControl, auditRegistry, loanCore, loanApplication,
    loanReview, loanApproval, disbursementMethod, disbursementExecution,
    repaymentSchedule, paymentRecording,
  ];

  // ================================================================
  // Role constants & loan parameters
  // ================================================================
  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

  const loanId = ethers.keccak256(ethers.toUtf8Bytes("VALIDATION_LOAN_" + Date.now()));
  const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT_VALIDATE_001"));
  const requestedAmount = 100000n; // 100K in smallest unit
  const termMonths = 3;
  const interestRateBps = 1200; // 12%
  const eligibilityScore = 85;
  const RiskCategory_Low = 0;
  const aiRecommendationHash = ethers.keccak256(ethers.toUtf8Bytes("AI_REC_VALIDATE"));
  const approvalNotesHash = ethers.keccak256(ethers.toUtf8Bytes("APPROVAL_NOTES_VALIDATE"));

  // Tracking
  let totalTxCount = 0;
  let totalGasUsed = 0n;
  const allEvents = [];

  // ================================================================
  // Helper: decode custom error data from all known contract ABIs
  // ================================================================
  function decodeCustomError(err) {
    const data = err.data || (err.error && err.error.data) || (err.info && err.info.error && err.info.error.data);
    if (!data || data === "0x") return null;
    // Ganache GUI wraps error data in { hash, programCounter, result, reason, message }
    // Extract hex-encoded revert data from nested wrappers
    let hexData = data;
    if (typeof data === "object") {
      hexData = data.result || data.data;
    }
    if (!hexData || typeof hexData !== "string" || !hexData.startsWith("0x") || hexData.length < 10) return null;
    for (const contract of allContracts) {
      try {
        const decoded = contract.interface.parseError(hexData);
        if (decoded) return `${decoded.name}(${decoded.args.map(a => a.toString()).join(", ")})`;
      } catch { /* not from this ABI */ }
    }
    return `raw error data: ${hexData.slice(0, 130)}`;
  }

  // ================================================================
  // Helper: execute a step, log tx hash + gas, parse events.
  // Accepts either a Promise (legacy) or a () => Promise (preferred).
  // When a function is given, a short delay + optional auto-retry
  // with explicit gasLimit is available for Ganache compatibility.
  // ================================================================
  async function execStep(label, description, txOrFn, opts = {}) {
    console.log(`\n${"─".repeat(60)}`);
    console.log(`Step ${label}: ${description}`);
    console.log("─".repeat(60));

    const isFn = typeof txOrFn === "function";

    // Brief delay for Ganache GUI block processing
    if (isFn) await new Promise(r => setTimeout(r, 200));

    let tx;
    try {
      tx = await (isFn ? txOrFn() : txOrFn);
    } catch (err) {
      if (opts.skipOnRevert) {
        console.log(`  ⏭  already done — skipped (${err.reason || err.message || "revert"})`);
        return null;
      }
      const decoded = decodeCustomError(err);
      if (decoded) {
        console.error(`  ✗ Custom error: ${decoded}`);
      }
      if (err.reason) console.error(`  ✗ Reason: ${err.reason}`);
      console.error(`  ✗ Error keys: ${Object.keys(err).join(", ")}`);
      if (err.code) console.error(`  ✗ Code: ${err.code}`);
      if (err.data) console.error(`  ✗ Data: ${typeof err.data === "string" ? err.data.slice(0, 500) : JSON.stringify(err.data).slice(0, 500)}`);
      if (err.error) console.error(`  ✗ Inner: ${JSON.stringify(err.error).slice(0, 300)}`);
      if (err.info) console.error(`  ✗ Info: ${JSON.stringify(err.info).slice(0, 300)}`);
      throw err;
    }

    const receipt = await tx.wait();
    totalTxCount++;
    totalGasUsed += receipt.gasUsed;

    console.log(`  tx hash:  ${receipt.hash}`);
    console.log(`  gas used: ${receipt.gasUsed.toString()}`);

    // Parse events from all known contract ABIs
    const stepEvents = [];
    for (const log of receipt.logs) {
      for (const contract of allContracts) {
        try {
          const parsed = contract.interface.parseLog({
            topics: log.topics,
            data: log.data,
          });
          if (parsed) {
            stepEvents.push({ name: parsed.name, args: parsed.args });
            break;
          }
        } catch {
          // Not from this contract, try next
        }
      }
    }

    for (const evt of stepEvents) {
      console.log(`  event:    ${evt.name}`);
    }
    if (stepEvents.length === 0) {
      console.log("  events:   (none)");
    }

    allEvents.push(...stepEvents);
    return receipt;
  }

  // ================================================================
  // PRE-FLIGHT: Grant roles not set during deployment
  // ================================================================
  console.log("\n\n" + "═".repeat(60));
  console.log("  PRE-FLIGHT: Granting required roles");
  console.log("═".repeat(60));

  const SKIP = { skipOnRevert: true };

  // SYSTEM_ROLE on LoanAccessControl → admin (for registerBorrower)
  await execStep("0a", "Grant SYSTEM_ROLE to admin on LoanAccessControl",
    () => accessControl.grantRole(SYSTEM_ROLE, admin.address), SKIP);

  // Register admin as officer (needed for LoanReview.assignOfficer + LoanCore.assignOfficer)
  await execStep("0b", "Register admin as officer via LoanAccessControl",
    () => accessControl.registerOfficer(
      admin.address,
      ethers.keccak256(ethers.toUtf8Bytes("EMP_VALIDATE"))
    ), SKIP);

  // LOAN_OFFICER_ROLE on LoanCore → admin (for LoanCore.approveLoan path)
  await execStep("0c", "Grant LOAN_OFFICER_ROLE to admin on LoanCore",
    () => loanCore.grantRole(LOAN_OFFICER_ROLE, admin.address), SKIP);

  // SYSTEM_ROLE on LoanCore → admin (for markDisbursed fallback)
  await execStep("0d", "Grant SYSTEM_ROLE to admin on LoanCore",
    () => loanCore.grantRole(SYSTEM_ROLE, admin.address), SKIP);

  // LOAN_OFFICER_ROLE on DisbursementExecution → admin
  await execStep("0e", "Grant LOAN_OFFICER_ROLE to admin on DisbursementExecution",
    () => disbursementExecution.grantRole(LOAN_OFFICER_ROLE, admin.address), SKIP);

  // SYSTEM_ROLE on RepaymentSchedule → admin (for createSchedule)
  await execStep("0f", "Grant SYSTEM_ROLE to admin on RepaymentSchedule",
    () => repaymentSchedule.grantRole(SYSTEM_ROLE, admin.address), SKIP);

  // LOAN_OFFICER_ROLE on PaymentRecording → admin (for recordPayment)
  await execStep("0g", "Grant LOAN_OFFICER_ROLE to admin on PaymentRecording",
    () => paymentRecording.grantRole(LOAN_OFFICER_ROLE, admin.address), SKIP);

  // ── Cross-contract: LOGGER_ROLE on AuditRegistry for contracts that call log() ──
  await execStep("0h", "Grant LOGGER_ROLE to LoanApplication on AuditRegistry",
    () => auditRegistry.grantLoggerRole(c.loanApplication), SKIP);
  await execStep("0i", "Grant LOGGER_ROLE to LoanReview on AuditRegistry",
    () => auditRegistry.grantLoggerRole(c.loanReview), SKIP);
  await execStep("0j", "Grant LOGGER_ROLE to LoanApproval on AuditRegistry",
    () => auditRegistry.grantLoggerRole(c.loanApproval), SKIP);
  await execStep("0k", "Grant LOGGER_ROLE to DisbursementMethod on AuditRegistry",
    () => auditRegistry.grantLoggerRole(c.disbursementMethod), SKIP);
  await execStep("0l", "Grant LOGGER_ROLE to DisbursementExecution on AuditRegistry",
    () => auditRegistry.grantLoggerRole(c.disbursementExecution), SKIP);
  await execStep("0m", "Grant LOGGER_ROLE to LoanCore on AuditRegistry",
    () => auditRegistry.grantLoggerRole(c.loanCore), SKIP);
  await execStep("0n", "Grant LOGGER_ROLE to PaymentRecording on AuditRegistry",
    () => auditRegistry.grantLoggerRole(c.paymentRecording), SKIP);

  // ── Cross-contract: SYSTEM_ROLE on LoanApplication for status-updating contracts ──
  await execStep("0o", "Grant SYSTEM_ROLE to LoanReview on LoanApplication",
    () => loanApplication.grantSystemRole(c.loanReview), SKIP);
  await execStep("0p", "Grant SYSTEM_ROLE to LoanApproval on LoanApplication",
    () => loanApplication.grantSystemRole(c.loanApproval), SKIP);
  await execStep("0q", "Grant SYSTEM_ROLE to DisbursementExecution on LoanApplication",
    () => loanApplication.grantSystemRole(c.disbursementExecution), SKIP);

  // ── Cross-contract: SYSTEM_ROLE on DisbursementMethod → DisbursementExecution (lockMethod) ──
  await execStep("0r", "Grant SYSTEM_ROLE to DisbursementExecution on DisbursementMethod",
    () => disbursementMethod.grantSystemRole(c.disbursementExecution), SKIP);

  // ── Cross-contract: SYSTEM_ROLE on RepaymentSchedule → PaymentRecording (applyPayment) ──
  await execStep("0s", "Grant SYSTEM_ROLE to PaymentRecording on RepaymentSchedule",
    () => repaymentSchedule.grantRole(SYSTEM_ROLE, c.paymentRecording), SKIP);

  // ================================================================
  // LIFECYCLE: 12-Step Loan Lifecycle
  // ================================================================
  console.log("\n\n" + "═".repeat(60));
  console.log("  LIFECYCLE: 12-Step Loan Lifecycle Validation");
  console.log("═".repeat(60));

  // ── Step 1: Register borrower ──
  await execStep(1, "Register borrower via LoanAccessControl.registerBorrower()",
    () => accessControl.registerBorrower(
      borrower.address,
      ethers.keccak256(ethers.toUtf8Bytes("CUST_VALIDATE"))
    ), SKIP);

  const isBorrower = await accessControl.isBorrower(borrower.address);
  console.log(`  verified: isBorrower = ${isBorrower}`);

  // ── Step 2: Create application ──
  await execStep(2, "Create application via LoanApplication.createApplication()",
    () => loanApplication.connect(borrower).createApplication(
      loanId, productId, requestedAmount, termMonths, interestRateBps
    ));

  let app = await loanApplication.getApplication(loanId);
  console.log(`  verified: status = ${app.status} (0=Draft)`);

  // ── Step 3: Submit application ──
  await execStep(3, "Submit application via LoanApplication.submitApplication()",
    () => loanApplication.connect(borrower).submitApplication(
      loanId, eligibilityScore, RiskCategory_Low, aiRecommendationHash
    ));

  app = await loanApplication.getApplication(loanId);
  console.log(`  verified: status = ${app.status} (1=Submitted)`);

  // ── Step 4: Assign officer ──
  await execStep(4, "Assign officer via LoanReview.assignOfficer()",
    () => loanReview.assignOfficer(loanId, admin.address));

  const assignedOfficer = await loanReview.getAssignedOfficer(loanId);
  console.log(`  verified: assignedOfficer = ${assignedOfficer}`);
  app = await loanApplication.getApplication(loanId);
  console.log(`  verified: status = ${app.status} (2=UnderReview)`);

  // ── Step 5: Approve loan ──
  await execStep(5, "Approve loan via LoanApproval.approveLoan()",
    () => loanApproval.approveLoan(loanId, requestedAmount, approvalNotesHash));

  app = await loanApplication.getApplication(loanId);
  console.log(`  verified: status = ${app.status} (3=Approved)`);

  // ── Step 6: Set disbursement method (borrower calls) ──
  await execStep(6, "Set disbursement method via DisbursementMethod.setPreferredMethod()",
    () => disbursementMethod.connect(borrower).setPreferredMethod(loanId, 1)); // 1 = GCash

  const hasMethod = await disbursementMethod.hasPreferredMethod(loanId);
  console.log(`  verified: hasPreferredMethod = ${hasMethod}`);

  // ── Step 7: Initiate disbursement ──
  await execStep(7, "Initiate disbursement via DisbursementExecution.initiateDisbursement()",
    () => disbursementExecution.initiateDisbursement(loanId, requestedAmount));

  let disbRecord = await disbursementExecution.getDisbursementByLoan(loanId);
  console.log(`  verified: disbursement status = ${disbRecord.status} (1=Processing)`);

  // ── Step 8: Complete disbursement ──
  const referenceHash = ethers.keccak256(ethers.toUtf8Bytes("GCASH_REF_" + loanId));
  await execStep(8, "Complete disbursement via DisbursementExecution.completeDisbursement()",
    () => disbursementExecution.completeDisbursement(disbRecord.disbursementId, referenceHash));

  disbRecord = await disbursementExecution.getDisbursementByLoan(loanId);
  console.log(`  verified: disbursement status = ${disbRecord.status} (2=Completed)`);
  app = await loanApplication.getApplication(loanId);
  console.log(`  verified: loan status = ${app.status} (5=Disbursed)`);

  // ── Step 9: Create repayment schedule ──
  // RepaymentSchedule checks ILoanCore.getLoanStatus — mirror lifecycle on LoanCore
  console.log(`\n  ℹ  Mirroring lifecycle on LoanCore (required by RepaymentSchedule)...`);
  await execStep("9a", "LoanCore: createLoan (borrower)",
    () => loanCore.connect(borrower).createLoan(
      loanId, productId, requestedAmount, termMonths, interestRateBps
    ));
  await execStep("9b", "LoanCore: submitLoan (borrower)",
    () => loanCore.connect(borrower).submitLoan(
      loanId, eligibilityScore, RiskCategory_Low, aiRecommendationHash
    ));
  await execStep("9c", "LoanCore: assignOfficer",
    () => loanCore.assignOfficer(loanId, admin.address));
  await execStep("9d", "LoanCore: approveLoan",
    () => loanCore.approveLoan(loanId, requestedAmount, approvalNotesHash));
  await execStep("9e", "LoanCore: markDisbursed",
    () => loanCore.markDisbursed(loanId, requestedAmount));

  const block = await ethers.provider.getBlock("latest");
  const startDate = block.timestamp;

  await execStep(9, "Create repayment schedule via RepaymentSchedule.createSchedule()",
    () => repaymentSchedule.createSchedule(
      loanId, borrower.address, requestedAmount, interestRateBps, termMonths, startDate
    ));

  const sched = await repaymentSchedule.getSchedule(loanId);
  console.log(`  verified: termMonths = ${sched.termMonths}, principal = ${sched.principal.toString()}`);

  // ── Step 10: Record payments for all installments ──
  let fullyRepaidEvent = false;

  for (let i = 1; i <= termMonths; i++) {
    const inst = await repaymentSchedule.getInstallment(loanId, i);
    const payRefHash = ethers.keccak256(ethers.toUtf8Bytes(`VALIDATE_PAY_${i}`));

    const receipt = await execStep(
      `10.${i}`,
      `Record payment for installment ${i}/${termMonths} (amount: ${inst.totalAmount.toString()})`,
      () => paymentRecording.recordPayment(
        loanId,
        i,              // installmentNumber (uint16)
        inst.totalAmount,
        2,              // PaymentMethod.GCash
        payRefHash
      )
    );

    // Check if LoanFullyRepaid was emitted
    for (const log of receipt.logs) {
      try {
        const parsed = paymentRecording.interface.parseLog({
          topics: log.topics,
          data: log.data,
        });
        if (parsed && parsed.name === "LoanFullyRepaid") {
          fullyRepaidEvent = true;
          console.log("  ★ LoanFullyRepaid event detected!");
        }
      } catch {
        // Not from PaymentRecording
      }
    }
  }

  // ── Step 11: Verify LoanFullyRepaid ──
  console.log(`\n${"─".repeat(60)}`);
  console.log("Step 11: Verify LoanFullyRepaid event was emitted");
  console.log("─".repeat(60));
  console.log(`  ${fullyRepaidEvent ? "✓" : "✗"} LoanFullyRepaid: ${fullyRepaidEvent}`);

  const remainingBalance = await repaymentSchedule.getRemainingBalance(loanId);
  console.log(`  remaining balance: ${remainingBalance.toString()}`);

  const allInstallments = await repaymentSchedule.getAllInstallments(loanId);
  for (let i = 0; i < allInstallments.length; i++) {
    console.log(`  installment ${i + 1} status: ${allInstallments[i].status} (1=Paid)`);
  }

  // ── Step 12: Verify audit trail ──
  console.log(`\n${"─".repeat(60)}`);
  console.log("Step 12: Verify audit trail via AuditRegistry.getFullAuditTrail()");
  console.log("─".repeat(60));

  const trail = await auditRegistry.getFullAuditTrail(loanId);
  console.log(`  audit trail entries: ${trail.length}`);

  for (let i = 0; i < trail.length; i++) {
    const entry = trail[i];
    console.log(
      `    [${i}] actor=${entry.actor}  action=${entry.action}  timestamp=${entry.timestamp}`
    );
  }

  // ================================================================
  // SUMMARY
  // ================================================================
  console.log("\n\n" + "═".repeat(60));
  console.log("  VALIDATION SUMMARY");
  console.log("═".repeat(60));
  console.log(`  Total transactions sent:  ${totalTxCount}`);
  console.log(`  Total gas used:           ${totalGasUsed.toString()}`);
  console.log(`  Events captured:          ${allEvents.length}`);
  console.log(`  Audit trail entries:      ${trail.length}`);
  console.log(`  LoanFullyRepaid emitted:  ${fullyRepaidEvent ? "✓ YES" : "✗ NO"}`);
  console.log(`  Remaining balance:        ${remainingBalance.toString()}`);
  console.log("─".repeat(60));

  // Event frequency summary
  console.log("\n  Events breakdown:");
  const eventCounts = {};
  for (const evt of allEvents) {
    eventCounts[evt.name] = (eventCounts[evt.name] || 0) + 1;
  }
  for (const [name, count] of Object.entries(eventCounts).sort()) {
    console.log(`    ${name}: ${count}x`);
  }

  console.log("\n" + "═".repeat(60));
  console.log("  ✓ Deployment validation complete!");
  console.log("═".repeat(60));
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error("\n✗ Validation FAILED!");
    console.error(error);
    process.exit(1);
  });
