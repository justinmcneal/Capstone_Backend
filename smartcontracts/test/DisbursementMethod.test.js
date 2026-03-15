const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

describe("DisbursementMethod", function () {
    let disbursementMethod;
    let loanApplication;
    let loanApproval;
    let loanReview;
    let accessControl;
    let auditRegistry;
    let admin, borrower1, borrower2, officer1, systemContract, unauthorized;
    
    const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
    const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
    const BORROWER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("BORROWER_ROLE"));
    const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));

    // Test data
    const loanId1 = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const loanId2 = ethers.keccak256(ethers.toUtf8Bytes("LOAN002"));
    const loanIdNonExistent = ethers.keccak256(ethers.toUtf8Bytes("LOAN_NONEXISTENT"));
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT_MSME_001"));
    const requestedAmount = ethers.parseEther("10000");
    const termMonths = 12;
    const interestRateBps = 150;
    const eligibilityScore = 85;
    const aiRecommendationHash = ethers.keccak256(ethers.toUtf8Bytes("AI_RECOMMENDATION_DATA"));
    const approvalNotesHash = ethers.keccak256(ethers.toUtf8Bytes("APPROVAL_NOTES"));

    // Disbursement methods
    const Method = {
        BankTransfer: 0,
        GCash: 1,
        Cash: 2,
        Check: 3,
        Wallet: 4
    };

    beforeEach(async function () {
        [admin, borrower1, borrower2, officer1, systemContract, unauthorized] = await ethers.getSigners();

        // Deploy LoanAccessControl
        const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
        accessControl = await upgrades.deployProxy(
            LoanAccessControl,
            [admin.address],
            { kind: "uups" }
        );
        await accessControl.waitForDeployment();

        // Deploy AuditRegistry
        const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
        auditRegistry = await upgrades.deployProxy(
            AuditRegistry,
            [admin.address],
            { kind: "uups" }
        );
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
            [
                await accessControl.getAddress(),
                await auditRegistry.getAddress(),
                await loanApplication.getAddress(),
                admin.address
            ],
            { kind: "uups" }
        );
        await loanReview.waitForDeployment();

        // Deploy LoanApproval
        const LoanApproval = await ethers.getContractFactory("LoanApproval");
        loanApproval = await upgrades.deployProxy(
            LoanApproval,
            [
                await accessControl.getAddress(),
                await auditRegistry.getAddress(),
                await loanApplication.getAddress(),
                await loanReview.getAddress(),
                admin.address
            ],
            { kind: "uups" }
        );
        await loanApproval.waitForDeployment();

        // Deploy DisbursementMethod
        const DisbursementMethod = await ethers.getContractFactory("DisbursementMethod");
        disbursementMethod = await upgrades.deployProxy(
            DisbursementMethod,
            [
                await accessControl.getAddress(),
                await auditRegistry.getAddress(),
                await loanApplication.getAddress(),
                admin.address
            ],
            { kind: "uups" }
        );
        await disbursementMethod.waitForDeployment();

        // Grant logger roles
        await auditRegistry.connect(admin).grantLoggerRole(await loanApplication.getAddress());
        await auditRegistry.connect(admin).grantLoggerRole(await loanReview.getAddress());
        await auditRegistry.connect(admin).grantLoggerRole(await loanApproval.getAddress());
        await auditRegistry.connect(admin).grantLoggerRole(await disbursementMethod.getAddress());

        // Grant SYSTEM_ROLE
        await loanApplication.connect(admin).grantSystemRole(await loanReview.getAddress());
        await loanApplication.connect(admin).grantSystemRole(await loanApproval.getAddress());
        await disbursementMethod.connect(admin).grantSystemRole(systemContract.address);

        // Register borrowers
        await accessControl.connect(admin).grantRole(SYSTEM_ROLE, admin.address);
        const borrower1IdHash = ethers.keccak256(ethers.toUtf8Bytes("BORROWER001"));
        const borrower2IdHash = ethers.keccak256(ethers.toUtf8Bytes("BORROWER002"));
        await accessControl.connect(admin).registerBorrower(borrower1.address, borrower1IdHash);
        await accessControl.connect(admin).registerBorrower(borrower2.address, borrower2IdHash);

        // Register officer
        const officer1IdHash = ethers.keccak256(ethers.toUtf8Bytes("OFFICER001"));
        await accessControl.connect(admin).registerOfficer(officer1.address, officer1IdHash);
    });

    // Helper: create, submit, assign, and approve loan
    async function createAndApproveLoan(loanId, borrower) {
        await loanApplication.connect(borrower).createApplication(
            loanId, productId, requestedAmount, termMonths, interestRateBps
        );
        await loanApplication.connect(borrower).submitApplication(
            loanId, eligibilityScore, 0, aiRecommendationHash
        );
        await loanReview.connect(admin).assignOfficer(loanId, officer1.address);
        await loanApproval.connect(officer1).approveLoan(
            loanId, requestedAmount, approvalNotesHash
        );
    }

    describe("Deployment", function () {
        it("Should set the correct admin", async function () {
            expect(await disbursementMethod.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
        });

        it("Should set the correct access control address", async function () {
            expect(await disbursementMethod.accessControl()).to.equal(await accessControl.getAddress());
        });

        it("Should set the correct audit registry address", async function () {
            expect(await disbursementMethod.auditRegistry()).to.equal(await auditRegistry.getAddress());
        });

        it("Should set the correct loan application address", async function () {
            expect(await disbursementMethod.loanApplication()).to.equal(await loanApplication.getAddress());
        });

        it("Should initialize counters to zero", async function () {
            const stats = await disbursementMethod.getStats();
            expect(stats[0]).to.equal(0); // totalMethodsSet
            expect(stats[1]).to.equal(0); // totalMethodsUpdated
        });

        it("Should revert if initialized with zero addresses", async function () {
            const DisbursementMethod = await ethers.getContractFactory("DisbursementMethod");
            await expect(
                upgrades.deployProxy(
                    DisbursementMethod,
                    [
                        ethers.ZeroAddress,
                        await auditRegistry.getAddress(),
                        await loanApplication.getAddress(),
                        admin.address
                    ],
                    { kind: "uups" }
                )
            ).to.be.revertedWithCustomError(DisbursementMethod, "ZeroAddress");
        });
    });

    describe("setPreferredMethod", function () {
        beforeEach(async function () {
            await createAndApproveLoan(loanId1, borrower1);
        });

        it("Should set preferred method successfully (BankTransfer)", async function () {
            const tx = await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.BankTransfer
            );

            await expect(tx)
                .to.emit(disbursementMethod, "DisbursementMethodSelected")
                .withArgs(loanId1, borrower1.address, Method.BankTransfer, await getBlockTimestamp(tx));
        });

        it("Should set preferred method successfully (GCash)", async function () {
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.GCash
            );

            const method = await disbursementMethod.getPreferredMethod(loanId1);
            expect(method).to.equal(Method.GCash);
        });

        it("Should set preferred method successfully (Cash)", async function () {
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.Cash
            );

            const method = await disbursementMethod.getPreferredMethod(loanId1);
            expect(method).to.equal(Method.Cash);
        });

        it("Should set preferred method successfully (Check)", async function () {
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.Check
            );

            const method = await disbursementMethod.getPreferredMethod(loanId1);
            expect(method).to.equal(Method.Check);
        });

        it("Should set preferred method successfully (Wallet)", async function () {
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.Wallet
            );

            const method = await disbursementMethod.getPreferredMethod(loanId1);
            expect(method).to.equal(Method.Wallet);
        });

        it("Should increment totalMethodsSet counter", async function () {
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.BankTransfer
            );

            const stats = await disbursementMethod.getStats();
            expect(stats[0]).to.equal(1);
        });

        it("Should mark hasPreferredMethod as true", async function () {
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.GCash
            );

            expect(await disbursementMethod.hasPreferredMethod(loanId1)).to.be.true;
        });

        it("Should store complete method selection details", async function () {
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.Check
            );

            const selection = await disbursementMethod.getMethodSelection(loanId1);
            expect(selection.loanId).to.equal(loanId1);
            expect(selection.borrower).to.equal(borrower1.address);
            expect(selection.method).to.equal(Method.Check);
            expect(selection.isLocked).to.be.false;
            expect(selection.selectedAt).to.be.gt(0);
            expect(selection.updatedAt).to.equal(selection.selectedAt);
        });

        it("Should log to audit registry", async function () {
            const tx = await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.BankTransfer
            );
            await expect(tx).to.emit(auditRegistry, "AuditLogged");
        });

        it("Should revert if loan does not exist", async function () {
            await expect(
                disbursementMethod.connect(borrower1).setPreferredMethod(
                    loanIdNonExistent, Method.BankTransfer
                )
            ).to.be.revertedWithCustomError(disbursementMethod, "LoanNotFound");
        });

        it("Should revert if caller is not the borrower", async function () {
            await expect(
                disbursementMethod.connect(borrower2).setPreferredMethod(
                    loanId1, Method.BankTransfer
                )
            ).to.be.revertedWithCustomError(disbursementMethod, "NotBorrower");
        });

        it("Should revert if loan is not in Approved status (Draft)", async function () {
            const draftLoanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN_DRAFT"));
            await loanApplication.connect(borrower1).createApplication(
                draftLoanId, productId, requestedAmount, termMonths, interestRateBps
            );

            await expect(
                disbursementMethod.connect(borrower1).setPreferredMethod(
                    draftLoanId, Method.BankTransfer
                )
            ).to.be.revertedWithCustomError(disbursementMethod, "InvalidLoanStatus");
        });

        it("Should revert if loan is not in Approved status (Submitted)", async function () {
            const submittedLoanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN_SUBMITTED"));
            await loanApplication.connect(borrower1).createApplication(
                submittedLoanId, productId, requestedAmount, termMonths, interestRateBps
            );
            await loanApplication.connect(borrower1).submitApplication(
                submittedLoanId, eligibilityScore, 0, aiRecommendationHash
            );

            await expect(
                disbursementMethod.connect(borrower1).setPreferredMethod(
                    submittedLoanId, Method.BankTransfer
                )
            ).to.be.revertedWithCustomError(disbursementMethod, "InvalidLoanStatus");
        });

        it("Should revert if invalid method value", async function () {
            // Solidity 0.8.x automatically validates enum values
            await expect(
                disbursementMethod.connect(borrower1).setPreferredMethod(
                    loanId1, 99 // Invalid method
                )
            ).to.be.reverted; // Will revert with panic code for invalid enum
        });

        it("Should revert when contract is paused", async function () {
            await disbursementMethod.connect(admin).pause();

            await expect(
                disbursementMethod.connect(borrower1).setPreferredMethod(
                    loanId1, Method.BankTransfer
                )
            ).to.be.revertedWithCustomError(disbursementMethod, "EnforcedPause");
        });
    });

    describe("Update Preferred Method", function () {
        beforeEach(async function () {
            await createAndApproveLoan(loanId1, borrower1);
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.BankTransfer
            );
        });

        it("Should update method successfully", async function () {
            const tx = await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.GCash
            );

            await expect(tx)
                .to.emit(disbursementMethod, "DisbursementMethodUpdated")
                .withArgs(loanId1, borrower1.address, Method.BankTransfer, Method.GCash, await getBlockTimestamp(tx));
        });

        it("Should update method value correctly", async function () {
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.Check
            );

            const method = await disbursementMethod.getPreferredMethod(loanId1);
            expect(method).to.equal(Method.Check);
        });

        it("Should increment totalMethodsUpdated counter", async function () {
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.Cash
            );

            const stats = await disbursementMethod.getStats();
            expect(stats[1]).to.equal(1);
        });

        it("Should update updatedAt timestamp", async function () {
            const selectionBefore = await disbursementMethod.getMethodSelection(loanId1);
            
            await ethers.provider.send("evm_increaseTime", [100]);
            await ethers.provider.send("evm_mine");

            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.Wallet
            );

            const selectionAfter = await disbursementMethod.getMethodSelection(loanId1);
            expect(selectionAfter.updatedAt).to.be.gt(selectionBefore.updatedAt);
        });

        it("Should not change selectedAt timestamp", async function () {
            const selectionBefore = await disbursementMethod.getMethodSelection(loanId1);
            
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.GCash
            );

            const selectionAfter = await disbursementMethod.getMethodSelection(loanId1);
            expect(selectionAfter.selectedAt).to.equal(selectionBefore.selectedAt);
        });

        it("Should allow multiple updates", async function () {
            await disbursementMethod.connect(borrower1).setPreferredMethod(loanId1, Method.GCash);
            await disbursementMethod.connect(borrower1).setPreferredMethod(loanId1, Method.Cash);
            await disbursementMethod.connect(borrower1).setPreferredMethod(loanId1, Method.Check);

            const method = await disbursementMethod.getPreferredMethod(loanId1);
            expect(method).to.equal(Method.Check);

            const stats = await disbursementMethod.getStats();
            expect(stats[1]).to.equal(3); // 3 updates
        });
    });

    describe("lockMethod", function () {
        beforeEach(async function () {
            await createAndApproveLoan(loanId1, borrower1);
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.BankTransfer
            );
        });

        it("Should lock method successfully (SYSTEM_ROLE)", async function () {
            const tx = await disbursementMethod.connect(systemContract).lockMethod(loanId1);

            await expect(tx)
                .to.emit(disbursementMethod, "DisbursementMethodLocked")
                .withArgs(loanId1, Method.BankTransfer, await getBlockTimestamp(tx));
        });

        it("Should mark method as locked", async function () {
            await disbursementMethod.connect(systemContract).lockMethod(loanId1);

            expect(await disbursementMethod.isMethodLocked(loanId1)).to.be.true;
        });

        it("Should update isLocked flag in selection", async function () {
            await disbursementMethod.connect(systemContract).lockMethod(loanId1);

            const selection = await disbursementMethod.getMethodSelection(loanId1);
            expect(selection.isLocked).to.be.true;
        });

        // Gas optimization: auditRegistry.log() call was removed from lockMethod()
        it("Should succeed without emitting audit log (gas optimization)", async function () {
            const tx = await disbursementMethod.connect(systemContract).lockMethod(loanId1);
            await expect(tx).to.not.emit(auditRegistry, "AuditLogged");
        });

        it("Should revert if caller is not SYSTEM_ROLE", async function () {
            await expect(
                disbursementMethod.connect(borrower1).lockMethod(loanId1)
            ).to.be.revertedWithCustomError(disbursementMethod, "NotBorrower");
        });

        it("Should revert if method not set", async function () {
            await createAndApproveLoan(loanId2, borrower1);

            await expect(
                disbursementMethod.connect(systemContract).lockMethod(loanId2)
            ).to.be.revertedWithCustomError(disbursementMethod, "MethodNotSet");
        });

        it("Should revert if already locked", async function () {
            await disbursementMethod.connect(systemContract).lockMethod(loanId1);

            await expect(
                disbursementMethod.connect(systemContract).lockMethod(loanId1)
            ).to.be.revertedWithCustomError(disbursementMethod, "MethodAlreadyLocked");
        });

        it("Should prevent updates after locking", async function () {
            await disbursementMethod.connect(systemContract).lockMethod(loanId1);

            await expect(
                disbursementMethod.connect(borrower1).setPreferredMethod(loanId1, Method.GCash)
            ).to.be.revertedWithCustomError(disbursementMethod, "MethodAlreadyLocked");
        });
    });

    describe("View Functions", function () {
        it("Should return false for hasPreferredMethod if not set", async function () {
            await createAndApproveLoan(loanId1, borrower1);
            expect(await disbursementMethod.hasPreferredMethod(loanId1)).to.be.false;
        });

        it("Should revert getPreferredMethod if not set", async function () {
            await createAndApproveLoan(loanId1, borrower1);

            await expect(
                disbursementMethod.getPreferredMethod(loanId1)
            ).to.be.revertedWithCustomError(disbursementMethod, "MethodNotSet");
        });

        it("Should revert getMethodSelection if not set", async function () {
            await createAndApproveLoan(loanId1, borrower1);

            await expect(
                disbursementMethod.getMethodSelection(loanId1)
            ).to.be.revertedWithCustomError(disbursementMethod, "MethodNotSet");
        });

        it("Should return false for isMethodLocked if not set", async function () {
            await createAndApproveLoan(loanId1, borrower1);
            expect(await disbursementMethod.isMethodLocked(loanId1)).to.be.false;
        });
    });

    describe("Admin Functions", function () {
        it("Should allow admin to pause", async function () {
            await disbursementMethod.connect(admin).pause();
            expect(await disbursementMethod.paused()).to.be.true;
        });

        it("Should allow admin to unpause", async function () {
            await disbursementMethod.connect(admin).pause();
            await disbursementMethod.connect(admin).unpause();
            expect(await disbursementMethod.paused()).to.be.false;
        });

        it("Should revert if non-admin tries to pause", async function () {
            await expect(
                disbursementMethod.connect(unauthorized).pause()
            ).to.be.reverted;
        });

        it("Should allow admin to grant system role", async function () {
            await disbursementMethod.connect(admin).grantSystemRole(unauthorized.address);
            expect(await disbursementMethod.hasRole(SYSTEM_ROLE, unauthorized.address)).to.be.true;
        });

        it("Should allow admin to revoke system role", async function () {
            await disbursementMethod.connect(admin).grantSystemRole(unauthorized.address);
            await disbursementMethod.connect(admin).revokeSystemRole(unauthorized.address);
            expect(await disbursementMethod.hasRole(SYSTEM_ROLE, unauthorized.address)).to.be.false;
        });
    });

    describe("Full Lifecycle", function () {
        it("Should handle complete method selection → update → lock flow", async function () {
            await createAndApproveLoan(loanId1, borrower1);

            // Set initial method
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.BankTransfer
            );
            expect(await disbursementMethod.getPreferredMethod(loanId1)).to.equal(Method.BankTransfer);

            // Update method
            await disbursementMethod.connect(borrower1).setPreferredMethod(
                loanId1, Method.GCash
            );
            expect(await disbursementMethod.getPreferredMethod(loanId1)).to.equal(Method.GCash);

            // Lock method
            await disbursementMethod.connect(systemContract).lockMethod(loanId1);
            expect(await disbursementMethod.isMethodLocked(loanId1)).to.be.true;

            // Verify cannot update after lock
            await expect(
                disbursementMethod.connect(borrower1).setPreferredMethod(loanId1, Method.Cash)
            ).to.be.revertedWithCustomError(disbursementMethod, "MethodAlreadyLocked");

            // Verify stats
            const stats = await disbursementMethod.getStats();
            expect(stats[0]).to.equal(1); // totalMethodsSet
            expect(stats[1]).to.equal(1); // totalMethodsUpdated
        });

        it("Should handle multiple loans independently", async function () {
            await createAndApproveLoan(loanId1, borrower1);
            await createAndApproveLoan(loanId2, borrower1);

            // Set different methods
            await disbursementMethod.connect(borrower1).setPreferredMethod(loanId1, Method.BankTransfer);
            await disbursementMethod.connect(borrower1).setPreferredMethod(loanId2, Method.GCash);

            expect(await disbursementMethod.getPreferredMethod(loanId1)).to.equal(Method.BankTransfer);
            expect(await disbursementMethod.getPreferredMethod(loanId2)).to.equal(Method.GCash);

            // Lock one loan
            await disbursementMethod.connect(systemContract).lockMethod(loanId1);
            expect(await disbursementMethod.isMethodLocked(loanId1)).to.be.true;
            expect(await disbursementMethod.isMethodLocked(loanId2)).to.be.false;

            // Can still update unlocked loan
            await disbursementMethod.connect(borrower1).setPreferredMethod(loanId2, Method.Check);
            expect(await disbursementMethod.getPreferredMethod(loanId2)).to.equal(Method.Check);
        });
    });

    // Helper to get block timestamp from transaction
    async function getBlockTimestamp(tx) {
        const receipt = await tx.wait();
        const block = await ethers.provider.getBlock(receipt.blockNumber);
        return block.timestamp;
    }
});
