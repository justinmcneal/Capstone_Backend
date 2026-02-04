// Test suite for LoanAccessControl contract - Aligned with actual contract implementation
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

describe("LoanAccessControl", function () {
  let accessControl;
  let admin, officer1, officer2, borrower1, borrower2, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const BORROWER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("BORROWER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
  const PAUSER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("PAUSER_ROLE"));
  const UPGRADER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("UPGRADER_ROLE"));

  beforeEach(async function () {
    [admin, officer1, officer2, borrower1, borrower2, other] = await ethers.getSigners();

    const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
    accessControl = await upgrades.deployProxy(
      LoanAccessControl,
      [admin.address],
      { kind: "uups" }
    );
    await accessControl.waitForDeployment();
  });

  describe("Deployment", function () {
    it("Should set deployer as admin", async function () {
      expect(await accessControl.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
    });

    it("Should set correct version", async function () {
      expect(await accessControl.VERSION()).to.equal(1);
    });

    it("Should not be paused initially", async function () {
      expect(await accessControl.paused()).to.be.false;
    });

    it("Should grant admin the pauser role", async function () {
      expect(await accessControl.hasRole(PAUSER_ROLE, admin.address)).to.be.true;
    });

    it("Should grant admin the upgrader role", async function () {
      expect(await accessControl.hasRole(UPGRADER_ROLE, admin.address)).to.be.true;
    });
  });

  describe("Officer Registration", function () {
    const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));

    it("Should register officer successfully", async function () {
      await expect(
        accessControl.registerOfficer(officer1.address, employeeIdHash)
      ).to.emit(accessControl, "OfficerRegistered");

      expect(await accessControl.hasRole(LOAN_OFFICER_ROLE, officer1.address)).to.be.true;
    });

    it("Should track officer details via getOfficerInfo", async function () {
      await accessControl.registerOfficer(officer1.address, employeeIdHash);
      
      const [empIdHash, isActive, registeredAt] = await accessControl.getOfficerInfo(officer1.address);
      expect(empIdHash).to.equal(employeeIdHash);
      expect(isActive).to.be.true;
      expect(registeredAt).to.be.gt(0);
    });

    it("Should not allow non-admin to register officer", async function () {
      await expect(
        accessControl.connect(other).registerOfficer(officer1.address, employeeIdHash)
      ).to.be.reverted;
    });

    it("Should not allow duplicate registration", async function () {
      await accessControl.registerOfficer(officer1.address, employeeIdHash);
      
      await expect(
        accessControl.registerOfficer(officer1.address, employeeIdHash)
      ).to.be.revertedWith("LoanAccessControl: already registered");
    });

    it("Should not allow zero address", async function () {
      await expect(
        accessControl.registerOfficer(ethers.ZeroAddress, employeeIdHash)
      ).to.be.revertedWith("LoanAccessControl: zero address");
    });

    it("Should not allow empty employee ID", async function () {
      await expect(
        accessControl.registerOfficer(officer1.address, ethers.ZeroHash)
      ).to.be.revertedWith("LoanAccessControl: empty employee ID");
    });
  });

  describe("Officer Deactivation", function () {
    const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));

    beforeEach(async function () {
      await accessControl.registerOfficer(officer1.address, employeeIdHash);
    });

    it("Should deactivate officer successfully", async function () {
      await expect(
        accessControl.deactivateOfficer(officer1.address)
      ).to.emit(accessControl, "OfficerDeactivated");

      const [, isActive,] = await accessControl.getOfficerInfo(officer1.address);
      expect(isActive).to.be.false;
    });

    it("Should not affect role on deactivation", async function () {
      await accessControl.deactivateOfficer(officer1.address);
      // Role is still there, just marked inactive
      expect(await accessControl.hasRole(LOAN_OFFICER_ROLE, officer1.address)).to.be.true;
    });

    it("Should reactivate officer", async function () {
      await accessControl.deactivateOfficer(officer1.address);
      
      await expect(
        accessControl.reactivateOfficer(officer1.address)
      ).to.emit(accessControl, "OfficerReactivated");

      const [, isActive,] = await accessControl.getOfficerInfo(officer1.address);
      expect(isActive).to.be.true;
    });

    it("Should not deactivate already inactive officer", async function () {
      await accessControl.deactivateOfficer(officer1.address);
      
      await expect(
        accessControl.deactivateOfficer(officer1.address)
      ).to.be.revertedWith("LoanAccessControl: already inactive");
    });

    it("Should not reactivate already active officer", async function () {
      await expect(
        accessControl.reactivateOfficer(officer1.address)
      ).to.be.revertedWith("LoanAccessControl: already active");
    });
  });

  describe("Borrower Registration", function () {
    const customerIdHash = ethers.keccak256(ethers.toUtf8Bytes("CUST001"));

    beforeEach(async function () {
      // Grant SYSTEM_ROLE to admin for borrower registration
      await accessControl.grantRole(SYSTEM_ROLE, admin.address);
    });

    it("Should register borrower successfully", async function () {
      await expect(
        accessControl.registerBorrower(borrower1.address, customerIdHash)
      ).to.emit(accessControl, "BorrowerRegistered");

      expect(await accessControl.hasRole(BORROWER_ROLE, borrower1.address)).to.be.true;
    });

    it("Should track borrower details via getBorrowerInfo", async function () {
      await accessControl.registerBorrower(borrower1.address, customerIdHash);
      
      const [custIdHash, registeredAt] = await accessControl.getBorrowerInfo(borrower1.address);
      expect(custIdHash).to.equal(customerIdHash);
      expect(registeredAt).to.be.gt(0);
    });

    it("Should not allow non-system to register borrower", async function () {
      await expect(
        accessControl.connect(other).registerBorrower(borrower1.address, customerIdHash)
      ).to.be.reverted;
    });

    it("Should not allow duplicate borrower registration", async function () {
      await accessControl.registerBorrower(borrower1.address, customerIdHash);
      
      await expect(
        accessControl.registerBorrower(borrower1.address, customerIdHash)
      ).to.be.revertedWith("LoanAccessControl: already registered");
    });
  });

  describe("Pause Functionality", function () {
    it("Should pause via emergencyPause when admin calls", async function () {
      await expect(
        accessControl.emergencyPause("System maintenance")
      ).to.emit(accessControl, "EmergencyPaused");

      expect(await accessControl.paused()).to.be.true;
    });

    it("Should store pause reason", async function () {
      await accessControl.emergencyPause("Security issue detected");
      
      expect(await accessControl.pauseReason()).to.equal("Security issue detected");
      expect(await accessControl.pausedBy()).to.equal(admin.address);
    });

    it("Should unpause when admin calls", async function () {
      await accessControl.emergencyPause("Testing");
      
      await accessControl.unpause();

      expect(await accessControl.paused()).to.be.false;
    });

    it("Should not allow non-pauser to pause", async function () {
      await expect(
        accessControl.connect(other).emergencyPause("Unauthorized")
      ).to.be.reverted;
    });

    it("Should clear pause info after unpause", async function () {
      await accessControl.emergencyPause("Testing");
      await accessControl.unpause();

      expect(await accessControl.pauseReason()).to.equal("");
      expect(await accessControl.pausedBy()).to.equal(ethers.ZeroAddress);
    });
  });

  describe("Validation Functions", function () {
    const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));
    const customerIdHash = ethers.keccak256(ethers.toUtf8Bytes("CUST001"));

    beforeEach(async function () {
      await accessControl.registerOfficer(officer1.address, employeeIdHash);
      await accessControl.grantRole(SYSTEM_ROLE, admin.address);
      await accessControl.registerBorrower(borrower1.address, customerIdHash);
    });

    it("Should validate active officer", async function () {
      expect(await accessControl.isActiveOfficer(officer1.address)).to.be.true;
    });

    it("Should return false for deactivated officer", async function () {
      await accessControl.deactivateOfficer(officer1.address);
      expect(await accessControl.isActiveOfficer(officer1.address)).to.be.false;
    });

    it("Should validate borrower via isBorrower", async function () {
      expect(await accessControl.isBorrower(borrower1.address)).to.be.true;
    });

    it("Should return false for non-borrower", async function () {
      expect(await accessControl.isBorrower(other.address)).to.be.false;
    });

    it("Should return false for non-officer", async function () {
      expect(await accessControl.isActiveOfficer(other.address)).to.be.false;
    });
  });

  describe("Role Management", function () {
    it("Should allow admin to grant SYSTEM_ROLE", async function () {
      await accessControl.grantRole(SYSTEM_ROLE, other.address);
      expect(await accessControl.hasRole(SYSTEM_ROLE, other.address)).to.be.true;
    });

    it("Should not allow non-admin to grant roles", async function () {
      await expect(
        accessControl.connect(other).grantRole(SYSTEM_ROLE, borrower1.address)
      ).to.be.reverted;
    });
  });

  describe("Upgrade Authorization", function () {
    it("Should only allow UPGRADER_ROLE to upgrade", async function () {
      // Admin has UPGRADER_ROLE
      expect(await accessControl.hasRole(UPGRADER_ROLE, admin.address)).to.be.true;
      
      // Other does not
      expect(await accessControl.hasRole(UPGRADER_ROLE, other.address)).to.be.false;
    });

    it("Should upgrade successfully when admin calls", async function () {
      const LoanAccessControlV2 = await ethers.getContractFactory("LoanAccessControl");
      
      // Should succeed with upgrader role
      const upgraded = await upgrades.upgradeProxy(
        await accessControl.getAddress(),
        LoanAccessControlV2
      );
      
      expect(await upgraded.VERSION()).to.equal(1);
    });
  });
});
