const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

/**
 * Gas Benchmark Test — Task 4.2
 * Measures gas for each target operation and compares against targets.
 */
describe("Gas Benchmark", function () {
  let admin, borrower, officer;
  let accessControl, auditRegistry, loanApplication, loanReview, loanApproval;
  let disbursementMethod, disbursementExecution, repaymentSchedule, paymentRecording;
  let loanCore;

  // Test data
  const loanId = ethers.keccak256(ethers.toUtf8Bytes("GAS_BENCH_LOAN_1"));
  const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT_1"));
  const requestedAmount = ethers.parseEther("100000");
  const termMonths = 12;
  const interestRateBps = 150;
  const approvalNotesHash = ethers.keccak256(ethers.toUtf8Bytes("approved"));

  // Gas targets from implementation plan
  const GAS_TARGETS = {
    createApplication: 150_000,
    submitApplication: 80_000,
    approveLoan: 80_000,
    initiateDisbursement: 100_000,
    completeDisbursement: 80_000,
    createSchedule: 500_000,
    recordPayment: 100_000,
  };

  before(async function () {
    [admin, borrower, officer] = await ethers.getSigners();

    // Deploy all contracts
    const AccessControl = await ethers.getContractFactory("LoanAccessControl");
    accessControl = await upgrades.deployProxy(AccessControl, [admin.address], { kind: "uups" });

    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    auditRegistry = await upgrades.deployProxy(AuditRegistry, [admin.address], { kind: "uups" });

    const LoanApplication = await ethers.getContractFactory("LoanApplication");
    loanApplication = await upgrades.deployProxy(
      LoanApplication,
      [await accessControl.getAddress(), await auditRegistry.getAddress(), admin.address],
      { kind: "uups" }
    );

    const LoanReview = await ethers.getContractFactory("LoanReview");
    loanReview = await upgrades.deployProxy(
      LoanReview,
      [
        await accessControl.getAddress(),
        await auditRegistry.getAddress(),
        await loanApplication.getAddress(),
        admin.address,
      ],
      { kind: "uups" }
    );

    const LoanApproval = await ethers.getContractFactory("LoanApproval");
    loanApproval = await upgrades.deployProxy(
      LoanApproval,
      [
        await accessControl.getAddress(),
        await auditRegistry.getAddress(),
        await loanApplication.getAddress(),
        await loanReview.getAddress(),
        admin.address,
      ],
      { kind: "uups" }
    );

    const DisbursementMethod = await ethers.getContractFactory("DisbursementMethod");
    disbursementMethod = await upgrades.deployProxy(
      DisbursementMethod,
      [
        await accessControl.getAddress(),
        await auditRegistry.getAddress(),
        await loanApplication.getAddress(),
        admin.address,
      ],
      { kind: "uups" }
    );

    const DisbursementExecution = await ethers.getContractFactory("DisbursementExecution");
    disbursementExecution = await upgrades.deployProxy(
      DisbursementExecution,
      [
        await accessControl.getAddress(),
        await auditRegistry.getAddress(),
        await loanApplication.getAddress(),
        await disbursementMethod.getAddress(),
        admin.address,
      ],
      { kind: "uups" }
    );

    const LoanCore = await ethers.getContractFactory("LoanCore");
    loanCore = await upgrades.deployProxy(
      LoanCore,
      [await accessControl.getAddress(), await auditRegistry.getAddress(), admin.address],
      { kind: "uups" }
    );

    const RepaymentSchedule = await ethers.getContractFactory("RepaymentSchedule");
    repaymentSchedule = await upgrades.deployProxy(
      RepaymentSchedule,
      [await loanCore.getAddress(), admin.address],
      { kind: "uups" }
    );

    const PaymentRecording = await ethers.getContractFactory("PaymentRecording");
    paymentRecording = await upgrades.deployProxy(
      PaymentRecording,
      [await repaymentSchedule.getAddress(), await auditRegistry.getAddress(), admin.address],
      { kind: "uups" }
    );

    // Wire permissions
    const borrowerHash = ethers.keccak256(ethers.toUtf8Bytes("BORROWER_1"));
    const officerHash = ethers.keccak256(ethers.toUtf8Bytes("OFFICER_1"));
    const SYSTEM_ROLE_AC = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
    await accessControl.grantRole(SYSTEM_ROLE_AC, admin.address);
    await accessControl.registerBorrower(borrower.address, borrowerHash);
    await accessControl.registerOfficer(officer.address, officerHash);

    // Grant SYSTEM_ROLE to contracts that need it
    await loanApplication.grantSystemRole(await loanReview.getAddress());
    await loanApplication.grantSystemRole(await loanApproval.getAddress());
    await loanApplication.grantSystemRole(await disbursementExecution.getAddress());
    await disbursementMethod.grantSystemRole(await disbursementExecution.getAddress());

    // Grant LOGGER_ROLE
    const contracts = [loanApplication, loanReview, loanApproval, disbursementMethod, disbursementExecution, paymentRecording, loanCore];
    for (const c of contracts) {
      await auditRegistry.grantLoggerRole(await c.getAddress());
    }

    // Grant officer roles
    await loanApplication.grantSystemRole(borrower.address);
    const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
    await disbursementExecution.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await paymentRecording.grantRole(LOAN_OFFICER_ROLE, officer.address);

    // RepaymentSchedule: grant SYSTEM_ROLE to PaymentRecording
    const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
    await repaymentSchedule.grantRole(SYSTEM_ROLE, await paymentRecording.getAddress());
  });

  // Helper to measure gas
  async function measureGas(txPromise) {
    const tx = await txPromise;
    const receipt = await tx.wait();
    return Number(receipt.gasUsed);
  }

  // Results storage
  const results = {};

  it("Benchmark: createApplication", async function () {
    const gas = await measureGas(
      loanApplication.connect(borrower).createApplication(
        loanId, productId, requestedAmount, termMonths, interestRateBps
      )
    );
    results.createApplication = gas;
    console.log(`    createApplication: ${gas.toLocaleString()} gas (target: ${GAS_TARGETS.createApplication.toLocaleString()})`);
  });

  it("Benchmark: submitApplication", async function () {
    const aiHash = ethers.keccak256(ethers.toUtf8Bytes("ai_recommendation"));
    const gas = await measureGas(
      loanApplication.connect(borrower).submitApplication(loanId, 85, 1, aiHash)
    );
    results.submitApplication = gas;
    console.log(`    submitApplication: ${gas.toLocaleString()} gas (target: ${GAS_TARGETS.submitApplication.toLocaleString()})`);
  });

  it("Benchmark: assignOfficer + approveLoan", async function () {
    await loanReview.connect(admin).assignOfficer(loanId, officer.address);

    const gas = await measureGas(
      loanApproval.connect(officer).approveLoan(loanId, requestedAmount, approvalNotesHash)
    );
    results.approveLoan = gas;
    console.log(`    approveLoan: ${gas.toLocaleString()} gas (target: ${GAS_TARGETS.approveLoan.toLocaleString()})`);
  });

  it("Benchmark: setPreferredMethod + initiateDisbursement", async function () {
    await disbursementMethod.connect(borrower).setPreferredMethod(loanId, 0);

    const gas = await measureGas(
      disbursementExecution.connect(officer).initiateDisbursement(loanId, requestedAmount)
    );
    results.initiateDisbursement = gas;
    console.log(`    initiateDisbursement: ${gas.toLocaleString()} gas (target: ${GAS_TARGETS.initiateDisbursement.toLocaleString()})`);
  });

  it("Benchmark: completeDisbursement", async function () {
    const record = await disbursementExecution.getDisbursementByLoan(loanId);
    const refHash = ethers.keccak256(ethers.toUtf8Bytes("REF_001"));

    const gas = await measureGas(
      disbursementExecution.connect(officer).completeDisbursement(record.disbursementId, refHash)
    );
    results.completeDisbursement = gas;
    console.log(`    completeDisbursement: ${gas.toLocaleString()} gas (target: ${GAS_TARGETS.completeDisbursement.toLocaleString()})`);
  });

  it("Benchmark: createSchedule (12 months)", async function () {
    // Need to use LoanCore for RepaymentSchedule (it checks ILoanCore.getLoanStatus)
    // Create a separate loan through LoanCore path
    const loanId2 = ethers.keccak256(ethers.toUtf8Bytes("GAS_BENCH_LOAN_2"));
    const SYSTEM_ROLE_LC = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
    const LOAN_OFFICER_ROLE_LC = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
    await loanCore.grantRole(SYSTEM_ROLE_LC, admin.address);
    await loanCore.grantRole(LOAN_OFFICER_ROLE_LC, officer.address);
    await loanCore.connect(borrower).createLoan(loanId2, productId, requestedAmount, termMonths, interestRateBps);
    const aiHash2 = ethers.keccak256(ethers.toUtf8Bytes("ai_rec_2"));
    await loanCore.connect(borrower).submitLoan(loanId2, 85, 1, aiHash2);
    await loanCore.assignOfficer(loanId2, officer.address);
    await loanCore.connect(officer).approveLoan(loanId2, requestedAmount, approvalNotesHash);
    await loanCore.markDisbursed(loanId2, requestedAmount);

    const gas = await measureGas(
      repaymentSchedule.connect(admin).createSchedule(
        loanId2, borrower.address, requestedAmount, interestRateBps, termMonths, Math.floor(Date.now() / 1000)
      )
    );
    results.createSchedule = gas;
    console.log(`    createSchedule (12mo): ${gas.toLocaleString()} gas (target: ${GAS_TARGETS.createSchedule.toLocaleString()})`);
  });

  it("Benchmark: recordPayment", async function () {
    const loanId2 = ethers.keccak256(ethers.toUtf8Bytes("GAS_BENCH_LOAN_2"));
    const refHash = ethers.keccak256(ethers.toUtf8Bytes("PAY_REF_001"));
    const schedule = await repaymentSchedule.getSchedule(loanId2);

    const gas = await measureGas(
      paymentRecording.connect(officer).recordPayment(
        loanId2, 1, schedule.monthlyPayment, 0, refHash
      )
    );
    results.recordPayment = gas;
    console.log(`    recordPayment: ${gas.toLocaleString()} gas (target: ${GAS_TARGETS.recordPayment.toLocaleString()})`);
  });

  after(function () {
    console.log("\n    ╔═══════════════════════════════════════════════════════════╗");
    console.log("    ║              GAS OPTIMIZATION RESULTS                     ║");
    console.log("    ╠═══════════════════════════════════════════════════════════╣");
    for (const [op, gas] of Object.entries(results)) {
      const target = GAS_TARGETS[op];
      const status = gas <= target ? "✅" : "⚠️";
      const pct = ((gas / target) * 100).toFixed(0);
      console.log(`    ║ ${status} ${op.padEnd(25)} ${gas.toLocaleString().padStart(10)} / ${target.toLocaleString().padStart(10)}  (${pct}%) ║`);
    }
    console.log("    ╚═══════════════════════════════════════════════════════════╝");
  });
});
