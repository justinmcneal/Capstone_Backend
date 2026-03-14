// Test suite for RepaymentSchedule contract
// Task 3.1 — Schedule generation and structure
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("RepaymentSchedule", function () {
  let repaymentSchedule;
  let loanCore;
  let auditRegistry;
  let accessControl;
  let admin, officer, borrower, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

  const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN_SCHED_001"));
  const principal = ethers.parseEther("12000");    // 12 000 tokens
  const interestRateBps = 150;                      // 1.5% monthly
  const termMonths = 12;

  const SECONDS_PER_DAY = 86400n;
  const DAYS_PER_MONTH = 30n;

  // InstallmentStatus enum
  const InstallmentStatus = {
    Pending: 0,
    Paid: 1,
    Partial: 2,
    Overdue: 3,
  };

  /**
   * Helper: deploy all dependencies and put a single loan into Disbursed state.
   */
  beforeEach(async function () {
    [admin, officer, borrower, other] = await ethers.getSigners();

    // ── AuditRegistry ──
    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    auditRegistry = await upgrades.deployProxy(AuditRegistry, [admin.address], { kind: "uups" });
    await auditRegistry.waitForDeployment();

    // ── LoanAccessControl ──
    const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
    accessControl = await upgrades.deployProxy(LoanAccessControl, [admin.address], { kind: "uups" });
    await accessControl.waitForDeployment();

    // ── LoanCore ──
    const LoanCore = await ethers.getContractFactory("LoanCore");
    loanCore = await upgrades.deployProxy(
      LoanCore,
      [await accessControl.getAddress(), await auditRegistry.getAddress(), admin.address],
      { kind: "uups" }
    );
    await loanCore.waitForDeployment();

    // ── RepaymentSchedule ──
    const RepaymentSchedule = await ethers.getContractFactory("RepaymentSchedule");
    repaymentSchedule = await upgrades.deployProxy(
      RepaymentSchedule,
      [await loanCore.getAddress(), admin.address],
      { kind: "uups" }
    );
    await repaymentSchedule.waitForDeployment();

    // ── Permissions ──
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());
    await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address);

    // Grant roles on RepaymentSchedule
    await repaymentSchedule.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await repaymentSchedule.grantRole(SYSTEM_ROLE, admin.address);

    // Register borrower & officer in access control
    await accessControl.grantRole(SYSTEM_ROLE, admin.address);
    await accessControl.registerBorrower(
      borrower.address,
      ethers.keccak256(ethers.toUtf8Bytes("CUST_SCHED"))
    );
    await accessControl.registerOfficer(
      officer.address,
      ethers.keccak256(ethers.toUtf8Bytes("EMP_SCHED"))
    );

    // Create ➜ Submit ➜ Assign ➜ Approve ➜ Disburse
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD_SCHED"));
    await loanCore.connect(borrower).createLoan(loanId, productId, principal, termMonths, interestRateBps);
    await loanCore.connect(borrower).submitLoan(
      loanId,
      85,
      0, // Low risk
      ethers.keccak256(ethers.toUtf8Bytes("AI_REC_SCHED"))
    );
    await loanCore.assignOfficer(loanId, officer.address);
    await loanCore.connect(officer).approveLoan(
      loanId,
      principal,
      ethers.keccak256(ethers.toUtf8Bytes("NOTES_SCHED"))
    );
    await loanCore.markDisbursed(loanId, principal);
  });

  // ================================================================
  // Deployment
  // ================================================================
  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await repaymentSchedule.VERSION()).to.equal(1);
    });

    it("Should set loanCore address", async function () {
      expect(await repaymentSchedule.loanCore()).to.equal(await loanCore.getAddress());
    });

    it("Should grant admin roles to deployer", async function () {
      expect(await repaymentSchedule.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
    });

    it("Should revert initialize with zero loanCore", async function () {
      const RepaymentSchedule = await ethers.getContractFactory("RepaymentSchedule");
      await expect(
        upgrades.deployProxy(RepaymentSchedule, [ethers.ZeroAddress, admin.address], { kind: "uups" })
      ).to.be.revertedWithCustomError(RepaymentSchedule, "ZeroAddress");
    });

    it("Should revert initialize with zero admin", async function () {
      const RepaymentSchedule = await ethers.getContractFactory("RepaymentSchedule");
      await expect(
        upgrades.deployProxy(
          RepaymentSchedule,
          [await loanCore.getAddress(), ethers.ZeroAddress],
          { kind: "uups" }
        )
      ).to.be.revertedWithCustomError(RepaymentSchedule, "ZeroAddress");
    });
  });

  // ================================================================
  // Schedule Creation
  // ================================================================
  describe("Schedule Creation", function () {
    it("Should create schedule and emit ScheduleCreated", async function () {
      const startDate = await time.latest();
      await expect(
        repaymentSchedule
          .connect(admin)
          .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate)
      ).to.emit(repaymentSchedule, "ScheduleCreated");
    });

    it("Should store correct schedule fields", async function () {
      const startDate = await time.latest();
      const tx = await repaymentSchedule
        .connect(admin)
        .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate);
      await tx.wait();

      const sched = await repaymentSchedule.getSchedule(loanId);
      expect(sched.loanId).to.equal(loanId);
      expect(sched.borrower).to.equal(borrower.address);
      expect(sched.principal).to.equal(principal);
      expect(sched.interestRateBps).to.equal(interestRateBps);
      expect(sched.termMonths).to.equal(termMonths);
      expect(sched.totalPaid).to.equal(0);
    });

    it("Should calculate total amount = principal + (principal × rate × term)", async function () {
      const startDate = await time.latest();
      await repaymentSchedule
        .connect(admin)
        .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate);

      const sched = await repaymentSchedule.getSchedule(loanId);

      // monthlyInterest = principal * 150 / 10000 = 12000e18 * 150 / 10000 = 180e18
      // totalInterest   = 180e18 * 12 = 2160e18
      // totalAmount     = 12000e18 + 2160e18 = 14160e18
      const expectedMonthlyInterest = (principal * BigInt(interestRateBps)) / 10_000n;
      const expectedTotalInterest = expectedMonthlyInterest * BigInt(termMonths);
      const expectedTotal = principal + expectedTotalInterest;

      expect(sched.totalAmount).to.equal(expectedTotal);
      expect(sched.totalInterest).to.equal(expectedTotalInterest);
    });

    it("Should calculate correct monthly payment", async function () {
      const startDate = await time.latest();
      await repaymentSchedule
        .connect(admin)
        .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate);

      const sched = await repaymentSchedule.getSchedule(loanId);

      const monthlyPrincipal = principal / BigInt(termMonths);
      const monthlyInterest = (principal * BigInt(interestRateBps)) / 10_000n;
      const expectedMonthly = monthlyPrincipal + monthlyInterest;

      expect(sched.monthlyPayment).to.equal(expectedMonthly);
    });

    it("Should reject duplicate schedule (once per loan)", async function () {
      const startDate = await time.latest();
      await repaymentSchedule
        .connect(admin)
        .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate);

      await expect(
        repaymentSchedule
          .connect(admin)
          .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate)
      ).to.be.revertedWithCustomError(repaymentSchedule, "ScheduleAlreadyExists");
    });

    it("Should reject when loan is not Disbursed", async function () {
      // Create a new loan that stays in Approved (not disbursed)
      const newLoanId = ethers.keccak256(ethers.toUtf8Bytes("NOT_DISBURSED"));
      const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD2"));
      await loanCore.connect(borrower).createLoan(newLoanId, productId, principal, termMonths, interestRateBps);
      await loanCore.connect(borrower).submitLoan(
        newLoanId, 80, 0, ethers.keccak256(ethers.toUtf8Bytes("AI2"))
      );
      await loanCore.assignOfficer(newLoanId, officer.address);
      await loanCore.connect(officer).approveLoan(
        newLoanId, principal, ethers.keccak256(ethers.toUtf8Bytes("N2"))
      );
      // NOT calling markDisbursed

      const startDate = await time.latest();
      await expect(
        repaymentSchedule
          .connect(admin)
          .createSchedule(newLoanId, borrower.address, principal, interestRateBps, termMonths, startDate)
      ).to.be.revertedWithCustomError(repaymentSchedule, "LoanNotDisbursed");
    });

    it("Should reject zero principal", async function () {
      const startDate = await time.latest();
      await expect(
        repaymentSchedule
          .connect(admin)
          .createSchedule(loanId, borrower.address, 0, interestRateBps, termMonths, startDate)
      ).to.be.revertedWithCustomError(repaymentSchedule, "InvalidPrincipal");
    });

    it("Should reject zero term", async function () {
      const startDate = await time.latest();
      await expect(
        repaymentSchedule
          .connect(admin)
          .createSchedule(loanId, borrower.address, principal, interestRateBps, 0, startDate)
      ).to.be.revertedWithCustomError(repaymentSchedule, "InvalidTerm");
    });

    it("Should reject term > 360", async function () {
      const startDate = await time.latest();
      await expect(
        repaymentSchedule
          .connect(admin)
          .createSchedule(loanId, borrower.address, principal, interestRateBps, 361, startDate)
      ).to.be.revertedWithCustomError(repaymentSchedule, "InvalidTerm");
    });

    it("Should reject unauthorized caller", async function () {
      const startDate = await time.latest();
      await expect(
        repaymentSchedule
          .connect(other)
          .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate)
      ).to.be.revertedWithCustomError(repaymentSchedule, "NotAuthorized");
    });

    it("Should allow LOAN_OFFICER_ROLE to create schedule", async function () {
      const startDate = await time.latest();
      await expect(
        repaymentSchedule
          .connect(officer)
          .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate)
      ).to.emit(repaymentSchedule, "ScheduleCreated");
    });

    it("Should revert when contract is paused", async function () {
      await repaymentSchedule.connect(admin).pause();
      const startDate = await time.latest();
      await expect(
        repaymentSchedule
          .connect(admin)
          .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate)
      ).to.be.revertedWithCustomError(repaymentSchedule, "EnforcedPause");
    });
  });

  // ================================================================
  // Installment Generation
  // ================================================================
  describe("Installment Generation", function () {
    let startDate;

    beforeEach(async function () {
      startDate = await time.latest();
      await repaymentSchedule
        .connect(admin)
        .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate);
    });

    it("Should generate correct number of installments", async function () {
      const all = await repaymentSchedule.getAllInstallments(loanId);
      expect(all.length).to.equal(termMonths);
    });

    it("Should set installment due dates 30 days apart", async function () {
      const all = await repaymentSchedule.getAllInstallments(loanId);
      for (let i = 0; i < all.length; i++) {
        const expectedDue = BigInt(startDate) + BigInt(i + 1) * DAYS_PER_MONTH * SECONDS_PER_DAY;
        expect(all[i].dueDate).to.equal(expectedDue);
      }
    });

    it("Should set all installments to Pending", async function () {
      const all = await repaymentSchedule.getAllInstallments(loanId);
      for (const inst of all) {
        expect(inst.status).to.equal(InstallmentStatus.Pending);
      }
    });

    it("Should set correct per-installment amounts", async function () {
      const sched = await repaymentSchedule.getSchedule(loanId);
      const inst = await repaymentSchedule.getInstallment(loanId, 1);

      expect(inst.totalAmount).to.equal(sched.monthlyPayment);
      expect(inst.principalAmount + inst.interestAmount).to.equal(inst.totalAmount);
    });

    it("Should set paidAmount = 0 and paidAt = 0 for all installments", async function () {
      const all = await repaymentSchedule.getAllInstallments(loanId);
      for (const inst of all) {
        expect(inst.paidAmount).to.equal(0);
        expect(inst.paidAt).to.equal(0);
      }
    });

    it("Should number installments 1 through termMonths", async function () {
      const all = await repaymentSchedule.getAllInstallments(loanId);
      for (let i = 0; i < all.length; i++) {
        expect(all[i].number).to.equal(i + 1);
      }
    });
  });

  // ================================================================
  // View Functions
  // ================================================================
  describe("View Functions", function () {
    let startDate;

    beforeEach(async function () {
      startDate = await time.latest();
      await repaymentSchedule
        .connect(admin)
        .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate);
    });

    describe("getSchedule", function () {
      it("Should return correct schedule", async function () {
        const sched = await repaymentSchedule.getSchedule(loanId);
        expect(sched.loanId).to.equal(loanId);
        expect(sched.borrower).to.equal(borrower.address);
      });

      it("Should revert for non-existent loan", async function () {
        const fakeLoanId = ethers.keccak256(ethers.toUtf8Bytes("FAKE"));
        await expect(
          repaymentSchedule.getSchedule(fakeLoanId)
        ).to.be.revertedWithCustomError(repaymentSchedule, "ScheduleNotFound");
      });
    });

    describe("getInstallment", function () {
      it("Should return correct installment by number", async function () {
        const inst = await repaymentSchedule.getInstallment(loanId, 6);
        expect(inst.number).to.equal(6);
      });

      it("Should revert for out-of-range installment number", async function () {
        await expect(
          repaymentSchedule.getInstallment(loanId, 13) // termMonths is 12
        ).to.be.revertedWithCustomError(repaymentSchedule, "InstallmentNotFound");
      });

      it("Should revert for installment 0", async function () {
        await expect(
          repaymentSchedule.getInstallment(loanId, 0)
        ).to.be.revertedWithCustomError(repaymentSchedule, "InstallmentNotFound");
      });
    });

    describe("getAllInstallments", function () {
      it("Should return all installments in order", async function () {
        const all = await repaymentSchedule.getAllInstallments(loanId);
        expect(all.length).to.equal(termMonths);
        for (let i = 0; i < all.length; i++) {
          expect(all[i].number).to.equal(i + 1);
        }
      });
    });

    describe("getRemainingBalance", function () {
      it("Should return totalAmount when nothing is paid", async function () {
        const sched = await repaymentSchedule.getSchedule(loanId);
        const remaining = await repaymentSchedule.getRemainingBalance(loanId);
        expect(remaining).to.equal(sched.totalAmount);
      });

      it("Should revert for non-existent schedule", async function () {
        const fakeLoanId = ethers.keccak256(ethers.toUtf8Bytes("FAKE2"));
        await expect(
          repaymentSchedule.getRemainingBalance(fakeLoanId)
        ).to.be.revertedWithCustomError(repaymentSchedule, "ScheduleNotFound");
      });
    });
  });

  // ================================================================
  // Math Validation
  // ================================================================
  describe("Math Validation", function () {
    it("Should handle small principal correctly", async function () {
      // Use a new loan with small principal
      const smallLoanId = ethers.keccak256(ethers.toUtf8Bytes("SMALL_LOAN"));
      const smallPrincipal = ethers.parseEther("100"); // 100 tokens
      const smallTerm = 2;
      const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD_SMALL"));

      await loanCore.connect(borrower).createLoan(smallLoanId, productId, smallPrincipal, smallTerm, 100);
      await loanCore.connect(borrower).submitLoan(
        smallLoanId, 85, 0, ethers.keccak256(ethers.toUtf8Bytes("AI_SMALL"))
      );
      await loanCore.assignOfficer(smallLoanId, officer.address);
      await loanCore.connect(officer).approveLoan(
        smallLoanId, smallPrincipal, ethers.keccak256(ethers.toUtf8Bytes("N_SMALL"))
      );
      await loanCore.markDisbursed(smallLoanId, smallPrincipal);

      const startDate = await time.latest();
      await repaymentSchedule
        .connect(admin)
        .createSchedule(smallLoanId, borrower.address, smallPrincipal, 100, smallTerm, startDate);

      const sched = await repaymentSchedule.getSchedule(smallLoanId);

      // monthlyInterest = 100e18 * 100 / 10000 = 1e18
      // totalInterest   = 1e18 * 2 = 2e18
      // totalAmount     = 100e18 + 2e18 = 102e18
      expect(sched.totalInterest).to.equal(ethers.parseEther("2"));
      expect(sched.totalAmount).to.equal(ethers.parseEther("102"));
    });

    it("Should handle 0% interest (interestRateBps = 0)", async function () {
      const zeroIntLoanId = ethers.keccak256(ethers.toUtf8Bytes("ZERO_INT"));
      const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD_ZERO_INT"));
      const zeroIntPrincipal = ethers.parseEther("6000");
      const zeroTerm = 6;

      await loanCore.connect(borrower).createLoan(zeroIntLoanId, productId, zeroIntPrincipal, zeroTerm, 0);
      await loanCore.connect(borrower).submitLoan(
        zeroIntLoanId, 90, 0, ethers.keccak256(ethers.toUtf8Bytes("AI_ZERO"))
      );
      await loanCore.assignOfficer(zeroIntLoanId, officer.address);
      await loanCore.connect(officer).approveLoan(
        zeroIntLoanId, zeroIntPrincipal, ethers.keccak256(ethers.toUtf8Bytes("N_ZERO"))
      );
      await loanCore.markDisbursed(zeroIntLoanId, zeroIntPrincipal);

      const startDate = await time.latest();
      await repaymentSchedule
        .connect(admin)
        .createSchedule(zeroIntLoanId, borrower.address, zeroIntPrincipal, 0, zeroTerm, startDate);

      const sched = await repaymentSchedule.getSchedule(zeroIntLoanId);
      expect(sched.totalInterest).to.equal(0);
      expect(sched.totalAmount).to.equal(zeroIntPrincipal);
      expect(sched.monthlyPayment).to.equal(zeroIntPrincipal / BigInt(zeroTerm));
    });
  });

  // ================================================================
  // Admin Functions
  // ================================================================
  describe("Admin Functions", function () {
    it("Should allow admin to pause", async function () {
      await repaymentSchedule.connect(admin).pause();
      expect(await repaymentSchedule.paused()).to.be.true;
    });

    it("Should allow admin to unpause", async function () {
      await repaymentSchedule.connect(admin).pause();
      await repaymentSchedule.connect(admin).unpause();
      expect(await repaymentSchedule.paused()).to.be.false;
    });

    it("Should not allow non-admin to pause", async function () {
      await expect(
        repaymentSchedule.connect(other).pause()
      ).to.be.reverted;
    });

    it("Should allow admin to setLoanCore", async function () {
      const newAddr = ethers.Wallet.createRandom().address;
      await repaymentSchedule.connect(admin).setLoanCore(newAddr);
      expect(await repaymentSchedule.loanCore()).to.equal(newAddr);
    });

    it("Should revert setLoanCore with zero address", async function () {
      await expect(
        repaymentSchedule.connect(admin).setLoanCore(ethers.ZeroAddress)
      ).to.be.revertedWithCustomError(repaymentSchedule, "ZeroAddress");
    });
  });
});
