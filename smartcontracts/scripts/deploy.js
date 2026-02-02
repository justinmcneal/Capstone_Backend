// Deployment script for MSME Loan Smart Contracts
// Deploy order matters due to contract dependencies

const { ethers, upgrades } = require("hardhat");

async function main() {
  console.log("Starting deployment of MSME Loan Contracts...\n");

  const [deployer] = await ethers.getSigners();
  console.log("Deploying contracts with account:", deployer.address);
  console.log("Account balance:", (await ethers.provider.getBalance(deployer.address)).toString());
  console.log("");

  // Track deployed addresses
  const deployedContracts = {};

  // ============ 1. Deploy LoanAccessControl ============
  console.log("1. Deploying LoanAccessControl...");
  const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
  const accessControl = await upgrades.deployProxy(
    LoanAccessControl,
    [deployer.address],
    { kind: "uups" }
  );
  await accessControl.waitForDeployment();
  deployedContracts.accessControl = await accessControl.getAddress();
  console.log("   LoanAccessControl deployed to:", deployedContracts.accessControl);

  // ============ 2. Deploy AuditRegistry ============
  console.log("2. Deploying AuditRegistry...");
  const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
  const auditRegistry = await upgrades.deployProxy(
    AuditRegistry,
    [deployer.address],
    { kind: "uups" }
  );
  await auditRegistry.waitForDeployment();
  deployedContracts.auditRegistry = await auditRegistry.getAddress();
  console.log("   AuditRegistry deployed to:", deployedContracts.auditRegistry);

  // ============ 3. Deploy LoanCore ============
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

  // ============ 4. Deploy Disbursement ============
  console.log("4. Deploying Disbursement...");
  const Disbursement = await ethers.getContractFactory("Disbursement");
  const disbursement = await upgrades.deployProxy(
    Disbursement,
    [
      deployedContracts.loanCore,
      deployedContracts.auditRegistry,
      deployer.address
    ],
    { kind: "uups" }
  );
  await disbursement.waitForDeployment();
  deployedContracts.disbursement = await disbursement.getAddress();
  console.log("   Disbursement deployed to:", deployedContracts.disbursement);

  // ============ 5. Deploy Repayment ============
  console.log("5. Deploying Repayment...");
  const Repayment = await ethers.getContractFactory("Repayment");
  const repayment = await upgrades.deployProxy(
    Repayment,
    [
      deployedContracts.loanCore,
      deployedContracts.auditRegistry,
      deployer.address
    ],
    { kind: "uups" }
  );
  await repayment.waitForDeployment();
  deployedContracts.repayment = await repayment.getAddress();
  console.log("   Repayment deployed to:", deployedContracts.repayment);

  // ============ 6. Configure Cross-Contract References ============
  console.log("\n6. Configuring cross-contract references...");
  
  // Set contract references in LoanCore
  const loanCoreContract = await ethers.getContractAt("LoanCore", deployedContracts.loanCore);
  await loanCoreContract.setContracts(
    deployedContracts.disbursement,
    deployedContracts.repayment,
    ethers.ZeroAddress  // No oracle contract
  );
  console.log("   LoanCore references configured");

  // Grant LOGGER_ROLE to contracts in AuditRegistry
  const auditRegistryContract = await ethers.getContractAt("AuditRegistry", deployedContracts.auditRegistry);
  await auditRegistryContract.grantLoggerRole(deployedContracts.loanCore);
  await auditRegistryContract.grantLoggerRole(deployedContracts.disbursement);
  await auditRegistryContract.grantLoggerRole(deployedContracts.repayment);
  console.log("   AuditRegistry logger roles granted");

  // Grant roles
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
  
  // Grant SYSTEM_ROLE to Disbursement and Repayment in LoanCore
  await loanCoreContract.grantRole(SYSTEM_ROLE, deployedContracts.disbursement);
  await loanCoreContract.grantRole(SYSTEM_ROLE, deployedContracts.repayment);
  console.log("   System roles granted");

  // ============ 7. Verify Deployment ============
  console.log("\n7. Verifying deployment...");
  
  // Check versions
  const accessControlVersion = await (await ethers.getContractAt("LoanAccessControl", deployedContracts.accessControl)).VERSION();
  const loanCoreVersion = await (await ethers.getContractAt("LoanCore", deployedContracts.loanCore)).VERSION();
  console.log("   LoanAccessControl version:", accessControlVersion.toString());
  console.log("   LoanCore version:", loanCoreVersion.toString());

  // ============ Summary ============
  console.log("\n" + "=".repeat(60));
  console.log("DEPLOYMENT COMPLETE");
  console.log("=".repeat(60));
  console.log("\nDeployed Contract Addresses:");
  console.log("-".repeat(60));
  Object.entries(deployedContracts).forEach(([name, address]) => {
    console.log(`${name.padEnd(20)}: ${address}`);
  });
  console.log("-".repeat(60));

  // Save to file
  const fs = require("fs");
  const deploymentData = {
    network: network.name,
    timestamp: new Date().toISOString(),
    deployer: deployer.address,
    contracts: deployedContracts
  };
  
  fs.writeFileSync(
    `./deployments/${network.name}-${Date.now()}.json`,
    JSON.stringify(deploymentData, null, 2)
  );
  console.log(`\nDeployment data saved to ./deployments/`);

  return deployedContracts;
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
