// Test suite for LoanAccessControl contract
const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

describe("LoanAccessControl", function () {
  let accessControl;
  let admin, officer1, officer2, borrower1, borrower2, other;

  const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const BORROWER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("BORROWER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));

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
  });

  describe("Officer Registration", function () {
    const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));

    it("Should register officer successfully", async function () {
      await expect(
        accessControl.registerOfficer(officer1.address, employeeIdHash)
      ).to.emit(accessControl, "OfficerRegistered")
        .withArgs(officer1.address, employeeIdHash);

      expect(await accessControl.hasRole(LOAN_OFFICER_ROLE, officer1.address)).to.be.true;
    });

    it("Should track officer details", async function () {
      await accessControl.registerOfficer(officer1.address, employeeIdHash);
      
      const details = await accessControl.officerDetails(officer1.address);
      expect(details.employeeIdHash).to.equal(employeeIdHash);
      expect(details.isActive).to.be.true;
      expect(details.totalAssigned).to.equal(0);
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
      ).to.be.revertedWithCustomError(accessControl, "AlreadyRegistered");
    });

    it("Should not allow zero address", async function () {
      await expect(
        accessControl.registerOfficer(ethers.ZeroAddress, employeeIdHash)
      ).to.be.revertedWithCustomError(accessControl, "InvalidAddress");
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
      ).to.emit(accessControl, "OfficerDeactivated")
        .withArgs(officer1.address);

      const details = await accessControl.officerDetails(officer1.address);
      expect(details.isActive).to.be.false;
    });

    it("Should not affect role on deactivation", async function () {
      await accessControl.deactivateOfficer(officer1.address);
      // Role is still there, just marked inactive
      expect(await accessControl.hasRole(LOAN_OFFICER_ROLE, officer1.address)).to.be.true;
    });

    it("Should reactivate officer", async function () {
      await accessControl.deactivateOfficer(officer1.address);
      await accessControl.reactivateOfficer(officer1.address);

      const details = await accessControl.officerDetails(officer1.address);
      expect(details.isActive).to.be.true;
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
      ).to.emit(accessControl, "BorrowerRegistered")
        .withArgs(borrower1.address, customerIdHash);

      expect(await accessControl.hasRole(BORROWER_ROLE, borrower1.address)).to.be.true;
    });

    it("Should track borrower details", async function () {
      await accessControl.registerBorrower(borrower1.address, customerIdHash);
      
      const details = await accessControl.borrowerDetails(borrower1.address);
      expect(details.customerIdHash).to.equal(customerIdHash);
      expect(details.isActive).to.be.true;
    });

    it("Should not allow non-system to register borrower", async function () {
      await expect(
        accessControl.connect(other).registerBorrower(borrower1.address, customerIdHash)
      ).to.be.reverted;
    });
  });

  describe("Pause Functionality", function () {
    it("Should pause when admin calls", async function () {
      await accessControl.pause();
      expect(await accessControl.paused()).to.be.true;
    });

    it("Should unpause when admin calls", async function () {
      await accessControl.pause();
      await accessControl.unpause();
      expect(await accessControl.paused()).to.be.false;
    });

    it("Should not allow non-admin to pause", async function () {
      await expect(
        accessControl.connect(other).pause()
      ).to.be.reverted;
    });

    it("Should emit Paused event", async function () {
      await expect(accessControl.pause())
        .to.emit(accessControl, "Paused");
    });
  });

  describe("Workload Tracking", function () {
    const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));

    beforeEach(async function () {
      await accessControl.registerOfficer(officer1.address, employeeIdHash);
      await accessControl.grantRole(SYSTEM_ROLE, admin.address);
    });

    it("Should increment workload", async function () {
      await accessControl.incrementOfficerWorkload(officer1.address);
      
      const details = await accessControl.officerDetails(officer1.address);
      expect(details.totalAssigned).to.equal(1);
    });

    it("Should decrement workload", async function () {
      await accessControl.incrementOfficerWorkload(officer1.address);
      await accessControl.decrementOfficerWorkload(officer1.address);
      
      const details = await accessControl.officerDetails(officer1.address);
      expect(details.totalAssigned).to.equal(0);
    });

    it("Should not decrement below zero", async function () {
      // Should not revert but stay at 0
      await accessControl.decrementOfficerWorkload(officer1.address);
      
      const details = await accessControl.officerDetails(officer1.address);
      expect(details.totalAssigned).to.equal(0);
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

    it("Should validate active borrower", async function () {
      expect(await accessControl.isActiveBorrower(borrower1.address)).to.be.true;
    });

    it("Should check both role and registration", async function () {
      expect(await accessControl.isActiveOfficer(other.address)).to.be.false;
      expect(await accessControl.isActiveBorrower(other.address)).to.be.false;
    });
  });

  describe("Upgrade Authorization", function () {
    it("Should only allow UPGRADER_ROLE to upgrade", async function () {
      const UPGRADER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("UPGRADER_ROLE"));
      
      // Deploy V2
      const LoanAccessControlV2 = await ethers.getContractFactory("LoanAccessControl");
      
      // Should fail without upgrader role for other
      await expect(
        upgrades.upgradeProxy(await accessControl.getAddress(), LoanAccessControlV2.connect(other))
      ).to.be.reverted;
      
      // Grant upgrader role and try again
      await accessControl.grantRole(UPGRADER_ROLE, admin.address);
      
      // Should succeed with upgrader role
      const upgraded = await upgrades.upgradeProxy(
        await accessControl.getAddress(),
        LoanAccessControlV2
      );
      expect(await upgraded.VERSION()).to.equal(1);
    });
  });
});
