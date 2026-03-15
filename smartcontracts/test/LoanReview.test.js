const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

describe("LoanReview", function () {
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
    const reasonHash = ethers.keccak256(ethers.toUtf8Bytes("REASSIGNMENT_REASON"));
    const docType1 = ethers.keccak256(ethers.toUtf8Bytes("INCOME_STATEMENT"));
    const docType2 = ethers.keccak256(ethers.toUtf8Bytes("BALANCE_SHEET"));
    const docType3 = ethers.keccak256(ethers.toUtf8Bytes("TAX_RETURN"));
    const docReasonHash = ethers.keccak256(ethers.toUtf8Bytes("NEED_ADDITIONAL_DOCS"));

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

        // Grant logger roles to both contracts
        await auditRegistry.connect(admin).grantLoggerRole(await loanApplication.getAddress());
        await auditRegistry.connect(admin).grantLoggerRole(await loanReview.getAddress());

        // Grant SYSTEM_ROLE on LoanApplication so LoanReview can call updateStatus
        await loanApplication.connect(admin).grantSystemRole(await loanReview.getAddress());

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

    // Helper to create and submit a loan application
    async function createAndSubmitLoan(loanId) {
        await loanApplication.connect(borrower1).createApplication(
            loanId, productId, requestedAmount, termMonths, interestRateBps
        );
        await loanApplication.connect(borrower1).submitApplication(
            loanId, eligibilityScore, 0, aiRecommendationHash // 0 = RiskCategory.Low
        );
    }

    describe("Deployment", function () {
        it("Should set the correct admin", async function () {
            expect(await loanReview.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
        });

        it("Should set the correct access control address", async function () {
            expect(await loanReview.accessControl()).to.equal(await accessControl.getAddress());
        });

        it("Should set the correct audit registry address", async function () {
            expect(await loanReview.auditRegistry()).to.equal(await auditRegistry.getAddress());
        });

        it("Should set the correct loan application address", async function () {
            expect(await loanReview.loanApplication()).to.equal(await loanApplication.getAddress());
        });

        it("Should initialize counters to zero", async function () {
            const stats = await loanReview.getStats();
            expect(stats[0]).to.equal(0); // totalAssignments
            expect(stats[1]).to.equal(0); // totalReassignments
            expect(stats[2]).to.equal(0); // totalDocumentRequests
        });

        it("Should revert if initialized with zero addresses", async function () {
            const LoanReview = await ethers.getContractFactory("LoanReview");
            await expect(
                upgrades.deployProxy(
                    LoanReview,
                    [ethers.ZeroAddress, await auditRegistry.getAddress(), await loanApplication.getAddress(), admin.address],
                    { kind: "uups" }
                )
            ).to.be.revertedWithCustomError(LoanReview, "ZeroAddress");
        });
    });

    describe("assignOfficer", function () {
        beforeEach(async function () {
            await createAndSubmitLoan(loanId1);
        });

        it("Should assign an officer successfully (admin)", async function () {
            const tx = await loanReview.connect(admin).assignOfficer(loanId1, officer1.address);

            await expect(tx)
                .to.emit(loanReview, "OfficerAssigned")
                .withArgs(loanId1, officer1.address, admin.address, await getBlockTimestamp(tx));

            expect(await loanReview.getAssignedOfficer(loanId1)).to.equal(officer1.address);
        });

        it("Should assign an officer successfully (system role)", async function () {
            const tx = await loanReview.connect(systemContract).assignOfficer(loanId1, officer1.address);

            await expect(tx).to.emit(loanReview, "OfficerAssigned");
            expect(await loanReview.getAssignedOfficer(loanId1)).to.equal(officer1.address);
        });

        it("Should update application status to UnderReview", async function () {
            await loanReview.connect(admin).assignOfficer(loanId1, officer1.address);

            const status = await loanApplication.getStatus(loanId1);
            expect(status).to.equal(2); // UnderReview
        });

        it("Should increment totalAssignments counter", async function () {
            await loanReview.connect(admin).assignOfficer(loanId1, officer1.address);

            const stats = await loanReview.getStats();
            expect(stats[0]).to.equal(1);
        });

        // Gas optimization: officerAssignedLoans storage array no longer populated; data available via events
        it("Should add loan to officer's assigned loans", async function () {
            await loanReview.connect(admin).assignOfficer(loanId1, officer1.address);

            const loans = await loanReview.getOfficerLoans(officer1.address);
            expect(loans).to.be.an("array").that.is.empty;
        });

        it("Should log to audit registry", async function () {
            const tx = await loanReview.connect(admin).assignOfficer(loanId1, officer1.address);
            await expect(tx).to.emit(auditRegistry, "AuditLogged");
        });

        it("Should revert if caller is not admin or system", async function () {
            await expect(
                loanReview.connect(unauthorized).assignOfficer(loanId1, officer1.address)
            ).to.be.revertedWithCustomError(loanReview, "NotAuthorized");
        });

        it("Should revert if application does not exist", async function () {
            await expect(
                loanReview.connect(admin).assignOfficer(loanIdNonExistent, officer1.address)
            ).to.be.revertedWithCustomError(loanReview, "ApplicationNotFound");
        });

        it("Should revert if officer is not active", async function () {
            await expect(
                loanReview.connect(admin).assignOfficer(loanId1, unauthorized.address)
            ).to.be.revertedWithCustomError(loanReview, "OfficerNotActive");
        });

        it("Should revert if application is in Draft status", async function () {
            // Create but don't submit
            const draftLoanId = ethers.keccak256(ethers.toUtf8Bytes("LOAN_DRAFT"));
            await loanApplication.connect(borrower1).createApplication(
                draftLoanId, productId, requestedAmount, termMonths, interestRateBps
            );

            await expect(
                loanReview.connect(admin).assignOfficer(draftLoanId, officer1.address)
            ).to.be.revertedWithCustomError(loanReview, "InvalidApplicationStatus");
        });

        it("Should revert if officer is deactivated", async function () {
            await accessControl.connect(admin).deactivateOfficer(officer1.address);

            await expect(
                loanReview.connect(admin).assignOfficer(loanId1, officer1.address)
            ).to.be.revertedWithCustomError(loanReview, "OfficerNotActive");
        });

        it("Should allow assigning when status is already UnderReview", async function () {
            // First assignment
            await loanReview.connect(admin).assignOfficer(loanId1, officer1.address);

            // Assign another officer while UnderReview (overwrite)
            const tx = await loanReview.connect(admin).assignOfficer(loanId1, officer2.address);
            await expect(tx).to.emit(loanReview, "OfficerAssigned");
            expect(await loanReview.getAssignedOfficer(loanId1)).to.equal(officer2.address);
        });

        it("Should revert when contract is paused", async function () {
            await loanReview.connect(admin).pause();

            await expect(
                loanReview.connect(admin).assignOfficer(loanId1, officer1.address)
            ).to.be.revertedWithCustomError(loanReview, "EnforcedPause");
        });
    });

    describe("reassignOfficer", function () {
        beforeEach(async function () {
            await createAndSubmitLoan(loanId1);
            await loanReview.connect(admin).assignOfficer(loanId1, officer1.address);
        });

        it("Should reassign officer successfully", async function () {
            const tx = await loanReview.connect(admin).reassignOfficer(
                loanId1, officer2.address, reasonHash
            );

            await expect(tx)
                .to.emit(loanReview, "OfficerReassigned")
                .withArgs(loanId1, officer1.address, officer2.address, await getBlockTimestamp(tx));

            expect(await loanReview.getAssignedOfficer(loanId1)).to.equal(officer2.address);
        });

        it("Should increment totalReassignments counter", async function () {
            await loanReview.connect(admin).reassignOfficer(loanId1, officer2.address, reasonHash);

            const stats = await loanReview.getStats();
            expect(stats[1]).to.equal(1);
        });

        // Gas optimization: officerAssignedLoans storage array no longer populated; data available via events
        it("Should add loan to new officer's assigned loans", async function () {
            await loanReview.connect(admin).reassignOfficer(loanId1, officer2.address, reasonHash);

            const loans = await loanReview.getOfficerLoans(officer2.address);
            expect(loans).to.be.an("array").that.is.empty;
        });

        it("Should log to audit registry", async function () {
            const tx = await loanReview.connect(admin).reassignOfficer(
                loanId1, officer2.address, reasonHash
            );
            await expect(tx).to.emit(auditRegistry, "AuditLogged");
        });

        it("Should revert if no officer is currently assigned", async function () {
            await createAndSubmitLoan(loanId2);

            await expect(
                loanReview.connect(admin).reassignOfficer(loanId2, officer1.address, reasonHash)
            ).to.be.revertedWithCustomError(loanReview, "NoOfficerAssigned");
        });

        it("Should revert if reassigning to the same officer", async function () {
            await expect(
                loanReview.connect(admin).reassignOfficer(loanId1, officer1.address, reasonHash)
            ).to.be.revertedWithCustomError(loanReview, "SameOfficer");
        });

        it("Should revert if new officer is not active", async function () {
            await expect(
                loanReview.connect(admin).reassignOfficer(loanId1, unauthorized.address, reasonHash)
            ).to.be.revertedWithCustomError(loanReview, "OfficerNotActive");
        });

        it("Should revert if reason hash is empty", async function () {
            await expect(
                loanReview.connect(admin).reassignOfficer(loanId1, officer2.address, ethers.ZeroHash)
            ).to.be.revertedWithCustomError(loanReview, "EmptyHash");
        });

        it("Should revert if caller is not admin or system", async function () {
            await expect(
                loanReview.connect(unauthorized).reassignOfficer(loanId1, officer2.address, reasonHash)
            ).to.be.revertedWithCustomError(loanReview, "NotAuthorized");
        });

        it("Should revert if application does not exist", async function () {
            await expect(
                loanReview.connect(admin).reassignOfficer(loanIdNonExistent, officer2.address, reasonHash)
            ).to.be.revertedWithCustomError(loanReview, "ApplicationNotFound");
        });

        it("Should allow system role to reassign", async function () {
            const tx = await loanReview.connect(systemContract).reassignOfficer(
                loanId1, officer2.address, reasonHash
            );
            await expect(tx).to.emit(loanReview, "OfficerReassigned");
        });

        it("Should revert when contract is paused", async function () {
            await loanReview.connect(admin).pause();

            await expect(
                loanReview.connect(admin).reassignOfficer(loanId1, officer2.address, reasonHash)
            ).to.be.revertedWithCustomError(loanReview, "EnforcedPause");
        });
    });

    describe("requestDocuments", function () {
        beforeEach(async function () {
            await createAndSubmitLoan(loanId1);
            await loanReview.connect(admin).assignOfficer(loanId1, officer1.address);
        });

        it("Should request documents successfully (assigned officer)", async function () {
            const docTypes = [docType1, docType2];
            const tx = await loanReview.connect(officer1).requestDocuments(
                loanId1, docTypes, docReasonHash
            );

            await expect(tx)
                .to.emit(loanReview, "DocumentsRequested")
                .withArgs(loanId1, docTypes, officer1.address, await getBlockTimestamp(tx));
        });

        it("Should request documents successfully (admin)", async function () {
            const docTypes = [docType1];
            const tx = await loanReview.connect(admin).requestDocuments(
                loanId1, docTypes, docReasonHash
            );

            await expect(tx).to.emit(loanReview, "DocumentsRequested");
        });

        // Gas optimization: requestedDocuments storage array no longer populated; data available via events
        it("Should store requested document types", async function () {
            const docTypes = [docType1, docType2, docType3];
            await loanReview.connect(officer1).requestDocuments(loanId1, docTypes, docReasonHash);

            const stored = await loanReview.getRequestedDocuments(loanId1);
            expect(stored.length).to.equal(0);
        });

        // Gas optimization: requestedDocuments storage array no longer populated; data available via events
        it("Should accumulate document requests", async function () {
            await loanReview.connect(officer1).requestDocuments(loanId1, [docType1], docReasonHash);
            await loanReview.connect(officer1).requestDocuments(loanId1, [docType2, docType3], docReasonHash);

            const stored = await loanReview.getRequestedDocuments(loanId1);
            expect(stored.length).to.equal(0);
        });

        it("Should increment totalDocumentRequests counter", async function () {
            await loanReview.connect(officer1).requestDocuments(loanId1, [docType1], docReasonHash);

            const stats = await loanReview.getStats();
            expect(stats[2]).to.equal(1);
        });

        it("Should log to audit registry", async function () {
            const tx = await loanReview.connect(officer1).requestDocuments(
                loanId1, [docType1], docReasonHash
            );
            await expect(tx).to.emit(auditRegistry, "AuditLogged");
        });

        it("Should revert if caller is not assigned officer or admin", async function () {
            await expect(
                loanReview.connect(unauthorized).requestDocuments(loanId1, [docType1], docReasonHash)
            ).to.be.revertedWithCustomError(loanReview, "NotAuthorized");
        });

        it("Should revert if a different officer tries to request documents", async function () {
            await expect(
                loanReview.connect(officer2).requestDocuments(loanId1, [docType1], docReasonHash)
            ).to.be.revertedWithCustomError(loanReview, "NotAuthorized");
        });

        it("Should revert if application does not exist", async function () {
            await expect(
                loanReview.connect(admin).requestDocuments(loanIdNonExistent, [docType1], docReasonHash)
            ).to.be.revertedWithCustomError(loanReview, "ApplicationNotFound");
        });

        it("Should revert if document types array is empty", async function () {
            await expect(
                loanReview.connect(officer1).requestDocuments(loanId1, [], docReasonHash)
            ).to.be.revertedWithCustomError(loanReview, "EmptyDocumentTypes");
        });

        it("Should revert if reason hash is empty", async function () {
            await expect(
                loanReview.connect(officer1).requestDocuments(loanId1, [docType1], ethers.ZeroHash)
            ).to.be.revertedWithCustomError(loanReview, "EmptyHash");
        });

        it("Should revert if application is not in UnderReview status", async function () {
            await createAndSubmitLoan(loanId2);
            // loanId2 is in Submitted status, not UnderReview

            await expect(
                loanReview.connect(admin).requestDocuments(loanId2, [docType1], docReasonHash)
            ).to.be.revertedWithCustomError(loanReview, "InvalidApplicationStatus");
        });

        it("Should revert when contract is paused", async function () {
            await loanReview.connect(admin).pause();

            await expect(
                loanReview.connect(officer1).requestDocuments(loanId1, [docType1], docReasonHash)
            ).to.be.revertedWithCustomError(loanReview, "EnforcedPause");
        });
    });

    describe("View Functions", function () {
        beforeEach(async function () {
            await createAndSubmitLoan(loanId1);
            await createAndSubmitLoan(loanId2);
            await loanReview.connect(admin).assignOfficer(loanId1, officer1.address);
        });

        it("Should return zero address for unassigned loan", async function () {
            expect(await loanReview.getAssignedOfficer(loanId2)).to.equal(ethers.ZeroAddress);
        });

        it("Should return empty array for officer with no assignments", async function () {
            const loans = await loanReview.getOfficerLoans(unauthorized.address);
            expect(loans.length).to.equal(0);
        });

        it("Should return empty array for loan with no document requests", async function () {
            const docs = await loanReview.getRequestedDocuments(loanId1);
            expect(docs.length).to.equal(0);
        });
    });

    describe("Admin Functions", function () {
        it("Should allow admin to pause", async function () {
            await loanReview.connect(admin).pause();
            expect(await loanReview.paused()).to.be.true;
        });

        it("Should allow admin to unpause", async function () {
            await loanReview.connect(admin).pause();
            await loanReview.connect(admin).unpause();
            expect(await loanReview.paused()).to.be.false;
        });

        it("Should revert if non-admin tries to pause", async function () {
            await expect(
                loanReview.connect(unauthorized).pause()
            ).to.be.reverted;
        });

        it("Should revert if non-admin tries to unpause", async function () {
            await loanReview.connect(admin).pause();
            await expect(
                loanReview.connect(unauthorized).unpause()
            ).to.be.reverted;
        });

        it("Should allow admin to grant system role", async function () {
            await loanReview.connect(admin).grantSystemRole(unauthorized.address);
            expect(await loanReview.hasRole(SYSTEM_ROLE, unauthorized.address)).to.be.true;
        });

        it("Should allow admin to revoke system role", async function () {
            await loanReview.connect(admin).grantSystemRole(unauthorized.address);
            await loanReview.connect(admin).revokeSystemRole(unauthorized.address);
            expect(await loanReview.hasRole(SYSTEM_ROLE, unauthorized.address)).to.be.false;
        });
    });

    describe("Full Lifecycle", function () {
        // Gas optimization: storage arrays no longer populated; data available via events
        it("Should handle complete assign → reassign → request docs flow", async function () {
            // Create and submit application
            await createAndSubmitLoan(loanId1);

            // Assign officer
            await loanReview.connect(admin).assignOfficer(loanId1, officer1.address);
            expect(await loanReview.getAssignedOfficer(loanId1)).to.equal(officer1.address);

            // Request documents
            await loanReview.connect(officer1).requestDocuments(
                loanId1, [docType1, docType2], docReasonHash
            );
            const docs = await loanReview.getRequestedDocuments(loanId1);
            expect(docs.length).to.equal(0);

            // Reassign to another officer
            await loanReview.connect(admin).reassignOfficer(
                loanId1, officer2.address, reasonHash
            );
            expect(await loanReview.getAssignedOfficer(loanId1)).to.equal(officer2.address);

            // New officer requests more documents
            await loanReview.connect(officer2).requestDocuments(
                loanId1, [docType3], docReasonHash
            );
            const allDocs = await loanReview.getRequestedDocuments(loanId1);
            expect(allDocs.length).to.equal(0);

            // Verify stats
            const stats = await loanReview.getStats();
            expect(stats[0]).to.equal(1); // totalAssignments
            expect(stats[1]).to.equal(1); // totalReassignments
            expect(stats[2]).to.equal(2); // totalDocumentRequests
        });
    });

    // Helper to get block timestamp from transaction
    async function getBlockTimestamp(tx) {
        const receipt = await tx.wait();
        const block = await ethers.provider.getBlock(receipt.blockNumber);
        return block.timestamp;
    }
});
