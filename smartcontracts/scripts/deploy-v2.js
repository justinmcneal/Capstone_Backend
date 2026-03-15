// Deployment script for MSME Loan Smart Contracts — V2 Refactored Architecture
// Deploy order matters due to contract dependencies

const { ethers, upgrades } = require("hardhat");

async function main() {
  console.log("Starting deployment of MSME Loan V2 Contracts...\n");

  const [deployer] = await ethers.getSigners();
  console.log("Deploying contracts with account:", deployer.address);
  console.log("Account balance:", (await ethers.provider.getBalance(deployer.address)).toString());
  console.log("");

  const backendWallet = process.env.BACKEND_WALLET || null;
  if (backendWallet) {
    console.log("Backend service wallet:", backendWallet);
  }
  console.log("");

  // Track deployed addresses
  const deployedContracts = {};

  try {
    // ============ 1. Deploy AuditRegistry ============
    console.log("1. Deploying AuditRegistry...");
    const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
    const auditRegistry = await upgrades.deployProxy(
      AuditRegistry,
      [deployer.address],
      { kind: "uups" }
    );
    await auditRegistry.waitForDeployment();
    deployedContracts.auditRegistry = await auditRegistry.getAddress();
    console.log("   AuditRegistry deployed to:", deployedContracts.auditRegistry);

    // ============ 2. Deploy LoanAccessControl ============
    console.log("2. Deploying LoanAccessControl...");
    const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
    const accessControl = await upgrades.deployProxy(
      LoanAccessControl,
      [deployer.address],
      { kind: "uups" }
    );
    await accessControl.waitForDeployment();
    deployedContracts.accessControl = await accessControl.getAddress();
    console.log("   LoanAccessControl deployed to:", deployedContracts.accessControl);

    // ============ 3. Deploy LoanCore (monolith, needed by RepaymentSchedule) ============
    console.log("3. Deploying LoanCore...");
    const LoanCore = await ethers.getContractFactory("LoanCore");
    const loanCore = await upgrades.deployProxy(
      LoanCore,
      [
        deployedContracts.accessControl,
        deployedContracts.auditRegistry,
        deployer.address
      ],
      { kind: "uups" }
    );
    await loanCore.waitForDeployment();
    deployedContracts.loanCore = await loanCore.getAddress();
    console.log("   LoanCore deployed to:", deployedContracts.loanCore);

    // ============ 4. Deploy LoanApplication ============
    console.log("4. Deploying LoanApplication...");
    const LoanApplication = await ethers.getContractFactory("LoanApplication");
    const loanApplication = await upgrades.deployProxy(
      LoanApplication,
      [
        deployedContracts.accessControl,
        deployedContracts.auditRegistry,
        deployer.address
      ],
      { kind: "uups" }
    );
    await loanApplication.waitForDeployment();
    deployedContracts.loanApplication = await loanApplication.getAddress();
    console.log("   LoanApplication deployed to:", deployedContracts.loanApplication);

    // ============ 5. Deploy LoanReview ============
    console.log("5. Deploying LoanReview...");
    const LoanReview = await ethers.getContractFactory("LoanReview");
    const loanReview = await upgrades.deployProxy(
      LoanReview,
      [
        deployedContracts.accessControl,
        deployedContracts.auditRegistry,
        deployedContracts.loanApplication,
        deployer.address
      ],
      { kind: "uups" }
    );
    await loanReview.waitForDeployment();
    deployedContracts.loanReview = await loanReview.getAddress();
    console.log("   LoanReview deployed to:", deployedContracts.loanReview);

    // ============ 6. Deploy LoanApproval ============
    console.log("6. Deploying LoanApproval...");
    const LoanApproval = await ethers.getContractFactory("LoanApproval");
    const loanApproval = await upgrades.deployProxy(
      LoanApproval,
      [
        deployedContracts.accessControl,
        deployedContracts.auditRegistry,
        deployedContracts.loanApplication,
        deployedContracts.loanReview,
        deployer.address
      ],
      { kind: "uups" }
    );
    await loanApproval.waitForDeployment();
    deployedContracts.loanApproval = await loanApproval.getAddress();
    console.log("   LoanApproval deployed to:", deployedContracts.loanApproval);

    // ============ 7. Deploy DisbursementMethod ============
    console.log("7. Deploying DisbursementMethod...");
    const DisbursementMethod = await ethers.getContractFactory("DisbursementMethod");
    const disbursementMethod = await upgrades.deployProxy(
      DisbursementMethod,
      [
        deployedContracts.accessControl,
        deployedContracts.auditRegistry,
        deployedContracts.loanApplication,
        deployer.address
      ],
      { kind: "uups" }
    );
    await disbursementMethod.waitForDeployment();
    deployedContracts.disbursementMethod = await disbursementMethod.getAddress();
    console.log("   DisbursementMethod deployed to:", deployedContracts.disbursementMethod);

    // ============ 8. Deploy DisbursementExecution ============
    console.log("8. Deploying DisbursementExecution...");
    const DisbursementExecution = await ethers.getContractFactory("DisbursementExecution");
    const disbursementExecution = await upgrades.deployProxy(
      DisbursementExecution,
      [
        deployedContracts.accessControl,
        deployedContracts.auditRegistry,
        deployedContracts.loanApplication,
        deployedContracts.disbursementMethod,
        deployer.address
      ],
      { kind: "uups" }
    );
    await disbursementExecution.waitForDeployment();
    deployedContracts.disbursementExecution = await disbursementExecution.getAddress();
    console.log("   DisbursementExecution deployed to:", deployedContracts.disbursementExecution);

    // ============ 9. Deploy RepaymentSchedule ============
    console.log("9. Deploying RepaymentSchedule...");
    const RepaymentSchedule = await ethers.getContractFactory("RepaymentSchedule");
    const repaymentSchedule = await upgrades.deployProxy(
      RepaymentSchedule,
      [
        deployedContracts.loanCore,
        deployer.address
      ],
      { kind: "uups" }
    );
    await repaymentSchedule.waitForDeployment();
    deployedContracts.repaymentSchedule = await repaymentSchedule.getAddress();
    console.log("   RepaymentSchedule deployed to:", deployedContracts.repaymentSchedule);

    // ============ 10. Deploy PaymentRecording ============
    console.log("10. Deploying PaymentRecording...");
    const PaymentRecording = await ethers.getContractFactory("PaymentRecording");
    const paymentRecording = await upgrades.deployProxy(
      PaymentRecording,
      [
        deployedContracts.repaymentSchedule,
        deployedContracts.auditRegistry,
        deployer.address
      ],
      { kind: "uups" }
    );
    await paymentRecording.waitForDeployment();
    deployedContracts.paymentRecording = await paymentRecording.getAddress();
    console.log("   PaymentRecording deployed to:", deployedContracts.paymentRecording);

    // ============ 11. Post-Deployment Wiring ============
    console.log("\n11. Configuring cross-contract roles and references...");

    // 11a. Grant LOGGER_ROLE on AuditRegistry to all logging contracts
    console.log("   11a. Granting LOGGER_ROLE on AuditRegistry...");
    const auditRegistryContract = await ethers.getContractAt("AuditRegistry", deployedContracts.auditRegistry);
    await auditRegistryContract.grantLoggerRole(deployedContracts.loanCore);
    await auditRegistryContract.grantLoggerRole(deployedContracts.loanApplication);
    await auditRegistryContract.grantLoggerRole(deployedContracts.loanReview);
    await auditRegistryContract.grantLoggerRole(deployedContracts.loanApproval);
    await auditRegistryContract.grantLoggerRole(deployedContracts.disbursementMethod);
    await auditRegistryContract.grantLoggerRole(deployedContracts.disbursementExecution);
    await auditRegistryContract.grantLoggerRole(deployedContracts.paymentRecording);
    console.log("        LOGGER_ROLE granted to 7 contracts");

    // 11b. Grant SYSTEM_ROLE on LoanApplication to status-updating contracts
    console.log("   11b. Granting SYSTEM_ROLE on LoanApplication...");
    const loanApplicationContract = await ethers.getContractAt("LoanApplication", deployedContracts.loanApplication);
    await loanApplicationContract.grantSystemRole(deployedContracts.loanReview);
    await loanApplicationContract.grantSystemRole(deployedContracts.loanApproval);
    await loanApplicationContract.grantSystemRole(deployedContracts.disbursementExecution);
    console.log("        SYSTEM_ROLE granted to LoanReview, LoanApproval, DisbursementExecution");

    // 11c. Grant SYSTEM_ROLE on DisbursementMethod to DisbursementExecution
    console.log("   11c. Granting SYSTEM_ROLE on DisbursementMethod...");
    const disbursementMethodContract = await ethers.getContractAt("DisbursementMethod", deployedContracts.disbursementMethod);
    await disbursementMethodContract.grantSystemRole(deployedContracts.disbursementExecution);
    console.log("        SYSTEM_ROLE granted to DisbursementExecution");

    // 11d. Grant SYSTEM_ROLE on RepaymentSchedule to PaymentRecording
    console.log("   11d. Granting SYSTEM_ROLE on RepaymentSchedule...");
    const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
    const repaymentScheduleContract = await ethers.getContractAt("RepaymentSchedule", deployedContracts.repaymentSchedule);
    await repaymentScheduleContract.grantRole(SYSTEM_ROLE, deployedContracts.paymentRecording);
    console.log("        SYSTEM_ROLE granted to PaymentRecording");

    // 11e. Grant SYSTEM_ROLE on LoanCore to DisbursementExecution
    console.log("   11e. Granting SYSTEM_ROLE on LoanCore...");
    const loanCoreContract = await ethers.getContractAt("LoanCore", deployedContracts.loanCore);
    await loanCoreContract.grantRole(SYSTEM_ROLE, deployedContracts.disbursementExecution);
    console.log("        SYSTEM_ROLE granted to DisbursementExecution");

    // 11f. Configure LoanCore cross-contract references
    // LoanCore.setContracts validates non-zero for all params; use deployer as oracle placeholder
    console.log("   11f. Configuring LoanCore cross-contract references...");
    await loanCoreContract.setContracts(
      deployedContracts.disbursementExecution,
      deployedContracts.repaymentSchedule,
      deployer.address  // Oracle placeholder (non-zero required)
    );
    console.log("        LoanCore references configured (oracle = deployer placeholder)");

    // Optional: Grant SYSTEM_ROLE to backend service wallet
    if (backendWallet) {
      console.log("\n   Granting SYSTEM_ROLE to backend wallet:", backendWallet);
      await loanApplicationContract.grantSystemRole(backendWallet);
      await disbursementMethodContract.grantSystemRole(backendWallet);
      await loanCoreContract.grantRole(SYSTEM_ROLE, backendWallet);
      await repaymentScheduleContract.grantRole(SYSTEM_ROLE, backendWallet);
      console.log("        Backend wallet roles granted");
    }

    console.log("\n   Cross-contract wiring complete.");

    // ============ 12. Verify Deployment ============
    console.log("\n12. Verifying deployment...");

    const versionChecks = [
      { name: "LoanAccessControl", address: deployedContracts.accessControl },
      { name: "AuditRegistry", address: deployedContracts.auditRegistry },
      { name: "LoanCore", address: deployedContracts.loanCore },
      { name: "LoanApplication", address: deployedContracts.loanApplication },
      { name: "LoanReview", address: deployedContracts.loanReview },
      { name: "LoanApproval", address: deployedContracts.loanApproval },
      { name: "DisbursementMethod", address: deployedContracts.disbursementMethod },
      { name: "DisbursementExecution", address: deployedContracts.disbursementExecution },
      { name: "RepaymentSchedule", address: deployedContracts.repaymentSchedule },
      { name: "PaymentRecording", address: deployedContracts.paymentRecording },
    ];

    for (const { name, address } of versionChecks) {
      try {
        const contract = await ethers.getContractAt(name, address);
        const version = await contract.VERSION();
        console.log(`   ${name} version: ${version.toString()}`);
      } catch {
        console.log(`   ${name}: VERSION() not available`);
      }
    }

    // ============ Summary ============
    console.log("\n" + "=".repeat(60));
    console.log("V2 DEPLOYMENT COMPLETE");
    console.log("=".repeat(60));
    console.log("\nDeployed Contract Addresses:");
    console.log("-".repeat(60));
    Object.entries(deployedContracts).forEach(([name, address]) => {
      console.log(`${name.padEnd(25)}: ${address}`);
    });
    console.log("-".repeat(60));

    // ============ 13. Save Deployment Data ============
    const fs = require("fs");
    const deploymentData = {
      network: network.name,
      timestamp: new Date().toISOString(),
      deployer: deployer.address,
      backendWallet: backendWallet || "not configured",
      contracts: deployedContracts
    };

    const filename = `./deployments/v2-${network.name}-${Date.now()}.json`;
    fs.writeFileSync(
      filename,
      JSON.stringify(deploymentData, null, 2)
    );
    console.log(`\nDeployment data saved to ${filename}`);

    return deployedContracts;

  } catch (error) {
    console.error("\nDeployment failed!");
    console.error(error);

    // Print any contracts that were deployed before failure
    if (Object.keys(deployedContracts).length > 0) {
      console.log("\nPartially deployed contracts:");
      Object.entries(deployedContracts).forEach(([name, address]) => {
        console.log(`  ${name}: ${address}`);
      });
    }

    throw error;
  }
}

// Create deployments directory if it doesn't exist
const fs = require("fs");
if (!fs.existsSync("./deployments")) {
  fs.mkdirSync("./deployments");
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
