// Test suite for Disbursement contract
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("Disbursement", function () {
  let disbursement;
  let loanCore;
  let accessControl;
  let auditRegistry;
  let admin, officer, borrower, treasury, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

  const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
  const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD001"));
  const requestedAmount = ethers.parseEther("10000");
  const approvedAmount = ethers.parseEther("8000");
  const aiHash = ethers.keccak256(ethers.toUtf8Bytes("AI_ANALYSIS"));
  const notesHash = ethers.keccak256(ethers.toUtf8Bytes("NOTES"));

  beforeEach(async function () {
    [admin, officer, borrower, treasury, other] = await ethers.getSigners();

    // Deploy AccessControl
    const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
    accessControl = await upgrades.deployProxy(
      LoanAccessControl,
      [admin.address],
      { kind: "uups" }
    );
    await accessControl.waitForDeployment();

    // Deploy AuditRegistry
    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    auditRegistry = await upgrades.deployProxy(
      AuditRegistry,
      [admin.address],
      { kind: "uups" }
    );
    await auditRegistry.waitForDeployment();

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

    // Deploy Disbursement
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

    // Setup roles and permissions
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());
    await auditRegistry.grantLoggerRole(await disbursement.getAddress());
    
    // Register officer in AccessControl
    const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));
    await accessControl.registerOfficer(officer.address, employeeIdHash);
    
    // Register borrower
    await accessControl.grantRole(SYSTEM_ROLE, admin.address);
    const customerIdHash = ethers.keccak256(ethers.toUtf8Bytes("CUST001"));
    await accessControl.registerBorrower(borrower.address, customerIdHash);

    // Grant roles in LoanCore
    await loanCore.grantRole(SYSTEM_ROLE, admin.address);
    await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address);
    
    // Grant SYSTEM_ROLE to Disbursement contract so it can update loan status
    await loanCore.grantRole(SYSTEM_ROLE, await disbursement.getAddress());
    
    // Grant roles in Disbursement
    await disbursement.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await disbursement.grantRole(SYSTEM_ROLE, admin.address);

    // Create and approve a loan
    await loanCore.connect(borrower).createLoan(
      loanId,
      productId,
      requestedAmount,
      12, // termMonths
      150 // interestRateBps
    );
    await loanCore.connect(borrower).submitLoan(loanId, 75, 1, aiHash);
    await loanCore.connect(admin).assignOfficer(loanId, officer.address);
    await loanCore.connect(officer).approveLoan(loanId, approvedAmount, notesHash);
  });

  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await disbursement.VERSION()).to.equal(1);
    });

    it("Should set default reversal window", async function () {
      expect(await disbursement.reversalWindowHours()).to.equal(72);
    });
  });

  describe("Initiate Disbursement", function () {
    const transactionRef = ethers.keccak256(ethers.toUtf8Bytes("TXN001"));

    it("Should initiate disbursement successfully", async function () {
      await expect(
        disbursement.connect(officer).initiateDisbursement(
          loanId,
          approvedAmount,
          treasury.address,
          borrower.address,
          0, // BankTransfer method
          transactionRef
        )
      ).to.emit(disbursement, "DisbursementInitiated");

      const disbRecord = await disbursement.getDisbursement(loanId);
      expect(disbRecord.amount).to.equal(approvedAmount);
      expect(disbRecord.status).to.equal(0); // Pending
    });

    it("Should not allow disbursement more than approved", async function () {
      const tooMuch = ethers.parseEther("15000");
      
      await expect(
        disbursement.connect(officer).initiateDisbursement(
          loanId,
          tooMuch,
          treasury.address,
          borrower.address,
          0,
          transactionRef
        )
      ).to.be.revertedWithCustomError(disbursement, "AmountExceedsApproved");
    });

    it("Should not allow non-officer to initiate", async function () {
      await expect(
        disbursement.connect(other).initiateDisbursement(
          loanId,
          approvedAmount,
          treasury.address,
          borrower.address,
          0,
          transactionRef
        )
      ).to.be.reverted;
    });

    it("Should not allow duplicate disbursement", async function () {
      await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        treasury.address,
        borrower.address,
        0,
        transactionRef
      );

      await expect(
        disbursement.connect(officer).initiateDisbursement(
          loanId,
          approvedAmount,
          treasury.address,
          borrower.address,
          0,
          ethers.keccak256(ethers.toUtf8Bytes("TXN002"))
        )
      ).to.be.revertedWithCustomError(disbursement, "DisbursementAlreadyExists");
    });
  });

  describe("Complete Disbursement", function () {
    const transactionRef = ethers.keccak256(ethers.toUtf8Bytes("TXN001"));
    const confirmationRef = ethers.keccak256(ethers.toUtf8Bytes("CONFIRM001"));

    beforeEach(async function () {
      await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        treasury.address,
        borrower.address,
        0,
        transactionRef
      );
    });

    it("Should complete disbursement successfully", async function () {
      await expect(
        disbursement.connect(admin).completeDisbursement(loanId, confirmationRef)
      ).to.emit(disbursement, "DisbursementCompleted");

      const disbRecord = await disbursement.getDisbursement(loanId);
      expect(disbRecord.status).to.equal(1); // Completed
    });

    it("Should update loan status to Disbursed", async function () {
      await disbursement.connect(admin).completeDisbursement(loanId, confirmationRef);
      
      const loan = await loanCore.getLoan(loanId);
      expect(loan.status).to.equal(5); // Disbursed
    });

    it("Should not complete non-pending disbursement", async function () {
      await disbursement.connect(admin).completeDisbursement(loanId, confirmationRef);
      
      await expect(
        disbursement.connect(admin).completeDisbursement(loanId, confirmationRef)
      ).to.be.revertedWithCustomError(disbursement, "InvalidDisbursementStatus");
    });
  });

  describe("Failed Disbursement", function () {
    const transactionRef = ethers.keccak256(ethers.toUtf8Bytes("TXN001"));
    const reasonHash = ethers.keccak256(ethers.toUtf8Bytes("INSUFFICIENT_FUNDS"));

    beforeEach(async function () {
      await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        treasury.address,
        borrower.address,
        0,
        transactionRef
      );
    });

    it("Should mark disbursement as failed", async function () {
      await expect(
        disbursement.connect(admin).failDisbursement(loanId, reasonHash)
      ).to.emit(disbursement, "DisbursementFailed");

      const disbRecord = await disbursement.getDisbursement(loanId);
      expect(disbRecord.status).to.equal(2); // Failed
    });

    it("Should revert loan status to Approved", async function () {
      await disbursement.connect(admin).failDisbursement(loanId, reasonHash);
      
      const loan = await loanCore.getLoan(loanId);
      expect(loan.status).to.equal(3); // Approved (reverted from awaiting disbursement)
    });
  });

  describe("Reversal", function () {
    const transactionRef = ethers.keccak256(ethers.toUtf8Bytes("TXN001"));
    const confirmationRef = ethers.keccak256(ethers.toUtf8Bytes("CONFIRM001"));
    const reversalReason = ethers.keccak256(ethers.toUtf8Bytes("FRAUD_DETECTED"));

    beforeEach(async function () {
      await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        treasury.address,
        borrower.address,
        0,
        transactionRef
      );
      await disbursement.connect(admin).completeDisbursement(loanId, confirmationRef);
    });

    it("Should reverse within reversal window", async function () {
      await expect(
        disbursement.connect(admin).reverseDisbursement(loanId, reversalReason)
      ).to.emit(disbursement, "DisbursementReversed");

      const disbRecord = await disbursement.getDisbursement(loanId);
      expect(disbRecord.status).to.equal(3); // Reversed
    });

    it("Should not reverse after window expires", async function () {
      // Fast forward 73 hours
      await time.increase(73 * 60 * 60);

      await expect(
        disbursement.connect(admin).reverseDisbursement(loanId, reversalReason)
      ).to.be.revertedWithCustomError(disbursement, "ReversalWindowExpired");
    });

    it("Should allow admin to update reversal window", async function () {
      await disbursement.connect(admin).setReversalWindow(48);
      expect(await disbursement.reversalWindowHours()).to.equal(48);
    });
  });

  describe("Disbursement Methods", function () {
    const transactionRef = ethers.keccak256(ethers.toUtf8Bytes("TXN001"));

    it("Should accept GCash method", async function () {
      await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        treasury.address,
        borrower.address,
        2, // GCash
        transactionRef
      );

      const disbRecord = await disbursement.getDisbursement(loanId);
      expect(disbRecord.method).to.equal(2);
    });

    it("Should accept Maya method", async function () {
      await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        treasury.address,
        borrower.address,
        3, // Maya
        transactionRef
      );

      const disbRecord = await disbursement.getDisbursement(loanId);
      expect(disbRecord.method).to.equal(3);
    });

    it("Should accept Cash method", async function () {
      await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        treasury.address,
        borrower.address,
        1, // Cash
        transactionRef
      );

      const disbRecord = await disbursement.getDisbursement(loanId);
      expect(disbRecord.method).to.equal(1);
    });
  });
});
