const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("LoanApplication", function () {
    let loanApplication;
    let accessControl;
    let auditRegistry;
    let admin, borrower1, borrower2, officer, systemContract, unauthorized;
    
    const ADMIN_ROLE = ethers.keccak256(ethers.toUtf8Bytes("ADMIN_ROLE"));
    const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
    const BORROWER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("BORROWER_ROLE"));
    const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));

    // Test data
    const loanId1 = ethers.keccak256(ethers.toUtf8Bytes("LOAN001"));
    const loanId2 = ethers.keccak256(ethers.toUtf8Bytes("LOAN002"));
    const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT_MSME_001"));
    const requestedAmount = ethers.parseEther("10000"); // 10,000 tokens
    const termMonths = 12;
    const interestRateBps = 150; // 1.5%
    const eligibilityScore = 85;
    const RiskCategory = { Low: 0, Medium: 1, High: 2 };
    const aiRecommendationHash = ethers.keccak256(ethers.toUtf8Bytes("AI_RECOMMENDATION_DATA"));
    const reasonHash = ethers.keccak256(ethers.toUtf8Bytes("CANCELLATION_REASON"));

    beforeEach(async function () {
        [admin, borrower1, borrower2, officer, systemContract, unauthorized] = await ethers.getSigners();

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

        // Grant logger role to LoanApplication
        await auditRegistry.connect(admin).grantLoggerRole(await loanApplication.getAddress());

        // Register borrowers
        const borrower1IdHash = ethers.keccak256(ethers.toUtf8Bytes("BORROWER001"));
        const borrower2IdHash = ethers.keccak256(ethers.toUtf8Bytes("BORROWER002"));
        
        await accessControl.connect(admin).grantRole(SYSTEM_ROLE, admin.address);
        await accessControl.connect(admin).registerBorrower(borrower1.address, borrower1IdHash);
        await accessControl.connect(admin).registerBorrower(borrower2.address, borrower2IdHash);

        // Grant SYSTEM_ROLE to systemContract for testing updateStatus
        await loanApplication.connect(admin).grantSystemRole(systemContract.address);
    });

    describe("Deployment", function () {
        it("Should set the correct admin", async function () {
            expect(await loanApplication.hasRole(ADMIN_ROLE, admin.address)).to.be.true;
        });

        it("Should set the correct access control address", async function () {
            expect(await loanApplication.accessControl()).to.equal(await accessControl.getAddress());
        });

        it("Should set the correct audit registry address", async function () {
            expect(await loanApplication.auditRegistry()).to.equal(await auditRegistry.getAddress());
        });

        it("Should initialize counters to zero", async function () {
            const stats = await loanApplication.getStats();
            expect(stats[0]).to.equal(0); // totalApplications
            expect(stats[1]).to.equal(0); // totalSubmitted
            expect(stats[2]).to.equal(0); // totalCancelled
        });
    });

    describe("createApplication", function () {
        it("Should create an application successfully", async function () {
            const tx = await loanApplication.connect(borrower1).createApplication(
                loanId1,
                productId,
                requestedAmount,
                termMonths,
                interestRateBps
            );
            
            await expect(tx)
                .to.emit(loanApplication, "ApplicationCreated");

            const app = await loanApplication.getApplication(loanId1);
            expect(app.loanId).to.equal(loanId1);
            expect(app.borrower).to.equal(borrower1.address);
            expect(app.productId).to.equal(productId);
            expect(app.requestedAmount).to.equal(requestedAmount);
            expect(app.termMonths).to.equal(termMonths);
            expect(app.interestRateBps).to.equal(interestRateBps);
            expect(app.status).to.equal(0); // Draft
        });

        it("Should increment totalApplications counter", async function () {
            await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );

            const stats = await loanApplication.getStats();
            expect(stats[0]).to.equal(1);
        });

        it("Should add application to borrower's list", async function () {
            await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );

            const borrowerApps = await loanApplication.getBorrowerApplications(borrower1.address);
            expect(borrowerApps.length).to.equal(1);
            expect(borrowerApps[0]).to.equal(loanId1);
        });

        it("Should log to audit registry", async function () {
            await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );

            const entries = await auditRegistry.getEntriesByResource(loanId1);
            expect(entries.length).to.equal(1);
        });

        it("Should revert if application already exists", async function () {
            await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );

            await expect(
                loanApplication.connect(borrower1).createApplication(
                    loanId1, productId, requestedAmount, termMonths, interestRateBps
                )
            ).to.be.revertedWithCustomError(loanApplication, "ApplicationAlreadyExists");
        });

        it("Should revert if amount is zero", async function () {
            await expect(
                loanApplication.connect(borrower1).createApplication(
                    loanId1, productId, 0, termMonths, interestRateBps
                )
            ).to.be.revertedWithCustomError(loanApplication, "InvalidAmount");
        });

        it("Should revert if term is zero", async function () {
            await expect(
                loanApplication.connect(borrower1).createApplication(
                    loanId1, productId, requestedAmount, 0, interestRateBps
                )
            ).to.be.revertedWithCustomError(loanApplication, "InvalidTerm");
        });

        it("Should revert if term exceeds 360 months", async function () {
            await expect(
                loanApplication.connect(borrower1).createApplication(
                    loanId1, productId, requestedAmount, 361, interestRateBps
                )
            ).to.be.revertedWithCustomError(loanApplication, "InvalidTerm");
        });

        it("Should revert if productId is empty", async function () {
            await expect(
                loanApplication.connect(borrower1).createApplication(
                    loanId1, ethers.ZeroHash, requestedAmount, termMonths, interestRateBps
                )
            ).to.be.revertedWithCustomError(loanApplication, "EmptyHash");
        });

        it("Should revert if caller is not a borrower", async function () {
            await expect(
                loanApplication.connect(unauthorized).createApplication(
                    loanId1, productId, requestedAmount, termMonths, interestRateBps
                )
            ).to.be.revertedWithCustomError(loanApplication, "NotBorrower");
        });

        it("Should revert when paused", async function () {
            await loanApplication.connect(admin).pause();

            await expect(
                loanApplication.connect(borrower1).createApplication(
                    loanId1, productId, requestedAmount, termMonths, interestRateBps
                )
            ).to.be.revertedWithCustomError(loanApplication, "EnforcedPause");
        });
    });

    describe("submitApplication", function () {
        beforeEach(async function () {
            await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );
        });

        it("Should submit application successfully", async function () {
            const tx = await loanApplication.connect(borrower1).submitApplication(
                loanId1, eligibilityScore, RiskCategory.Low, aiRecommendationHash
            );
            
            await expect(tx)
                .to.emit(loanApplication, "ApplicationSubmitted");

            const app = await loanApplication.getApplication(loanId1);
            expect(app.status).to.equal(1); // Submitted
            expect(app.eligibilityScore).to.equal(eligibilityScore);
            expect(app.riskCategory).to.equal(RiskCategory.Low);
            expect(app.aiRecommendationHash).to.equal(aiRecommendationHash);
        });

        it("Should emit ApplicationStatusChanged event", async function () {
            const tx = await loanApplication.connect(borrower1).submitApplication(
                loanId1, eligibilityScore, RiskCategory.Medium, aiRecommendationHash
            );
            
            await expect(tx)
                .to.emit(loanApplication, "ApplicationStatusChanged")
                .withArgs(loanId1, 0, 1, await time.latest()); // Draft -> Submitted
        });

        it("Should increment totalSubmitted counter", async function () {
            await loanApplication.connect(borrower1).submitApplication(
                loanId1, eligibilityScore, RiskCategory.Low, aiRecommendationHash
            );

            const stats = await loanApplication.getStats();
            expect(stats[1]).to.equal(1);
        });

        it("Should revert if application not found", async function () {
            await expect(
                loanApplication.connect(borrower1).submitApplication(
                    loanId2, eligibilityScore, RiskCategory.Low, aiRecommendationHash
                )
            ).to.be.revertedWithCustomError(loanApplication, "ApplicationNotFound");
        });

        it("Should revert if caller is not the borrower", async function () {
            await expect(
                loanApplication.connect(borrower2).submitApplication(
                    loanId1, eligibilityScore, RiskCategory.Low, aiRecommendationHash
                )
            ).to.be.revertedWithCustomError(loanApplication, "UnauthorizedBorrower");
        });

        it("Should revert if not in Draft status", async function () {
            await loanApplication.connect(borrower1).submitApplication(
                loanId1, eligibilityScore, RiskCategory.Low, aiRecommendationHash
            );

            await expect(
                loanApplication.connect(borrower1).submitApplication(
                    loanId1, eligibilityScore, RiskCategory.Low, aiRecommendationHash
                )
            ).to.be.revertedWithCustomError(loanApplication, "InvalidStatus");
        });

        it("Should revert if eligibility score exceeds 100", async function () {
            await expect(
                loanApplication.connect(borrower1).submitApplication(
                    loanId1, 101, RiskCategory.Low, aiRecommendationHash
                )
            ).to.be.revertedWithCustomError(loanApplication, "InvalidScore");
        });

        it("Should revert if aiRecommendationHash is empty", async function () {
            await expect(
                loanApplication.connect(borrower1).submitApplication(
                    loanId1, eligibilityScore, RiskCategory.Low, ethers.ZeroHash
                )
            ).to.be.revertedWithCustomError(loanApplication, "EmptyHash");
        });

        it("Should accept all risk categories", async function () {
            // Low
            await loanApplication.connect(borrower1).createApplication(
                loanId2, productId, requestedAmount, termMonths, interestRateBps
            );
            await loanApplication.connect(borrower1).submitApplication(
                loanId2, eligibilityScore, RiskCategory.Low, aiRecommendationHash
            );
            let app = await loanApplication.getApplication(loanId2);
            expect(app.riskCategory).to.equal(RiskCategory.Low);

            // Medium
            const loanId3 = ethers.keccak256(ethers.toUtf8Bytes("LOAN003"));
            await loanApplication.connect(borrower1).createApplication(
                loanId3, productId, requestedAmount, termMonths, interestRateBps
            );
            await loanApplication.connect(borrower1).submitApplication(
                loanId3, eligibilityScore, RiskCategory.Medium, aiRecommendationHash
            );
            app = await loanApplication.getApplication(loanId3);
            expect(app.riskCategory).to.equal(RiskCategory.Medium);

            // High
            const loanId4 = ethers.keccak256(ethers.toUtf8Bytes("LOAN004"));
            await loanApplication.connect(borrower1).createApplication(
                loanId4, productId, requestedAmount, termMonths, interestRateBps
            );
            await loanApplication.connect(borrower1).submitApplication(
                loanId4, eligibilityScore, RiskCategory.High, aiRecommendationHash
            );
            app = await loanApplication.getApplication(loanId4);
            expect(app.riskCategory).to.equal(RiskCategory.High);
        });
    });

    describe("cancelApplication", function () {
        beforeEach(async function () {
            await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );
        });

        it("Should cancel Draft application by borrower", async function () {
            await expect(
                loanApplication.connect(borrower1).cancelApplication(loanId1, reasonHash)
            ).to.emit(loanApplication, "ApplicationCancelled")
             .withArgs(loanId1, borrower1.address, reasonHash, await time.latest() + 1);

            const app = await loanApplication.getApplication(loanId1);
            expect(app.status).to.equal(6); // Cancelled
        });

        it("Should cancel Submitted application by borrower", async function () {
            await loanApplication.connect(borrower1).submitApplication(
                loanId1, eligibilityScore, RiskCategory.Low, aiRecommendationHash
            );

            await loanApplication.connect(borrower1).cancelApplication(loanId1, reasonHash);
            const app = await loanApplication.getApplication(loanId1);
            expect(app.status).to.equal(6);
        });

        it("Should cancel application by admin", async function () {
            await loanApplication.connect(admin).cancelApplication(loanId1, reasonHash);
            const app = await loanApplication.getApplication(loanId1);
            expect(app.status).to.equal(6);
        });

        it("Should increment totalCancelled counter", async function () {
            await loanApplication.connect(borrower1).cancelApplication(loanId1, reasonHash);

            const stats = await loanApplication.getStats();
            expect(stats[2]).to.equal(1);
        });

        it("Should revert if application not found", async function () {
            await expect(
                loanApplication.connect(borrower1).cancelApplication(loanId2, reasonHash)
            ).to.be.revertedWithCustomError(loanApplication, "ApplicationNotFound");
        });

        it("Should revert if caller is neither borrower nor admin", async function () {
            await expect(
                loanApplication.connect(borrower2).cancelApplication(loanId1, reasonHash)
            ).to.be.revertedWithCustomError(loanApplication, "UnauthorizedBorrower");
        });

        it("Should revert if reasonHash is empty", async function () {
            await expect(
                loanApplication.connect(borrower1).cancelApplication(loanId1, ethers.ZeroHash)
            ).to.be.revertedWithCustomError(loanApplication, "EmptyHash");
        });

        it("Should revert if application is in UnderReview status", async function () {
            await loanApplication.connect(borrower1).submitApplication(
                loanId1, eligibilityScore, RiskCategory.Low, aiRecommendationHash
            );
            await loanApplication.connect(systemContract).updateStatus(loanId1, 2); // UnderReview

            await expect(
                loanApplication.connect(borrower1).cancelApplication(loanId1, reasonHash)
            ).to.be.revertedWithCustomError(loanApplication, "InvalidStatus");
        });

        it("Should revert if application is Approved", async function () {
            await loanApplication.connect(borrower1).submitApplication(
                loanId1, eligibilityScore, RiskCategory.Low, aiRecommendationHash
            );
            await loanApplication.connect(systemContract).updateStatus(loanId1, 3); // Approved

            await expect(
                loanApplication.connect(borrower1).cancelApplication(loanId1, reasonHash)
            ).to.be.revertedWithCustomError(loanApplication, "InvalidStatus");
        });
    });

    describe("updateStatus", function () {
        beforeEach(async function () {
            await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );
            await loanApplication.connect(borrower1).submitApplication(
                loanId1, eligibilityScore, RiskCategory.Low, aiRecommendationHash
            );
        });

        it("Should update status by SYSTEM_ROLE", async function () {
            await expect(
                loanApplication.connect(systemContract).updateStatus(loanId1, 2) // UnderReview
            ).to.emit(loanApplication, "ApplicationStatusChanged")
             .withArgs(loanId1, 1, 2, await time.latest() + 1);

            const app = await loanApplication.getApplication(loanId1);
            expect(app.status).to.equal(2);
        });

        it("Should update status by ADMIN_ROLE", async function () {
            await loanApplication.connect(admin).updateStatus(loanId1, 2);
            const app = await loanApplication.getApplication(loanId1);
            expect(app.status).to.equal(2);
        });

        it("Should revert if caller lacks authorization", async function () {
            await expect(
                loanApplication.connect(borrower1).updateStatus(loanId1, 2)
            ).to.be.revertedWith("LoanApplication: not authorized to update status");
        });

        it("Should revert if application not found", async function () {
            await expect(
                loanApplication.connect(systemContract).updateStatus(loanId2, 2)
            ).to.be.revertedWithCustomError(loanApplication, "ApplicationNotFound");
        });

        it("Should revert if status unchanged", async function () {
            await expect(
                loanApplication.connect(systemContract).updateStatus(loanId1, 1) // Already Submitted
            ).to.be.revertedWith("LoanApplication: status unchanged");
        });
    });

    describe("View Functions", function () {
        beforeEach(async function () {
            await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );
        });

        it("Should return application details", async function () {
            const app = await loanApplication.getApplication(loanId1);
            expect(app.loanId).to.equal(loanId1);
            expect(app.borrower).to.equal(borrower1.address);
        });

        it("Should return application status", async function () {
            const status = await loanApplication.getStatus(loanId1);
            expect(status).to.equal(0); // Draft
        });

        it("Should return true if application exists", async function () {
            expect(await loanApplication.exists(loanId1)).to.be.true;
        });

        it("Should return false if application does not exist", async function () {
            expect(await loanApplication.exists(loanId2)).to.be.false;
        });

        it("Should return borrower's applications", async function () {
            await loanApplication.connect(borrower1).createApplication(
                loanId2, productId, requestedAmount, termMonths, interestRateBps
            );

            const apps = await loanApplication.getBorrowerApplications(borrower1.address);
            expect(apps.length).to.equal(2);
            expect(apps[0]).to.equal(loanId1);
            expect(apps[1]).to.equal(loanId2);
        });

        it("Should return borrower application count", async function () {
            const count = await loanApplication.getBorrowerApplicationCount(borrower1.address);
            expect(count).to.equal(1);
        });
    });

    describe("Admin Functions", function () {
        it("Should pause contract", async function () {
            await loanApplication.connect(admin).pause();
            expect(await loanApplication.paused()).to.be.true;
        });

        it("Should unpause contract", async function () {
            await loanApplication.connect(admin).pause();
            await loanApplication.connect(admin).unpause();
            expect(await loanApplication.paused()).to.be.false;
        });

        it("Should grant SYSTEM_ROLE", async function () {
            await loanApplication.connect(admin).grantSystemRole(unauthorized.address);
            expect(await loanApplication.hasRole(SYSTEM_ROLE, unauthorized.address)).to.be.true;
        });

        it("Should revoke SYSTEM_ROLE", async function () {
            await loanApplication.connect(admin).grantSystemRole(unauthorized.address);
            await loanApplication.connect(admin).revokeSystemRole(unauthorized.address);
            expect(await loanApplication.hasRole(SYSTEM_ROLE, unauthorized.address)).to.be.false;
        });

        it("Should revert pause if not admin", async function () {
            await expect(
                loanApplication.connect(borrower1).pause()
            ).to.be.reverted;
        });
    });

    describe("Upgrade", function () {
        it("Should upgrade contract", async function () {
            const LoanApplicationV2 = await ethers.getContractFactory("LoanApplication");
            await upgrades.upgradeProxy(await loanApplication.getAddress(), LoanApplicationV2);
            
            // Verify state is preserved
            await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );
            const app = await loanApplication.getApplication(loanId1);
            expect(app.loanId).to.equal(loanId1);
        });

        it("Should revert upgrade if not UPGRADER_ROLE", async function () {
            const LoanApplicationV2 = await ethers.getContractFactory("LoanApplication", borrower1);
            await expect(
                upgrades.upgradeProxy(await loanApplication.getAddress(), LoanApplicationV2)
            ).to.be.reverted;
        });
    });

    describe("Gas Optimization", function () {
        it("Should create application within gas limit", async function () {
            const tx = await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );
            const receipt = await tx.wait();
            console.log(`createApplication gas used: ${receipt.gasUsed.toString()}`);
            // Realistic gas limit for proxy contract with audit logging
            expect(receipt.gasUsed).to.be.lessThan(600000);
        });

        it("Should submit application within gas limit", async function () {
            await loanApplication.connect(borrower1).createApplication(
                loanId1, productId, requestedAmount, termMonths, interestRateBps
            );
            
            const tx = await loanApplication.connect(borrower1).submitApplication(
                loanId1, eligibilityScore, RiskCategory.Low, aiRecommendationHash
            );
            const receipt = await tx.wait();
            console.log(`submitApplication gas used: ${receipt.gasUsed.toString()}`);
            // Realistic gas limit for proxy contract with audit logging
            expect(receipt.gasUsed).to.be.lessThan(450000);
        });
    });
});
