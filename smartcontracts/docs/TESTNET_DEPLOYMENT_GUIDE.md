# Testnet Deployment Guide

Complete guide to deploy smart contracts to Ethereum Sepolia testnet and verify on Etherscan.

---

## Prerequisites

### 1. Create a Wallet (MetaMask)

1. Install [MetaMask](https://metamask.io/) browser extension
2. Create a new wallet or import existing one
3. **CRITICAL:** Backup your secret recovery phrase securely
4. Copy your wallet address (e.g., `0x1234...abcd`)

### 2. Get Testnet ETH (Free)

You need Sepolia ETH to pay for gas fees:

**Faucets (choose one):**
- [Alchemy Sepolia Faucet](https://sepoliafaucet.com/) - Requires Alchemy account
- [Infura Sepolia Faucet](https://www.infura.io/faucet/sepolia) - Requires Infura account
- [Sepolia PoW Faucet](https://sepolia-faucet.pk910.de/) - Mine testnet ETH

**Process:**
1. Switch MetaMask to Sepolia network
2. Visit any faucet
3. Paste your wallet address
4. Receive 0.5-1 Sepolia ETH (usually within minutes)

### 3. Get RPC Provider API Key

Choose one provider (free tier works):

**Option A: Alchemy (Recommended)**
1. Sign up at [alchemy.com](https://www.alchemy.com/)
2. Create new app → Select "Ethereum" → "Sepolia"
3. Copy the HTTPS URL: `https://eth-sepolia.g.alchemy.com/v2/YOUR-API-KEY`

**Option B: Infura**
1. Sign up at [infura.io](https://infura.io/)
2. Create new project → Ethereum → Sepolia
3. Copy the HTTPS URL: `https://sepolia.infura.io/v3/YOUR-PROJECT-ID`

### 4. Get Etherscan API Key (for verification)

1. Sign up at [etherscan.io](https://etherscan.io/)
2. Go to "API Keys" → Create new API key
3. Copy the API key (e.g., `ABC123...`)

---

## Setup Configuration

### Step 1: Install Dependencies

```bash
cd smartcontracts
npm install --save-dev @nomiclabs/hardhat-etherscan dotenv
```

### Step 2: Create Environment File

Create `.env` file in the `smartcontracts` directory:

```bash
touch .env
```

Add the following (replace with your actual values):

```env
# Your wallet's private key (NEVER commit this!)
PRIVATE_KEY=your_wallet_private_key_here

# RPC URL from Alchemy or Infura
SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR-API-KEY

# Etherscan API key for contract verification
ETHERSCAN_API_KEY=your_etherscan_api_key_here
```

**⚠️ SECURITY WARNING:**
- NEVER share your private key
- NEVER commit `.env` to git
- Use a separate wallet for testing (not your main wallet)

**To get your private key from MetaMask:**
1. Open MetaMask
2. Click 3 dots → Account Details → Export Private Key
3. Enter password → Copy the key

### Step 3: Add `.env` to `.gitignore`

Ensure `.gitignore` contains:

```
.env
node_modules/
cache/
artifacts/
```

### Step 4: Update `hardhat.config.js`

Add Sepolia network configuration:

```javascript
require("@nomicfoundation/hardhat-toolbox");
require("@nomiclabs/hardhat-etherscan");
require("dotenv").config();

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.20",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200
      }
    }
  },
  networks: {
    localhost: {
      url: "http://127.0.0.1:8545",
      chainId: 31337
    },
    sepolia: {
      url: process.env.SEPOLIA_RPC_URL,
      accounts: [process.env.PRIVATE_KEY],
      chainId: 11155111,
      gasPrice: "auto"
    }
  },
  etherscan: {
    apiKey: process.env.ETHERSCAN_API_KEY
  }
};
```

---

## Deployment Process

### Step 1: Check Your Balance

```bash
npx hardhat run scripts/check-balance.js --network sepolia
```

Create `scripts/check-balance.js` if needed:

```javascript
const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const balance = await hre.ethers.provider.getBalance(deployer.address);
  
  console.log("Deployer address:", deployer.address);
  console.log("Balance:", hre.ethers.formatEther(balance), "ETH");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
```

**Expected:** At least 0.2 ETH for deployment

### Step 2: Compile Contracts

```bash
npm run compile
```

Verify no errors.

### Step 3: Deploy to Sepolia

```bash
npx hardhat run scripts/deploy.js --network sepolia
```

**This will take 2-5 minutes.** You'll see:

```
Deploying contracts to Sepolia testnet...
Network: sepolia (chain ID: 11155111)
Deployer: 0xYourAddress

1. Deploying LoanAccessControl...
   ⏳ Waiting for confirmation...
   ✅ LoanAccessControl deployed to: 0xabcd...1234
   Transaction: 0x1234...abcd

2. Deploying AuditRegistry...
   ⏳ Waiting for confirmation...
   ✅ AuditRegistry deployed to: 0xefgh...5678
   
[... continues for all 5 contracts]

✅ All contracts deployed successfully!
📝 Addresses saved to: deployed-addresses-sepolia.json
```

**Save the contract addresses!** You'll need them for verification.

### Step 4: Wait for Block Confirmations

Wait ~1 minute for blocks to be mined and indexed by Etherscan.

---

## Contract Verification

Verification allows anyone to view your contract source code on Etherscan.

### Option 1: Verify Using Hardhat Plugin

Create `scripts/verify.js`:

```javascript
const hre = require("hardhat");
const addresses = require("../deployed-addresses-sepolia.json");

async function main() {
  console.log("Verifying contracts on Etherscan...\n");

  // Verify LoanAccessControl
  console.log("1. Verifying LoanAccessControl...");
  await hre.run("verify:verify", {
    address: addresses.LoanAccessControl,
    constructorArguments: []
  });

  // Verify AuditRegistry
  console.log("2. Verifying AuditRegistry...");
  await hre.run("verify:verify", {
    address: addresses.AuditRegistry,
    constructorArguments: []
  });

  // Verify LoanCore
  console.log("3. Verifying LoanCore...");
  await hre.run("verify:verify", {
    address: addresses.LoanCore,
    constructorArguments: []
  });

  // Verify Disbursement
  console.log("4. Verifying Disbursement...");
  await hre.run("verify:verify", {
    address: addresses.Disbursement,
    constructorArguments: []
  });

  // Verify Repayment
  console.log("5. Verifying Repayment...");
  await hre.run("verify:verify", {
    address: addresses.Repayment,
    constructorArguments: []
  });

  console.log("\n✅ All contracts verified!");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
```

Run verification:

```bash
npx hardhat run scripts/verify.js --network sepolia
```

### Option 2: Manual Verification on Etherscan

For each contract:

1. Go to [sepolia.etherscan.io](https://sepolia.etherscan.io/)
2. Search for your contract address
3. Click "Contract" tab → "Verify and Publish"
4. Select:
   - Compiler Type: Solidity (Single file)
   - Compiler Version: v0.8.20
   - License: MIT
5. Copy contract source code from `contracts/` folder
6. Add OpenZeppelin imports
7. Submit

---

## Testing on Testnet

### Connect Hardhat Console to Sepolia

```bash
npx hardhat console --network sepolia
```

### Quick Test Script

```javascript
// Get deployer account
const [deployer] = await ethers.getSigners();
console.log("Connected as:", deployer.address);

// Connect to deployed contracts (use your addresses)
const loanCore = await ethers.getContractAt(
  "LoanCore", 
  "0xYOUR_LOANCORE_ADDRESS"
);

// Check version
const version = await loanCore.VERSION();
console.log("LoanCore Version:", version.toString());

// Create a test loan
const loanId = ethers.keccak256(ethers.toUtf8Bytes("TEST-SEPOLIA-001"));
const productId = ethers.keccak256(ethers.toUtf8Bytes("PRODUCT-001"));
const amount = ethers.parseEther("1000");

await loanCore.createLoan(loanId, productId, amount, 12, 150);
console.log("✅ Loan created on Sepolia!");
```

---

## View on Etherscan

### Contract Pages

Visit: `https://sepolia.etherscan.io/address/YOUR_CONTRACT_ADDRESS`

You can:
- ✅ View transaction history
- ✅ See contract events
- ✅ Read contract state
- ✅ Write to contract (if connected with MetaMask)

### Transaction Pages

Each transaction shows:
- Block number
- Timestamp
- Gas used
- Transaction status
- Events emitted
- Function called

Example: `https://sepolia.etherscan.io/tx/0xTRANSACTION_HASH`

---

## Cost Estimation

### Deployment Costs (Sepolia)

| Contract | Gas Used | Cost (ETH) | USD Equivalent* |
|----------|----------|------------|-----------------|
| LoanAccessControl | ~500K | 0.01 | ~$20 |
| AuditRegistry | ~450K | 0.009 | ~$18 |
| LoanCore | ~3.5M | 0.07 | ~$140 |
| Disbursement | ~2M | 0.04 | ~$80 |
| Repayment | ~3M | 0.06 | ~$120 |
| **Total** | **~9.45M** | **~0.19** | **~$380** |

*Estimates based on 20 gwei gas price and $2000 ETH

**Note:** Testnet ETH is free! These costs only apply to mainnet.

---

## Troubleshooting

### Error: "Insufficient funds"

**Solution:** Get more testnet ETH from faucets

### Error: "Invalid API Key"

**Solution:** 
1. Check `.env` file has correct Etherscan API key
2. Ensure no extra spaces in API key
3. Wait a few minutes after creating API key

### Error: "Transaction underpriced"

**Solution:** Increase gas price in `hardhat.config.js`:

```javascript
sepolia: {
  url: process.env.SEPOLIA_RPC_URL,
  accounts: [process.env.PRIVATE_KEY],
  gasPrice: 30000000000 // 30 gwei
}
```

### Error: "Nonce too high"

**Solution:** Reset MetaMask account:
1. Settings → Advanced → Clear activity tab data

### Error: "Contract verification failed"

**Solution:**
1. Wait 2-3 minutes after deployment
2. Ensure contract is deployed (check on Etherscan)
3. Try manual verification on Etherscan website

### Transactions Taking Too Long

**Normal:** Sepolia blocks are ~12-15 seconds
**If stuck (>5 minutes):** Check [sepolia.etherscan.io](https://sepolia.etherscan.io/) for network status

---

## Security Checklist

Before deploying to testnet:

- [ ] `.env` file is in `.gitignore`
- [ ] Using a separate test wallet (not main wallet)
- [ ] Private key is never hardcoded in scripts
- [ ] Contract access controls are configured correctly
- [ ] All tests pass: `npm test`
- [ ] Contracts are compiled without warnings

Before deploying to mainnet:

- [ ] Full security audit completed
- [ ] Extensive testnet testing done
- [ ] Emergency pause mechanisms tested
- [ ] Upgrade strategy documented
- [ ] Multi-sig wallet for admin role
- [ ] Insurance/bug bounty program considered

---

## Next Steps

After successful deployment:

1. **Share contract addresses** with your team
2. **Test all functions** on Sepolia testnet
3. **Document transaction hashes** for important operations
4. **Set up monitoring** (e.g., Tenderly, Defender)
5. **Create frontend** to interact with contracts
6. **Get security audit** before mainnet deployment

---

## Additional Resources

- [Hardhat Documentation](https://hardhat.org/docs)
- [Etherscan API](https://docs.etherscan.io/)
- [Sepolia Testnet Info](https://sepolia.dev/)
- [OpenZeppelin Security](https://docs.openzeppelin.com/contracts/4.x/api/security)
- [Ethereum Gas Tracker](https://etherscan.io/gastracker)

---

## Quick Reference

### Common Commands

```bash
# Deploy to Sepolia
npx hardhat run scripts/deploy.js --network sepolia

# Verify contracts
npx hardhat run scripts/verify.js --network sepolia

# Console on Sepolia
npx hardhat console --network sepolia

# Check balance
npx hardhat run scripts/check-balance.js --network sepolia

# Run tests
npm test
```

### Network Info

| Network | Chain ID | Block Explorer |
|---------|----------|----------------|
| Localhost | 31337 | N/A |
| Sepolia | 11155111 | sepolia.etherscan.io |
| Mainnet | 1 | etherscan.io |

### Gas Price References

- **Low:** 10-20 gwei (slower, cheaper)
- **Medium:** 20-40 gwei (normal)
- **High:** 40-100 gwei (faster, expensive)

Check current prices: [ethgasstation.info](https://ethgasstation.info/)
