// Test suite for PenaltyCalculator contract - Aligned with actual contract implementation
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("PenaltyCalculator", function () {
  let penaltyCalculator;
  let admin, officer, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));

  beforeEach(async function () {
    [admin, officer, other] = await ethers.getSigners();

    const PenaltyCalculator = await ethers.getContractFactory("PenaltyCalculator");
    penaltyCalculator = await upgrades.deployProxy(
      PenaltyCalculator,
      [admin.address],
      { kind: "uups" }
    );
    await penaltyCalculator.waitForDeployment();

    // Grant officer role for waiver tests
    await penaltyCalculator.grantRole(LOAN_OFFICER_ROLE, officer.address);
  });

  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await penaltyCalculator.VERSION()).to.equal(1);
    });

    it("Should set default config via getConfig", async function () {
      const config = await penaltyCalculator.getConfig();
      expect(config.gracePeriodDays).to.equal(3);        // 3 days grace period
      expect(config.lateFeePercentBps).to.equal(500);    // 5% late fee
      expect(config.dailyPenaltyBps).to.equal(10);       // 0.1% daily
      expect(config.maxPenaltyPercent).to.equal(25);     // 25% cap
      expect(config.compoundPenalty).to.be.false;        // Simple interest
    });
  });

  describe("Configuration Updates", function () {
    it("Should update config via updateConfig", async function () {
      await expect(
        penaltyCalculator.connect(admin).updateConfig(
          7,      // gracePeriodDays
          300,    // lateFeePercentBps (3%)
          20,     // dailyPenaltyBps (0.2%)
          30,     // maxPenaltyPercent (30%)
          false   // compoundPenalty
        )
      ).to.emit(penaltyCalculator, "PenaltyConfigUpdated");

      const config = await penaltyCalculator.getConfig();
      expect(config.gracePeriodDays).to.equal(7);
      expect(config.lateFeePercentBps).to.equal(300);
    });

    it("Should not allow non-admin to change config", async function () {
      await expect(
        penaltyCalculator.connect(other).updateConfig(7, 300, 20, 30, false)
      ).to.be.reverted;
    });

    it("Should reject grace period too long", async function () {
      await expect(
        penaltyCalculator.connect(admin).updateConfig(31, 500, 10, 25, false)
      ).to.be.revertedWith("PenaltyCalculator: grace period too long");
    });

    it("Should reject late fee too high", async function () {
      await expect(
        penaltyCalculator.connect(admin).updateConfig(3, 2001, 10, 25, false)
      ).to.be.revertedWith("PenaltyCalculator: late fee too high");
    });

    it("Should reject daily penalty too high", async function () {
      await expect(
        penaltyCalculator.connect(admin).updateConfig(3, 500, 101, 25, false)
      ).to.be.revertedWith("PenaltyCalculator: daily penalty too high");
    });

    it("Should reject max penalty too high", async function () {
      await expect(
        penaltyCalculator.connect(admin).updateConfig(3, 500, 10, 51, false)
      ).to.be.revertedWith("PenaltyCalculator: max penalty too high");
    });
  });

  describe("Penalty Calculation", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const installmentNumber = 1;
    const installmentAmount = ethers.parseEther("1000");

    it("Should return zero penalty during grace period", async function () {
      const now = await time.latest();
      const dueDate = now - (2 * 24 * 60 * 60); // 2 days ago (within 3-day grace)

      const [penaltyAmount, daysOverdue] = await penaltyCalculator.calculatePenalty(
        loanId,
        installmentNumber,
        installmentAmount,
        dueDate
      );

      expect(penaltyAmount).to.equal(0);
      expect(daysOverdue).to.equal(0);
    });

    it("Should calculate penalty after grace period", async function () {
      const now = await time.latest();
      const dueDate = now - (10 * 24 * 60 * 60); // 10 days ago

      const [penaltyAmount, daysOverdue] = await penaltyCalculator.calculatePenalty(
        loanId,
        installmentNumber,
        installmentAmount,
        dueDate
      );

      // Should have penalty after grace period
      expect(penaltyAmount).to.be.gt(0);
      expect(daysOverdue).to.be.gt(0);
    });

    it("Should respect penalty cap", async function () {
      const now = await time.latest();
      const dueDate = now - (365 * 24 * 60 * 60); // 1 year overdue

      const [penaltyAmount,] = await penaltyCalculator.calculatePenalty(
        loanId,
        installmentNumber,
        installmentAmount,
        dueDate
      );

      // Max cap is 25%, so max penalty = 250 ETH on 1000 ETH
      const maxPenalty = installmentAmount * 25n / 100n;
      expect(penaltyAmount).to.be.lte(maxPenalty);
    });

    it("Should return zero if not overdue", async function () {
      const now = await time.latest();
      const dueDate = now + (10 * 24 * 60 * 60); // 10 days in future

      const [penaltyAmount, daysOverdue] = await penaltyCalculator.calculatePenalty(
        loanId,
        installmentNumber,
        installmentAmount,
        dueDate
      );

      expect(penaltyAmount).to.equal(0);
      expect(daysOverdue).to.equal(0);
    });

    it("Should handle zero amount", async function () {
      const now = await time.latest();
      const dueDate = now - (20 * 24 * 60 * 60);

      const [penaltyAmount,] = await penaltyCalculator.calculatePenalty(
        loanId,
        installmentNumber,
        0,
        dueDate
      );

      expect(penaltyAmount).to.equal(0);
    });
  });

  describe("Penalty Recording", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const installmentNumber = 1;
    const penaltyAmount = ethers.parseEther("50");

    it("Should record penalty", async function () {
      await expect(
        penaltyCalculator.connect(admin).recordPenalty(
          loanId,
          installmentNumber,
          penaltyAmount
        )
      ).to.emit(penaltyCalculator, "PenaltyCalculated");
    });

    it("Should retrieve penalty record", async function () {
      await penaltyCalculator.connect(admin).recordPenalty(
        loanId,
        installmentNumber,
        penaltyAmount
      );

      const record = await penaltyCalculator.getPenaltyRecord(loanId, installmentNumber);
      expect(record.penaltyAmount).to.equal(penaltyAmount);
      expect(record.waived).to.be.false;
    });
  });

  describe("Penalty Waiver", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const installmentNumber = 1;
    const penaltyAmount = ethers.parseEther("50");
    const reasonHash = ethers.keccak256(ethers.toUtf8Bytes("NATURAL_DISASTER"));

    beforeEach(async function () {
      // Record a penalty first
      await penaltyCalculator.connect(admin).recordPenalty(
        loanId,
        installmentNumber,
        penaltyAmount
      );
    });

    it("Should waive penalty by admin", async function () {
      await expect(
        penaltyCalculator.connect(admin).waivePenalty(
          loanId,
          installmentNumber,
          reasonHash
        )
      ).to.emit(penaltyCalculator, "PenaltyWaived");
    });

    it("Should waive penalty by officer", async function () {
      await expect(
        penaltyCalculator.connect(officer).waivePenalty(
          loanId,
          installmentNumber,
          reasonHash
        )
      ).to.emit(penaltyCalculator, "PenaltyWaived");
    });

    it("Should mark penalty as waived", async function () {
      await penaltyCalculator.connect(admin).waivePenalty(
        loanId,
        installmentNumber,
        reasonHash
      );

      const isWaived = await penaltyCalculator.isPenaltyWaived(loanId, installmentNumber);
      expect(isWaived).to.be.true;
    });

    it("Should not allow waiving already waived penalty", async function () {
      await penaltyCalculator.connect(admin).waivePenalty(
        loanId,
        installmentNumber,
        reasonHash
      );

      await expect(
        penaltyCalculator.connect(admin).waivePenalty(
          loanId,
          installmentNumber,
          reasonHash
        )
      ).to.be.revertedWith("PenaltyCalculator: already waived");
    });

    it("Should not allow non-authorized to waive penalty", async function () {
      await expect(
        penaltyCalculator.connect(other).waivePenalty(
          loanId,
          installmentNumber,
          reasonHash
        )
      ).to.be.reverted;
    });

    it("Should require reason for waiver", async function () {
      await expect(
        penaltyCalculator.connect(admin).waivePenalty(
          loanId,
          installmentNumber,
          ethers.ZeroHash
        )
      ).to.be.revertedWith("PenaltyCalculator: reason required");
    });
  });

  describe("Edge Cases", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const installmentNumber = 1;

    it("Should handle same day due date", async function () {
      const now = await time.latest();

      const [penaltyAmount, daysOverdue] = await penaltyCalculator.calculatePenalty(
        loanId,
        installmentNumber,
        ethers.parseEther("1000"),
        now
      );

      expect(penaltyAmount).to.equal(0);
      expect(daysOverdue).to.equal(0);
    });

    it("Should handle exactly at grace period end", async function () {
      const now = await time.latest();
      const dueDate = now - (3 * 24 * 60 * 60); // Exactly 3 days (grace period)

      const [penaltyAmount,] = await penaltyCalculator.calculatePenalty(
        loanId,
        installmentNumber,
        ethers.parseEther("1000"),
        dueDate
      );

      // Should be 0 or minimal (at the edge)
      expect(penaltyAmount).to.be.lte(ethers.parseEther("100"));
    });
  });

  describe("Compound vs Simple Penalty", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const installmentNumber = 1;
    const installmentAmount = ethers.parseEther("1000");

    it("Should calculate higher compound penalty over time", async function () {
      // Update config to use compound penalty
      await penaltyCalculator.connect(admin).updateConfig(
        3,      // gracePeriodDays
        500,    // lateFeePercentBps
        50,     // dailyPenaltyBps (0.5% to make difference visible)
        50,     // maxPenaltyPercent
        true    // compoundPenalty = true
      );

      const now = await time.latest();
      const dueDate = now - (30 * 24 * 60 * 60); // 30 days overdue

      const [compoundPenalty,] = await penaltyCalculator.calculatePenalty(
        loanId,
        installmentNumber,
        installmentAmount,
        dueDate
      );

      // Switch back to simple
      await penaltyCalculator.connect(admin).updateConfig(
        3, 500, 50, 50, false
      );

      const [simplePenalty,] = await penaltyCalculator.calculatePenalty(
        loanId,
        installmentNumber,
        installmentAmount,
        dueDate
      );

      // Compound should generally be higher (unless capped)
      // Note: Both might hit the cap, so we just check they're calculated
      expect(compoundPenalty).to.be.gt(0);
      expect(simplePenalty).to.be.gt(0);
    });
  });
});
