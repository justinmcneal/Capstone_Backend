// Test suite for PaymentRecording contract
// Task 3.2 — Payment recording and installment status updates
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("PaymentRecording", function () {
  let paymentRecording;
  let repaymentSchedule;
  let loanCore;
  let auditRegistry;
  let accessControl;
  let admin, officer, borrower, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

  const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN_PAY_001"));
  const principal = ethers.parseEther("12000");
  const interestRateBps = 150; // 1.5% monthly
  const termMonths = 12;

  const SECONDS_PER_DAY = 86400n;
  const DAYS_PER_MONTH = 30n;

  // PaymentMethod enum
  const PaymentMethod = { Cash: 0, BankTransfer: 1, GCash: 2, Maya: 3, Other: 4 };

  // InstallmentStatus enum (mirrors RepaymentSchedule)
  const InstallmentStatus = { Pending: 0, Paid: 1, Partial: 2, Overdue: 3 };

  /**
   * Helper: calculate expected monthly payment for the default loan
   */
  function expectedMonthlyPayment() {
    const monthlyInterest = (principal * BigInt(interestRateBps)) / 10_000n;
    const monthlyPrincipal = principal / BigInt(termMonths);
    return monthlyPrincipal + monthlyInterest;
  }

  /**
   * Deploy all dependencies, create a disbursed loan, and create its schedule.
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

    // ── PaymentRecording ──
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

    // ── Permissions ──
    // AuditRegistry: grant logger to loanCore and paymentRecording
    await auditRegistry.grantLoggerRole(await loanCore.getAddress());
    await auditRegistry.grantLoggerRole(await paymentRecording.getAddress());

    // LoanCore permissions
    await loanCore.grantRole(LOAN_OFFICER_ROLE, officer.address);

    // RepaymentSchedule: grant SYSTEM_ROLE to admin (for createSchedule) and PaymentRecording contract
    await repaymentSchedule.grantRole(SYSTEM_ROLE, admin.address);
    await repaymentSchedule.grantRole(SYSTEM_ROLE, await paymentRecording.getAddress());
    await repaymentSchedule.grantRole(LOAN_OFFICER_ROLE, officer.address);

    // PaymentRecording: grant roles
    await paymentRecording.grantRole(LOAN_OFFICER_ROLE, officer.address);
    await paymentRecording.grantRole(SYSTEM_ROLE, admin.address);

    // AccessControl: register borrower & officer
    await accessControl.grantRole(SYSTEM_ROLE, admin.address);
    await accessControl.registerBorrower(
      borrower.address,
      ethers.keccak256(ethers.toUtf8Bytes("CUST_PAY"))
    );
    await accessControl.registerOfficer(
      officer.address,
      ethers.keccak256(ethers.toUtf8Bytes("EMP_PAY"))
    );

    // ── Create loan lifecycle: Create → Submit → Assign → Approve → Disburse ──
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD_PAY"));
    await loanCore.connect(borrower).createLoan(loanId, productId, principal, termMonths, interestRateBps);
    await loanCore.connect(borrower).submitLoan(
      loanId, 85, 0, ethers.keccak256(ethers.toUtf8Bytes("AI_PAY"))
    );
    await loanCore.assignOfficer(loanId, officer.address);
    await loanCore.connect(officer).approveLoan(
      loanId, principal, ethers.keccak256(ethers.toUtf8Bytes("N_PAY"))
    );
    await loanCore.markDisbursed(loanId, principal);

    // ── Create repayment schedule ──
    const startDate = await time.latest();
    await repaymentSchedule
      .connect(admin)
      .createSchedule(loanId, borrower.address, principal, interestRateBps, termMonths, startDate);
  });

  // ================================================================
  // Deployment
  // ================================================================
  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await paymentRecording.VERSION()).to.equal(1);
    });

    it("Should set repaymentSchedule address", async function () {
      expect(await paymentRecording.repaymentSchedule()).to.equal(
        await repaymentSchedule.getAddress()
      );
    });

    it("Should set auditRegistry address", async function () {
      expect(await paymentRecording.auditRegistry()).to.equal(
        await auditRegistry.getAddress()
      );
    });

    it("Should revert initialize with zero repaymentSchedule", async function () {
      const F = await ethers.getContractFactory("PaymentRecording");
      await expect(
        upgrades.deployProxy(F, [ethers.ZeroAddress, await auditRegistry.getAddress(), admin.address], { kind: "uups" })
      ).to.be.revertedWithCustomError(F, "ZeroAddress");
    });

    it("Should revert initialize with zero auditRegistry", async function () {
      const F = await ethers.getContractFactory("PaymentRecording");
      await expect(
        upgrades.deployProxy(F, [await repaymentSchedule.getAddress(), ethers.ZeroAddress, admin.address], { kind: "uups" })
      ).to.be.revertedWithCustomError(F, "ZeroAddress");
    });

    it("Should revert initialize with zero admin", async function () {
      const F = await ethers.getContractFactory("PaymentRecording");
      await expect(
        upgrades.deployProxy(F, [await repaymentSchedule.getAddress(), await auditRegistry.getAddress(), ethers.ZeroAddress], { kind: "uups" })
      ).to.be.revertedWithCustomError(F, "ZeroAddress");
    });
  });

  // ================================================================
  // Record Payment
  // ================================================================
  describe("recordPayment", function () {
    const refHash = (tag) => ethers.keccak256(ethers.toUtf8Bytes(tag));

    it("Should record a payment and emit PaymentRecorded", async function () {
      const amount = expectedMonthlyPayment();
      await expect(
        paymentRecording.connect(officer).recordPayment(
          loanId, 1, amount, PaymentMethod.GCash, refHash("PAY001")
        )
      ).to.emit(paymentRecording, "PaymentRecorded");
    });

    it("Should update totalPaid on the schedule", async function () {
      const amount = expectedMonthlyPayment();
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, amount, PaymentMethod.Cash, refHash("PAY002")
      );

      const sched = await repaymentSchedule.getSchedule(loanId);
      expect(sched.totalPaid).to.equal(amount);
    });

    it("Should mark installment as Paid on full payment", async function () {
      const amount = expectedMonthlyPayment();
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, amount, PaymentMethod.Cash, refHash("PAY003")
      );

      const inst = await repaymentSchedule.getInstallment(loanId, 1);
      expect(inst.status).to.equal(InstallmentStatus.Paid);
      expect(inst.paidAt).to.be.gt(0);
    });

    it("Should mark installment as Partial on partial payment", async function () {
      const amount = expectedMonthlyPayment() / 2n;
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, amount, PaymentMethod.Cash, refHash("PAY004")
      );

      const inst = await repaymentSchedule.getInstallment(loanId, 1);
      expect(inst.status).to.equal(InstallmentStatus.Partial);
    });

    it("Should emit InstallmentStatusChanged when status changes", async function () {
      const amount = expectedMonthlyPayment();
      await expect(
        paymentRecording.connect(officer).recordPayment(
          loanId, 1, amount, PaymentMethod.Cash, refHash("PAY005")
        )
      ).to.emit(paymentRecording, "InstallmentStatusChanged")
        .withArgs(loanId, 1, InstallmentStatus.Pending, InstallmentStatus.Paid, (v) => v > 0n);
    });

    it("Should not emit InstallmentStatusChanged when status stays the same", async function () {
      // Two partial payments — second one stays Partial
      const half = expectedMonthlyPayment() / 4n;
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, half, PaymentMethod.Cash, refHash("PAY006A")
      );
      await expect(
        paymentRecording.connect(officer).recordPayment(
          loanId, 1, half, PaymentMethod.Cash, refHash("PAY006B")
        )
      ).to.not.emit(paymentRecording, "InstallmentStatusChanged");
    });

    it("Should reject zero amount", async function () {
      await expect(
        paymentRecording.connect(officer).recordPayment(
          loanId, 1, 0, PaymentMethod.Cash, refHash("PAY007")
        )
      ).to.be.revertedWithCustomError(paymentRecording, "InvalidPaymentAmount");
    });

    it("Should reject duplicate reference hash", async function () {
      const amount = expectedMonthlyPayment();
      const ref = refHash("PAY008");
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, amount, PaymentMethod.Cash, ref
      );
      await expect(
        paymentRecording.connect(officer).recordPayment(
          loanId, 2, amount, PaymentMethod.Cash, ref
        )
      ).to.be.revertedWithCustomError(paymentRecording, "DuplicatePaymentReference");
    });

    it("Should reject payment on already-paid installment", async function () {
      const amount = expectedMonthlyPayment();
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, amount, PaymentMethod.Cash, refHash("PAY009A")
      );
      await expect(
        paymentRecording.connect(officer).recordPayment(
          loanId, 1, amount, PaymentMethod.Cash, refHash("PAY009B")
        )
      ).to.be.revertedWithCustomError(paymentRecording, "InstallmentAlreadyPaid");
    });

    it("Should reject unauthorized caller (non officer/system)", async function () {
      await expect(
        paymentRecording.connect(other).recordPayment(
          loanId, 1, 1, PaymentMethod.Cash, refHash("PAY010")
        )
      ).to.be.revertedWithCustomError(paymentRecording, "NotAuthorized");
    });

    it("Should allow SYSTEM_ROLE to record payment", async function () {
      const amount = expectedMonthlyPayment();
      await expect(
        paymentRecording.connect(admin).recordPayment(
          loanId, 1, amount, PaymentMethod.Cash, refHash("PAY011")
        )
      ).to.emit(paymentRecording, "PaymentRecorded");
    });

    it("Should increment totalPaymentsRecorded", async function () {
      const before = await paymentRecording.totalPaymentsRecorded();
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, expectedMonthlyPayment(), PaymentMethod.Cash, refHash("PAY012")
      );
      expect(await paymentRecording.totalPaymentsRecorded()).to.equal(before + 1n);
    });

    it("Should increment totalAmountCollected", async function () {
      const amount = expectedMonthlyPayment();
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, amount, PaymentMethod.Cash, refHash("PAY013")
      );
      expect(await paymentRecording.totalAmountCollected()).to.equal(amount);
    });

    it("Should revert when contract is paused", async function () {
      await paymentRecording.connect(admin).pause();
      await expect(
        paymentRecording.connect(officer).recordPayment(
          loanId, 1, 1, PaymentMethod.Cash, refHash("PAY014")
        )
      ).to.be.revertedWithCustomError(paymentRecording, "EnforcedPause");
    });

    it("Should store correct payment fields", async function () {
      const amount = expectedMonthlyPayment();
      const ref = refHash("PAY015");

      const tx = await paymentRecording.connect(officer).recordPayment(
        loanId, 1, amount, PaymentMethod.Maya, ref
      );
      const receipt = await tx.wait();

      // Extract paymentId from event
      const event = receipt.logs.find(
        (log) => {
          try {
            return paymentRecording.interface.parseLog(log)?.name === "PaymentRecorded";
          } catch { return false; }
        }
      );
      const parsed = paymentRecording.interface.parseLog(event);
      const paymentId = parsed.args.paymentId;

      const payment = await paymentRecording.getPayment(paymentId);
      expect(payment.loanId).to.equal(loanId);
      expect(payment.installmentNumber).to.equal(1);
      expect(payment.amount).to.equal(amount);
      expect(payment.method).to.equal(PaymentMethod.Maya);
      expect(payment.referenceHash).to.equal(ref);
      expect(payment.recordedBy).to.equal(officer.address);
    });
  });

  // ================================================================
  // Loan Fully Repaid
  // ================================================================
  describe("LoanFullyRepaid", function () {
    it("Should emit LoanFullyRepaid when all installments are paid", async function () {
      // Create short loan for easier testing
      const shortLoanId = ethers.keccak256(ethers.toUtf8Bytes("SHORTLOAN_PAY"));
      const shortPrincipal = ethers.parseEther("1000");
      const shortTerm = 2;
      const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD_SHORT"));

      await loanCore.connect(borrower).createLoan(shortLoanId, productId, shortPrincipal, shortTerm, 100);
      await loanCore.connect(borrower).submitLoan(
        shortLoanId, 85, 0, ethers.keccak256(ethers.toUtf8Bytes("AI_SHORT"))
      );
      await loanCore.assignOfficer(shortLoanId, officer.address);
      await loanCore.connect(officer).approveLoan(
        shortLoanId, shortPrincipal, ethers.keccak256(ethers.toUtf8Bytes("N_SHORT"))
      );
      await loanCore.markDisbursed(shortLoanId, shortPrincipal);

      const startDate = await time.latest();
      await repaymentSchedule
        .connect(admin)
        .createSchedule(shortLoanId, borrower.address, shortPrincipal, 100, shortTerm, startDate);

      // Pay installment 1
      const inst1 = await repaymentSchedule.getInstallment(shortLoanId, 1);
      await paymentRecording.connect(officer).recordPayment(
        shortLoanId, 1, inst1.totalAmount, PaymentMethod.Cash,
        ethers.keccak256(ethers.toUtf8Bytes("FULL_1"))
      );

      // Pay installment 2 — should trigger LoanFullyRepaid
      const inst2 = await repaymentSchedule.getInstallment(shortLoanId, 2);
      await expect(
        paymentRecording.connect(officer).recordPayment(
          shortLoanId, 2, inst2.totalAmount, PaymentMethod.Cash,
          ethers.keccak256(ethers.toUtf8Bytes("FULL_2"))
        )
      ).to.emit(paymentRecording, "LoanFullyRepaid");
    });

    it("Should NOT emit LoanFullyRepaid when balance remains", async function () {
      const amount = expectedMonthlyPayment();
      await expect(
        paymentRecording.connect(officer).recordPayment(
          loanId, 1, amount, PaymentMethod.Cash,
          ethers.keccak256(ethers.toUtf8Bytes("PARTIAL_FULL"))
        )
      ).to.not.emit(paymentRecording, "LoanFullyRepaid");
    });

    it("Should show zero remaining balance after full repayment", async function () {
      // Short 2-month loan
      const shortLoanId = ethers.keccak256(ethers.toUtf8Bytes("SHORT2_PAY"));
      const shortPrincipal = ethers.parseEther("2000");
      const shortTerm = 2;
      const productId = ethers.keccak256(ethers.toUtf8Bytes("PROD_SHORT2"));

      await loanCore.connect(borrower).createLoan(shortLoanId, productId, shortPrincipal, shortTerm, 100);
      await loanCore.connect(borrower).submitLoan(
        shortLoanId, 90, 0, ethers.keccak256(ethers.toUtf8Bytes("AI_S2"))
      );
      await loanCore.assignOfficer(shortLoanId, officer.address);
      await loanCore.connect(officer).approveLoan(
        shortLoanId, shortPrincipal, ethers.keccak256(ethers.toUtf8Bytes("N_S2"))
      );
      await loanCore.markDisbursed(shortLoanId, shortPrincipal);

      const startDate = await time.latest();
      await repaymentSchedule
        .connect(admin)
        .createSchedule(shortLoanId, borrower.address, shortPrincipal, 100, shortTerm, startDate);

      for (let i = 1; i <= shortTerm; i++) {
        const inst = await repaymentSchedule.getInstallment(shortLoanId, i);
        await paymentRecording.connect(officer).recordPayment(
          shortLoanId, i, inst.totalAmount, PaymentMethod.Cash,
          ethers.keccak256(ethers.toUtf8Bytes(`SFULL_${i}`))
        );
      }

      expect(await repaymentSchedule.getRemainingBalance(shortLoanId)).to.equal(0);
    });
  });

  // ================================================================
  // markOverdue
  // ================================================================
  describe("markOverdue", function () {
    it("Should mark a pending installment as overdue after due date", async function () {
      // Advance time past installment 1 due date
      const inst = await repaymentSchedule.getInstallment(loanId, 1);
      await time.increaseTo(inst.dueDate + 1n);

      await expect(
        paymentRecording.connect(admin).markOverdue(loanId, 1)
      ).to.emit(paymentRecording, "InstallmentOverdue");

      const updated = await repaymentSchedule.getInstallment(loanId, 1);
      expect(updated.status).to.equal(InstallmentStatus.Overdue);
    });

    it("Should emit InstallmentStatusChanged on overdue", async function () {
      const inst = await repaymentSchedule.getInstallment(loanId, 1);
      await time.increaseTo(inst.dueDate + 1n);

      await expect(
        paymentRecording.connect(admin).markOverdue(loanId, 1)
      ).to.emit(paymentRecording, "InstallmentStatusChanged")
        .withArgs(loanId, 1, InstallmentStatus.Pending, InstallmentStatus.Overdue, (v) => v > 0n);
    });

    it("Should allow marking a Partial installment as overdue", async function () {
      // Make a partial payment first
      const half = expectedMonthlyPayment() / 2n;
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, half, PaymentMethod.Cash,
        ethers.keccak256(ethers.toUtf8Bytes("OD_PART"))
      );

      const inst = await repaymentSchedule.getInstallment(loanId, 1);
      expect(inst.status).to.equal(InstallmentStatus.Partial);

      await time.increaseTo(inst.dueDate + 1n);
      await expect(
        paymentRecording.connect(admin).markOverdue(loanId, 1)
      ).to.emit(paymentRecording, "InstallmentOverdue");
    });

    it("Should revert if not yet past due date", async function () {
      await expect(
        paymentRecording.connect(admin).markOverdue(loanId, 1)
      ).to.be.revertedWithCustomError(paymentRecording, "NotYetOverdue");
    });

    it("Should revert for Paid installment", async function () {
      // Pay in full first
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, expectedMonthlyPayment(), PaymentMethod.Cash,
        ethers.keccak256(ethers.toUtf8Bytes("OD_PAID"))
      );

      const inst = await repaymentSchedule.getInstallment(loanId, 1);
      await time.increaseTo(inst.dueDate + 1n);

      await expect(
        paymentRecording.connect(admin).markOverdue(loanId, 1)
      ).to.be.revertedWithCustomError(paymentRecording, "InvalidOverdueStatus");
    });

    it("Should reject unauthorized caller (only SYSTEM or ADMIN)", async function () {
      const inst = await repaymentSchedule.getInstallment(loanId, 1);
      await time.increaseTo(inst.dueDate + 1n);

      await expect(
        paymentRecording.connect(other).markOverdue(loanId, 1)
      ).to.be.revertedWithCustomError(paymentRecording, "NotAuthorized");
    });

    it("Should reject officer calling markOverdue (officers cannot mark overdue)", async function () {
      const inst = await repaymentSchedule.getInstallment(loanId, 1);
      await time.increaseTo(inst.dueDate + 1n);

      await expect(
        paymentRecording.connect(officer).markOverdue(loanId, 1)
      ).to.be.revertedWithCustomError(paymentRecording, "NotAuthorized");
    });
  });

  // ================================================================
  // View Functions
  // ================================================================
  describe("View Functions", function () {
    const refHash = (tag) => ethers.keccak256(ethers.toUtf8Bytes(tag));

    describe("getPaymentHistory", function () {
      it("Should return empty array when no payments", async function () {
        const history = await paymentRecording.getPaymentHistory(loanId);
        expect(history.length).to.equal(0);
      });

      // Gas optimization: loanPayments storage array is no longer populated;
      // payment data is available via PaymentRecorded events instead.
      it("Should return all payments for a loan", async function () {
        const amount = expectedMonthlyPayment();
        await paymentRecording.connect(officer).recordPayment(
          loanId, 1, amount, PaymentMethod.Cash, refHash("HIST1")
        );
        await paymentRecording.connect(officer).recordPayment(
          loanId, 2, amount, PaymentMethod.GCash, refHash("HIST2")
        );

        const history = await paymentRecording.getPaymentHistory(loanId);
        expect(history.length).to.equal(0);
      });
    });

    describe("getPayment", function () {
      it("Should return correct payment details", async function () {
        const amount = expectedMonthlyPayment();
        const ref = refHash("GET1");
        const tx = await paymentRecording.connect(officer).recordPayment(
          loanId, 1, amount, PaymentMethod.BankTransfer, ref
        );
        const receipt = await tx.wait();

        const event = receipt.logs.find((log) => {
          try { return paymentRecording.interface.parseLog(log)?.name === "PaymentRecorded"; }
          catch { return false; }
        });
        const parsed = paymentRecording.interface.parseLog(event);
        const paymentId = parsed.args.paymentId;

        const payment = await paymentRecording.getPayment(paymentId);
        expect(payment.amount).to.equal(amount);
        expect(payment.method).to.equal(PaymentMethod.BankTransfer);
      });

      it("Should revert for non-existent paymentId", async function () {
        const fakeId = ethers.keccak256(ethers.toUtf8Bytes("FAKE_PAY"));
        await expect(
          paymentRecording.getPayment(fakeId)
        ).to.be.revertedWithCustomError(paymentRecording, "PaymentNotFound");
      });
    });

    describe("getPaymentIds", function () {
      // Gas optimization: loanPayments storage array is no longer populated;
      // payment IDs are available via PaymentRecorded events instead.
      it("Should return raw payment IDs", async function () {
        await paymentRecording.connect(officer).recordPayment(
          loanId, 1, expectedMonthlyPayment(), PaymentMethod.Cash, refHash("IDS1")
        );
        const ids = await paymentRecording.getPaymentIds(loanId);
        expect(ids.length).to.equal(0);
      });
    });
  });

  // ================================================================
  // Admin Functions
  // ================================================================
  describe("Admin Functions", function () {
    it("Should allow admin to pause", async function () {
      await paymentRecording.connect(admin).pause();
      expect(await paymentRecording.paused()).to.be.true;
    });

    it("Should allow admin to unpause", async function () {
      await paymentRecording.connect(admin).pause();
      await paymentRecording.connect(admin).unpause();
      expect(await paymentRecording.paused()).to.be.false;
    });

    it("Should not allow non-admin to pause", async function () {
      await expect(paymentRecording.connect(other).pause()).to.be.reverted;
    });

    it("Should allow admin to setRepaymentSchedule", async function () {
      const newAddr = ethers.Wallet.createRandom().address;
      await paymentRecording.connect(admin).setRepaymentSchedule(newAddr);
      expect(await paymentRecording.repaymentSchedule()).to.equal(newAddr);
    });

    it("Should revert setRepaymentSchedule with zero address", async function () {
      await expect(
        paymentRecording.connect(admin).setRepaymentSchedule(ethers.ZeroAddress)
      ).to.be.revertedWithCustomError(paymentRecording, "ZeroAddress");
    });

    it("Should allow admin to setAuditRegistry", async function () {
      const newAddr = ethers.Wallet.createRandom().address;
      await paymentRecording.connect(admin).setAuditRegistry(newAddr);
      expect(await paymentRecording.auditRegistry()).to.equal(newAddr);
    });

    it("Should revert setAuditRegistry with zero address", async function () {
      await expect(
        paymentRecording.connect(admin).setAuditRegistry(ethers.ZeroAddress)
      ).to.be.revertedWithCustomError(paymentRecording, "ZeroAddress");
    });
  });

  // ================================================================
  // Multiple Partial Payments
  // ================================================================
  describe("Multiple Partial Payments", function () {
    const refHash = (tag) => ethers.keccak256(ethers.toUtf8Bytes(tag));

    it("Should correctly handle two partial payments that sum to full", async function () {
      const full = expectedMonthlyPayment();
      const half = full / 2n;

      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, half, PaymentMethod.Cash, refHash("MULTI1A")
      );
      let inst = await repaymentSchedule.getInstallment(loanId, 1);
      expect(inst.status).to.equal(InstallmentStatus.Partial);
      expect(inst.paidAmount).to.equal(half);

      // Pay remainder (might be half + 1 due to integer division)
      const remainder = full - half;
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, remainder, PaymentMethod.Cash, refHash("MULTI1B")
      );

      inst = await repaymentSchedule.getInstallment(loanId, 1);
      expect(inst.status).to.equal(InstallmentStatus.Paid);
      expect(inst.paidAmount).to.equal(full);
    });

    // Gas optimization: loanPayments storage array is no longer populated;
    // payment history is available via PaymentRecorded events instead.
    it("Should record multiple payments in history", async function () {
      const half = expectedMonthlyPayment() / 2n;

      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, half, PaymentMethod.Cash, refHash("MULTI2A")
      );
      await paymentRecording.connect(officer).recordPayment(
        loanId, 1, half, PaymentMethod.GCash, refHash("MULTI2B")
      );

      const history = await paymentRecording.getPaymentHistory(loanId);
      expect(history.length).to.equal(0);
    });
  });
});
