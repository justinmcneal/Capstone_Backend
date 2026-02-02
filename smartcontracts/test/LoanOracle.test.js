// Test suite for LoanOracle contract
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("LoanOracle", function () {
  let loanOracle;
  let accessControl;
  let admin, oracle1, oracle2, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const ORACLE_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ORACLE_ROLE"));

  beforeEach(async function () {
    [admin, oracle1, oracle2, other] = await ethers.getSigners();

    // Deploy AccessControl
    const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
    accessControl = await upgrades.deployProxy(
      LoanAccessControl,
      [admin.address],
      { kind: "uups" }
    );
    await accessControl.waitForDeployment();

    // Deploy LoanOracle
    const LoanOracle = await ethers.getContractFactory("LoanOracle");
    loanOracle = await upgrades.deployProxy(
      LoanOracle,
      [
        await accessControl.getAddress(),
        admin.address
      ],
      { kind: "uups" }
    );
    await loanOracle.waitForDeployment();

    // Grant oracle role
    await loanOracle.grantRole(ORACLE_ROLE, oracle1.address);
  });

  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await loanOracle.VERSION()).to.equal(1);
    });

    it("Should set default data staleness", async function () {
      expect(await loanOracle.maxDataStalenessSeconds()).to.equal(3600); // 1 hour
    });
  });

  describe("AI Score Submission", function () {
    const applicationId = ethers.keccak256(ethers.toUtf8Bytes("APP001"));

    it("Should submit AI score successfully", async function () {
      const eligibilityScore = 78;
      const riskLevel = 1; // Medium
      const analysisHash = ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS"));
      const recommendedAmount = ethers.parseEther("10000");
      const recommendedTerm = 12;

      await expect(
        loanOracle.connect(oracle1).submitAIScore(
          applicationId,
          eligibilityScore,
          riskLevel,
          analysisHash,
          recommendedAmount,
          recommendedTerm
        )
      ).to.emit(loanOracle, "AIScoreSubmitted");

      const scoreData = await loanOracle.getAIScore(applicationId);
      expect(scoreData.eligibilityScore).to.equal(eligibilityScore);
      expect(scoreData.riskLevel).to.equal(riskLevel);
      expect(scoreData.isValid).to.be.true;
    });

    it("Should reject score above 100", async function () {
      await expect(
        loanOracle.connect(oracle1).submitAIScore(
          applicationId,
          101, // Invalid score
          1,
          ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS")),
          ethers.parseEther("10000"),
          12
        )
      ).to.be.revertedWithCustomError(loanOracle, "InvalidScore");
    });

    it("Should not allow non-oracle to submit", async function () {
      await expect(
        loanOracle.connect(other).submitAIScore(
          applicationId,
          78,
          1,
          ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS")),
          ethers.parseEther("10000"),
          12
        )
      ).to.be.reverted;
    });

    it("Should allow score update", async function () {
      // First submission
      await loanOracle.connect(oracle1).submitAIScore(
        applicationId, 70, 1,
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS1")),
        ethers.parseEther("10000"), 12
      );

      // Update with new score
      await loanOracle.connect(oracle1).submitAIScore(
        applicationId, 85, 0,
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS2")),
        ethers.parseEther("15000"), 18
      );

      const scoreData = await loanOracle.getAIScore(applicationId);
      expect(scoreData.eligibilityScore).to.equal(85);
    });
  });

  describe("Payment Confirmation", function () {
    const paymentId = ethers.keccak256(ethers.toUtf8Bytes("PAY001"));
    const transactionHash = ethers.keccak256(ethers.toUtf8Bytes("TXHASH"));

    it("Should confirm payment successfully", async function () {
      const amount = ethers.parseEther("1000");
      const method = 0; // BankTransfer
      const externalRef = ethers.keccak256(ethers.toUtf8Bytes("EXTREF"));

      await expect(
        loanOracle.connect(oracle1).confirmPayment(
          paymentId,
          amount,
          method,
          transactionHash,
          externalRef
        )
      ).to.emit(loanOracle, "PaymentConfirmed");

      const confirmation = await loanOracle.getPaymentConfirmation(paymentId);
      expect(confirmation.amount).to.equal(amount);
      expect(confirmation.isConfirmed).to.be.true;
    });

    it("Should not confirm duplicate payment", async function () {
      const amount = ethers.parseEther("1000");
      
      await loanOracle.connect(oracle1).confirmPayment(
        paymentId,
        amount,
        0,
        transactionHash,
        ethers.keccak256(ethers.toUtf8Bytes("EXTREF"))
      );

      await expect(
        loanOracle.connect(oracle1).confirmPayment(
          paymentId,
          amount,
          0,
          transactionHash,
          ethers.keccak256(ethers.toUtf8Bytes("EXTREF2"))
        )
      ).to.be.revertedWithCustomError(loanOracle, "PaymentAlreadyConfirmed");
    });
  });

  describe("Disbursement Confirmation", function () {
    const disbursementId = ethers.keccak256(ethers.toUtf8Bytes("DISB001"));
    const transactionHash = ethers.keccak256(ethers.toUtf8Bytes("TXHASH"));

    it("Should confirm disbursement successfully", async function () {
      const amount = ethers.parseEther("10000");
      const externalRef = ethers.keccak256(ethers.toUtf8Bytes("EXTREF"));

      await expect(
        loanOracle.connect(oracle1).confirmDisbursement(
          disbursementId,
          amount,
          transactionHash,
          externalRef
        )
      ).to.emit(loanOracle, "DisbursementConfirmed");

      const confirmation = await loanOracle.getDisbursementConfirmation(disbursementId);
      expect(confirmation.amount).to.equal(amount);
      expect(confirmation.isConfirmed).to.be.true;
    });
  });

  describe("Data Staleness", function () {
    const applicationId = ethers.keccak256(ethers.toUtf8Bytes("APP001"));

    it("Should return valid score within staleness window", async function () {
      await loanOracle.connect(oracle1).submitAIScore(
        applicationId, 78, 1,
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS")),
        ethers.parseEther("10000"), 12
      );

      const isStale = await loanOracle.isScoreStale(applicationId);
      expect(isStale).to.be.false;
    });

    it("Should detect stale score", async function () {
      await loanOracle.connect(oracle1).submitAIScore(
        applicationId, 78, 1,
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS")),
        ethers.parseEther("10000"), 12
      );

      // Fast forward beyond staleness window
      await time.increase(3601);

      const isStale = await loanOracle.isScoreStale(applicationId);
      expect(isStale).to.be.true;
    });

    it("Should allow admin to update staleness threshold", async function () {
      await loanOracle.connect(admin).setMaxDataStaleness(7200); // 2 hours
      expect(await loanOracle.maxDataStalenessSeconds()).to.equal(7200);
    });
  });

  describe("Document Verification", function () {
    const documentId = ethers.keccak256(ethers.toUtf8Bytes("DOC001"));

    it("Should submit document verification", async function () {
      const documentHash = ethers.keccak256(ethers.toUtf8Bytes("DOCHASH"));
      const verificationStatus = 1; // Verified
      const confidence = 95;

      await expect(
        loanOracle.connect(oracle1).submitDocumentVerification(
          documentId,
          documentHash,
          verificationStatus,
          confidence
        )
      ).to.emit(loanOracle, "DocumentVerified");

      const verification = await loanOracle.getDocumentVerification(documentId);
      expect(verification.status).to.equal(verificationStatus);
      expect(verification.confidence).to.equal(confidence);
    });

    it("Should reject confidence above 100", async function () {
      await expect(
        loanOracle.connect(oracle1).submitDocumentVerification(
          documentId,
          ethers.keccak256(ethers.toUtf8Bytes("DOCHASH")),
          1,
          101 // Invalid confidence
        )
      ).to.be.revertedWithCustomError(loanOracle, "InvalidConfidence");
    });
  });

  describe("Oracle Management", function () {
    it("Should register new oracle", async function () {
      await loanOracle.connect(admin).grantRole(ORACLE_ROLE, oracle2.address);
      expect(await loanOracle.hasRole(ORACLE_ROLE, oracle2.address)).to.be.true;
    });

    it("Should revoke oracle access", async function () {
      await loanOracle.connect(admin).revokeRole(ORACLE_ROLE, oracle1.address);
      expect(await loanOracle.hasRole(ORACLE_ROLE, oracle1.address)).to.be.false;
    });

    it("Should track oracle submissions", async function () {
      const applicationId = ethers.keccak256(ethers.toUtf8Bytes("APP001"));
      
      await loanOracle.connect(oracle1).submitAIScore(
        applicationId, 78, 1,
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS")),
        ethers.parseEther("10000"), 12
      );

      const scoreData = await loanOracle.getAIScore(applicationId);
      expect(scoreData.submittedBy).to.equal(oracle1.address);
    });
  });

  describe("Price Feed (Future Extension)", function () {
    it("Should have placeholder for exchange rate updates", async function () {
      // This tests that the contract has the capability for future price feeds
      // For currency conversion if needed
      const rate = await loanOracle.getExchangeRate("PHP", "USD");
      // Default should be 0 or some base rate
      expect(rate).to.equal(0); // Not yet implemented
    });
  });

  describe("Emergency Controls", function () {
    it("Should invalidate score", async function () {
      const applicationId = ethers.keccak256(ethers.toUtf8Bytes("APP001"));
      
      await loanOracle.connect(oracle1).submitAIScore(
        applicationId, 78, 1,
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS")),
        ethers.parseEther("10000"), 12
      );

      await loanOracle.connect(admin).invalidateScore(applicationId);

      const scoreData = await loanOracle.getAIScore(applicationId);
      expect(scoreData.isValid).to.be.false;
    });

    it("Should not allow non-admin to invalidate", async function () {
      const applicationId = ethers.keccak256(ethers.toUtf8Bytes("APP001"));
      
      await loanOracle.connect(oracle1).submitAIScore(
        applicationId, 78, 1,
        ethers.keccak256(ethers.toUtf8Bytes("ANALYSIS")),
        ethers.parseEther("10000"), 12
      );

      await expect(
        loanOracle.connect(other).invalidateScore(applicationId)
      ).to.be.reverted;
    });
  });
});
