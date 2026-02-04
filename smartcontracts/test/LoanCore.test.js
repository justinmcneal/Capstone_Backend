// Test suite for LoanCore contract
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

describe("LoanCore", function () {
  let loanCore;
  let accessControl;
  let auditRegistry;
  let admin, officer, borrower, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const BORROWER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("BORROWER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

  beforeEach(async function () {
    [admin, officer, borrower, other] = await ethers.getSigners();

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

    // Grant logger role to LoanCore
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());

    // Register officer
    const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));
    await accessControl.registerOfficer(officer.address, employeeIdHash);

    // Register borrower - need to grant SYSTEM_ROLE first
    await accessControl.grantRole(SYSTEM_ROLE, admin.address);
    const customerIdHash = ethers.keccak256(ethers.toUtf8Bytes("CUST001"));
    await accessControl.registerBorrower(borrower.address, customerIdHash);

    // Grant SYSTEM_ROLE to admin for loan creation on behalf of borrower
    await loanCore.grantRole(SYSTEM_ROLE, admin.address);
  });

  describe("Deployment", function () {
    it("Should set the correct version", async function () {
      expect(await loanCore.VERSION()).to.equal(1);
    });

    it("Should set admin roles correctly", async function () {
      expect(await loanCore.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
    });
  });

  describe("Loan Creation", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD001"));
    const requestedAmount = ethers.parseEther("10000"); // 10,000 units
    const termMonths = 12;
    const interestRateBps = 150; // 1.5%

    it("Should create a loan successfully", async function () {
      await expect(
        loanCore.connect(borrower).createLoan(
          loanId,
          productId,
          requestedAmount,
          termMonths,
          interestRateBps
        )
      ).to.emit(loanCore, "LoanCreated");

      const loan = await loanCore.getLoan(loanId);
      expect(loan.borrower).to.equal(borrower.address);
      expect(loan.requestedAmount).to.equal(requestedAmount);
      expect(loan.status).to.equal(0); // Draft
    });

    it("Should not create duplicate loans", async function () {
      await loanCore.connect(borrower).createLoan(
        loanId,
        productId,
        requestedAmount,
        termMonths,
        interestRateBps
      );

      await expect(
        loanCore.connect(borrower).createLoan(
          loanId,
          productId,
          requestedAmount,
          termMonths,
          interestRateBps
        )
      ).to.be.revertedWithCustomError(loanCore, "LoanAlreadyExists");
    });

    it("Should reject zero amount", async function () {
      await expect(
        loanCore.connect(borrower).createLoan(
          loanId,
          productId,
          0,
          termMonths,
          interestRateBps
        )
      ).to.be.revertedWithCustomError(loanCore, "InvalidAmount");
    });
  });

  describe("Loan Submission", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN002"));
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD001"));
    const requestedAmount = ethers.parseEther("10000");
    const aiHash = ethers.keccak256(ethers.toUtf8Bytes("AI_ANALYSIS"));

    beforeEach(async function () {
      await loanCore.connect(borrower).createLoan(
        loanId,
        productId,
        requestedAmount,
        12,
        150
      );
    });

    it("Should submit loan successfully", async function () {
      await expect(
        loanCore.connect(borrower).submitLoan(
          loanId,
          75, // eligibility score
          1,  // Medium risk
          aiHash
        )
      ).to.emit(loanCore, "LoanSubmitted");

      const loan = await loanCore.getLoan(loanId);
      expect(loan.status).to.equal(1); // Submitted
      expect(loan.eligibilityScore).to.equal(75);
    });

    it("Should only allow borrower to submit their loan", async function () {
      await expect(
        loanCore.connect(other).submitLoan(loanId, 75, 1, aiHash)
      ).to.be.revertedWithCustomError(loanCore, "UnauthorizedBorrower");
    });
  });

  describe("Officer Assignment", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN003"));
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD001"));
    const aiHash = ethers.keccak256(ethers.toUtf8Bytes("AI_ANALYSIS"));

    beforeEach(async function () {
      await loanCore.connect(borrower).createLoan(
        loanId,
        productId,
        ethers.parseEther("10000"),
        12,
        150
      );
      await loanCore.connect(borrower).submitLoan(loanId, 75, 1, aiHash);
    });

    it("Should assign officer successfully", async function () {
      await expect(
        loanCore.connect(admin).assignOfficer(loanId, officer.address)
      ).to.emit(loanCore, "LoanAssigned");

      const loan = await loanCore.getLoan(loanId);
      expect(loan.assignedOfficer).to.equal(officer.address);
      expect(loan.status).to.equal(2); // UnderReview
    });

    it("Should not allow non-admin to assign", async function () {
      await expect(
        loanCore.connect(other).assignOfficer(loanId, officer.address)
      ).to.be.revertedWith("LoanCore: not authorized to assign");
    });
  });

  describe("Loan Approval/Rejection", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN004"));
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD001"));
    const requestedAmount = ethers.parseEther("10000");
    const aiHash = ethers.keccak256(ethers.toUtf8Bytes("AI_ANALYSIS"));
    const notesHash = ethers.keccak256(ethers.toUtf8Bytes("NOTES"));

    beforeEach(async function () {
      // Grant officer role in LoanCore
      await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address);

      await loanCore.connect(borrower).createLoan(
        loanId,
        productId,
        requestedAmount,
        12,
        150
      );
      await loanCore.connect(borrower).submitLoan(loanId, 75, 1, aiHash);
      await loanCore.connect(admin).assignOfficer(loanId, officer.address);
    });

    it("Should approve loan successfully", async function () {
      const approvedAmount = ethers.parseEther("8000");

      await expect(
        loanCore.connect(officer).approveLoan(loanId, approvedAmount, notesHash)
      ).to.emit(loanCore, "LoanApproved");

      const loan = await loanCore.getLoan(loanId);
      expect(loan.status).to.equal(3); // Approved
      expect(loan.approvedAmount).to.equal(approvedAmount);
    });

    it("Should not approve more than requested", async function () {
      const tooMuch = ethers.parseEther("15000");

      await expect(
        loanCore.connect(officer).approveLoan(loanId, tooMuch, notesHash)
      ).to.be.revertedWith("LoanCore: exceeds requested");
    });

    it("Should reject loan successfully", async function () {
      const reasonHash = ethers.keccak256(ethers.toUtf8Bytes("INSUFFICIENT_INCOME"));

      await expect(
        loanCore.connect(officer).rejectLoan(loanId, reasonHash, notesHash)
      ).to.emit(loanCore, "LoanRejected");

      const loan = await loanCore.getLoan(loanId);
      expect(loan.status).to.equal(4); // Rejected
    });
  });

  describe("Statistics", function () {
    it("Should track loan counts", async function () {
      const stats = await loanCore.getStats();
      expect(stats._totalLoans).to.equal(0);
    });
  });
});
