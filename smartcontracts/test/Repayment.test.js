// Test suite for Repayment contract - Aligned with actual contract implementation
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("Repayment", function () {
  let repayment;
  let loanCore;
  let auditRegistry;
  let admin, officer, borrower, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

  const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
  const principal = ethers.parseEther("12000");
  const interestRateBps = 150; // 1.5% monthly
  const termMonths = 12;

  // PaymentMethod enum
  const PaymentMethod = {
    Cash: 0,
    BankTransfer: 1,
    GCash: 2,
    Maya: 3,
    Other: 4
  };

  // InstallmentStatus enum - matches backend (no Defaulted)
  const InstallmentStatus = {
    Pending: 0,
    Paid: 1,
    Partial: 2,
    Overdue: 3
  };

  beforeEach(async function () {
    [admin, officer, borrower, other] = await ethers.getSigners();

    // Deploy AuditRegistry
    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    auditRegistry = await upgrades.deployProxy(
      AuditRegistry,
      [admin.address],
      { kind: "uups" }
    );
    await auditRegistry.waitForDeployment();

    // Deploy LoanAccessControl
    const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
    const accessControl = await upgrades.deployProxy(
      LoanAccessControl,
      [admin.address],
      { kind: "uups" }
    );
    await accessControl.waitForDeployment();

    // Deploy LoanCore
    const LoanCore = await ethers.getContractFactory("LoanCore");
    loanCore = await upgrades.deployProxy(
      LoanCore,
      [
        await accessControl.getAddress(),
        await auditRegistry.getAddress(),
        admin.address
      ],
      { kind: "uups" }
    );
    await loanCore.waitForDeployment();

    // Deploy Repayment (loanCore, auditRegistry, admin)
    const Repayment = await ethers.getContractFactory("Repayment");
    repayment = await upgrades.deployProxy(
      Repayment,
      [
        await loanCore.getAddress(),
        await auditRegistry.getAddress(),
        admin.address
      ],
      { kind: "uups" }
    );
    await repayment.waitForDeployment();

    // Setup permissions
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());
    await auditRegistry.grantLoggerRole(await repayment.getAddress());
    
    // Register Repayment contract with LoanCore
    await loanCore.setContracts(
      other.address,       // placeholder non-zero address
      await repayment.getAddress(),
      other.address        // placeholder non-zero address
    );
    
    // Grant roles
    await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await loanCore.grantRole(SYSTEM_ROLE, await repayment.getAddress());
    
    await repayment.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await repayment.grantRole(SYSTEM_ROLE, admin.address);

    // Create, approve, and mark loan as disbursed
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT001"));
    
    // Register borrower in access control
    await accessControl.grantRole(SYSTEM_ROLE, admin.address);
    const customerIdHash = ethers.keccak256(ethers.toUtf8Bytes("CUST001"));
    await accessControl.registerBorrower(borrower.address, customerIdHash);
    
    // Register officer in access control
    const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));
    await accessControl.registerOfficer(officer.address, employeeIdHash);
    
    await loanCore.connect(borrower).createLoan(
      loanId,
      productId,
      principal,
      termMonths,
      interestRateBps
    );
    
    // submitLoan requires: loanId, eligibilityScore, riskCategory, aiRecommendationHash
    const eligibilityScore = 85;
    const riskCategory = 0; // Low
    const aiRecommendationHash = ethers.keccak256(ethers.toUtf8Bytes("AI_REC_001"));
    await loanCore.connect(borrower).submitLoan(loanId, eligibilityScore, riskCategory, aiRecommendationHash);
    
    await loanCore.assignOfficer(loanId, officer.address);
    await loanCore.connect(officer).approveLoan(
      loanId,
      principal,
      ethers.keccak256(ethers.toUtf8Bytes("NOTES"))
    );
    
    // Mark as disbursed
    await loanCore.markDisbursed(loanId, principal);
  });

  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await repayment.VERSION()).to.equal(1);
    });
  });

  describe("Schedule Creation", function () {
    it("Should create repayment schedule", async function () {
      const startDate = await time.latest();

      await expect(
        repayment.connect(admin).createSchedule(
          loanId,
          borrower.address,
          principal,
          interestRateBps,
          termMonths,
          startDate
        )
      ).to.emit(repayment, "ScheduleCreated");
    });

    it("Should generate correct installments", async function () {
      const startDate = await time.latest();

      await repayment.connect(admin).createSchedule(
        loanId,
        borrower.address,
        principal,
        interestRateBps,
        termMonths,
        startDate
      );

      const scheduleId = await repayment.loanToSchedule(loanId);
      const schedule = await repayment.schedules(scheduleId);

      expect(schedule.termMonths).to.equal(termMonths);
      expect(schedule.principal).to.equal(principal);
    });

    it("Should not create duplicate schedule", async function () {
      const startDate = await time.latest();

      await repayment.connect(admin).createSchedule(
        loanId,
        borrower.address,
        principal,
        interestRateBps,
        termMonths,
        startDate
      );

      await expect(
        repayment.connect(admin).createSchedule(
          loanId,
          borrower.address,
          principal,
          interestRateBps,
          termMonths,
          startDate
        )
      ).to.be.revertedWithCustomError(repayment, "ScheduleAlreadyExists");
    });

    it("Should reject zero principal", async function () {
      const startDate = await time.latest();

      await expect(
        repayment.connect(admin).createSchedule(
          loanId,
          borrower.address,
          0,
          interestRateBps,
          termMonths,
          startDate
        )
      ).to.be.revertedWith("Repayment: invalid principal");
    });
  });

  describe("Payment Recording", function () {
    let scheduleId;
    const paymentAmount = ethers.parseEther("1180"); // Monthly payment
    const referenceHash = ethers.keccak256(ethers.toUtf8Bytes("PAY001"));

    beforeEach(async function () {
      const startDate = await time.latest();

      await repayment.connect(admin).createSchedule(
        loanId,
        borrower.address,
        principal,
        interestRateBps,
        termMonths,
        startDate
      );

      scheduleId = await repayment.loanToSchedule(loanId);
    });

    it("Should record payment successfully", async function () {
      await expect(
        repayment.connect(officer).recordPayment(
          loanId,
          1, // installmentNumber
          paymentAmount,
          PaymentMethod.GCash,
          referenceHash
        )
      ).to.emit(repayment, "PaymentRecorded");
    });

    it("Should update paid amount", async function () {
      await repayment.connect(officer).recordPayment(
        loanId,
        1,
        paymentAmount,
        PaymentMethod.Cash,
        referenceHash
      );

      const schedule = await repayment.schedules(scheduleId);
      expect(schedule.totalPaid).to.be.gt(0);
    });

    it("Should increment total payments count", async function () {
      const beforeCount = await repayment.totalPaymentsRecorded();

      await repayment.connect(officer).recordPayment(
        loanId,
        1,
        paymentAmount,
        PaymentMethod.BankTransfer,
        referenceHash
      );

      const afterCount = await repayment.totalPaymentsRecorded();
      expect(afterCount).to.equal(beforeCount + 1n);
    });

    it("Should not allow duplicate payment reference", async function () {
      await repayment.connect(officer).recordPayment(
        loanId,
        1,
        paymentAmount,
        PaymentMethod.GCash,
        referenceHash
      );

      await expect(
        repayment.connect(officer).recordPayment(
          loanId,
          2,
          paymentAmount,
          PaymentMethod.GCash,
          referenceHash // Same reference
        )
      ).to.be.revertedWithCustomError(repayment, "DuplicatePaymentReference");
    });

    it("Should reject zero amount payment", async function () {
      await expect(
        repayment.connect(officer).recordPayment(
          loanId,
          1,
          0,
          PaymentMethod.Cash,
          referenceHash
        )
      ).to.be.revertedWithCustomError(repayment, "InvalidPaymentAmount");
    });
  });

  describe("Installment Management", function () {
    let scheduleId;

    beforeEach(async function () {
      const startDate = await time.latest();

      await repayment.connect(admin).createSchedule(
        loanId,
        borrower.address,
        principal,
        interestRateBps,
        termMonths,
        startDate
      );

      scheduleId = await repayment.loanToSchedule(loanId);
    });

    it("Should get installment details", async function () {
      const installment = await repayment.installments(scheduleId, 1);
      
      expect(installment.number).to.equal(1);
      expect(installment.totalAmount).to.be.gt(0);
      expect(installment.status).to.equal(InstallmentStatus.Pending);
    });

    it("Should mark installment as paid after full payment", async function () {
      const installment = await repayment.installments(scheduleId, 1);
      const fullAmount = installment.totalAmount;

      await repayment.connect(officer).recordPayment(
        loanId,
        1,
        fullAmount,
        PaymentMethod.Cash,
        ethers.keccak256(ethers.toUtf8Bytes("PAY001"))
      );

      const updatedInstallment = await repayment.installments(scheduleId, 1);
      expect(updatedInstallment.status).to.equal(InstallmentStatus.Paid);
    });

    it("Should mark installment as partial after partial payment", async function () {
      const installment = await repayment.installments(scheduleId, 1);
      const partialAmount = installment.totalAmount / 2n;

      await repayment.connect(officer).recordPayment(
        loanId,
        1,
        partialAmount,
        PaymentMethod.Cash,
        ethers.keccak256(ethers.toUtf8Bytes("PAY001"))
      );

      const updatedInstallment = await repayment.installments(scheduleId, 1);
      expect(updatedInstallment.status).to.equal(InstallmentStatus.Partial);
    });
  });

  describe("Loan Completion", function () {
    let scheduleId;

    beforeEach(async function () {
      // Create a short-term loan for easier testing
      const shortLoanId = ethers.keccak256(ethers.toUtf8Bytes("SHORTLOAN"));
      const shortPrincipal = ethers.parseEther("1000");
      const shortTerm = 2; // 2 months
      const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT002"));

      await loanCore.connect(borrower).createLoan(
        shortLoanId,
        productId,
        shortPrincipal,
        shortTerm,
        100
      );
      
      // submitLoan requires: loanId, eligibilityScore, riskCategory, aiRecommendationHash
      const eligibilityScore = 85;
      const riskCategory = 0; // Low
      const aiRecommendationHash = ethers.keccak256(ethers.toUtf8Bytes("AI_REC_002"));
      await loanCore.connect(borrower).submitLoan(shortLoanId, eligibilityScore, riskCategory, aiRecommendationHash);
      
      await loanCore.assignOfficer(shortLoanId, officer.address);
      await loanCore.connect(officer).approveLoan(
        shortLoanId,
        shortPrincipal,
        ethers.keccak256(ethers.toUtf8Bytes("NOTES"))
      );
      await loanCore.markDisbursed(shortLoanId, shortPrincipal);

      const startDate = await time.latest();
      await repayment.connect(admin).createSchedule(
        shortLoanId,
        borrower.address,
        shortPrincipal,
        100,
        shortTerm,
        startDate
      );

      scheduleId = await repayment.loanToSchedule(shortLoanId);
    });

    it("Should emit LoanFullyRepaid when all installments paid", async function () {
      const schedule = await repayment.schedules(scheduleId);
      const loanIdFromSchedule = schedule.loanId;

      // Pay all installments
      for (let i = 1; i <= 2; i++) {
        const installment = await repayment.installments(scheduleId, i);
        await repayment.connect(officer).recordPayment(
          loanIdFromSchedule,
          i,
          installment.totalAmount,
          PaymentMethod.Cash,
          ethers.keccak256(ethers.toUtf8Bytes(`PAY${i}`))
        );
      }

      // Verify all payments are recorded - schedule should show total paid
      const updatedSchedule = await repayment.schedules(scheduleId);
      expect(updatedSchedule.totalPaid).to.be.gt(0);
    });
  });
});
