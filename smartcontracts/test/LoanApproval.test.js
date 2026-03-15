const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

describe("LoanApproval", function () {
    let loanApproval;
    let loanReview;
    let loanApplication;
    let accessControl;
    let auditRegistry;
    let admin, officer1, officer2, borrower1, systemContract, unauthorized;

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
    const rejectionReasonHash = ethers.keccak256(ethers.toUtf8Bytes("REJECTION_REASON"));
    const rejectionNotesHash = ethers.keccak256(ethers.toUtf8Bytes("REJECTION_NOTES"));

    beforeEach(async function () {
        [admin, officer1, officer2, borrower1, systemContract, unauthorized] = await ethers.getSigners();

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

        // Grant logger roles
        await auditRegistry.connect(admin).grantLoggerRole(await loanApplication.getAddress());
        await auditRegistry.connect(admin).grantLoggerRole(await loanReview.getAddress());
        await auditRegistry.connect(admin).grantLoggerRole(await loanApproval.getAddress());

        // Grant SYSTEM_ROLE on LoanApplication so LoanReview and LoanApproval can call updateStatus
        await loanApplication.connect(admin).grantSystemRole(await loanReview.getAddress());
        await loanApplication.connect(admin).grantSystemRole(await loanApproval.getAddress());

        // Register borrower
        await accessControl.connect(admin).grantRole(SYSTEM_ROLE, admin.address);
        const borrowerIdHash = ethers.keccak256(ethers.toUtf8Bytes("BORROWER001"));
        await accessControl.connect(admin).registerBorrower(borrower1.address, borrowerIdHash);

        // Register officers
        const officer1IdHash = ethers.keccak256(ethers.toUtf8Bytes("OFFICER001"));
        const officer2IdHash = ethers.keccak256(ethers.toUtf8Bytes("OFFICER002"));
        await accessControl.connect(admin).registerOfficer(officer1.address, officer1IdHash);
        await accessControl.connect(admin).registerOfficer(officer2.address, officer2IdHash);

        // Grant SYSTEM_ROLE to systemContract on LoanReview
        await loanReview.connect(admin).grantSystemRole(systemContract.address);
    });

    // Helper: create, submit, and assign loan to officer
    async function createSubmitAndAssignLoan(loanId, officer) {
        await loanApplication.connect(borrower1).createApplication(
            loanId, productId, requestedAmount, termMonths, interestRateBps
        );
        await loanApplication.connect(borrower1).submitApplication(
            loanId, eligibilityScore, 0, aiRecommendationHash
        );
        await loanReview.connect(admin).assignOfficer(loanId, officer.address);
    }

    // Helper: get block timestamp from tx
    async function getBlockTimestamp(tx) {
        const receipt = await tx.wait();
        const block = await ethers.provider.getBlock(receipt.blockNumber);
        return block.timestamp;
    }

    describe("Deployment", function () {
        it("Should set the correct admin", async function () {
            expect(await loanApproval.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
        });

        it("Should set the correct access control address", async function () {
            expect(await loanApproval.accessControl()).to.equal(await accessControl.getAddress());
        });

        it("Should set the correct audit registry address", async function () {
            expect(await loanApproval.auditRegistry()).to.equal(await auditRegistry.getAddress());
        });

        it("Should set the correct loan application address", async function () {
            expect(await loanApproval.loanApplication()).to.equal(await loanApplication.getAddress());
        });

        it("Should set the correct loan review address", async function () {
            expect(await loanApproval.loanReviewContract()).to.equal(await loanReview.getAddress());
        });

        it("Should initialize counters to zero", async function () {
            const stats = await loanApproval.getStats();
            expect(stats[0]).to.equal(0); // totalApproved
            expect(stats[1]).to.equal(0); // totalRejected
        });

        it("Should revert if initialized with zero addresses", async function () {
            const LoanApproval = await ethers.getContractFactory("LoanApproval");
            await expect(
                upgrades.deployProxy(
                    LoanApproval,
                    [
                        ethers.ZeroAddress,
                        await auditRegistry.getAddress(),
                        await loanApplication.getAddress(),
                        await loanReview.getAddress(),
                        admin.address
                    ],
                    { kind: "uups" }
                )
            ).to.be.revertedWithCustomError(LoanApproval, "ZeroAddress");
        });
    });

    describe("approveLoan", function () {
        beforeEach(async function () {
            await createSubmitAndAssignLoan(loanId1, officer1);
        });

        it("Should approve loan successfully (assigned officer)", async function () {
            const approvedAmt = ethers.parseEther("8000");
            const tx = await loanApproval.connect(officer1).approveLoan(
                loanId1, approvedAmt, approvalNotesHash
            );

            await expect(tx)
                .to.emit(loanApproval, "LoanApproved")
                .withArgs(loanId1, officer1.address, approvedAmt, approvalNotesHash, await getBlockTimestamp(tx));
        });

        it("Should approve loan successfully (admin)", async function () {
            const approvedAmt = ethers.parseEther("10000");
            const tx = await loanApproval.connect(admin).approveLoan(
                loanId1, approvedAmt, approvalNotesHash
            );

            await expect(tx).to.emit(loanApproval, "LoanApproved");
        });

        it("Should update application status to Approved", async function () {
            await loanApproval.connect(officer1).approveLoan(
                loanId1, requestedAmount, approvalNotesHash
            );

            const status = await loanApplication.getStatus(loanId1);
            expect(status).to.equal(3); // Approved
        });

        it("Should store approval details correctly", async function () {
            const approvedAmt = ethers.parseEther("7500");
            await loanApproval.connect(officer1).approveLoan(
                loanId1, approvedAmt, approvalNotesHash
            );

            const details = await loanApproval.getApprovalDetails(loanId1);
            expect(details.amount).to.equal(approvedAmt);
            expect(details.notesHash).to.equal(approvalNotesHash);
            expect(details.officer).to.equal(officer1.address);
            expect(details.timestamp).to.be.gt(0);
        });

        it("Should increment totalApproved counter", async function () {
            await loanApproval.connect(officer1).approveLoan(
                loanId1, requestedAmount, approvalNotesHash
            );

            const stats = await loanApproval.getStats();
            expect(stats[0]).to.equal(1);
        });

        it("Should allow approving exact requested amount", async function () {
            const tx = await loanApproval.connect(officer1).approveLoan(
                loanId1, requestedAmount, approvalNotesHash
            );
            await expect(tx).to.emit(loanApproval, "LoanApproved");
        });

        it("Should allow approving less than requested amount", async function () {
            const lesserAmount = ethers.parseEther("5000");
            const tx = await loanApproval.connect(officer1).approveLoan(
                loanId1, lesserAmount, approvalNotesHash
            );
            await expect(tx).to.emit(loanApproval, "LoanApproved");
        });

        it("Should log to audit registry", async function () {
            const tx = await loanApproval.connect(officer1).approveLoan(
                loanId1, requestedAmount, approvalNotesHash
            );
            await expect(tx).to.emit(auditRegistry, "AuditLogged");
        });

        it("Should revert if approved amount exceeds requested amount", async function () {
            const excessiveAmount = ethers.parseEther("20000");
            await expect(
                loanApproval.connect(officer1).approveLoan(loanId1, excessiveAmount, approvalNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "AmountExceedsRequested");
        });

        it("Should revert if approved amount is zero", async function () {
            await expect(
                loanApproval.connect(officer1).approveLoan(loanId1, 0, approvalNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "InvalidAmount");
        });

        it("Should revert if caller is not assigned officer or admin", async function () {
            await expect(
                loanApproval.connect(unauthorized).approveLoan(loanId1, requestedAmount, approvalNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "NotAuthorized");
        });

        it("Should revert if a different officer tries to approve", async function () {
            await expect(
                loanApproval.connect(officer2).approveLoan(loanId1, requestedAmount, approvalNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "NotAuthorized");
        });

        it("Should revert if application does not exist", async function () {
            await expect(
                loanApproval.connect(admin).approveLoan(loanIdNonExistent, requestedAmount, approvalNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "ApplicationNotFound");
        });

        it("Should revert if application is not in UnderReview status", async function () {
            // Create but don't submit or assign
            const draftLoanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN_DRAFT"));
            await loanApplication.connect(borrower1).createApplication(
                draftLoanId, productId, requestedAmount, termMonths, interestRateBps
            );

            await expect(
                loanApproval.connect(admin).approveLoan(draftLoanId, requestedAmount, approvalNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "InvalidApplicationStatus");
        });

        it("Should revert when contract is paused", async function () {
            await loanApproval.connect(admin).pause();

            await expect(
                loanApproval.connect(officer1).approveLoan(loanId1, requestedAmount, approvalNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "EnforcedPause");
        });

        it("Should allow approval with empty notes hash", async function () {
            const tx = await loanApproval.connect(officer1).approveLoan(
                loanId1, requestedAmount, ethers.ZeroHash
            );
            await expect(tx).to.emit(loanApproval, "LoanApproved");
        });
    });

    describe("rejectLoan", function () {
        beforeEach(async function () {
            await createSubmitAndAssignLoan(loanId1, officer1);
        });

        it("Should reject loan successfully (assigned officer)", async function () {
            const tx = await loanApproval.connect(officer1).rejectLoan(
                loanId1, rejectionReasonHash, rejectionNotesHash
            );

            await expect(tx)
                .to.emit(loanApproval, "LoanRejected")
                .withArgs(loanId1, officer1.address, rejectionReasonHash, await getBlockTimestamp(tx));
        });

        it("Should reject loan successfully (admin)", async function () {
            const tx = await loanApproval.connect(admin).rejectLoan(
                loanId1, rejectionReasonHash, rejectionNotesHash
            );

            await expect(tx).to.emit(loanApproval, "LoanRejected");
        });

        it("Should update application status to Rejected", async function () {
            await loanApproval.connect(officer1).rejectLoan(
                loanId1, rejectionReasonHash, rejectionNotesHash
            );

            const status = await loanApplication.getStatus(loanId1);
            expect(status).to.equal(4); // Rejected
        });

        it("Should store rejection details correctly", async function () {
            await loanApproval.connect(officer1).rejectLoan(
                loanId1, rejectionReasonHash, rejectionNotesHash
            );

            const details = await loanApproval.getRejectionDetails(loanId1);
            expect(details.reasonHash).to.equal(rejectionReasonHash);
            expect(details.notesHash).to.equal(rejectionNotesHash);
            expect(details.officer).to.equal(officer1.address);
            expect(details.timestamp).to.be.gt(0);
        });

        it("Should increment totalRejected counter", async function () {
            await loanApproval.connect(officer1).rejectLoan(
                loanId1, rejectionReasonHash, rejectionNotesHash
            );

            const stats = await loanApproval.getStats();
            expect(stats[1]).to.equal(1);
        });

        it("Should log to audit registry", async function () {
            const tx = await loanApproval.connect(officer1).rejectLoan(
                loanId1, rejectionReasonHash, rejectionNotesHash
            );
            await expect(tx).to.emit(auditRegistry, "AuditLogged");
        });

        it("Should revert if rejection reason hash is empty", async function () {
            await expect(
                loanApproval.connect(officer1).rejectLoan(loanId1, ethers.ZeroHash, rejectionNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "EmptyHash");
        });

        it("Should revert if caller is not assigned officer or admin", async function () {
            await expect(
                loanApproval.connect(unauthorized).rejectLoan(loanId1, rejectionReasonHash, rejectionNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "NotAuthorized");
        });

        it("Should revert if a different officer tries to reject", async function () {
            await expect(
                loanApproval.connect(officer2).rejectLoan(loanId1, rejectionReasonHash, rejectionNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "NotAuthorized");
        });

        it("Should revert if application does not exist", async function () {
            await expect(
                loanApproval.connect(admin).rejectLoan(loanIdNonExistent, rejectionReasonHash, rejectionNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "ApplicationNotFound");
        });

        it("Should revert if application is not in UnderReview status", async function () {
            const draftLoanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN_DRAFT2"));
            await loanApplication.connect(borrower1).createApplication(
                draftLoanId, productId, requestedAmount, termMonths, interestRateBps
            );

            await expect(
                loanApproval.connect(admin).rejectLoan(draftLoanId, rejectionReasonHash, rejectionNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "InvalidApplicationStatus");
        });

        it("Should revert when contract is paused", async function () {
            await loanApproval.connect(admin).pause();

            await expect(
                loanApproval.connect(officer1).rejectLoan(loanId1, rejectionReasonHash, rejectionNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "EnforcedPause");
        });

        it("Should allow rejection with empty notes hash", async function () {
            const tx = await loanApproval.connect(officer1).rejectLoan(
                loanId1, rejectionReasonHash, ethers.ZeroHash
            );
            await expect(tx).to.emit(loanApproval, "LoanRejected");
        });
    });

    describe("View Functions", function () {
        it("Should return zero values for unapproved loan", async function () {
            const details = await loanApproval.getApprovalDetails(loanId1);
            expect(details.amount).to.equal(0);
            expect(details.notesHash).to.equal(ethers.ZeroHash);
            expect(details.officer).to.equal(ethers.ZeroAddress);
            expect(details.timestamp).to.equal(0);
        });

        it("Should return zero values for non-rejected loan", async function () {
            const details = await loanApproval.getRejectionDetails(loanId1);
            expect(details.reasonHash).to.equal(ethers.ZeroHash);
            expect(details.notesHash).to.equal(ethers.ZeroHash);
            expect(details.officer).to.equal(ethers.ZeroAddress);
            expect(details.timestamp).to.equal(0);
        });
    });

    describe("Admin Functions", function () {
        it("Should allow admin to pause", async function () {
            await loanApproval.connect(admin).pause();
            expect(await loanApproval.paused()).to.be.true;
        });

        it("Should allow admin to unpause", async function () {
            await loanApproval.connect(admin).pause();
            await loanApproval.connect(admin).unpause();
            expect(await loanApproval.paused()).to.be.false;
        });

        it("Should revert if non-admin tries to pause", async function () {
            await expect(
                loanApproval.connect(unauthorized).pause()
            ).to.be.reverted;
        });

        it("Should revert if non-admin tries to unpause", async function () {
            await loanApproval.connect(admin).pause();
            await expect(
                loanApproval.connect(unauthorized).unpause()
            ).to.be.reverted;
        });

        it("Should allow admin to update loan review contract", async function () {
            const newAddress = officer2.address; // just using a non-zero address for test
            await loanApproval.connect(admin).setLoanReviewContract(newAddress);
            expect(await loanApproval.loanReviewContract()).to.equal(newAddress);
        });

        it("Should revert if setting loan review to zero address", async function () {
            await expect(
                loanApproval.connect(admin).setLoanReviewContract(ethers.ZeroAddress)
            ).to.be.revertedWithCustomError(loanApproval, "ZeroAddress");
        });

        it("Should revert if non-admin sets loan review contract", async function () {
            await expect(
                loanApproval.connect(unauthorized).setLoanReviewContract(officer2.address)
            ).to.be.reverted;
        });
    });

    describe("Full Lifecycle", function () {
        it("Should handle complete submit → assign → approve flow", async function () {
            await createSubmitAndAssignLoan(loanId1, officer1);

            const approvedAmt = ethers.parseEther("9000");
            await loanApproval.connect(officer1).approveLoan(
                loanId1, approvedAmt, approvalNotesHash
            );

            // Verify final state
            const status = await loanApplication.getStatus(loanId1);
            expect(status).to.equal(3); // Approved

            const details = await loanApproval.getApprovalDetails(loanId1);
            expect(details.amount).to.equal(approvedAmt);
            expect(details.officer).to.equal(officer1.address);

            const stats = await loanApproval.getStats();
            expect(stats[0]).to.equal(1); // totalApproved
            expect(stats[1]).to.equal(0); // totalRejected
        });

        it("Should handle complete submit → assign → reject flow", async function () {
            await createSubmitAndAssignLoan(loanId1, officer1);

            await loanApproval.connect(officer1).rejectLoan(
                loanId1, rejectionReasonHash, rejectionNotesHash
            );

            // Verify final state
            const status = await loanApplication.getStatus(loanId1);
            expect(status).to.equal(4); // Rejected

            const details = await loanApproval.getRejectionDetails(loanId1);
            expect(details.reasonHash).to.equal(rejectionReasonHash);
            expect(details.officer).to.equal(officer1.address);

            const stats = await loanApproval.getStats();
            expect(stats[0]).to.equal(0); // totalApproved
            expect(stats[1]).to.equal(1); // totalRejected
        });

        it("Should handle multiple loans with mixed decisions", async function () {
            await createSubmitAndAssignLoan(loanId1, officer1);
            await createSubmitAndAssignLoan(loanId2, officer2);

            // Approve first loan
            await loanApproval.connect(officer1).approveLoan(
                loanId1, requestedAmount, approvalNotesHash
            );

            // Reject second loan
            await loanApproval.connect(officer2).rejectLoan(
                loanId2, rejectionReasonHash, rejectionNotesHash
            );

            const stats = await loanApproval.getStats();
            expect(stats[0]).to.equal(1); // totalApproved
            expect(stats[1]).to.equal(1); // totalRejected

            expect(await loanApplication.getStatus(loanId1)).to.equal(3); // Approved
            expect(await loanApplication.getStatus(loanId2)).to.equal(4); // Rejected
        });

        it("Should prevent double approval", async function () {
            await createSubmitAndAssignLoan(loanId1, officer1);

            await loanApproval.connect(officer1).approveLoan(
                loanId1, requestedAmount, approvalNotesHash
            );

            // Trying to approve again should fail (status is now Approved, not UnderReview)
            await expect(
                loanApproval.connect(officer1).approveLoan(loanId1, requestedAmount, approvalNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "InvalidApplicationStatus");
        });

        it("Should prevent approval after rejection", async function () {
            await createSubmitAndAssignLoan(loanId1, officer1);

            await loanApproval.connect(officer1).rejectLoan(
                loanId1, rejectionReasonHash, rejectionNotesHash
            );

            await expect(
                loanApproval.connect(officer1).approveLoan(loanId1, requestedAmount, approvalNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "InvalidApplicationStatus");
        });

        it("Should prevent rejection after approval", async function () {
            await createSubmitAndAssignLoan(loanId1, officer1);

            await loanApproval.connect(officer1).approveLoan(
                loanId1, requestedAmount, approvalNotesHash
            );

            await expect(
                loanApproval.connect(officer1).rejectLoan(loanId1, rejectionReasonHash, rejectionNotesHash)
            ).to.be.revertedWithCustomError(loanApproval, "InvalidApplicationStatus");
        });
    });
});
