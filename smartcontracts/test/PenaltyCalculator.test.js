// Test suite for PenaltyCalculator contract
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("PenaltyCalculator", function () {
  let penaltyCalculator;
  let admin, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));

  beforeEach(async function () {
    [admin, other] = await ethers.getSigners();

    const PenaltyCalculator = await ethers.getContractFactory("PenaltyCalculator");
    penaltyCalculator = await upgrades.deployProxy(
      PenaltyCalculator,
      [admin.address],
      { kind: "uups" }
    );
    await penaltyCalculator.waitForDeployment();
  });

  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await penaltyCalculator.VERSION()).to.equal(1);
    });

    it("Should set default parameters", async function () {
      expect(await penaltyCalculator.gracePeriodDays()).to.equal(7);
      expect(await penaltyCalculator.lateFeePercent()).to.equal(500); // 5%
      expect(await penaltyCalculator.dailyPenaltyBps()).to.equal(50); // 0.5% per day
      expect(await penaltyCalculator.maxPenaltyCap()).to.equal(2500); // 25%
    });
  });

  describe("Parameter Configuration", function () {
    it("Should update grace period", async function () {
      await expect(
        penaltyCalculator.connect(admin).setGracePeriod(14)
      ).to.emit(penaltyCalculator, "GracePeriodUpdated")
        .withArgs(7, 14);

      expect(await penaltyCalculator.gracePeriodDays()).to.equal(14);
    });

    it("Should update late fee percent", async function () {
      await expect(
        penaltyCalculator.connect(admin).setLateFeePercent(300) // 3%
      ).to.emit(penaltyCalculator, "LateFeeUpdated")
        .withArgs(500, 300);

      expect(await penaltyCalculator.lateFeePercent()).to.equal(300);
    });

    it("Should update daily penalty", async function () {
      await expect(
        penaltyCalculator.connect(admin).setDailyPenalty(100) // 1% per day
      ).to.emit(penaltyCalculator, "DailyPenaltyUpdated")
        .withArgs(50, 100);

      expect(await penaltyCalculator.dailyPenaltyBps()).to.equal(100);
    });

    it("Should update penalty cap", async function () {
      await expect(
        penaltyCalculator.connect(admin).setPenaltyCap(3000) // 30%
      ).to.emit(penaltyCalculator, "PenaltyCapUpdated")
        .withArgs(2500, 3000);

      expect(await penaltyCalculator.maxPenaltyCap()).to.equal(3000);
    });

    it("Should not allow non-admin to change parameters", async function () {
      await expect(
        penaltyCalculator.connect(other).setGracePeriod(14)
      ).to.be.reverted;
    });

    it("Should not allow late fee above 100%", async function () {
      await expect(
        penaltyCalculator.connect(admin).setLateFeePercent(10001)
      ).to.be.revertedWithCustomError(penaltyCalculator, "InvalidParameter");
    });
  });

  describe("Penalty Calculation", function () {
    const installmentAmount = ethers.parseEther("1000");

    it("Should return zero penalty during grace period", async function () {
      const now = Math.floor(Date.now() / 1000);
      const dueDate = now - 3 * 24 * 60 * 60; // 3 days overdue (within 7-day grace)

      const penalty = await penaltyCalculator.calculatePenalty(
        installmentAmount,
        dueDate,
        now
      );

      expect(penalty).to.equal(0);
    });

    it("Should calculate late fee after grace period", async function () {
      const now = Math.floor(Date.now() / 1000);
      const dueDate = now - 10 * 24 * 60 * 60; // 10 days overdue

      const penalty = await penaltyCalculator.calculatePenalty(
        installmentAmount,
        dueDate,
        now
      );

      // Late fee: 5% of 1000 = 50
      // Daily penalty: 0.5% * 3 days (10-7 grace) = 1.5% = 15
      // Total: 65 ETH expected
      expect(penalty).to.be.gt(0);
    });

    it("Should respect penalty cap", async function () {
      const now = Math.floor(Date.now() / 1000);
      const dueDate = now - 100 * 24 * 60 * 60; // 100 days overdue

      const penalty = await penaltyCalculator.calculatePenalty(
        installmentAmount,
        dueDate,
        now
      );

      // Max cap is 25%, so max penalty = 250 on 1000
      expect(penalty).to.be.lte(ethers.parseEther("250"));
    });

    it("Should return zero if not overdue", async function () {
      const now = Math.floor(Date.now() / 1000);
      const dueDate = now + 10 * 24 * 60 * 60; // 10 days in future

      const penalty = await penaltyCalculator.calculatePenalty(
        installmentAmount,
        dueDate,
        now
      );

      expect(penalty).to.equal(0);
    });
  });

  describe("Days Overdue Calculation", function () {
    it("Should calculate days overdue correctly", async function () {
      const now = Math.floor(Date.now() / 1000);
      const dueDate = now - 15 * 24 * 60 * 60; // 15 days ago

      const daysOverdue = await penaltyCalculator.getDaysOverdue(dueDate, now);
      expect(daysOverdue).to.equal(15);
    });

    it("Should return zero if not overdue", async function () {
      const now = Math.floor(Date.now() / 1000);
      const dueDate = now + 5 * 24 * 60 * 60; // 5 days in future

      const daysOverdue = await penaltyCalculator.getDaysOverdue(dueDate, now);
      expect(daysOverdue).to.equal(0);
    });
  });

  describe("Penalty Waiver", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const reasonHash = ethers.keccak256(ethers.toUtf8Bytes("NATURAL_DISASTER"));

    it("Should record penalty waiver", async function () {
      const waivedAmount = ethers.parseEther("50");

      await expect(
        penaltyCalculator.connect(admin).waivePenalty(
          loanId,
          waivedAmount,
          reasonHash
        )
      ).to.emit(penaltyCalculator, "PenaltyWaived")
        .withArgs(loanId, waivedAmount, reasonHash);
    });

    it("Should track total waived amount", async function () {
      const waivedAmount1 = ethers.parseEther("50");
      const waivedAmount2 = ethers.parseEther("30");
      const reasonHash2 = ethers.keccak256(ethers.toUtf8Bytes("PAYMENT_DIFFICULTY"));

      await penaltyCalculator.connect(admin).waivePenalty(loanId, waivedAmount1, reasonHash);
      await penaltyCalculator.connect(admin).waivePenalty(loanId, waivedAmount2, reasonHash2);

      const totalWaived = await penaltyCalculator.getTotalWaived(loanId);
      expect(totalWaived).to.equal(ethers.parseEther("80"));
    });

    it("Should not allow non-admin to waive penalty", async function () {
      await expect(
        penaltyCalculator.connect(other).waivePenalty(
          loanId,
          ethers.parseEther("50"),
          reasonHash
        )
      ).to.be.reverted;
    });
  });

  describe("Penalty Breakdown", function () {
    const installmentAmount = ethers.parseEther("1000");

    it("Should provide detailed breakdown", async function () {
      const now = Math.floor(Date.now() / 1000);
      const dueDate = now - 20 * 24 * 60 * 60; // 20 days overdue

      const breakdown = await penaltyCalculator.getPenaltyBreakdown(
        installmentAmount,
        dueDate,
        now
      );

      expect(breakdown.lateFee).to.be.gt(0);
      expect(breakdown.dailyPenalty).to.be.gt(0);
      expect(breakdown.totalPenalty).to.equal(breakdown.lateFee + breakdown.dailyPenalty);
      expect(breakdown.daysOverdue).to.equal(20);
    });
  });

  describe("Batch Calculation", function () {
    it("Should calculate penalties for multiple installments", async function () {
      const now = Math.floor(Date.now() / 1000);
      
      const amounts = [
        ethers.parseEther("1000"),
        ethers.parseEther("1000"),
        ethers.parseEther("1000")
      ];
      
      const dueDates = [
        now - 30 * 24 * 60 * 60, // 30 days overdue
        now - 15 * 24 * 60 * 60, // 15 days overdue
        now - 5 * 24 * 60 * 60   // 5 days overdue (in grace)
      ];

      const penalties = await penaltyCalculator.calculateBatchPenalties(
        amounts,
        dueDates,
        now
      );

      expect(penalties[0]).to.be.gt(penalties[1]); // Older debt has more penalty
      expect(penalties[2]).to.equal(0); // Within grace period
    });
  });

  describe("Edge Cases", function () {
    it("Should handle zero amount", async function () {
      const now = Math.floor(Date.now() / 1000);
      const dueDate = now - 20 * 24 * 60 * 60;

      const penalty = await penaltyCalculator.calculatePenalty(
        0,
        dueDate,
        now
      );

      expect(penalty).to.equal(0);
    });

    it("Should handle same day due date", async function () {
      const now = Math.floor(Date.now() / 1000);

      const penalty = await penaltyCalculator.calculatePenalty(
        ethers.parseEther("1000"),
        now,
        now
      );

      expect(penalty).to.equal(0);
    });
  });
});
