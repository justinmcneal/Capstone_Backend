const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

describe("DisbursementExecution", function () {
    let disbursementExecution;
    let disbursementMethod;
    let loanApplication;
    let loanApproval;
    let loanReview;
    let accessControl;
    let auditRegistry;
    let admin, borrower, officer, systemContract, unauthorized;
    
    const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
    const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
    const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
    const UPGRADER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("UPGRADER_ROLE"));

    // Test data
    const loanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const loanId2 = ethers.keccak256(ethers.toUtf8Bytes("LOAN002"));
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT_MSME_001"));
    const requestedAmount = ethers.parseEther("10000");
    const disbursementAmount = ethers.parseEther("10000");
    const termMonths = 12;
    const interestRateBps = 150;
    const eligibilityScore = 85;
    const aiRecommendationHash = ethers.keccak256(ethers.toUtf8Bytes("AI_REC"));
    const approvalNotesHash = ethers.keccak256(ethers.toUtf8Bytes("APPROVAL_NOTES"));
    const referenceHash = ethers.keccak256(ethers.toUtf8Bytes("REF001"));
    const reasonHash = ethers.keccak256(ethers.toUtf8Bytes("REASON001"));

    // Enums
    const Method = { BankTransfer: 0, GCash: 1, Cash: 2, Maya: 3, Other: 4 };
    const Status = { Pending: 0, Processing: 1, Completed: 2, Cancelled: 3 };
    const LoanStatus = { Draft: 0, Submitted: 1, UnderReview: 2, Approved: 3, Rejected: 4, Disbursed: 5, Cancelled: 6 };
    const RiskCategory = { Low: 0, Medium: 1, High: 2 };

    beforeEach(async function () {
        [admin, borrower, officer, systemContract, unauthorized] = await ethers.getSigners();

        // Deploy LoanAccessControl
        const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
        accessControl = await upgrades.deployProxy(LoanAccessControl, [admin.address], { kind: "uups" });
        await accessControl.waitForDeployment();

        // Deploy AuditRegistry
        const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
        auditRegistry = await upgrades.deployProxy(AuditRegistry, [admin.address], { kind: "uups" });
        await auditRegistry.waitForDeployment();

        // Deploy LoanApplication
        const LoanApplication = await ethers.getContractFactory("LoanApplication");
        loanApplication = await upgrades.deployProxy(
            LoanApplication,
            [await accessControl.getAddress(), await auditRegistry.getAddress(), admin.address],
            { kind: "uups" }
        );
        await loanApplication.waitForDeployment();

        // Deploy LoanReview
        const LoanReview = await ethers.getContractFactory("LoanReview");
        loanReview = await upgrades.deployProxy(
            LoanReview,
            [await accessControl.getAddress(), await auditRegistry.getAddress(), await loanApplication.getAddress(), admin.address],
            { kind: "uups" }
        );
        await loanReview.waitForDeployment();

        // Deploy LoanApproval
        const LoanApproval = await ethers.getContractFactory("LoanApproval");
        loanApproval = await upgrades.deployProxy(
            LoanApproval,
            [await accessControl.getAddress(), await auditRegistry.getAddress(), await loanApplication.getAddress(), await loanReview.getAddress(), admin.address],
            { kind: "uups" }
        );
        await loanApproval.waitForDeployment();

        // Deploy DisbursementMethod
        const DisbursementMethod = await ethers.getContractFactory("DisbursementMethod");
        disbursementMethod = await upgrades.deployProxy(
            DisbursementMethod,
            [await accessControl.getAddress(), await auditRegistry.getAddress(), await loanApplication.getAddress(), admin.address],
            { kind: "uups" }
        );
        await disbursementMethod.waitForDeployment();

        // Deploy DisbursementExecution
        const DisbursementExecution = await ethers.getContractFactory("DisbursementExecution");
        disbursementExecution = await upgrades.deployProxy(
            DisbursementExecution,
            [await accessControl.getAddress(), await auditRegistry.getAddress(), await loanApplication.getAddress(), await disbursementMethod.getAddress(), admin.address],
            { kind: "uups" }
        );
        await disbursementExecution.waitForDeployment();

        // Setup permissions
        await auditRegistry.grantLoggerRole(await loanApplication.getAddress());
        await auditRegistry.grantLoggerRole(await loanReview.getAddress());
        await auditRegistry.grantLoggerRole(await loanApproval.getAddress());
        await auditRegistry.grantLoggerRole(await disbursementMethod.getAddress());
        await auditRegistry.grantLoggerRole(await disbursementExecution.getAddress());

        await loanApplication.grantSystemRole(await loanReview.getAddress());
        await loanApplication.grantSystemRole(await loanApproval.getAddress());
        await loanApplication.grantSystemRole(await disbursementExecution.getAddress());

        await disbursementMethod.grantSystemRole(await disbursementExecution.getAddress());

        await accessControl.grantRole(SYSTEM_ROLE, admin.address);
        await disbursementExecution.grantRole(LOAN_OFFICER_ROLE, officer.address);

        // Register users
        const customerIdHash = ethers.keccak256(ethers.toUtf8Bytes("CUST001"));
        await accessControl.registerBorrower(borrower.address, customerIdHash);
        const employeeIdHash = ethers.keccak256(ethers.toUtf8Bytes("EMP001"));
        await accessControl.registerOfficer(officer.address, employeeIdHash);
    });

    async function createAndApproveLoan(lId, bwr) {
        await loanApplication.connect(bwr).createApplication(lId, productId, requestedAmount, termMonths, interestRateBps);
        await loanApplication.connect(bwr).submitApplication(lId, eligibilityScore, RiskCategory.Low, aiRecommendationHash);
        await loanReview.assignOfficer(lId, officer.address);
        await loanApproval.connect(officer).approveLoan(lId, requestedAmount, approvalNotesHash);
    }

    describe("Deployment", function () {
        it("Should set correct version", async function () {
            expect(await disbursementExecution.VERSION()).to.equal(1);
        });

        it("Should set correct contract addresses", async function () {
            expect(await disbursementExecution.accessControl()).to.equal(await accessControl.getAddress());
            expect(await disbursementExecution.auditRegistry()).to.equal(await auditRegistry.getAddress());
            expect(await disbursementExecution.loanApplication()).to.equal(await loanApplication.getAddress());
            expect(await disbursementExecution.disbursementMethod()).to.equal(await disbursementMethod.getAddress());
        });

        it("Should grant admin roles", async function () {
            expect(await disbursementExecution.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
            expect(await disbursementExecution.hasRole(UPGRADER_ROLE, admin.address)).to.be.true;
        });

        it("Should revert with zero addresses", async function () {
            const DisbursementExecution = await ethers.getContractFactory("DisbursementExecution");
            await expect(
                upgrades.deployProxy(DisbursementExecution, [ethers.ZeroAddress, await auditRegistry.getAddress(), await loanApplication.getAddress(), await disbursementMethod.getAddress(), admin.address], { kind: "uups" })
            ).to.be.revertedWithCustomError(disbursementExecution, "ZeroAddress");
        });
    });

    describe("initiateDisbursement", function () {
        beforeEach(async function () {
            await createAndApproveLoan(loanId, borrower);
            await disbursementMethod.connect(borrower).setPreferredMethod(loanId, Method.BankTransfer);
        });

        it("Should initiate disbursement successfully", async function () {
            await expect(disbursementExecution.connect(officer).initiateDisbursement(loanId, disbursementAmount))
                .to.emit(disbursementExecution, "DisbursementInitiated");
        });

        it("Should return disbursement ID", async function () {
            const tx = await disbursementExecution.connect(officer).initiateDisbursement(loanId, disbursementAmount);
            await tx.wait();
            const record = await disbursementExecution.getDisbursementByLoan(loanId);
            expect(record.disbursementId).to.not.equal(ethers.ZeroHash);
        });

        it("Should lock disbursement method", async function () {
            await disbursementExecution.connect(officer).initiateDisbursement(loanId, disbursementAmount);
            expect(await disbursementMethod.isMethodLocked(loanId)).to.be.true;
        });

        it("Should increment total disbursements", async function () {
            const before = await disbursementExecution.totalDisbursements();
            await disbursementExecution.connect(officer).initiateDisbursement(loanId, disbursementAmount);
            expect(await disbursementExecution.totalDisbursements()).to.equal(before + 1n);
        });

        it("Should revert if loan not approved", async function () {
            const loanIdDraft = ethers.keccak256(ethers.toUtf8Bytes("LOAN_DRAFT"));
            await loanApplication.connect(borrower).createApplication(loanIdDraft, productId, requestedAmount, termMonths, interestRateBps);
            await expect(disbursementExecution.connect(officer).initiateDisbursement(loanIdDraft, disbursementAmount))
                .to.be.revertedWithCustomError(disbursementExecution, "LoanNotApproved");
        });

        it("Should revert if no preferred method set", async function () {
            const loanIdNoMethod = ethers.keccak256(ethers.toUtf8Bytes("LOAN_NO_METHOD"));
            await createAndApproveLoan(loanIdNoMethod, borrower);
            await expect(disbursementExecution.connect(officer).initiateDisbursement(loanIdNoMethod, disbursementAmount))
                .to.be.revertedWithCustomError(disbursementExecution, "NoPreferredMethod");
        });

        it("Should revert if amount is zero", async function () {
            await expect(disbursementExecution.connect(officer).initiateDisbursement(loanId, 0))
                .to.be.revertedWithCustomError(disbursementExecution, "InvalidAmount");
        });

        it("Should revert if amount exceeds requested", async function () {
            const tooMuch = ethers.parseEther("20000");
            await expect(disbursementExecution.connect(officer).initiateDisbursement(loanId, tooMuch))
                .to.be.revertedWithCustomError(disbursementExecution, "InvalidAmount");
        });

        it("Should revert if already disbursed", async function () {
            await disbursementExecution.connect(officer).initiateDisbursement(loanId, disbursementAmount);
            await expect(disbursementExecution.connect(officer).initiateDisbursement(loanId, disbursementAmount))
                .to.be.revertedWithCustomError(disbursementExecution, "AlreadyDisbursed");
        });

        it("Should revert if not authorized", async function () {
            await expect(disbursementExecution.connect(unauthorized).initiateDisbursement(loanId, disbursementAmount))
                .to.be.revertedWithCustomError(disbursementExecution, "NotAuthorized");
        });

        it("Should revert when paused", async function () {
            await disbursementExecution.pause();
            await expect(disbursementExecution.connect(officer).initiateDisbursement(loanId, disbursementAmount))
                .to.be.revertedWithCustomError(disbursementExecution, "EnforcedPause");
        });
    });

    describe("completeDisbursement", function () {
        let disbursementId;

        beforeEach(async function () {
            await createAndApproveLoan(loanId, borrower);
            await disbursementMethod.connect(borrower).setPreferredMethod(loanId, Method.GCash);
            const tx = await disbursementExecution.connect(officer).initiateDisbursement(loanId, disbursementAmount);
            await tx.wait();
            // Get disbursement ID from mapping
            const record = await disbursementExecution.getDisbursementByLoan(loanId);
            disbursementId = record.disbursementId;
        });

        it("Should complete disbursement successfully", async function () {
            await expect(disbursementExecution.connect(officer).completeDisbursement(disbursementId, referenceHash))
                .to.emit(disbursementExecution, "DisbursementCompleted");
        });

        it("Should update loan status to Disbursed", async function () {
            await disbursementExecution.connect(officer).completeDisbursement(disbursementId, referenceHash);
            const app = await loanApplication.getApplication(loanId);
            expect(app.status).to.equal(LoanStatus.Disbursed);
        });

        it("Should increment total completed", async function () {
            const before = await disbursementExecution.totalCompleted();
            await disbursementExecution.connect(officer).completeDisbursement(disbursementId, referenceHash);
            expect(await disbursementExecution.totalCompleted()).to.equal(before + 1n);
        });

        it("Should track total disbursed amount", async function () {
            const before = await disbursementExecution.totalDisbursedAmount();
            await disbursementExecution.connect(officer).completeDisbursement(disbursementId, referenceHash);
            expect(await disbursementExecution.totalDisbursedAmount()).to.equal(before + disbursementAmount);
        });

        it("Should mark reference as used", async function () {
            await disbursementExecution.connect(officer).completeDisbursement(disbursementId, referenceHash);
            expect(await disbursementExecution.isReferenceUsed(referenceHash)).to.be.true;
        });

        it("Should revert if disbursement not found", async function () {
            const fakeDisbursementId = ethers.keccak256(ethers.toUtf8Bytes("FAKE"));
            await expect(disbursementExecution.connect(officer).completeDisbursement(fakeDisbursementId, referenceHash))
                .to.be.revertedWithCustomError(disbursementExecution, "DisbursementNotFound");
        });

        it("Should revert if reference hash is empty", async function () {
            await expect(disbursementExecution.connect(officer).completeDisbursement(disbursementId, ethers.ZeroHash))
                .to.be.revertedWithCustomError(disbursementExecution, "EmptyHash");
        });

        it("Should revert if duplicate reference", async function () {
            await disbursementExecution.connect(officer).completeDisbursement(disbursementId, referenceHash);
            
            await createAndApproveLoan(loanId2, borrower);
            await disbursementMethod.connect(borrower).setPreferredMethod(loanId2, Method.Cash);
            const tx2 = await disbursementExecution.connect(officer).initiateDisbursement(loanId2, disbursementAmount);
            await tx2.wait();
            const record2 = await disbursementExecution.getDisbursementByLoan(loanId2);
            const disbursementId2 = record2.disbursementId;

            await expect(disbursementExecution.connect(officer).completeDisbursement(disbursementId2, referenceHash))
                .to.be.revertedWithCustomError(disbursementExecution, "DuplicateReference");
        });

        it("Should revert if invalid status", async function () {
            await disbursementExecution.connect(officer).completeDisbursement(disbursementId, referenceHash);
            const newRef = ethers.keccak256(ethers.toUtf8Bytes("REF002"));
            await expect(disbursementExecution.connect(officer).completeDisbursement(disbursementId, newRef))
                .to.be.revertedWithCustomError(disbursementExecution, "InvalidStatus");
        });

        it("Should revert if not authorized", async function () {
            await expect(disbursementExecution.connect(unauthorized).completeDisbursement(disbursementId, referenceHash))
                .to.be.revertedWithCustomError(disbursementExecution, "NotAuthorized");
        });
    });

    describe("cancelDisbursement", function () {
        let disbursementId;

        beforeEach(async function () {
            await createAndApproveLoan(loanId, borrower);
            await disbursementMethod.connect(borrower).setPreferredMethod(loanId, Method.Maya);
            const tx = await disbursementExecution.connect(officer).initiateDisbursement(loanId, disbursementAmount);
            await tx.wait();
            // Get disbursement ID from mapping
            const record = await disbursementExecution.getDisbursementByLoan(loanId);
            disbursementId = record.disbursementId;
        });

        it("Should cancel disbursement successfully", async function () {
            await expect(disbursementExecution.connect(officer).cancelDisbursement(disbursementId, reasonHash))
                .to.emit(disbursementExecution, "DisbursementCancelled");
        });

        it("Should increment total cancelled", async function () {
            const before = await disbursementExecution.totalCancelled();
            await disbursementExecution.connect(officer).cancelDisbursement(disbursementId, reasonHash);
            expect(await disbursementExecution.totalCancelled()).to.equal(before + 1n);
        });

        it("Should update disbursement status to Cancelled", async function () {
            await disbursementExecution.connect(officer).cancelDisbursement(disbursementId, reasonHash);
            const record = await disbursementExecution.getDisbursement(disbursementId);
            expect(record.status).to.equal(Status.Cancelled);
        });

        it("Should store cancellation reason", async function () {
            await disbursementExecution.connect(officer).cancelDisbursement(disbursementId, reasonHash);
            const record = await disbursementExecution.getDisbursement(disbursementId);
            expect(record.cancellationReason).to.equal(reasonHash);
        });

        it("Should keep loan status as Approved", async function () {
            await disbursementExecution.connect(officer).cancelDisbursement(disbursementId, reasonHash);
            const app = await loanApplication.getApplication(loanId);
            expect(app.status).to.equal(LoanStatus.Approved);
        });

        it("Should revert if disbursement not found", async function () {
            const fakeDisbursementId = ethers.keccak256(ethers.toUtf8Bytes("FAKE"));
            await expect(disbursementExecution.connect(officer).cancelDisbursement(fakeDisbursementId, reasonHash))
                .to.be.revertedWithCustomError(disbursementExecution, "DisbursementNotFound");
        });

        it("Should revert if reason hash is empty", async function () {
            await expect(disbursementExecution.connect(officer).cancelDisbursement(disbursementId, ethers.ZeroHash))
                .to.be.revertedWithCustomError(disbursementExecution, "EmptyHash");
        });

        it("Should revert if invalid status", async function () {
            await disbursementExecution.connect(officer).completeDisbursement(disbursementId, referenceHash);
            await expect(disbursementExecution.connect(officer).cancelDisbursement(disbursementId, reasonHash))
                .to.be.revertedWithCustomError(disbursementExecution, "InvalidStatus");
        });

        it("Should revert if not authorized", async function () {
            await expect(disbursementExecution.connect(unauthorized).cancelDisbursement(disbursementId, reasonHash))
                .to.be.revertedWithCustomError(disbursementExecution, "NotAuthorized");
        });
    });

    describe("View Functions", function () {
        let disbursementId;

        beforeEach(async function () {
            await createAndApproveLoan(loanId, borrower);
            await disbursementMethod.connect(borrower).setPreferredMethod(loanId, Method.BankTransfer);
            const tx = await disbursementExecution.connect(officer).initiateDisbursement(loanId, disbursementAmount);
            await tx.wait();
            // Get disbursement ID from mapping
            const record = await disbursementExecution.getDisbursementByLoan(loanId);
            disbursementId = record.disbursementId;
        });

        it("Should get disbursement by ID", async function () {
            const record = await disbursementExecution.getDisbursement(disbursementId);
            expect(record.disbursementId).to.equal(disbursementId);
            expect(record.loanId).to.equal(loanId);
            expect(record.borrower).to.equal(borrower.address);
            expect(record.amount).to.equal(disbursementAmount);
            expect(record.method).to.equal(Method.BankTransfer);
            expect(record.status).to.equal(Status.Processing);
        });

        it("Should get disbursement by loan ID", async function () {
            const record = await disbursementExecution.getDisbursementByLoan(loanId);
            expect(record.loanId).to.equal(loanId);
        });

        it("Should check if reference is used", async function () {
            expect(await disbursementExecution.isReferenceUsed(referenceHash)).to.be.false;
            await disbursementExecution.connect(officer).completeDisbursement(disbursementId, referenceHash);
            expect(await disbursementExecution.isReferenceUsed(referenceHash)).to.be.true;
        });

        it("Should check if loan has disbursement", async function () {
            expect(await disbursementExecution.hasDisbursement(loanId)).to.be.true;
            expect(await disbursementExecution.hasDisbursement(loanId2)).to.be.false;
        });

        it("Should get stats", async function () {
            const stats = await disbursementExecution.getStats();
            expect(stats[0]).to.equal(1); // totalDisbursements
            expect(stats[1]).to.equal(0); // totalCompleted
            expect(stats[2]).to.equal(0); // totalCancelled
            expect(stats[3]).to.equal(0); // totalDisbursedAmount
        });

        it("Should revert getDisbursement if not found", async function () {
            const fakeDisbursementId = ethers.keccak256(ethers.toUtf8Bytes("FAKE"));
            await expect(disbursementExecution.getDisbursement(fakeDisbursementId))
                .to.be.revertedWithCustomError(disbursementExecution, "DisbursementNotFound");
        });

        it("Should revert getDisbursementByLoan if not found", async function () {
            await expect(disbursementExecution.getDisbursementByLoan(loanId2))
                .to.be.revertedWithCustomError(disbursementExecution, "DisbursementNotFound");
        });
    });

    describe("Admin Functions", function () {
        it("Should pause and unpause", async function () {
            await disbursementExecution.pause();
            expect(await disbursementExecution.paused()).to.be.true;
            await disbursementExecution.unpause();
            expect(await disbursementExecution.paused()).to.be.false;
        });

        it("Should grant and revoke officer role", async function () {
            await disbursementExecution.grantOfficerRole(unauthorized.address);
            expect(await disbursementExecution.hasRole(LOAN_OFFICER_ROLE, unauthorized.address)).to.be.true;
            await disbursementExecution.revokeOfficerRole(unauthorized.address);
            expect(await disbursementExecution.hasRole(LOAN_OFFICER_ROLE, unauthorized.address)).to.be.false;
        });

        it("Should grant and revoke system role", async function () {
            await disbursementExecution.grantSystemRole(systemContract.address);
            expect(await disbursementExecution.hasRole(SYSTEM_ROLE, systemContract.address)).to.be.true;
            await disbursementExecution.revokeSystemRole(systemContract.address);
            expect(await disbursementExecution.hasRole(SYSTEM_ROLE, systemContract.address)).to.be.false;
        });

        it("Should update disbursement method contract", async function () {
            const DisbursementMethod = await ethers.getContractFactory("DisbursementMethod");
            const newDisbursementMethod = await upgrades.deployProxy(
                DisbursementMethod,
                [await accessControl.getAddress(), await auditRegistry.getAddress(), await loanApplication.getAddress(), admin.address],
                { kind: "uups" }
            );
            await newDisbursementMethod.waitForDeployment();
            
            await disbursementExecution.setDisbursementMethodContract(await newDisbursementMethod.getAddress());
            expect(await disbursementExecution.disbursementMethod()).to.equal(await newDisbursementMethod.getAddress());
        });

        it("Should revert setDisbursementMethodContract with zero address", async function () {
            await expect(disbursementExecution.setDisbursementMethodContract(ethers.ZeroAddress))
                .to.be.revertedWithCustomError(disbursementExecution, "ZeroAddress");
        });

        it("Should revert admin functions if not admin", async function () {
            await expect(disbursementExecution.connect(unauthorized).pause()).to.be.reverted;
            await expect(disbursementExecution.connect(unauthorized).grantOfficerRole(unauthorized.address)).to.be.reverted;
        });
    });

    describe("Upgrade", function () {
        it("Should upgrade contract", async function () {
            const DisbursementExecutionV2 = await ethers.getContractFactory("DisbursementExecution");
            await upgrades.upgradeProxy(await disbursementExecution.getAddress(), DisbursementExecutionV2);
            expect(await disbursementExecution.VERSION()).to.equal(1);
        });

        it("Should revert upgrade if not upgrader", async function () {
            const DisbursementExecutionV2 = await ethers.getContractFactory("DisbursementExecution", unauthorized);
            await expect(upgrades.upgradeProxy(await disbursementExecution.getAddress(), DisbursementExecutionV2))
                .to.be.reverted;
        });
    });
});
