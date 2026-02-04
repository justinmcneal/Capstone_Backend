// Deployment script for Token-based MSME Loan Smart Contracts
// This deploys the ERC20 token and token-based disbursement/repayment contracts

const { ethers, upgrades } = require("hardhat");

async function main() {
  console.log("Starting deployment of Token-based MSME Loan Contracts...\n");

  const [deployer] = await ethers.getSigners();
  console.log("Deploying contracts with account:", deployer.address);
  console.log("Account balance:", (await ethers.provider.getBalance(deployer.address)).toString());
  console.log("");

  // Configuration
  const TOKEN_NAME = "MSME Pathway Token";
  const TOKEN_SYMBOL = "MPT";
  const INITIAL_SUPPLY = ethers.parseEther("1000000000"); // 1 billion tokens
  const MAX_SUPPLY = ethers.parseEther("10000000000");    // 10 billion cap

  const deployedContracts = {};

  // ============ 1. Deploy LoanToken (ERC20) ============
  console.log("1. Deploying LoanToken (ERC20)...");
  const LoanToken = await ethers.getContractFactory("LoanToken");
  const loanToken = await LoanToken.deploy(
    TOKEN_NAME,
    TOKEN_SYMBOL,
    INITIAL_SUPPLY,
    deployer.address, // Treasury = deployer initially
    MAX_SUPPLY
  );
  await loanToken.waitForDeployment();
  deployedContracts.loanToken = await loanToken.getAddress();
  console.log("   LoanToken deployed to:", deployedContracts.loanToken);
  console.log("   - Name:", TOKEN_NAME);
  console.log("   - Symbol:", TOKEN_SYMBOL);
  console.log("   - Initial Supply:", ethers.formatEther(INITIAL_SUPPLY));

  // ============ 2. Deploy LoanAccessControl ============
  console.log("\n2. Deploying LoanAccessControl...");
  const LoanAccessControl = await ethers.getContractFactory("LoanAccessControl");
  const accessControl = await upgrades.deployProxy(
    LoanAccessControl,
    [deployer.address],
    { kind: "uups" }
  );
  await accessControl.waitForDeployment();
  deployedContracts.accessControl = await accessControl.getAddress();
  console.log("   LoanAccessControl deployed to:", deployedContracts.accessControl);

  // ============ 3. Deploy AuditRegistry ============
  console.log("3. Deploying AuditRegistry...");
  const AuditRegistry = await ethers.getContractFactory("AuditRegistry");
  const auditRegistry = await upgrades.deployProxy(
    AuditRegistry,
    [deployer.address],
    { kind: "uups" }
  );
  await auditRegistry.waitForDeployment();
  deployedContracts.auditRegistry = await auditRegistry.getAddress();
  console.log("   AuditRegistry deployed to:", deployedContracts.auditRegistry);

  // ============ 4. Deploy LoanCore ============
  console.log("4. Deploying LoanCore...");
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

  // ============ 5. Deploy TokenDisbursement ============
  console.log("5. Deploying TokenDisbursement...");
  const TokenDisbursement = await ethers.getContractFactory("TokenDisbursement");
  const tokenDisbursement = await upgrades.deployProxy(
    TokenDisbursement,
    [
      deployedContracts.loanToken,
      deployedContracts.loanCore,
      deployedContracts.auditRegistry,
      deployer.address, // Treasury
      deployer.address  // Admin
    ],
    { kind: "uups" }
  );
  await tokenDisbursement.waitForDeployment();
  deployedContracts.tokenDisbursement = await tokenDisbursement.getAddress();
  console.log("   TokenDisbursement deployed to:", deployedContracts.tokenDisbursement);

  // ============ 6. Deploy TokenRepayment ============
  console.log("6. Deploying TokenRepayment...");
  const TokenRepayment = await ethers.getContractFactory("TokenRepayment");
  const tokenRepayment = await upgrades.deployProxy(
    TokenRepayment,
    [
      deployedContracts.loanToken,
      deployedContracts.loanCore,
      deployedContracts.auditRegistry,
      deployer.address, // Treasury
      deployer.address  // Admin
    ],
    { kind: "uups" }
  );
  await tokenRepayment.waitForDeployment();
  deployedContracts.tokenRepayment = await tokenRepayment.getAddress();
  console.log("   TokenRepayment deployed to:", deployedContracts.tokenRepayment);

  // ============ 7. Configure Roles ============
  console.log("\n7. Configuring roles and permissions...");
  
  const SYSTEM_ROLE = ethers.keccak256(ethers.toUtf8Bytes("SYSTEM_ROLE"));
  const LOAN_OFFICER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOAN_OFFICER_ROLE"));
  const LOGGER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("LOGGER_ROLE"));

  // Grant SYSTEM_ROLE to TokenDisbursement
  await loanCore.grantRole(SYSTEM_ROLE, deployedContracts.tokenDisbursement);
  console.log("   - Granted SYSTEM_ROLE to TokenDisbursement");

  // Grant SYSTEM_ROLE to TokenRepayment
  await loanCore.grantRole(SYSTEM_ROLE, deployedContracts.tokenRepayment);
  console.log("   - Granted SYSTEM_ROLE to TokenRepayment");

  // Grant LOGGER_ROLE to contracts
  await auditRegistry.grantRole(LOGGER_ROLE, deployedContracts.loanCore);
  await auditRegistry.grantRole(LOGGER_ROLE, deployedContracts.tokenDisbursement);
  await auditRegistry.grantRole(LOGGER_ROLE, deployedContracts.tokenRepayment);
  console.log("   - Granted LOGGER_ROLE to core contracts");

  // ============ 8. Fund TokenDisbursement ============
  console.log("\n8. Funding TokenDisbursement contract...");
  const fundAmount = ethers.parseEther("100000000"); // 100 million tokens
  await loanToken.approve(deployedContracts.tokenDisbursement, fundAmount);
  await loanToken.transfer(deployedContracts.tokenDisbursement, fundAmount);
  console.log("   - Transferred", ethers.formatEther(fundAmount), "tokens to TokenDisbursement");

  // ============ Summary ============
  console.log("\n" + "=".repeat(60));
  console.log("DEPLOYMENT COMPLETE!");
  console.log("=".repeat(60));
  console.log("\nDeployed Contract Addresses:");
  console.log("-".repeat(60));
  Object.entries(deployedContracts).forEach(([name, address]) => {
    console.log(`${name.padEnd(25)} : ${address}`);
  });

  console.log("\n" + "-".repeat(60));
  console.log("Token Information:");
  console.log("-".repeat(60));
  console.log(`Name                     : ${TOKEN_NAME}`);
  console.log(`Symbol                   : ${TOKEN_SYMBOL}`);
  console.log(`Decimals                 : 18`);
  console.log(`Initial Supply           : ${ethers.formatEther(INITIAL_SUPPLY)}`);
  console.log(`Max Supply               : ${ethers.formatEther(MAX_SUPPLY)}`);
  console.log(`Treasury                 : ${deployer.address}`);

  // Write addresses to file for easy reference
  const fs = require("fs");
  const addressesPath = "./deployed-addresses.json";
  fs.writeFileSync(
    addressesPath,
    JSON.stringify({
      network: (await ethers.provider.getNetwork()).name,
      chainId: (await ethers.provider.getNetwork()).chainId.toString(),
      deployer: deployer.address,
      timestamp: new Date().toISOString(),
      contracts: deployedContracts,
      token: {
        name: TOKEN_NAME,
        symbol: TOKEN_SYMBOL,
        decimals: 18,
        initialSupply: INITIAL_SUPPLY.toString(),
        maxSupply: MAX_SUPPLY.toString()
      }
    }, null, 2)
  );
  console.log(`\nAddresses saved to: ${addressesPath}`);

  console.log("\n" + "=".repeat(60));
  console.log("NEXT STEPS:");
  console.log("=".repeat(60));
  console.log("1. Update your Django .env with these contract addresses");
  console.log("2. Register loan officers using accessControl.registerOfficer()");
  console.log("3. Register borrowers when they sign up");
  console.log("4. Borrowers need to approve TokenRepayment contract to spend their tokens");
  console.log("\nFor testing, you can mint more tokens using:");
  console.log(`   loanToken.mint(address, amount)`);
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
