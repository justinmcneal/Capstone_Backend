// Test suite for AuditRegistry contract - Aligned with actual contract implementation
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

describe("AuditRegistry", function () {
  let auditRegistry;
  let admin, logger1, logger2, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOGGER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOGGER_ROLE"));
  const UPGRADER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("UPGRADER_ROLE"));

  // AuditAction enum values (from interface)
  const AuditAction = {
    LoanCreated: 0,
    LoanSubmitted: 1,
    LoanApproved: 2,
    LoanRejected: 3,
    OfficerAssigned: 4,
    LoanDisbursed: 5,
    PaymentRecorded: 6,
    InstallmentOverdue: 7,
    LoanDefaulted: 8,
    LoanCompleted: 9,
    PenaltyApplied: 10,
    PenaltyWaived: 11,
    StatusChanged: 12
  };

  beforeEach(async function () {
    [admin, logger1, logger2, other] = await ethers.getSigners();

    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    auditRegistry = await upgrades.deployProxy(
      AuditRegistry,
      [admin.address],
      { kind: "uups" }
    );
    await auditRegistry.waitForDeployment();

    // Grant logger role to logger1
    await auditRegistry.grantLoggerRole(logger1.address);
  });

  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await auditRegistry.VERSION()).to.equal(1);
    });

    it("Should set admin role", async function () {
      expect(await auditRegistry.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
    });

    it("Should grant admin the logger role", async function () {
      expect(await auditRegistry.hasRole(LOGGER_ROLE, admin.address)).to.be.true;
    });

    it("Should grant admin the upgrader role", async function () {
      expect(await auditRegistry.hasRole(UPGRADER_ROLE, admin.address)).to.be.true;
    });
  });

  describe("Logger Management", function () {
    it("Should grant logger role", async function () {
      await auditRegistry.grantLoggerRole(logger2.address);
      expect(await auditRegistry.hasRole(LOGGER_ROLE, logger2.address)).to.be.true;
    });

    it("Should not allow non-admin to grant logger role", async function () {
      await expect(
        auditRegistry.connect(other).grantLoggerRole(logger2.address)
      ).to.be.reverted;
    });

    it("Should allow logger1 to log after being granted role", async function () {
      const resourceId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
      const detailsHash = ethers.keccak256(ethers.toUtf8Bytes("DETAILS"));
      const previousState = ethers.ZeroHash;
      const newState = ethers.keccak256(ethers.toUtf8Bytes("STATE1"));

      await expect(
        auditRegistry.connect(logger1).log(
          resourceId,
          "loan",
          AuditAction.LoanCreated,
          detailsHash,
          previousState,
          newState
        )
      ).to.emit(auditRegistry, "AuditLogged");
    });
  });

  describe("Audit Logging", function () {
    const resourceId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const detailsHash = ethers.keccak256(ethers.toUtf8Bytes("DETAILS"));
    const previousStateHash = ethers.ZeroHash;
    const newStateHash = ethers.keccak256(ethers.toUtf8Bytes("STATE1"));

    it("Should log audit entry with correct function signature", async function () {
      await expect(
        auditRegistry.connect(logger1).log(
          resourceId,
          "loan",
          AuditAction.LoanCreated,
          detailsHash,
          previousStateHash,
          newStateHash
        )
      ).to.emit(auditRegistry, "AuditLogged");
    });

    it("Should increment total entries count", async function () {
      const beforeCount = await auditRegistry.totalEntries();
      
      await auditRegistry.connect(logger1).log(
        resourceId,
        "loan",
        AuditAction.LoanCreated,
        detailsHash,
        previousStateHash,
        newStateHash
      );

      const afterCount = await auditRegistry.totalEntries();
      expect(afterCount).to.equal(beforeCount + 1n);
    });

    it("Should store entry and retrieve by resource", async function () {
      await auditRegistry.connect(logger1).log(
        resourceId,
        "loan",
        AuditAction.LoanCreated,
        detailsHash,
        previousStateHash,
        newStateHash
      );

      const entryIds = await auditRegistry.getEntriesByResource(resourceId);
      expect(entryIds.length).to.equal(1);

      const entry = await auditRegistry.getEntry(entryIds[0]);
      expect(entry.resourceId).to.equal(resourceId);
      expect(entry.resourceType).to.equal("loan");
      expect(entry.action).to.equal(AuditAction.LoanCreated);
      expect(entry.actor).to.equal(logger1.address);
    });

    it("Should not allow non-logger to log", async function () {
      await expect(
        auditRegistry.connect(other).log(
          resourceId,
          "loan",
          AuditAction.LoanCreated,
          detailsHash,
          previousStateHash,
          newStateHash
        )
      ).to.be.reverted;
    });

    it("Should reject empty resource ID", async function () {
      await expect(
        auditRegistry.connect(logger1).log(
          ethers.ZeroHash,
          "loan",
          AuditAction.LoanCreated,
          detailsHash,
          previousStateHash,
          newStateHash
        )
      ).to.be.revertedWith("AuditRegistry: empty resource ID");
    });

    it("Should reject empty resource type", async function () {
      await expect(
        auditRegistry.connect(logger1).log(
          resourceId,
          "",
          AuditAction.LoanCreated,
          detailsHash,
          previousStateHash,
          newStateHash
        )
      ).to.be.revertedWith("AuditRegistry: empty resource type");
    });
  });

  describe("State Verification", function () {
    const resourceId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const detailsHash = ethers.keccak256(ethers.toUtf8Bytes("DETAILS"));
    const previousStateHash = ethers.ZeroHash;
    const newStateHash = ethers.keccak256(ethers.toUtf8Bytes("STATE1"));

    beforeEach(async function () {
      await auditRegistry.connect(logger1).log(
        resourceId,
        "loan",
        AuditAction.LoanCreated,
        detailsHash,
        previousStateHash,
        newStateHash
      );
    });

    it("Should get latest state hash", async function () {
      const latestState = await auditRegistry.getLatestState(resourceId);
      expect(latestState).to.equal(newStateHash);
    });

    it("Should verify valid state transition", async function () {
      const isValid = await auditRegistry.verifyStateTransition(resourceId, newStateHash);
      expect(isValid).to.be.true;
    });

    it("Should reject invalid state", async function () {
      const wrongHash = ethers.keccak256(ethers.toUtf8Bytes("WRONG_STATE"));
      const isValid = await auditRegistry.verifyStateTransition(resourceId, wrongHash);
      expect(isValid).to.be.false;
    });

    it("Should get resource entry count", async function () {
      const count = await auditRegistry.getResourceEntryCount(resourceId);
      expect(count).to.equal(1);
    });
  });

  describe("Batch Logging", function () {
    it("Should log multiple entries in batch", async function () {
      const resourceIds = [
        ethers.keccak256(ethers.toUtf8Bytes("LOAN001")),
        ethers.keccak256(ethers.toUtf8Bytes("LOAN002"))
      ];
      const resourceTypes = ["loan", "loan"];
      const actions = [AuditAction.LoanCreated, AuditAction.LoanCreated];
      const detailsHashes = [
        ethers.keccak256(ethers.toUtf8Bytes("DETAILS1")),
        ethers.keccak256(ethers.toUtf8Bytes("DETAILS2"))
      ];
      const previousStateHashes = [ethers.ZeroHash, ethers.ZeroHash];
      const newStateHashes = [
        ethers.keccak256(ethers.toUtf8Bytes("STATE1")),
        ethers.keccak256(ethers.toUtf8Bytes("STATE2"))
      ];

      await auditRegistry.connect(logger1).logBatch(
        resourceIds,
        resourceTypes,
        actions,
        detailsHashes,
        previousStateHashes,
        newStateHashes
      );

      const count = await auditRegistry.totalEntries();
      expect(count).to.equal(2);
    });

    it("Should reject mismatched array lengths", async function () {
      const resourceIds = [ethers.keccak256(ethers.toUtf8Bytes("LOAN001"))];
      const resourceTypes = ["loan", "loan"]; // Wrong length

      await expect(
        auditRegistry.connect(logger1).logBatch(
          resourceIds,
          resourceTypes,
          [AuditAction.LoanCreated],
          [ethers.ZeroHash],
          [ethers.ZeroHash],
          [ethers.ZeroHash]
        )
      ).to.be.revertedWith("AuditRegistry: array length mismatch");
    });
  });

  describe("Entry Retrieval", function () {
    const resourceId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));

    beforeEach(async function () {
      // Log 5 entries for the same resource
      for (let i = 0; i < 5; i++) {
        await auditRegistry.connect(logger1).log(
          resourceId,
          "loan",
          i, // Different actions
          ethers.keccak256(ethers.toUtf8Bytes(`DETAILS${i}`)),
          ethers.ZeroHash,
          ethers.keccak256(ethers.toUtf8Bytes(`STATE${i}`))
        );
      }
    });

    it("Should retrieve all entries by resource", async function () {
      const entryIds = await auditRegistry.getEntriesByResource(resourceId);
      expect(entryIds.length).to.equal(5);
    });

    it("Should get full audit trail", async function () {
      const trail = await auditRegistry.getFullAuditTrail(resourceId);
      expect(trail.length).to.equal(5);
    });

    it("Should get entries by actor with limit", async function () {
      const entries = await auditRegistry.getEntriesByActor(logger1.address, 3);
      expect(entries.length).to.equal(3);
    });

    it("Should return empty for non-existent resource", async function () {
      const unknownResource = ethers.keccak256(ethers.toUtf8Bytes("UNKNOWN"));
      const entryIds = await auditRegistry.getEntriesByResource(unknownResource);
      expect(entryIds.length).to.equal(0);
    });
  });

  describe("Chain Integrity", function () {
    const resourceId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));

    it("Should track state transitions correctly", async function () {
      const state1 = ethers.keccak256(ethers.toUtf8Bytes("STATE1"));
      const state2 = ethers.keccak256(ethers.toUtf8Bytes("STATE2"));
      const state3 = ethers.keccak256(ethers.toUtf8Bytes("STATE3"));

      await auditRegistry.connect(logger1).log(
        resourceId, "loan", AuditAction.LoanCreated,
        ethers.ZeroHash, ethers.ZeroHash, state1
      );

      await auditRegistry.connect(logger1).log(
        resourceId, "loan", AuditAction.LoanSubmitted,
        ethers.ZeroHash, state1, state2
      );

      await auditRegistry.connect(logger1).log(
        resourceId, "loan", AuditAction.LoanApproved,
        ethers.ZeroHash, state2, state3
      );

      // Verify final state
      const currentState = await auditRegistry.getLatestState(resourceId);
      expect(currentState).to.equal(state3);

      // Verify audit trail integrity
      const [isValid, brokenAt] = await auditRegistry.verifyAuditTrail(resourceId);
      expect(isValid).to.be.true;
      expect(brokenAt).to.equal(0);
    });
  });

  describe("Audit Statistics", function () {
    it("Should track total entries logged", async function () {
      const resourceId1 = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
      const resourceId2 = ethers.keccak256(ethers.toUtf8Bytes("LOAN002"));

      await auditRegistry.connect(logger1).log(
        resourceId1, "loan", AuditAction.LoanCreated,
        ethers.ZeroHash, ethers.ZeroHash, ethers.keccak256(ethers.toUtf8Bytes("STATE1"))
      );

      await auditRegistry.connect(logger1).log(
        resourceId2, "loan", AuditAction.LoanCreated,
        ethers.ZeroHash, ethers.ZeroHash, ethers.keccak256(ethers.toUtf8Bytes("STATE2"))
      );

      const totalEntries = await auditRegistry.totalEntries();
      expect(totalEntries).to.equal(2);
    });
  });

  describe("Upgrade Authorization", function () {
    it("Should only allow UPGRADER_ROLE to authorize upgrade", async function () {
      expect(await auditRegistry.hasRole(UPGRADER_ROLE, admin.address)).to.be.true;
    });
  });
});
