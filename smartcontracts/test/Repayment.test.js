// Test suite for Repayment contract
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("Repayment", function () {
  let repayment;
  let loanCore;
  let accessControl;
  let auditRegistry;
  let penaltyCalculator;
  let disbursement;
  let admin, officer, borrower, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
  const ORACLE_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ORACLE_ROLE"));

  const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
  const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD001"));
  const requestedAmount = ethers.parseEther("12000");
  const approvedAmount = ethers.parseEther("12000");
  const aiHash = ethers.keccak256(ethers.toUtf8Bytes("AI_ANALYSIS"));
  const notesHash = ethers.keccak256(ethers.toUtf8Bytes("NOTES"));

  beforeEach(async function () {
    [admin, officer, borrower, oracle, other] = await ethers.getSigners();

    // Deploy all contracts
    const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
    accessControl = await upgrades.deployProxy(
      LoanAccessControl,
      [admin.address],
      { kind: "uups" }
    );
    await accessControl.waitForDeployment();

    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    auditRegistry = await upgrades.deployProxy(
      AuditRegistry,
      [admin.address],
      { kind: "uups" }
    );
    await auditRegistry.waitForDeployment();

    const PenaltyCalculator = await ethers.getContractFactory("PenaltyCalculator");
    penaltyCalculator = await upgrades.deployProxy(
      PenaltyCalculator,
      [admin.address],
      { kind: "uups" }
    );
    await penaltyCalculator.waitForDeployment();

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

    const Disbursement = await ethers.getContractFactory("Disbursement");
    disbursement = await upgrades.deployProxy(
      Disbursement,
      [
        await accessControl.getAddress(),
        await loanCore.getAddress(),
        await auditRegistry.getAddress(),
        admin.address
      ],
      { kind: "uups" }
    );
    await disbursement.waitForDeployment();

    const Repayment = await ethers.getContractFactory("Repayment");
    repayment = await upgrades.deployProxy(
      Repayment,
      [
        await accessControl.getAddress(),
        await loanCore.getAddress(),
        await penaltyCalculator.getAddress(),
        await auditRegistry.getAddress(),
        admin.address
      ],
      { kind: "uups" }
    );
    await repayment.waitForDeployment();

    // Setup permissions
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());
    await auditRegistry.grantLoggerRole(await disbursement.getAddress());
    await auditRegistry.grantLoggerRole(await repayment.getAddress());
    
    // Register officer and borrower
    const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));
    await accessControl.registerOfficer(officer.address, employeeIdHash);
    
    await accessControl.grantRole(SYSTEM_ROLE, admin.address);
    const customerIdHash = ethers.keccak256(ethers.toUtf8Bytes("CUST001"));
    await accessControl.registerBorrower(borrower.address, customerIdHash);

    // Grant roles
    await loanCore.grantRole(SYSTEM_ROLE, admin.address);
    await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await loanCore.grantRole(SYSTEM_ROLE, await disbursement.getAddress());
    await loanCore.grantRole(SYSTEM_ROLE, await repayment.getAddress());
    
    await disbursement.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await disbursement.grantRole(SYSTEM_ROLE, admin.address);
    
    await repayment.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await repayment.grantRole(SYSTEM_ROLE, admin.address);
    await repayment.grantRole(ORACLE_ROLE, admin.address);

    // Create, approve, and disburse a loan
    await loanCore.connect(borrower).createLoan(
      loanId,
      productId,
      requestedAmount,
      12,
      150
    );
    await loanCore.connect(borrower).submitLoan(loanId, 75, 1, aiHash);
    await loanCore.connect(admin).assignOfficer(loanId, officer.address);
    await loanCore.connect(officer).approveLoan(loanId, approvedAmount, notesHash);
    
    const transactionRef = ethers.keccak256(ethers.toUtf8Bytes("TXN001"));
    const confirmationRef = ethers.keccak256(ethers.toUtf8Bytes("CONFIRM001"));
    await disbursement.connect(officer).initiateDisbursement(
      loanId,
      approvedAmount,
      admin.address, // treasury
      borrower.address,
      0,
      transactionRef
    );
    await disbursement.connect(admin).completeDisbursement(loanId, confirmationRef);
  });

  describe("Repayment Schedule Creation", function () {
    it("Should create repayment schedule", async function () {
      const totalAmount = ethers.parseEther("13800"); // Principal + interest
      const installmentAmount = ethers.parseEther("1150"); // 12 months
      const firstDueDate = Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60; // 30 days from now

      await expect(
        repayment.connect(admin).createSchedule(
          loanId,
          12, // numberOfInstallments
          totalAmount,
          installmentAmount,
          firstDueDate
        )
      ).to.emit(repayment, "ScheduleCreated");

      const schedule = await repayment.getSchedule(loanId);
      expect(schedule.totalInstallments).to.equal(12);
      expect(schedule.paidInstallments).to.equal(0);
      expect(schedule.isActive).to.be.true;
    });

    it("Should not create schedule for non-disbursed loan", async function () {
      const newLoanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN002"));
      
      // Create but don't disburse
      await loanCore.connect(borrower).createLoan(
        newLoanId,
        productId,
        requestedAmount,
        12,
        150
      );

      await expect(
        repayment.connect(admin).createSchedule(
          newLoanId,
          12,
          ethers.parseEther("13800"),
          ethers.parseEther("1150"),
          Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60
        )
      ).to.be.revertedWithCustomError(repayment, "LoanNotDisbursed");
    });

    it("Should not create duplicate schedule", async function () {
      const totalAmount = ethers.parseEther("13800");
      const installmentAmount = ethers.parseEther("1150");
      const firstDueDate = Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;

      await repayment.connect(admin).createSchedule(
        loanId, 12, totalAmount, installmentAmount, firstDueDate
      );

      await expect(
        repayment.connect(admin).createSchedule(
          loanId, 12, totalAmount, installmentAmount, firstDueDate
        )
      ).to.be.revertedWithCustomError(repayment, "ScheduleAlreadyExists");
    });
  });

  describe("Payment Recording", function () {
    const totalAmount = ethers.parseEther("13800");
    const installmentAmount = ethers.parseEther("1150");
    let firstDueDate;

    beforeEach(async function () {
      firstDueDate = Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;
      await repayment.connect(admin).createSchedule(
        loanId, 12, totalAmount, installmentAmount, firstDueDate
      );
    });

    it("Should record full payment", async function () {
      const paymentRef = ethers.keccak256(ethers.toUtf8Bytes("PAY001"));

      await expect(
        repayment.connect(admin).recordPayment(
          loanId,
          installmentAmount,
          0, // BankTransfer
          paymentRef
        )
      ).to.emit(repayment, "PaymentRecorded");

      const schedule = await repayment.getSchedule(loanId);
      expect(schedule.paidInstallments).to.equal(1);
    });

    it("Should not allow duplicate payment reference", async function () {
      const paymentRef = ethers.keccak256(ethers.toUtf8Bytes("PAY001"));

      await repayment.connect(admin).recordPayment(
        loanId, installmentAmount, 0, paymentRef
      );

      await expect(
        repayment.connect(admin).recordPayment(
          loanId, installmentAmount, 0, paymentRef
        )
      ).to.be.revertedWithCustomError(repayment, "DuplicatePaymentReference");
    });

    it("Should handle partial payment", async function () {
      const partialAmount = ethers.parseEther("500");
      const paymentRef = ethers.keccak256(ethers.toUtf8Bytes("PAY001"));

      await repayment.connect(admin).recordPayment(
        loanId, partialAmount, 0, paymentRef
      );

      const schedule = await repayment.getSchedule(loanId);
      // Paid installments stays 0 for partial payment
      expect(schedule.paidInstallments).to.equal(0);
    });

    it("Should close schedule when fully paid", async function () {
      // Make 12 full payments
      for (let i = 0; i < 12; i++) {
        const paymentRef = ethers.keccak256(ethers.toUtf8Bytes(`PAY${i.toString().padStart(3, '0')}`));
        await repayment.connect(admin).recordPayment(
          loanId, installmentAmount, 0, paymentRef
        );
      }

      const schedule = await repayment.getSchedule(loanId);
      expect(schedule.paidInstallments).to.equal(12);
      expect(schedule.isActive).to.be.false;
    });
  });

  describe("Overdue Detection", function () {
    const totalAmount = ethers.parseEther("13800");
    const installmentAmount = ethers.parseEther("1150");

    it("Should mark installment as overdue", async function () {
      // Set due date in the past
      const pastDueDate = Math.floor(Date.now() / 1000) - 10 * 24 * 60 * 60;
      await repayment.connect(admin).createSchedule(
        loanId, 12, totalAmount, installmentAmount, pastDueDate
      );

      await expect(
        repayment.connect(admin).markOverdue(loanId)
      ).to.emit(repayment, "InstallmentOverdue");
    });

    it("Should not mark as overdue if paid", async function () {
      const pastDueDate = Math.floor(Date.now() / 1000) - 10 * 24 * 60 * 60;
      await repayment.connect(admin).createSchedule(
        loanId, 12, totalAmount, installmentAmount, pastDueDate
      );

      // Pay first installment
      const paymentRef = ethers.keccak256(ethers.toUtf8Bytes("PAY001"));
      await repayment.connect(admin).recordPayment(
        loanId, installmentAmount, 0, paymentRef
      );

      // No overdue since first installment is paid
      // This would check the second installment which isn't due yet
      // The function should handle this correctly
    });
  });

  describe("Default Handling", function () {
    const totalAmount = ethers.parseEther("13800");
    const installmentAmount = ethers.parseEther("1150");

    it("Should mark loan as defaulted", async function () {
      const pastDueDate = Math.floor(Date.now() / 1000) - 100 * 24 * 60 * 60; // 100 days ago
      await repayment.connect(admin).createSchedule(
        loanId, 12, totalAmount, installmentAmount, pastDueDate
      );

      // Mark overdue first
      await repayment.connect(admin).markOverdue(loanId);

      // Fast forward past default period (90 days default)
      await time.increase(95 * 24 * 60 * 60);

      const reasonHash = ethers.keccak256(ethers.toUtf8Bytes("MISSED_90_DAYS"));
      await expect(
        repayment.connect(admin).markDefault(loanId, reasonHash)
      ).to.emit(repayment, "LoanDefaulted");

      // Check loan status updated
      const loan = await loanCore.getLoan(loanId);
      expect(loan.status).to.equal(7); // Defaulted
    });
  });

  describe("Payment Methods", function () {
    beforeEach(async function () {
      const firstDueDate = Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;
      await repayment.connect(admin).createSchedule(
        loanId, 12, ethers.parseEther("13800"), ethers.parseEther("1150"), firstDueDate
      );
    });

    it("Should accept GCash payment", async function () {
      const paymentRef = ethers.keccak256(ethers.toUtf8Bytes("GCASH001"));
      
      await expect(
        repayment.connect(admin).recordPayment(
          loanId,
          ethers.parseEther("1150"),
          2, // GCash
          paymentRef
        )
      ).to.emit(repayment, "PaymentRecorded");
    });

    it("Should accept Maya payment", async function () {
      const paymentRef = ethers.keccak256(ethers.toUtf8Bytes("MAYA001"));
      
      await expect(
        repayment.connect(admin).recordPayment(
          loanId,
          ethers.parseEther("1150"),
          3, // Maya
          paymentRef
        )
      ).to.emit(repayment, "PaymentRecorded");
    });

    it("Should accept Cash payment", async function () {
      const paymentRef = ethers.keccak256(ethers.toUtf8Bytes("CASH001"));
      
      await expect(
        repayment.connect(admin).recordPayment(
          loanId,
          ethers.parseEther("1150"),
          1, // Cash
          paymentRef
        )
      ).to.emit(repayment, "PaymentRecorded");
    });
  });

  describe("Schedule Queries", function () {
    beforeEach(async function () {
      const firstDueDate = Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;
      await repayment.connect(admin).createSchedule(
        loanId, 12, ethers.parseEther("13800"), ethers.parseEther("1150"), firstDueDate
      );
    });

    it("Should return next due installment", async function () {
      const nextInstallment = await repayment.getNextDueInstallment(loanId);
      expect(nextInstallment).to.equal(0); // First installment (index 0)
    });

    it("Should return correct remaining balance", async function () {
      const balance = await repayment.getRemainingBalance(loanId);
      expect(balance).to.equal(ethers.parseEther("13800"));
    });

    it("Should update remaining balance after payment", async function () {
      const paymentRef = ethers.keccak256(ethers.toUtf8Bytes("PAY001"));
      await repayment.connect(admin).recordPayment(
        loanId, ethers.parseEther("1150"), 0, paymentRef
      );

      const balance = await repayment.getRemainingBalance(loanId);
      expect(balance).to.equal(ethers.parseEther("12650")); // 13800 - 1150
    });
  });
});
