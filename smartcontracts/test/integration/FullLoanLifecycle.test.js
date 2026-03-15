// Integration test — Full Loan Lifecycle across all contracts
// Task 4.1: End-to-end from borrower registration through full repayment + audit trail
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("Full Loan Lifecycle — Integration", function () {
  // ── Contract instances ──
  let accessControl;
  let auditRegistry;
  let loanApplication;
  let loanReview;
  let loanApproval;
  let disbursementMethod;
  let disbursementExecution;
  let repaymentSchedule;
  let paymentRecording;

  // ── Signers ──
  let admin, officer, borrower, other;

  // ── Role constants ──
  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

  // ── Loan parameters ──
  const loanId = ethers.keccak256(ethers.toUtf8Bytes("INTEG_LOAN_001"));
  const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT_MSME_001"));
  const requestedAmount = ethers.parseEther("6000");
  const termMonths = 3; // short term for easy full-repayment testing
  const interestRateBps = 200; // 2% monthly
  const eligibilityScore = 88;
  const aiRecommendationHash = ethers.keccak256(ethers.toUtf8Bytes("AI_REC_INTEG"));
  const approvalNotesHash = ethers.keccak256(ethers.toUtf8Bytes("APPROVAL_NOTES_INTEG"));

  // ── Enum mirrors ──
  const LoanStatus = {
    Draft: 0, Submitted: 1, UnderReview: 2, Approved: 3,
    Rejected: 4, Disbursed: 5, Cancelled: 6,
  };
  const RiskCategory = { Low: 0, Medium: 1, High: 2 };
  const DisbursementMethodEnum = { BankTransfer: 0, GCash: 1, Cash: 2, Check: 3, Wallet: 4 };
  const DisbursementStatus = { Pending: 0, Processing: 1, Completed: 2, Cancelled: 3 };
  const PaymentMethod = { Cash: 0, BankTransfer: 1, GCash: 2, Check: 3, Wallet: 4 };
  const InstallmentStatus = { Pending: 0, Paid: 1, Partial: 2, Overdue: 3 };

  // ================================================================
  // Deploy & wire every contract
  // ================================================================
  beforeEach(async function () {
    [admin, officer, borrower, other] = await ethers.getSigners();

    // ── 1. AuditRegistry ──
    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    auditRegistry = await upgrades.deployProxy(AuditRegistry, [admin.address], { kind: "uups" });
    await auditRegistry.waitForDeployment();

    // ── 2. LoanAccessControl ──
    const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
    accessControl = await upgrades.deployProxy(LoanAccessControl, [admin.address], { kind: "uups" });
    await accessControl.waitForDeployment();

    // ── 3. LoanApplication ──
    const LoanApplication = await ethers.getContractFactory("LoanApplication");
    loanApplication = await upgrades.deployProxy(
      LoanApplication,
      [await accessControl.getAddress(), await auditRegistry.getAddress(), admin.address],
      { kind: "uups" }
    );
    await loanApplication.waitForDeployment();

    // ── 4. LoanReview ──
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
    await loanReview.waitForDeployment();

    // ── 5. LoanApproval ──
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
    await loanApproval.waitForDeployment();

    // ── 6. DisbursementMethod ──
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
    await disbursementMethod.waitForDeployment();

    // ── 7. DisbursementExecution ──
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
    await disbursementExecution.waitForDeployment();

    // ── 8. RepaymentSchedule ──
    // Note: RepaymentSchedule uses ILoanCore — we need LoanCore for getLoanStatus.
    // BUT in the refactored architecture, DisbursementExecution sets loanApplication status to Disbursed.
    // RepaymentSchedule checks ILoanCore.getLoanStatus. We need to deploy LoanCore too
    // so RepaymentSchedule can verify Disbursed status.
    // Since the existing LoanCore reads its own state (not LoanApplication), we need it
    // in the lifecycle. Let's deploy it and mirror the disbursed state.
    const LoanCore = await ethers.getContractFactory("LoanCore");
    const loanCore = await upgrades.deployProxy(
      LoanCore,
      [await accessControl.getAddress(), await auditRegistry.getAddress(), admin.address],
      { kind: "uups" }
    );
    await loanCore.waitForDeployment();

    const RepaymentSchedule = await ethers.getContractFactory("RepaymentSchedule");
    repaymentSchedule = await upgrades.deployProxy(
      RepaymentSchedule,
      [await loanCore.getAddress(), admin.address],
      { kind: "uups" }
    );
    await repaymentSchedule.waitForDeployment();

    // ── 9. PaymentRecording ──
    const PaymentRecordingFactory = await ethers.getContractFactory("PaymentRecording");
    paymentRecording = await upgrades.deployProxy(
      PaymentRecordingFactory,
      [
        await repaymentSchedule.getAddress(),
        await auditRegistry.getAddress(),
        admin.address,
      ],
      { kind: "uups" }
    );
    await paymentRecording.waitForDeployment();

    // ================================================================
    // Wire permissions — the full contract graph
    // ================================================================

    // AuditRegistry: grant LOGGER_ROLE to every contract that calls log()
    await auditRegistry.grantLoggerRole(await loanApplication.getAddress());
    await auditRegistry.grantLoggerRole(await loanReview.getAddress());
    await auditRegistry.grantLoggerRole(await loanApproval.getAddress());
    await auditRegistry.grantLoggerRole(await disbursementMethod.getAddress());
    await auditRegistry.grantLoggerRole(await disbursementExecution.getAddress());
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());
    await auditRegistry.grantLoggerRole(await paymentRecording.getAddress());

    // LoanApplication: grant SYSTEM_ROLE to contracts that call updateStatus()
    await loanApplication.grantSystemRole(await loanReview.getAddress());
    await loanApplication.grantSystemRole(await loanApproval.getAddress());
    await loanApplication.grantSystemRole(await disbursementExecution.getAddress());

    // DisbursementMethod: grant SYSTEM_ROLE to DisbursementExecution (calls lockMethod)
    await disbursementMethod.grantSystemRole(await disbursementExecution.getAddress());

    // LoanCore: grant roles for the old-style lifecycle (needed for RepaymentSchedule check)
    await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await loanCore.grantRole(SYSTEM_ROLE, admin.address);

    // RepaymentSchedule: SYSTEM_ROLE → admin (createSchedule) + PaymentRecording (applyPayment)
    await repaymentSchedule.grantRole(SYSTEM_ROLE, admin.address);
    await repaymentSchedule.grantRole(SYSTEM_ROLE, await paymentRecording.getAddress());
    await repaymentSchedule.grantRole(LOAN_OFFICER_ROLE, officer.address);

    // PaymentRecording: grant roles
    await paymentRecording.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await paymentRecording.grantRole(SYSTEM_ROLE, admin.address);

    // DisbursementExecution: grant LOAN_OFFICER_ROLE to officer
    await disbursementExecution.grantRole(LOAN_OFFICER_ROLE, officer.address);

    // LoanAccessControl: grant SYSTEM_ROLE to admin (for registerBorrower)
    await accessControl.grantRole(SYSTEM_ROLE, admin.address);

    // ================================================================
    // Register borrower & officer in access control
    // ================================================================
    await accessControl.registerBorrower(
      borrower.address,
      ethers.keccak256(ethers.toUtf8Bytes("CUST_INTEG"))
    );
    await accessControl.registerOfficer(
      officer.address,
      ethers.keccak256(ethers.toUtf8Bytes("EMP_INTEG"))
    );

    // LoanCore also needs borrower & officer registered + loan created through its API
    // for getLoanStatus to return Disbursed
    await loanCore.connect(borrower).createLoan(
      loanId, productId, requestedAmount, termMonths, interestRateBps
    );
    await loanCore.connect(borrower).submitLoan(
      loanId, eligibilityScore, RiskCategory.Low, aiRecommendationHash
    );
    await loanCore.assignOfficer(loanId, officer.address);
    await loanCore.connect(officer).approveLoan(loanId, requestedAmount, approvalNotesHash);

    // We store loanCore reference for use inside tests
    this.loanCore = loanCore;
  });

  // ================================================================
  // THE FULL LIFECYCLE
  // ================================================================
  describe("Complete Loan Lifecycle (12 steps)", function () {

    it("Step 1: Register borrower via LoanAccessControl", async function () {
      // Already done in beforeEach — verify it worked
      expect(await accessControl.isBorrower(borrower.address)).to.be.true;
      const [customerIdHash, registeredAt] = await accessControl.getBorrowerInfo(borrower.address);
      expect(customerIdHash).to.equal(ethers.keccak256(ethers.toUtf8Bytes("CUST_INTEG")));
      expect(registeredAt).to.be.gt(0);
    });

    it("Step 2: Create application via LoanApplication.createApplication()", async function () {
      await expect(
        loanApplication.connect(borrower).createApplication(
          loanId, productId, requestedAmount, termMonths, interestRateBps
        )
      ).to.emit(loanApplication, "ApplicationCreated");

      const app = await loanApplication.getApplication(loanId);
      expect(app.borrower).to.equal(borrower.address);
      expect(app.status).to.equal(LoanStatus.Draft);
    });

    it("Step 3: Submit application via LoanApplication.submitApplication()", async function () {
      await loanApplication.connect(borrower).createApplication(
        loanId, productId, requestedAmount, termMonths, interestRateBps
      );

      await expect(
        loanApplication.connect(borrower).submitApplication(
          loanId, eligibilityScore, RiskCategory.Low, aiRecommendationHash
        )
      ).to.emit(loanApplication, "ApplicationSubmitted");

      const app = await loanApplication.getApplication(loanId);
      expect(app.status).to.equal(LoanStatus.Submitted);
    });

    it("Step 4: Assign officer via LoanReview.assignOfficer()", async function () {
      await loanApplication.connect(borrower).createApplication(
        loanId, productId, requestedAmount, termMonths, interestRateBps
      );
      await loanApplication.connect(borrower).submitApplication(
        loanId, eligibilityScore, RiskCategory.Low, aiRecommendationHash
      );

      await expect(
        loanReview.connect(admin).assignOfficer(loanId, officer.address)
      ).to.emit(loanReview, "OfficerAssigned");

      expect(await loanReview.getAssignedOfficer(loanId)).to.equal(officer.address);
      const app = await loanApplication.getApplication(loanId);
      expect(app.status).to.equal(LoanStatus.UnderReview);
    });

    it("Step 5: Approve loan via LoanApproval.approveLoan()", async function () {
      await loanApplication.connect(borrower).createApplication(
        loanId, productId, requestedAmount, termMonths, interestRateBps
      );
      await loanApplication.connect(borrower).submitApplication(
        loanId, eligibilityScore, RiskCategory.Low, aiRecommendationHash
      );
      await loanReview.connect(admin).assignOfficer(loanId, officer.address);

      await expect(
        loanApproval.connect(officer).approveLoan(loanId, requestedAmount, approvalNotesHash)
      ).to.emit(loanApproval, "LoanApproved");

      const app = await loanApplication.getApplication(loanId);
      expect(app.status).to.equal(LoanStatus.Approved);
    });

    it("Step 6: Set disbursement method via DisbursementMethod.setPreferredMethod()", async function () {
      await loanApplication.connect(borrower).createApplication(
        loanId, productId, requestedAmount, termMonths, interestRateBps
      );
      await loanApplication.connect(borrower).submitApplication(
        loanId, eligibilityScore, RiskCategory.Low, aiRecommendationHash
      );
      await loanReview.connect(admin).assignOfficer(loanId, officer.address);
      await loanApproval.connect(officer).approveLoan(loanId, requestedAmount, approvalNotesHash);

      await expect(
        disbursementMethod.connect(borrower).setPreferredMethod(loanId, DisbursementMethodEnum.GCash)
      ).to.emit(disbursementMethod, "DisbursementMethodSelected");

      expect(await disbursementMethod.hasPreferredMethod(loanId)).to.be.true;
    });

    it("Step 7: Initiate disbursement via DisbursementExecution.initiateDisbursement()", async function () {
      await loanApplication.connect(borrower).createApplication(
        loanId, productId, requestedAmount, termMonths, interestRateBps
      );
      await loanApplication.connect(borrower).submitApplication(
        loanId, eligibilityScore, RiskCategory.Low, aiRecommendationHash
      );
      await loanReview.connect(admin).assignOfficer(loanId, officer.address);
      await loanApproval.connect(officer).approveLoan(loanId, requestedAmount, approvalNotesHash);
      await disbursementMethod.connect(borrower).setPreferredMethod(loanId, DisbursementMethodEnum.GCash);

      await expect(
        disbursementExecution.connect(officer).initiateDisbursement(loanId, requestedAmount)
      ).to.emit(disbursementExecution, "DisbursementInitiated");

      const record = await disbursementExecution.getDisbursementByLoan(loanId);
      expect(record.status).to.equal(DisbursementStatus.Processing);
    });

    it("Step 8: Complete disbursement via DisbursementExecution.completeDisbursement()", async function () {
      await loanApplication.connect(borrower).createApplication(
        loanId, productId, requestedAmount, termMonths, interestRateBps
      );
      await loanApplication.connect(borrower).submitApplication(
        loanId, eligibilityScore, RiskCategory.Low, aiRecommendationHash
      );
      await loanReview.connect(admin).assignOfficer(loanId, officer.address);
      await loanApproval.connect(officer).approveLoan(loanId, requestedAmount, approvalNotesHash);
      await disbursementMethod.connect(borrower).setPreferredMethod(loanId, DisbursementMethodEnum.GCash);
      const tx = await disbursementExecution.connect(officer).initiateDisbursement(loanId, requestedAmount);
      await tx.wait();

      const record = await disbursementExecution.getDisbursementByLoan(loanId);
      const referenceHash = ethers.keccak256(ethers.toUtf8Bytes("GCASH_REF_12345"));

      await expect(
        disbursementExecution.connect(officer).completeDisbursement(record.disbursementId, referenceHash)
      ).to.emit(disbursementExecution, "DisbursementCompleted");

      const app = await loanApplication.getApplication(loanId);
      expect(app.status).to.equal(LoanStatus.Disbursed);
    });

    it("Step 9: Create repayment schedule via RepaymentSchedule.createSchedule()", async function () {
      // Mark disbursed in LoanCore (RepaymentSchedule checks ILoanCore)
      await this.loanCore.markDisbursed(loanId, requestedAmount);

      const startDate = await time.latest();
      await expect(
        repaymentSchedule.connect(admin).createSchedule(
          loanId, borrower.address, requestedAmount, interestRateBps, termMonths, startDate
        )
      ).to.emit(repaymentSchedule, "ScheduleCreated");

      const sched = await repaymentSchedule.getSchedule(loanId);
      expect(sched.termMonths).to.equal(termMonths);
      expect(sched.principal).to.equal(requestedAmount);
    });

    it("Step 10: Record payments for all installments via PaymentRecording.recordPayment()", async function () {
      await this.loanCore.markDisbursed(loanId, requestedAmount);

      const startDate = await time.latest();
      await repaymentSchedule.connect(admin).createSchedule(
        loanId, borrower.address, requestedAmount, interestRateBps, termMonths, startDate
      );

      for (let i = 1; i <= termMonths; i++) {
        const inst = await repaymentSchedule.getInstallment(loanId, i);
        await expect(
          paymentRecording.connect(officer).recordPayment(
            loanId, i, inst.totalAmount, PaymentMethod.GCash,
            ethers.keccak256(ethers.toUtf8Bytes(`INTEG_PAY_${i}`))
          )
        ).to.emit(paymentRecording, "PaymentRecorded");
      }

      // Verify all installments are Paid
      const all = await repaymentSchedule.getAllInstallments(loanId);
      for (const inst of all) {
        expect(inst.status).to.equal(InstallmentStatus.Paid);
      }
    });

    it("Step 11: Verify full repayment emits LoanFullyRepaid", async function () {
      await this.loanCore.markDisbursed(loanId, requestedAmount);

      const startDate = await time.latest();
      await repaymentSchedule.connect(admin).createSchedule(
        loanId, borrower.address, requestedAmount, interestRateBps, termMonths, startDate
      );

      // Pay installments 1 and 2
      for (let i = 1; i < termMonths; i++) {
        const inst = await repaymentSchedule.getInstallment(loanId, i);
        await paymentRecording.connect(officer).recordPayment(
          loanId, i, inst.totalAmount, PaymentMethod.Cash,
          ethers.keccak256(ethers.toUtf8Bytes(`INTEG_FULL_${i}`))
        );
      }

      // Pay last installment — should trigger LoanFullyRepaid
      const lastInst = await repaymentSchedule.getInstallment(loanId, termMonths);
      await expect(
        paymentRecording.connect(officer).recordPayment(
          loanId, termMonths, lastInst.totalAmount, PaymentMethod.Cash,
          ethers.keccak256(ethers.toUtf8Bytes(`INTEG_FULL_${termMonths}`))
        )
      ).to.emit(paymentRecording, "LoanFullyRepaid");

      // Remaining balance should be zero
      expect(await repaymentSchedule.getRemainingBalance(loanId)).to.equal(0);
    });

    it("Step 12: Verify audit trail via AuditRegistry.getFullAuditTrail()", async function () {
      // Run the full new-architecture lifecycle (steps 2–8)
      await loanApplication.connect(borrower).createApplication(
        loanId, productId, requestedAmount, termMonths, interestRateBps
      );
      await loanApplication.connect(borrower).submitApplication(
        loanId, eligibilityScore, RiskCategory.Low, aiRecommendationHash
      );
      await loanReview.connect(admin).assignOfficer(loanId, officer.address);
      await loanApproval.connect(officer).approveLoan(loanId, requestedAmount, approvalNotesHash);
      await disbursementMethod.connect(borrower).setPreferredMethod(loanId, DisbursementMethodEnum.GCash);
      const tx = await disbursementExecution.connect(officer).initiateDisbursement(loanId, requestedAmount);
      await tx.wait();
      const record = await disbursementExecution.getDisbursementByLoan(loanId);
      await disbursementExecution.connect(officer).completeDisbursement(
        record.disbursementId,
        ethers.keccak256(ethers.toUtf8Bytes("GCASH_REF_AUDIT"))
      );

      // Check audit trail for the loan
      const trail = await auditRegistry.getFullAuditTrail(loanId);
      expect(trail.length).to.be.gte(4); // At minimum: Created, Submitted, Assigned, Approved + status updates

      // Verify each entry has correct resourceId
      for (const entry of trail) {
        expect(entry.resourceId).to.equal(loanId);
        expect(entry.timestamp).to.be.gt(0);
      }
    });
  });

  // ================================================================
  // FULL END-TO-END IN A SINGLE TEST
  // ================================================================
  describe("Full End-to-End (single test)", function () {
    it("Should complete entire lifecycle: register → create → submit → assign → approve → disburse → schedule → pay all → verify", async function () {
      // ── Step 1: Borrower already registered in beforeEach ──
      expect(await accessControl.isBorrower(borrower.address)).to.be.true;

      // ── Step 2: Create application ──
      await loanApplication.connect(borrower).createApplication(
        loanId, productId, requestedAmount, termMonths, interestRateBps
      );
      let app = await loanApplication.getApplication(loanId);
      expect(app.status).to.equal(LoanStatus.Draft);

      // ── Step 3: Submit application ──
      await loanApplication.connect(borrower).submitApplication(
        loanId, eligibilityScore, RiskCategory.Low, aiRecommendationHash
      );
      app = await loanApplication.getApplication(loanId);
      expect(app.status).to.equal(LoanStatus.Submitted);

      // ── Step 4: Assign officer ──
      await loanReview.connect(admin).assignOfficer(loanId, officer.address);
      expect(await loanReview.getAssignedOfficer(loanId)).to.equal(officer.address);
      app = await loanApplication.getApplication(loanId);
      expect(app.status).to.equal(LoanStatus.UnderReview);

      // ── Step 5: Approve loan ──
      await loanApproval.connect(officer).approveLoan(loanId, requestedAmount, approvalNotesHash);
      app = await loanApplication.getApplication(loanId);
      expect(app.status).to.equal(LoanStatus.Approved);

      // ── Step 6: Set disbursement method ──
      await disbursementMethod.connect(borrower).setPreferredMethod(loanId, DisbursementMethodEnum.GCash);
      expect(await disbursementMethod.hasPreferredMethod(loanId)).to.be.true;

      // ── Step 7: Initiate disbursement ──
      const initTx = await disbursementExecution.connect(officer).initiateDisbursement(loanId, requestedAmount);
      await initTx.wait();
      let disbRecord = await disbursementExecution.getDisbursementByLoan(loanId);
      expect(disbRecord.status).to.equal(DisbursementStatus.Processing);

      // ── Step 8: Complete disbursement ──
      const disbRefHash = ethers.keccak256(ethers.toUtf8Bytes("GCASH_REF_E2E"));
      await disbursementExecution.connect(officer).completeDisbursement(
        disbRecord.disbursementId, disbRefHash
      );
      disbRecord = await disbursementExecution.getDisbursementByLoan(loanId);
      expect(disbRecord.status).to.equal(DisbursementStatus.Completed);
      app = await loanApplication.getApplication(loanId);
      expect(app.status).to.equal(LoanStatus.Disbursed);

      // ── Step 9: Create repayment schedule ──
      // Mark disbursed on LoanCore (RepaymentSchedule verifies via ILoanCore)
      await this.loanCore.markDisbursed(loanId, requestedAmount);
      const startDate = await time.latest();
      await repaymentSchedule.connect(admin).createSchedule(
        loanId, borrower.address, requestedAmount, interestRateBps, termMonths, startDate
      );
      const sched = await repaymentSchedule.getSchedule(loanId);
      expect(sched.termMonths).to.equal(termMonths);
      expect(sched.principal).to.equal(requestedAmount);

      // Verify installments
      const allInstallments = await repaymentSchedule.getAllInstallments(loanId);
      expect(allInstallments.length).to.equal(termMonths);

      // ── Step 10: Record payments for ALL installments ──
      for (let i = 1; i <= termMonths; i++) {
        const inst = await repaymentSchedule.getInstallment(loanId, i);
        await paymentRecording.connect(officer).recordPayment(
          loanId, i, inst.totalAmount, PaymentMethod.GCash,
          ethers.keccak256(ethers.toUtf8Bytes(`E2E_PAY_${i}`))
        );
      }

      // ── Step 11: Verify full repayment ──
      expect(await repaymentSchedule.getRemainingBalance(loanId)).to.equal(0);

      // All installments should be Paid
      const finalInstallments = await repaymentSchedule.getAllInstallments(loanId);
      for (const inst of finalInstallments) {
        expect(inst.status).to.equal(InstallmentStatus.Paid);
      }

      // Payment history storage array no longer populated (gas optimization);
      // events are the canonical source for payment history.
      const history = await paymentRecording.getPaymentHistory(loanId);
      expect(history.length).to.equal(0);

      // ── Step 12: Verify audit trail ──
      const trail = await auditRegistry.getFullAuditTrail(loanId);
      expect(trail.length).to.be.gte(4);
      // Trail entries should be chronologically ordered
      for (let i = 1; i < trail.length; i++) {
        expect(trail[i].timestamp).to.be.gte(trail[i - 1].timestamp);
      }
    });
  });

  // ================================================================
  // EDGE CASES ACROSS CONTRACT BOUNDARIES
  // ================================================================
  describe("Cross-contract edge cases", function () {
    it("Should reject schedule creation if loan not disbursed on LoanCore", async function () {
      // LoanCore loan is only approved (not disbursed) — createSchedule should revert
      const startDate = await time.latest();
      await expect(
        repaymentSchedule.connect(admin).createSchedule(
          loanId, borrower.address, requestedAmount, interestRateBps, termMonths, startDate
        )
      ).to.be.revertedWithCustomError(repaymentSchedule, "LoanNotDisbursed");
    });

    it("Should reject payment on non-existent schedule", async function () {
      const fakeLoanId = ethers.keccak256(ethers.toUtf8Bytes("FAKE_INTEG"));
      await expect(
        paymentRecording.connect(officer).recordPayment(
          fakeLoanId, 1, 100, PaymentMethod.Cash,
          ethers.keccak256(ethers.toUtf8Bytes("FAKE_REF"))
        )
      ).to.be.reverted; // Will revert on getInstallment → ScheduleNotFound
    });

    it("Should track partial payments across contract boundary", async function () {
      await this.loanCore.markDisbursed(loanId, requestedAmount);
      const startDate = await time.latest();
      await repaymentSchedule.connect(admin).createSchedule(
        loanId, borrower.address, requestedAmount, interestRateBps, termMonths, startDate
      );

      const inst = await repaymentSchedule.getInstallment(loanId, 1);
      const half = inst.totalAmount / 2n;

      // Partial payment
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, half, PaymentMethod.Cash,
        ethers.keccak256(ethers.toUtf8Bytes("CROSS_PARTIAL_1"))
      );

      // Verify state in RepaymentSchedule was mutated by PaymentRecording
      const updated = await repaymentSchedule.getInstallment(loanId, 1);
      expect(updated.status).to.equal(InstallmentStatus.Partial);
      expect(updated.paidAmount).to.equal(half);

      // Complete the payment
      const remainder = inst.totalAmount - half;
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, remainder, PaymentMethod.Cash,
        ethers.keccak256(ethers.toUtf8Bytes("CROSS_PARTIAL_2"))
      );

      const final = await repaymentSchedule.getInstallment(loanId, 1);
      expect(final.status).to.equal(InstallmentStatus.Paid);
    });

    it("Should correctly compute remaining balance after mixed payments", async function () {
      await this.loanCore.markDisbursed(loanId, requestedAmount);
      const startDate = await time.latest();
      await repaymentSchedule.connect(admin).createSchedule(
        loanId, borrower.address, requestedAmount, interestRateBps, termMonths, startDate
      );

      const sched = await repaymentSchedule.getSchedule(loanId);
      const totalAmount = sched.totalAmount;

      // Pay first installment fully
      const inst1 = await repaymentSchedule.getInstallment(loanId, 1);
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, inst1.totalAmount, PaymentMethod.Cash,
        ethers.keccak256(ethers.toUtf8Bytes("MIX_1"))
      );

      const remaining = await repaymentSchedule.getRemainingBalance(loanId);
      expect(remaining).to.equal(totalAmount - inst1.totalAmount);
    });

    it("Should handle overdue marking after time advancement", async function () {
      await this.loanCore.markDisbursed(loanId, requestedAmount);
      const startDate = await time.latest();
      await repaymentSchedule.connect(admin).createSchedule(
        loanId, borrower.address, requestedAmount, interestRateBps, termMonths, startDate
      );

      // Advance time past installment 1 due date
      const inst = await repaymentSchedule.getInstallment(loanId, 1);
      await time.increaseTo(inst.dueDate + 86400n); // 1 day past due

      await paymentRecording.connect(admin).markOverdue(loanId, 1);
      const updated = await repaymentSchedule.getInstallment(loanId, 1);
      expect(updated.status).to.equal(InstallmentStatus.Overdue);
    });
  });
});
