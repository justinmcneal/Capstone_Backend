// Test suite for Disbursement contract - Aligned with actual contract implementation
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("Disbursement", function () {
  let disbursement;
  let loanCore;
  let auditRegistry;
  let admin, officer, borrower, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

  const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
  const requestedAmount = ethers.parseEther("10000");
  const approvedAmount = ethers.parseEther("8000");

  // DisbursementMethod enum
  const DisbursementMethod = {
    BankTransfer: 0,
    Cash: 1,
    GCash: 2,
    Maya: 3,
    Other: 4
  };

  // DisbursementStatus enum - matches backend (no Failed/Reversed)
  const DisbursementStatus = {
    Pending: 0,
    Processing: 1,
    Completed: 2
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

    // Deploy Disbursement
    const Disbursement = await ethers.getContractFactory("Disbursement");
    disbursement = await upgrades.deployProxy(
      Disbursement,
      [
        await loanCore.getAddress(),
        await auditRegistry.getAddress(),
        admin.address
      ],
      { kind: "uups" }
    );
    await disbursement.waitForDeployment();

    // Setup permissions
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());
    await auditRegistry.grantLoggerRole(await disbursement.getAddress());
    
    // Register Disbursement contract with LoanCore
    await loanCore.setContracts(
      await disbursement.getAddress(),
      other.address, // placeholder non-zero address
      other.address  // placeholder non-zero address
    );
    
    // Grant roles
    await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await loanCore.grantRole(SYSTEM_ROLE, await disbursement.getAddress());
    
    await disbursement.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await disbursement.grantRole(SYSTEM_ROLE, admin.address);

    // Create and approve a loan
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
      requestedAmount,
      12,  // termMonths
      150  // interestRateBps
    );
    
    // submitLoan requires: loanId, eligibilityScore, riskCategory, aiRecommendationHash
    const eligibilityScore = 85;
    const riskCategory = 0; // Low
    const aiRecommendationHash = ethers.keccak256(ethers.toUtf8Bytes("AI_REC_001"));
    await loanCore.connect(borrower).submitLoan(loanId, eligibilityScore, riskCategory, aiRecommendationHash);
    
    await loanCore.assignOfficer(loanId, officer.address);
    await loanCore.connect(officer).approveLoan(
      loanId,
      approvedAmount,
      ethers.keccak256(ethers.toUtf8Bytes("NOTES"))
    );
  });

  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await disbursement.VERSION()).to.equal(1);
    });
  });

  describe("Initiate Disbursement", function () {
    it("Should initiate disbursement successfully", async function () {
      await expect(
        disbursement.connect(officer).initiateDisbursement(
          loanId,
          approvedAmount,
          DisbursementMethod.BankTransfer
        )
      ).to.emit(disbursement, "DisbursementInitiated");
    });

    it("Should return disbursement ID", async function () {
      const tx = await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        DisbursementMethod.BankTransfer
      );
      
      const receipt = await tx.wait();
      const event = receipt.logs.find(
        log => log.fragment && log.fragment.name === "DisbursementInitiated"
      );
      
      expect(event).to.not.be.undefined;
    });

    it("Should not allow disbursement more than approved", async function () {
      const tooMuch = ethers.parseEther("15000");
      
      await expect(
        disbursement.connect(officer).initiateDisbursement(
          loanId,
          tooMuch,
          DisbursementMethod.BankTransfer
        )
      ).to.be.revertedWith("Disbursement: invalid amount");
    });

    it("Should not allow non-authorized to initiate", async function () {
      await expect(
        disbursement.connect(other).initiateDisbursement(
          loanId,
          approvedAmount,
          DisbursementMethod.BankTransfer
        )
      ).to.be.reverted;
    });

    it("Should track total disbursements count", async function () {
      const beforeCount = await disbursement.totalDisbursements();
      
      await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        DisbursementMethod.GCash
      );

      const afterCount = await disbursement.totalDisbursements();
      expect(afterCount).to.equal(beforeCount + 1n);
    });
  });

  describe("Complete Disbursement", function () {
    let disbursementId;
    const referenceHash = ethers.keccak256(ethers.toUtf8Bytes("REF001"));

    beforeEach(async function () {
      const tx = await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        DisbursementMethod.BankTransfer
      );
      
      const receipt = await tx.wait();
      disbursementId = await disbursement.loanToDisbursement(loanId);
    });

    it("Should complete disbursement successfully", async function () {
      await expect(
        disbursement.connect(officer).completeDisbursement(
          disbursementId,
          referenceHash
        )
      ).to.emit(disbursement, "DisbursementCompleted");
    });

    it("Should update loan status to disbursed", async function () {
      await disbursement.connect(officer).completeDisbursement(
        disbursementId,
        referenceHash
      );

      const loanStatus = await loanCore.getLoanStatus(loanId);
      expect(loanStatus).to.equal(5); // Disbursed status (see LoanStatus enum)
    });

    it("Should track total disbursed amount", async function () {
      await disbursement.connect(officer).completeDisbursement(
        disbursementId,
        referenceHash
      );

      const totalDisbursed = await disbursement.totalDisbursedAmount();
      expect(totalDisbursed).to.equal(approvedAmount);
    });

    it("Should not allow duplicate reference", async function () {
      await disbursement.connect(officer).completeDisbursement(
        disbursementId,
        referenceHash
      );

      // Create another loan and try to use same reference
      const loanId2 = ethers.keccak256(ethers.toUtf8Bytes("LOAN002"));
      const productId2 = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT002"));
      await loanCore.connect(borrower).createLoan(
        loanId2,
        productId2,
        requestedAmount,
        12,
        150
      );
      
      // submitLoan requires: loanId, eligibilityScore, riskCategory, aiRecommendationHash
      const eligibilityScore2 = 80;
      const riskCategory2 = 0; // Low
      const aiRecommendationHash2 = ethers.keccak256(ethers.toUtf8Bytes("AI_REC_002"));
      await loanCore.connect(borrower).submitLoan(loanId2, eligibilityScore2, riskCategory2, aiRecommendationHash2);
      
      await loanCore.assignOfficer(loanId2, officer.address);
      await loanCore.connect(officer).approveLoan(
        loanId2,
        approvedAmount,
        ethers.keccak256(ethers.toUtf8Bytes("NOTES2"))
      );

      await disbursement.connect(officer).initiateDisbursement(
        loanId2,
        approvedAmount,
        DisbursementMethod.BankTransfer
      );

      const disbId2 = await disbursement.loanToDisbursement(loanId2);
      
      await expect(
        disbursement.connect(officer).completeDisbursement(
          disbId2,
          referenceHash // Same reference as before
        )
      ).to.be.revertedWithCustomError(disbursement, "DuplicateReference");
    });

    it("Should require reference hash", async function () {
      await expect(
        disbursement.connect(officer).completeDisbursement(
          disbursementId,
          ethers.ZeroHash
        )
      ).to.be.revertedWith("Disbursement: reference required");
    });
  });

  describe("View Functions", function () {
    let disbursementId;

    beforeEach(async function () {
      await disbursement.connect(officer).initiateDisbursement(
        loanId,
        approvedAmount,
        DisbursementMethod.Maya
      );
      
      disbursementId = await disbursement.loanToDisbursement(loanId);
    });

    it("Should get disbursement by ID", async function () {
      const record = await disbursement.disbursements(disbursementId);
      expect(record.amount).to.equal(approvedAmount);
      expect(record.loanId).to.equal(loanId);
      expect(record.method).to.equal(DisbursementMethod.Maya);
    });

    it("Should get disbursement ID by loan ID", async function () {
      const disbId = await disbursement.loanToDisbursement(loanId);
      expect(disbId).to.equal(disbursementId);
    });
  });
});
