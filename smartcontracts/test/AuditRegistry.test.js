// Test suite for AuditRegistry contract
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

describe("AuditRegistry", function () {
  let auditRegistry;
  let admin, logger1, logger2, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOGGER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOGGER_ROLE"));

  beforeEach(async function () {
    [admin, logger1, logger2, other] = await ethers.getSigners();

    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    auditRegistry = await upgrades.deployProxy(
      AuditRegistry,
      [admin.address],
      { kind: "uups" }
    );
    await auditRegistry.waitForDeployment();

    // Grant logger role
    await auditRegistry.grantLoggerRole(logger1.address);
  });

  describe("Deployment", function () {
    it("Should set correct version", async function () {
      expect(await auditRegistry.VERSION()).to.equal(1);
    });

    it("Should set admin role", async function () {
      expect(await auditRegistry.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
    });
  });

  describe("Logger Management", function () {
    it("Should grant logger role", async function () {
      await expect(
        auditRegistry.grantLoggerRole(logger2.address)
      ).to.emit(auditRegistry, "LoggerAdded")
        .withArgs(logger2.address);

      expect(await auditRegistry.hasRole(LOGGER_ROLE, logger2.address)).to.be.true;
    });

    it("Should revoke logger role", async function () {
      await expect(
        auditRegistry.revokeLoggerRole(logger1.address)
      ).to.emit(auditRegistry, "LoggerRemoved")
        .withArgs(logger1.address);

      expect(await auditRegistry.hasRole(LOGGER_ROLE, logger1.address)).to.be.false;
    });

    it("Should not allow non-admin to grant logger role", async function () {
      await expect(
        auditRegistry.connect(other).grantLoggerRole(logger2.address)
      ).to.be.reverted;
    });
  });

  describe("Audit Logging", function () {
    const entityId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const action = ethers.keccak256(ethers.toUtf8Bytes("LOAN_CREATED"));
    const previousStateHash = ethers.ZeroHash;
    const newStateHash = ethers.keccak256(ethers.toUtf8Bytes("STATE1"));
    const metadataHash = ethers.keccak256(ethers.toUtf8Bytes("METADATA"));

    it("Should log audit entry", async function () {
      await expect(
        auditRegistry.connect(logger1).logAuditEntry(
          entityId,
          action,
          previousStateHash,
          newStateHash,
          metadataHash
        )
      ).to.emit(auditRegistry, "AuditEntryLogged");
    });

    it("Should increment entry count", async function () {
      await auditRegistry.connect(logger1).logAuditEntry(
        entityId, action, previousStateHash, newStateHash, metadataHash
      );

      const count = await auditRegistry.getEntryCount(entityId);
      expect(count).to.equal(1);
    });

    it("Should store entry correctly", async function () {
      await auditRegistry.connect(logger1).logAuditEntry(
        entityId, action, previousStateHash, newStateHash, metadataHash
      );

      const entries = await auditRegistry.getEntries(entityId, 0, 1);
      expect(entries.length).to.equal(1);
      expect(entries[0].action).to.equal(action);
      expect(entries[0].actor).to.equal(logger1.address);
    });

    it("Should not allow non-logger to log", async function () {
      await expect(
        auditRegistry.connect(other).logAuditEntry(
          entityId, action, previousStateHash, newStateHash, metadataHash
        )
      ).to.be.reverted;
    });
  });

  describe("State Verification", function () {
    const entityId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const action = ethers.keccak256(ethers.toUtf8Bytes("LOAN_CREATED"));
    const previousStateHash = ethers.ZeroHash;
    const newStateHash = ethers.keccak256(ethers.toUtf8Bytes("STATE1"));
    const metadataHash = ethers.keccak256(ethers.toUtf8Bytes("METADATA"));

    beforeEach(async function () {
      await auditRegistry.connect(logger1).logAuditEntry(
        entityId, action, previousStateHash, newStateHash, metadataHash
      );
    });

    it("Should get current state hash", async function () {
      const currentState = await auditRegistry.getCurrentStateHash(entityId);
      expect(currentState).to.equal(newStateHash);
    });

    it("Should verify valid state", async function () {
      const isValid = await auditRegistry.verifyState(entityId, newStateHash);
      expect(isValid).to.be.true;
    });

    it("Should reject invalid state", async function () {
      const wrongHash = ethers.keccak256(ethers.toUtf8Bytes("WRONG_STATE"));
      const isValid = await auditRegistry.verifyState(entityId, wrongHash);
      expect(isValid).to.be.false;
    });
  });

  describe("Batch Logging", function () {
    it("Should log multiple entries in batch", async function () {
      const entityId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
      
      const entries = [
        {
          entityId,
          action: ethers.keccak256(ethers.toUtf8Bytes("ACTION1")),
          previousStateHash: ethers.ZeroHash,
          newStateHash: ethers.keccak256(ethers.toUtf8Bytes("STATE1")),
          metadataHash: ethers.keccak256(ethers.toUtf8Bytes("META1"))
        },
        {
          entityId,
          action: ethers.keccak256(ethers.toUtf8Bytes("ACTION2")),
          previousStateHash: ethers.keccak256(ethers.toUtf8Bytes("STATE1")),
          newStateHash: ethers.keccak256(ethers.toUtf8Bytes("STATE2")),
          metadataHash: ethers.keccak256(ethers.toUtf8Bytes("META2"))
        }
      ];

      await auditRegistry.connect(logger1).logBatchEntries(entries);

      const count = await auditRegistry.getEntryCount(entityId);
      expect(count).to.equal(2);
    });

    it("Should reject empty batch", async function () {
      await expect(
        auditRegistry.connect(logger1).logBatchEntries([])
      ).to.be.revertedWithCustomError(auditRegistry, "EmptyBatch");
    });
  });

  describe("Entry Retrieval", function () {
    const entityId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));

    beforeEach(async function () {
      // Log 5 entries
      for (let i = 0; i < 5; i++) {
        await auditRegistry.connect(logger1).logAuditEntry(
          entityId,
          ethers.keccak256(ethers.toUtf8Bytes(`ACTION${i}`)),
          ethers.ZeroHash,
          ethers.keccak256(ethers.toUtf8Bytes(`STATE${i}`)),
          ethers.keccak256(ethers.toUtf8Bytes(`META${i}`))
        );
      }
    });

    it("Should retrieve paginated entries", async function () {
      const page1 = await auditRegistry.getEntries(entityId, 0, 2);
      expect(page1.length).to.equal(2);

      const page2 = await auditRegistry.getEntries(entityId, 2, 2);
      expect(page2.length).to.equal(2);

      const page3 = await auditRegistry.getEntries(entityId, 4, 2);
      expect(page3.length).to.equal(1);
    });

    it("Should get latest entry", async function () {
      const latest = await auditRegistry.getLatestEntry(entityId);
      expect(latest.action).to.equal(ethers.keccak256(ethers.toUtf8Bytes("ACTION4")));
    });

    it("Should return empty for non-existent entity", async function () {
      const unknownEntity = ethers.keccak256(ethers.toUtf8Bytes("UNKNOWN"));
      const count = await auditRegistry.getEntryCount(unknownEntity);
      expect(count).to.equal(0);
    });
  });

  describe("Chain Integrity", function () {
    const entityId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));

    it("Should track state transitions", async function () {
      const state1 = ethers.keccak256(ethers.toUtf8Bytes("STATE1"));
      const state2 = ethers.keccak256(ethers.toUtf8Bytes("STATE2"));
      const state3 = ethers.keccak256(ethers.toUtf8Bytes("STATE3"));

      await auditRegistry.connect(logger1).logAuditEntry(
        entityId,
        ethers.keccak256(ethers.toUtf8Bytes("CREATE")),
        ethers.ZeroHash,
        state1,
        ethers.ZeroHash
      );

      await auditRegistry.connect(logger1).logAuditEntry(
        entityId,
        ethers.keccak256(ethers.toUtf8Bytes("UPDATE")),
        state1,
        state2,
        ethers.ZeroHash
      );

      await auditRegistry.connect(logger1).logAuditEntry(
        entityId,
        ethers.keccak256(ethers.toUtf8Bytes("FINALIZE")),
        state2,
        state3,
        ethers.ZeroHash
      );

      // Verify final state
      const currentState = await auditRegistry.getCurrentStateHash(entityId);
      expect(currentState).to.equal(state3);
    });
  });

  describe("Audit Statistics", function () {
    it("Should track total entries logged", async function () {
      const entityId1 = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
      const entityId2 = ethers.keccak256(ethers.toUtf8Bytes("LOAN002"));

      await auditRegistry.connect(logger1).logAuditEntry(
        entityId1,
        ethers.keccak256(ethers.toUtf8Bytes("ACTION1")),
        ethers.ZeroHash,
        ethers.keccak256(ethers.toUtf8Bytes("STATE1")),
        ethers.ZeroHash
      );

      await auditRegistry.connect(logger1).logAuditEntry(
        entityId2,
        ethers.keccak256(ethers.toUtf8Bytes("ACTION1")),
        ethers.ZeroHash,
        ethers.keccak256(ethers.toUtf8Bytes("STATE1")),
        ethers.ZeroHash
      );

      const stats = await auditRegistry.getStats();
      expect(stats._totalEntries).to.equal(2);
      expect(stats._totalEntities).to.equal(2);
    });
  });
});
