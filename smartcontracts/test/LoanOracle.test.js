// Test suite for LoanOracle contract - Aligned with actual contract implementation
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("LoanOracle", function () {
  let loanOracle;
  let admin, oracle1, oracle2, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const ORACLE_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ORACLE_ROLE"));
  const UPGRADER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("UPGRADER_ROLE"));

  beforeEach(async function () {
    [admin, oracle1, oracle2, other] = await ethers.getSigners();

    // Deploy LoanOracle with (admin, oracle) params
    const LoanOracle = await ethers.getContractFactory("LoanOracle");
    loanOracle = await upgrades.deployProxy(
      LoanOracle,
      [admin.address, oracle1.address],
      { kind: "uups" }
    );
    await loanOracle.waitForDeployment();
  });

  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await loanOracle.VERSION()).to.equal(1);
    });

    it("Should set admin role", async function () {
      expect(await loanOracle.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
    });

    it("Should grant oracle role to initial oracle", async function () {
      expect(await loanOracle.hasRole(ORACLE_ROLE, oracle1.address)).to.be.true;
    });

    it("Should set score validity period", async function () {
      expect(await loanOracle.SCORE_VALIDITY_PERIOD()).to.equal(7 * 24 * 60 * 60); // 7 days
    });
  });

  describe("AI Score Submission", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const eligibilityScore = 78;
    const riskCategory = 1; // Medium
    const recommendedAmount = ethers.parseEther("10000");
    const analysisHash = ethers.keccak256(ethers.toUtf8Bytes("AI_ANALYSIS"));

    it("Should submit AI score successfully", async function () {
      await expect(
        loanOracle.connect(oracle1).submitAIScore(
          loanId,
          eligibilityScore,
          riskCategory,
          recommendedAmount,
          analysisHash
        )
      ).to.emit(loanOracle, "AIScoreSubmitted");
    });

    it("Should store score correctly", async function () {
      await loanOracle.connect(oracle1).submitAIScore(
        loanId,
        eligibilityScore,
        riskCategory,
        recommendedAmount,
        analysisHash
      );

      const score = await loanOracle.getAIScore(loanId);
      expect(score.eligibilityScore).to.equal(eligibilityScore);
      expect(score.riskCategory).to.equal(riskCategory);
      expect(score.recommendedAmount).to.equal(recommendedAmount);
      expect(score.analysisHash).to.equal(analysisHash);
      expect(score.isValid).to.be.true;
    });

    it("Should reject score above 100", async function () {
      await expect(
        loanOracle.connect(oracle1).submitAIScore(
          loanId,
          101, // Invalid
          riskCategory,
          recommendedAmount,
          analysisHash
        )
      ).to.be.revertedWithCustomError(loanOracle, "InvalidScore");
    });

    it("Should reject invalid risk category", async function () {
      await expect(
        loanOracle.connect(oracle1).submitAIScore(
          loanId,
          eligibilityScore,
          3, // Invalid: must be 0, 1, or 2
          recommendedAmount,
          analysisHash
        )
      ).to.be.revertedWith("LoanOracle: invalid risk category");
    });

    it("Should not allow non-oracle to submit", async function () {
      await expect(
        loanOracle.connect(other).submitAIScore(
          loanId,
          eligibilityScore,
          riskCategory,
          recommendedAmount,
          analysisHash
        )
      ).to.be.reverted;
    });

    it("Should not allow duplicate score within validity period", async function () {
      await loanOracle.connect(oracle1).submitAIScore(
        loanId,
        eligibilityScore,
        riskCategory,
        recommendedAmount,
        analysisHash
      );

      await expect(
        loanOracle.connect(oracle1).submitAIScore(
          loanId,
          80, // Different score
          riskCategory,
          recommendedAmount,
          analysisHash
        )
      ).to.be.revertedWithCustomError(loanOracle, "ScoreAlreadyExists");
    });

    it("Should allow new score after validity period expires", async function () {
      await loanOracle.connect(oracle1).submitAIScore(
        loanId,
        eligibilityScore,
        riskCategory,
        recommendedAmount,
        analysisHash
      );

      // Fast forward past validity period (7 days)
      await time.increase(8 * 24 * 60 * 60);

      // Should allow new score
      await expect(
        loanOracle.connect(oracle1).submitAIScore(
          loanId,
          85,
          0, // Low risk
          recommendedAmount,
          ethers.keccak256(ethers.toUtf8Bytes("NEW_ANALYSIS"))
        )
      ).to.emit(loanOracle, "AIScoreSubmitted");
    });
  });

  describe("Score Invalidation", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));

    beforeEach(async function () {
      await loanOracle.connect(oracle1).submitAIScore(
        loanId,
        78,
        1,
        ethers.parseEther("10000"),
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS"))
      );
    });

    it("Should invalidate score by admin", async function () {
      await expect(
        loanOracle.connect(admin).invalidateScore(loanId)
      ).to.emit(loanOracle, "AIScoreInvalidated");
    });

    it("Should mark score as invalid", async function () {
      await loanOracle.connect(admin).invalidateScore(loanId);

      const score = await loanOracle.getAIScore(loanId);
      expect(score.isValid).to.be.false;
    });

    it("Should not allow non-admin to invalidate", async function () {
      await expect(
        loanOracle.connect(other).invalidateScore(loanId)
      ).to.be.reverted;
    });

    it("Should not invalidate non-existent score", async function () {
      const unknownLoan = ethers.keccak256(ethers.toUtf8Bytes("UNKNOWN"));
      
      await expect(
        loanOracle.connect(admin).invalidateScore(unknownLoan)
      ).to.be.revertedWithCustomError(loanOracle, "ScoreNotFound");
    });
  });

  describe("Score Validity Check", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));

    beforeEach(async function () {
      await loanOracle.connect(oracle1).submitAIScore(
        loanId,
        78,
        1,
        ethers.parseEther("10000"),
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS"))
      );
    });

    it("Should return true for valid score", async function () {
      const isValid = await loanOracle.isScoreValid(loanId);
      expect(isValid).to.be.true;
    });

    it("Should return false after invalidation", async function () {
      await loanOracle.connect(admin).invalidateScore(loanId);

      const isValid = await loanOracle.isScoreValid(loanId);
      expect(isValid).to.be.false;
    });

    it("Should return false after validity period expires", async function () {
      await time.increase(8 * 24 * 60 * 60); // 8 days

      const isValid = await loanOracle.isScoreValid(loanId);
      expect(isValid).to.be.false;
    });
  });

  describe("External Payment Confirmation", function () {
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const externalRef = ethers.keccak256(ethers.toUtf8Bytes("EXTPAY001"));
    const amount = ethers.parseEther("1000");

    it("Should confirm external payment", async function () {
      await expect(
        loanOracle.connect(oracle1).confirmExternalPayment(
          loanId,
          externalRef,
          amount
        )
      ).to.emit(loanOracle, "PaymentConfirmed");
    });

    it("Should store payment confirmation", async function () {
      await loanOracle.connect(oracle1).confirmExternalPayment(
        loanId,
        externalRef,
        amount
      );

      const payment = await loanOracle.getExternalPayment(externalRef);
      expect(payment.loanId).to.equal(loanId);
      expect(payment.amount).to.equal(amount);
      expect(payment.isConfirmed).to.be.true;
    });

    it("Should not allow duplicate payment confirmation", async function () {
      await loanOracle.connect(oracle1).confirmExternalPayment(
        loanId,
        externalRef,
        amount
      );

      await expect(
        loanOracle.connect(oracle1).confirmExternalPayment(
          loanId,
          externalRef, // Same reference
          amount
        )
      ).to.be.revertedWithCustomError(loanOracle, "PaymentAlreadyConfirmed");
    });

    it("Should check if payment is confirmed", async function () {
      await loanOracle.connect(oracle1).confirmExternalPayment(
        loanId,
        externalRef,
        amount
      );

      const isConfirmed = await loanOracle.isPaymentConfirmed(loanId, externalRef);
      expect(isConfirmed).to.be.true;
    });

    it("Should reject empty loan ID", async function () {
      await expect(
        loanOracle.connect(oracle1).confirmExternalPayment(
          ethers.ZeroHash,
          externalRef,
          amount
        )
      ).to.be.revertedWith("LoanOracle: empty loan ID");
    });

    it("Should reject zero amount", async function () {
      await expect(
        loanOracle.connect(oracle1).confirmExternalPayment(
          loanId,
          externalRef,
          0
        )
      ).to.be.revertedWith("LoanOracle: invalid amount");
    });
  });

  describe("Batch Payment Confirmation", function () {
    it("Should confirm multiple payments in batch", async function () {
      const loanIds = [
        ethers.keccak256(ethers.toUtf8Bytes("LOAN001")),
        ethers.keccak256(ethers.toUtf8Bytes("LOAN002")),
        ethers.keccak256(ethers.toUtf8Bytes("LOAN003"))
      ];
      const externalRefs = [
        ethers.keccak256(ethers.toUtf8Bytes("PAY001")),
        ethers.keccak256(ethers.toUtf8Bytes("PAY002")),
        ethers.keccak256(ethers.toUtf8Bytes("PAY003"))
      ];
      const amounts = [
        ethers.parseEther("100"),
        ethers.parseEther("200"),
        ethers.parseEther("300")
      ];

      const tx = await loanOracle.connect(oracle1).confirmPaymentsBatch(
        loanIds,
        externalRefs,
        amounts
      );

      const receipt = await tx.wait();
      
      // Check all payments are confirmed
      for (let i = 0; i < externalRefs.length; i++) {
        const isConfirmed = await loanOracle.isPaymentConfirmed(loanIds[i], externalRefs[i]);
        expect(isConfirmed).to.be.true;
      }
    });

    it("Should skip already confirmed payments", async function () {
      const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
      const externalRef = ethers.keccak256(ethers.toUtf8Bytes("PAY001"));

      // Confirm first
      await loanOracle.connect(oracle1).confirmExternalPayment(
        loanId,
        externalRef,
        ethers.parseEther("100")
      );

      // Try batch with same payment - should not revert
      await loanOracle.connect(oracle1).confirmPaymentsBatch(
        [loanId],
        [externalRef],
        [ethers.parseEther("100")]
      );
    });

    it("Should reject mismatched array lengths", async function () {
      await expect(
        loanOracle.connect(oracle1).confirmPaymentsBatch(
          [ethers.keccak256(ethers.toUtf8Bytes("LOAN001"))],
          [ethers.keccak256(ethers.toUtf8Bytes("PAY001")), ethers.keccak256(ethers.toUtf8Bytes("PAY002"))],
          [ethers.parseEther("100")]
        )
      ).to.be.revertedWith("LoanOracle: array mismatch");
    });
  });

  describe("Oracle Management", function () {
    it("Should add new oracle", async function () {
      await expect(
        loanOracle.connect(admin).addOracle(oracle2.address)
      ).to.emit(loanOracle, "OracleAddressUpdated");

      expect(await loanOracle.hasRole(ORACLE_ROLE, oracle2.address)).to.be.true;
    });

    it("Should remove oracle", async function () {
      await loanOracle.connect(admin).addOracle(oracle2.address);
      
      await expect(
        loanOracle.connect(admin).removeOracle(oracle2.address)
      ).to.emit(loanOracle, "OracleAddressUpdated");

      expect(await loanOracle.hasRole(ORACLE_ROLE, oracle2.address)).to.be.false;
    });

    it("Should not allow non-admin to add oracle", async function () {
      await expect(
        loanOracle.connect(other).addOracle(oracle2.address)
      ).to.be.reverted;
    });

    it("Should reject zero address for new oracle", async function () {
      await expect(
        loanOracle.connect(admin).addOracle(ethers.ZeroAddress)
      ).to.be.revertedWith("LoanOracle: zero address");
    });
  });

  describe("Statistics", function () {
    it("Should track total scores submitted", async function () {
      const loanId1 = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
      const loanId2 = ethers.keccak256(ethers.toUtf8Bytes("LOAN002"));

      await loanOracle.connect(oracle1).submitAIScore(
        loanId1, 75, 1, ethers.parseEther("10000"),
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS1"))
      );

      await loanOracle.connect(oracle1).submitAIScore(
        loanId2, 80, 0, ethers.parseEther("15000"),
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS2"))
      );

      const [totalScores, totalPayments] = await loanOracle.getStats();
      expect(totalScores).to.equal(2);
    });

    it("Should track total payments confirmed", async function () {
      await loanOracle.connect(oracle1).confirmExternalPayment(
        ethers.keccak256(ethers.toUtf8Bytes("LOAN001")),
        ethers.keccak256(ethers.toUtf8Bytes("PAY001")),
        ethers.parseEther("100")
      );

      await loanOracle.connect(oracle1).confirmExternalPayment(
        ethers.keccak256(ethers.toUtf8Bytes("LOAN002")),
        ethers.keccak256(ethers.toUtf8Bytes("PAY002")),
        ethers.parseEther("200")
      );

      const [totalScores, totalPayments] = await loanOracle.getStats();
      expect(totalPayments).to.equal(2);
    });
  });
});
