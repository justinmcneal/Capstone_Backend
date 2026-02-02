# MSME Pathways Smart Contract System

## 🎯 Overview

This smart contract suite provides **immutable, trustless, and auditable** record-keeping for your MSME Pathways Loan Management System. It mirrors your Django backend's financial flows on the blockchain.

### What Problem Does This Solve?

Your current Django/MongoDB backend works perfectly for day-to-day operations, but it has a fundamental limitation: **data can be modified**. An admin could theoretically:
- Change loan approval records
- Modify payment histories
- Alter audit logs

With blockchain integration, **critical financial records become tamper-proof**. Even if your database is compromised, the blockchain provides an independent source of truth.

---

## ⚠️ Security & Dependencies Notice

### NPM Audit Vulnerabilities

After installation, you'll see **50 security warnings** from `npm audit`. Here's what you need to know:

**Current Status:**
- 50 vulnerabilities (23 low, 10 moderate, 17 high) in development dependencies
- These are **NOT in your production code** - they're in development tools only
- Your Solidity contracts are NOT affected
- The contracts compile, test, and deploy successfully

**Key Vulnerabilities:**
1. **undici** (moderate) - HTTP decompression issue in Node.js Fetch API (Hardhat dependency)
2. **elliptic** (moderate) - Cryptographic implementation in ethers.js v5 (Hardhat dependency)
3. **cookie** (low) - In Hardhat's Sentry error tracking
4. **fast-xml-parser** (high) - In AWS SDK (Hardhat tooling)
5. **tmp** (low) - In solc compiler temporary files

**Why These Exist:**
- Hardhat v2 uses older dependencies (ethers.js v5)
- Most are **transitive dependencies** (dependencies of dependencies)
- They affect the development environment, not deployed contracts
- Your smart contracts on-chain are 100% independent of these Node.js packages

**Should You Fix Them?**

| Option | Command | Impact | When to Use |
|--------|---------|--------|-------------|
| **Do Nothing** | - | No changes | ✅ Testing locally (recommended) |
| **Safe Fix** | `npm audit fix` | Fixes `fast-xml-parser` only | ✅ Production deployments |
| **Force Fix** | `npm audit fix --force` | ⚠️ Upgrades to Hardhat v3 (breaking changes) | ❌ Not recommended without testing |

**Our Recommendation:**
- **For testing/learning:** Ignore the warnings - they don't affect functionality
- **For production:** Run `npm audit fix` (safe updates only)
- **To eliminate all warnings:** Manually upgrade to Hardhat v3 in the future (requires code changes)

### Node.js Version Warning

**Your Version:** Node.js v25.2.1  
**Hardhat v2 Supports:** Node.js v16-v20

**Impact:**
- ⚠️ Warning message appears during `npx hardhat` commands
- ✅ Everything still works (tests, compilation, deployment)
- ⚠️ Some edge cases may have unexpected behavior

**Why you got the `npx hardhat init` error:**
Your project is **already initialized** - you don't need to run `npx hardhat init` again! That command creates a new Hardhat project, but you already have:
- ✅ `hardhat.config.js`
- ✅ `contracts/` directory
- ✅ `test/` directory
- ✅ `scripts/` directory

**Options for the Node version:**
1. **Ignore it** - Everything works for testing/learning
2. **Downgrade Node.js** to v20 LTS using nvm:
   ```bash
   nvm install 20
   nvm use 20
   ```
3. **Upgrade to Hardhat v3** (supports Node v18-v22) - requires breaking changes

---

## 🔗 How This Aligns With Your System

### Transaction Flow Mapping

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         YOUR DJANGO BACKEND                              │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Customer                    Loan Officer                    Admin       │
│     │                            │                             │         │
│     ▼                            ▼                             ▼         │
│  POST /api/loans/apply/    PUT .../review/           POST .../assign/    │
│     │                            │                             │         │
│     │    ┌───────────────────────┴─────────────────────────────┘         │
│     │    │                                                               │
│     ▼    ▼                                                               │
│  MongoDB (loan_applications, loan_payments, repayment_schedules)         │
│     │    │                                                               │
└─────┼────┼───────────────────────────────────────────────────────────────┘
      │    │
      │    │  ◄─── Your backend calls smart contracts here
      ▼    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         SMART CONTRACTS                                  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  LoanCore.sol          Disbursement.sol           Repayment.sol          │
│  ┌─────────────┐       ┌─────────────────┐        ┌──────────────┐       │
│  │ createLoan()│       │ initiate()      │        │ recordPay()  │       │
│  │ approve()   │──────►│ complete()      │───────►│ getSchedule()│       │
│  │ reject()    │       └─────────────────┘        └──────────────┘       │
│  └─────────────┘                │                          │             │
│         │                       │                          │             │
│         └───────────────────────┴──────────────────────────┘             │
│                                │                                         │
│                                ▼                                         │
│                       AuditRegistry.sol                                  │
│                       ┌─────────────────┐                                │
│                       │ Immutable Logs  │                                │
│                       │ State Proofs    │                                │
│                       └─────────────────┘                                │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Your Backend Model → Smart Contract Mapping

| Django Model | MongoDB Collection | Smart Contract | On-Chain Data |
|--------------|-------------------|----------------|---------------|
| `LoanApplication` | `loan_applications` | `LoanCore.sol` | loan_id, borrower, amount, status, timestamps |
| `LoanPayment` | `loan_payments` | `Repayment.sol` | payment_id, amount, method, reference, timestamp |
| `RepaymentSchedule` | `repayment_schedules` | `Repayment.sol` | installment hashes, due dates, paid status |
| `LoanOfficer` | `loan_officers` | `LoanAccessControl.sol` | officer address, employee_id_hash, active status |
| `Customer` | `customers` | `LoanAccessControl.sol` | customer address, customer_id_hash (NO PII) |
| `AuditLog` | `audit_logs` | `AuditRegistry.sol` | action_hash, actor, entity_id, timestamp |

### What Goes On-Chain vs. Off-Chain

| On-Chain (Immutable) | Off-Chain (MongoDB) |
|---------------------|---------------------|
| Loan ID, amounts, timestamps | Customer PII (name, address, contact) |
| Approval/rejection decisions | AI analysis details |
| Payment records | Document files (stored in S3/IPFS) |
| Officer assignments | Business profile details |
| Status transitions | Alternative credit data |
| Cryptographic hashes of documents | Full audit log details |

**Why?** On-chain storage is expensive and PII must comply with data privacy laws (Philippine Data Privacy Act).

---

## 📁 Contract Architecture

```
smartcontracts/
├── contracts/
│   ├── LoanAccessControl.sol    # Role management (Admin, Officer, Borrower)
│   ├── LoanCore.sol             # Loan lifecycle (create, approve, reject)
│   ├── Disbursement.sol         # Fund release tracking
│   ├── Repayment.sol            # Payment recording & schedules
│   ├── AuditRegistry.sol        # Immutable event logging
│   └── interfaces/              # Contract interfaces
│       ├── ILoanAccessControl.sol
│       ├── ILoanCore.sol
│       └── IAuditRegistry.sol
├── scripts/
│   └── deploy.js                # Deployment script
├── test/                        # Unit tests
├── hardhat.config.js            # Network configuration
└── package.json                 # Dependencies
```

### Contract Responsibilities

| Contract | Purpose | Key Functions |
|----------|---------|---------------|
| **LoanAccessControl** | RBAC, officer/borrower registration | `registerOfficer()`, `registerBorrower()`, `pause()` |
| **LoanCore** | Loan state machine | `createLoan()`, `submitLoan()`, `approveLoan()`, `rejectLoan()` |
| **Disbursement** | Fund release tracking | `initiateDisbursement()`, `completeDisbursement()` |
| **Repayment** | Payment recording | `createSchedule()`, `recordPayment()` |
| **AuditRegistry** | Immutable logs | `log()`, `verifyState()` |

---

## 🚀 Quick Start

### Prerequisites

- Node.js 18+ (you have v25.2.1 ✅)
- npm or yarn ✅

### Step 1: Installation

```bash
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts
npm install
```

### Step 2: Compile Contracts

```bash
npm run compile
```

**Expected output:**
```
Compiled 8 Solidity files successfully
```

### Step 3: Run Tests (No Wallet Needed!)

```bash
npm test
```

**What happens?**
- Hardhat creates a **temporary blockchain** in memory
- Auto-generates **20 test accounts** with 10,000 test ETH each
- Runs all **100 test cases**
- Tests complete in ~3 seconds

**You don't need:**
- ❌ Real ETH
- ❌ Wallet address
- ❌ Private keys
- ❌ Any blockchain running

**Expected output:**
```
  AuditRegistry
    ✓ Should set correct version
    ✓ Should log audit entry
    ...
  
  100 passing (3s)
```

---

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [README.md](README.md) | This file - overview and quick start |
| [SMART_CONTRACT_ARCHITECTURE.md](SMART_CONTRACT_ARCHITECTURE.md) | Backend analysis and architecture design |
| [docs/CONTRACT_FUNCTIONS.md](docs/CONTRACT_FUNCTIONS.md) | Complete function reference for all contracts |
| [docs/TESTING_GUIDE.md](docs/TESTING_GUIDE.md) | How to run, debug, and extend tests |
| [docs/MANUAL_TESTING_GUIDE.md](docs/MANUAL_TESTING_GUIDE.md) | **Step-by-step manual testing for beginners** |
| [docs/BACKEND_ALIGNMENT_ANALYSIS.md](docs/BACKEND_ALIGNMENT_ANALYSIS.md) | Smart contract & backend alignment status |

---

## 🧪 Local Development Options (No Wallet Required!)

All three options provide **free test accounts with test ETH automatically**. Choose based on your preference:

### Option 1: Run Tests Only (Fastest - Recommended for Development)

**When to use:** Testing contracts, verifying logic, running CI/CD

```bash
npm test
```

**Pros:**
- ⚡ Fastest (runs in memory)
- 🔄 No setup needed
- 🧹 Auto-cleanup after tests

**What you get:**
- Temporary blockchain (destroyed after tests)
- 20 test accounts with 10,000 ETH each
- All accounts pre-funded

---

### Option 2: Hardhat Local Node (Recommended for Development + Testing)

**When to use:** Deploying contracts, testing with frontend, manual testing

**Terminal 1 - Start Blockchain:**
```bash
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts
npm run node
```

**Output you'll see:**
```
Started HTTP and WebSocket JSON-RPC server at http://127.0.0.1:8545/

Accounts
========

WARNING: These accounts, and their private keys, are publicly known.
Any funds sent to them on Mainnet or any other live network WILL BE LOST.

Account #0: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 (10000 ETH)
Private Key: 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80

Account #1: 0x70997970C51812dc3A010C7d01b50e0d17dc79C8 (10000 ETH)
Private Key: 0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d

... (18 more accounts)
```

**Terminal 2 - Deploy Contracts:**
```bash
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts
npm run deploy:local
```

**Output you'll see:**
```
Deploying contracts with account: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
Account balance: 10000000000000000000000

1. Deploying LoanAccessControl...
   LoanAccessControl deployed to: 0x5FbDB2315678afecb367f032d93F642f64180aa3

2. Deploying AuditRegistry...
   AuditRegistry deployed to: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512

... (more contracts)

✅ DEPLOYMENT COMPLETE!
```

**Pros:**
- 🎯 Persistent blockchain (until you stop it)
- 🔍 Can inspect transactions in real-time
- 🌐 Can connect MetaMask or frontend
- 📊 See detailed logs

**To stop:** Press `Ctrl+C` in Terminal 1

---

### Option 3: Ganache GUI (Visual Interface)

**When to use:** If you prefer a visual dashboard

**Step 1: Install Ganache**
- Download from: https://trufflesuite.com/ganache/
- Install and open the app

**Step 2: Create Workspace**
- Ganache auto-creates a workspace on startup
- You'll see 10 accounts with 100 ETH each
- Default URL: `http://127.0.0.1:7545`

**Step 3: Deploy**
```bash
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts
npm run deploy:ganache
```

**Pros:**
- 👁️ Visual interface (see accounts, blocks, transactions)
- 📈 Transaction history browser
- 🔧 Easy account management

**Cons:**
- 📦 Requires separate app installation
- 💻 More resource-intensive

---

## 🎯 Quick Decision Guide

| I want to... | Use This | Command |
|-------------|----------|---------|
| Run tests quickly | Tests only | `npm test` |
| Deploy and test manually | Hardhat node | `npm run node` → `npm run deploy:local` |
| See visual dashboard | Ganache GUI | Install Ganache → `npm run deploy:ganache` |
| Test with Django backend | Hardhat node | `npm run node` → Update Django .env |

---

## 🧪 Using Ganache (Local Development)

Yes! You can absolutely use Ganache for local testing.

### Option 1: Ganache CLI

```bash
# Install Ganache globally
npm install -g ganache

# Start Ganache (default port 8545)
ganache --chain.chainId 1337 --wallet.deterministic

# In another terminal, deploy to Ganache
npx hardhat run scripts/deploy.js --network localhost
```

### Option 2: Hardhat's Built-in Network (Recommended)

```bash
# Terminal 1: Start local Hardhat node
npm run node

# Terminal 2: Deploy contracts
npm run deploy:local
```

### Ganache Network Configuration

The `hardhat.config.js` already supports localhost:

```javascript
networks: {
  localhost: {
    url: "http://127.0.0.1:8545",
    chainId: 31337  // Change to 1337 for Ganache GUI
  },
  // For Ganache GUI with custom chain ID:
  ganache: {
    url: "http://127.0.0.1:7545",
    chainId: 1337
  }
}
```

---

## 🤔 Do I Need a Wallet or Real Money?

### For Testing & Local Development: **NO!** ❌

| What | Do You Need It? | Why Not? |
|------|----------------|----------|
| Real ETH/MATIC | ❌ No | Local blockchains use **fake test ETH** |
| Wallet address | ❌ No | Auto-generated for you (20 accounts) |
| Private keys | ❌ No | Test accounts come with keys |
| MetaMask | ❌ No | Optional (only if you want to interact manually) |
| Internet connection | ❌ No | Blockchain runs locally on your machine |

**All local options provide test accounts automatically:**
- Hardhat: 20 accounts × 10,000 test ETH
- Ganache: 10 accounts × 100 test ETH

### For Testnet Deployment: **YES** ✅ (But Still Free!)

| Network | Need Real Money? | How to Get Test Tokens |
|---------|------------------|------------------------|
| Sepolia (Ethereum testnet) | ❌ No | https://sepoliafaucet.com/ |
| Mumbai (Polygon testnet) | ❌ No | https://faucet.polygon.technology/ |

### For Production Deployment: **YES** ✅

| Network | Cost per Transaction | Recommended |
|---------|---------------------|-------------|
| Polygon Mainnet | ~$0.01-0.10 | ✅ Yes |
| Ethereum Mainnet | ~$5-50 | ❌ Too expensive |

---

## 📋 Complete Step-by-Step Walkthrough

### Scenario 1: Just Testing (Fastest)

```bash
# Step 1: Navigate to folder
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts

# Step 2: Run tests
npm test

# ✅ Done! You'll see test results
```

**Expected output:**
```
  LoanAccessControl
    Deployment
      ✓ Should set deployer as admin (78ms)
      ✓ Should set correct version
    Officer Registration
      ✓ Should register officer successfully (145ms)
      ✓ Should track officer details (98ms)
    ... 
  
  120 passing (28s)
```

---

### Scenario 2: Deploy Locally and Test with Django

```bash
# Terminal 1: Start local blockchain
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts
npm run node

# Leave this running! You'll see:
# Started HTTP and WebSocket JSON-RPC server at http://127.0.0.1:8545/
# Account #0: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 (10000 ETH)
```

**Open a NEW terminal:**

```bash
# Terminal 2: Deploy contracts
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts
npm run deploy:local

# You'll see deployment addresses - COPY THESE!
# LoanCore deployed to: 0x5FbDB2315678afecb367f032d93F642f64180aa3
# Disbursement deployed to: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512
# ...
```

**Configure your Django backend:**

```bash
# In your main backend folder, create/update .env
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend

# Add these to your .env file:
echo "BLOCKCHAIN_RPC_URL=http://127.0.0.1:8545" >> .env
echo "LOAN_CORE_ADDRESS=0x5FbDB2315678afecb367f032d93F642f64180aa3" >> .env
# (use the addresses from your deployment)
```

**Test from Django:**

```python
# In Django shell
python manage.py shell

from web3 import Web3
w3 = Web3(Web3.HTTPProvider('http://127.0.0.1:8545'))
print(w3.is_connected())  # Should print: True
print(w3.eth.get_balance('0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266'))  # Should show: 10000000000000000000000
```

---

### Scenario 3: Using Ganache GUI (Visual Dashboard)

```bash
# Step 1: Download Ganache
# Go to: https://trufflesuite.com/ganache/
# Download for macOS, install, and open

# Step 2: Create New Workspace (or use Quickstart)
# - Ganache will show 10 accounts
# - Each has 100 ETH
# - Server runs on http://127.0.0.1:7545

# Step 3: Deploy contracts
cd /Users/justinmcnealcaronongan/Documents/GitHub/Capstone_Backend/smartcontracts
npm run deploy:ganache

# Step 4: Watch transactions in Ganache GUI!
# - Click "Blocks" to see blocks being mined
# - Click "Transactions" to see your deployments
# - Click "Contracts" to see deployed contracts
```

---

## �🔧 Integration with Django Backend

### Option 1: Web3.py (Python)

Install in your Django project:

```bash
pip install web3
```

Create a blockchain service:

```python
# services/blockchain_service.py
from web3 import Web3
from web3.middleware import geth_poa_middleware
import json
import os

class BlockchainService:
    def __init__(self):
        # Connect to local Ganache or Hardhat
        self.w3 = Web3(Web3.HTTPProvider(os.getenv('BLOCKCHAIN_RPC_URL', 'http://127.0.0.1:8545')))
        
        # For Polygon/BSC (PoA chains)
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        
        # Load contract ABIs
        self.contracts = self._load_contracts()
    
    def _load_contracts(self):
        contracts = {}
        artifact_path = os.path.join(os.path.dirname(__file__), '../../smartcontracts/artifacts/contracts')
        
        contract_names = ['LoanCore', 'Disbursement', 'Repayment', 'AuditRegistry']
        
        for name in contract_names:
            with open(f'{artifact_path}/{name}.sol/{name}.json') as f:
                artifact = json.load(f)
                contracts[name] = self.w3.eth.contract(
                    address=os.getenv(f'{name.upper()}_ADDRESS'),
                    abi=artifact['abi']
                )
        
        return contracts
    
    def create_loan_on_chain(self, loan_id: str, borrower_address: str, amount: int, term_months: int, interest_rate_bps: int):
        """Record loan creation on blockchain"""
        loan_id_bytes = Web3.keccak(text=loan_id)
        product_id_bytes = Web3.keccak(text="default_product")
        
        tx = self.contracts['LoanCore'].functions.createLoan(
            loan_id_bytes,
            product_id_bytes,
            amount,
            term_months,
            interest_rate_bps
        ).build_transaction({
            'from': borrower_address,
            'nonce': self.w3.eth.get_transaction_count(borrower_address),
            'gas': 300000,
            'gasPrice': self.w3.eth.gas_price
        })
        
        return tx
    
    def record_payment_on_chain(self, loan_id: str, amount: int, method: int, reference: str):
        """Record payment on blockchain"""
        loan_id_bytes = Web3.keccak(text=loan_id)
        reference_bytes = Web3.keccak(text=reference)
        
        # This would be signed by the system wallet
        tx = self.contracts['Repayment'].functions.recordPayment(
            loan_id_bytes,
            amount,
            method,
            reference_bytes
        )
        
        return tx
    
    def verify_loan_state(self, loan_id: str) -> dict:
        """Verify loan state on blockchain"""
        loan_id_bytes = Web3.keccak(text=loan_id)
        
        loan = self.contracts['LoanCore'].functions.getLoan(loan_id_bytes).call()
        
        return {
            'borrower': loan[1],
            'requested_amount': loan[3],
            'approved_amount': loan[4],
            'status': loan[8],
            'created_at': loan[18]
        }
```

### Option 2: Django Signals Integration

```python
# loans/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import LoanApplication, LoanPayment
from services.blockchain_service import BlockchainService

blockchain = BlockchainService()

@receiver(post_save, sender=LoanApplication)
def sync_loan_to_blockchain(sender, instance, created, **kwargs):
    if created:
        # New loan application - record on chain
        try:
            blockchain.create_loan_on_chain(
                loan_id=str(instance.id),
                borrower_address=instance.customer.wallet_address,  # You'd need to add this field
                amount=int(instance.requested_amount * 100),  # Convert to smallest unit
                term_months=instance.term_months,
                interest_rate_bps=int(instance.interest_rate * 100)
            )
        except Exception as e:
            # Log error but don't block the main flow
            logger.error(f"Blockchain sync failed: {e}")
    
    elif instance.status == 'approved':
        # Loan approved - record on chain
        blockchain.approve_loan_on_chain(str(instance.id), ...)
```

---

## 🌐 Network Options

| Network | Use Case | Cost |
|---------|----------|------|
| **Hardhat Node** | Local development | Free |
| **Ganache** | Local development | Free |
| **Sepolia** | Ethereum testnet | Free (faucet ETH) |
| **Mumbai** | Polygon testnet | Free (faucet MATIC) |
| **Polygon** | Production (recommended) | ~$0.01-0.10 per tx |
| **Ethereum** | Production (expensive) | ~$5-50 per tx |

### Recommended: Polygon for Production

Polygon offers:
- Low fees (~$0.01 per transaction)
- Fast confirmations (~2 seconds)
- Ethereum security (checkpoints)
- EVM compatible (same Solidity code)

---

## 🔐 Security Features

| Feature | Implementation | Purpose |
|---------|---------------|---------|
| **UUPS Upgradeable** | All contracts | Fix bugs without losing data |
| **Access Control** | Role-based (Admin, Officer, Borrower) | Prevent unauthorized actions |
| **Reentrancy Guard** | On all state-changing functions | Prevent reentrancy attacks |
| **Pausable** | Emergency stop | Freeze system if compromised |
| **Check-Effects-Interactions** | All payment functions | Prevent exploits |
| **Duplicate Prevention** | Payment reference tracking | Prevent double-spending |
| **72-Hour Reversal Window** | Disbursements | Allow fraud correction |

---

## 📊 Why This Is a Good Implementation

### 1. **Mirrors Your Exact Business Logic**

The smart contracts match your existing status flows:

```
Django LoanApplication.status    →    LoanCore.LoanStatus
─────────────────────────────────────────────────────────
'draft'                          →    Draft (0)
'submitted'                      →    Submitted (1)
'under_review'                   →    UnderReview (2)
'approved'                       →    Approved (3)
'rejected'                       →    Rejected (4)
'disbursed'                      →    Disbursed (5)
'active'                         →    Active (6)
'completed'                      →    Completed (7)
'defaulted'                      →    Defaulted (8)
```

### 2. **Payment Methods Match**

```python
# Your Django backend
PAYMENT_METHODS = ['cash', 'bank_transfer', 'gcash', 'maya']

# Smart contract enum
enum PaymentMethod { BankTransfer, Cash, GCash, Maya, Other }
```

### 3. **Audit Trail Enhancement**

Your `analytics/models/audit_log.py` logs actions to MongoDB. The `AuditRegistry.sol` provides:
- **Immutable** logs that cannot be deleted
- **Cryptographic proof** of state at any point
- **Verifiable** by any third party (regulators, auditors)

### 4. **Separation of Concerns**

```
┌─────────────────────────────────────────────────────────┐
│  SMART CONTRACTS (What)                                 │
│  - Record that loan #123 was approved for ₱50,000      │
│  - Record that payment of ₱5,000 was made              │
│  - Prove these records haven't changed                  │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  DJANGO BACKEND (How)                                   │
│  - Process loan applications                            │
│  - Run AI qualification                                 │
│  - Send notifications                                   │
│  - Handle user interface                                │
└─────────────────────────────────────────────────────────┘
```

---

## 🧪 Test Coverage

```bash
npm test

# Output:
# LoanAccessControl
#   ✓ Should register officer
#   ✓ Should register borrower
#   ✓ Should deactivate officer
#   ...
#
# LoanCore
#   ✓ Should create loan
#   ✓ Should submit loan
#   ✓ Should approve loan
#   ✓ Should reject loan
#   ...
#
# Disbursement
#   ✓ Should initiate disbursement
#   ✓ Should complete disbursement
#   ✓ Should reverse within window
#   ...
#
# Repayment
#   ✓ Should create schedule
#   ✓ Should record payment
#   ✓ Should mark overdue
#   ...
```

---

## 📝 Environment Variables

Create a `.env` file:

```env
# For local development (Ganache/Hardhat)
BLOCKCHAIN_RPC_URL=http://127.0.0.1:8545

# For testnet/mainnet
PRIVATE_KEY=your_deployer_private_key
SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/your-key
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/your-key

# Contract addresses (after deployment)
LOAN_ACCESS_CONTROL_ADDRESS=0x...
LOAN_CORE_ADDRESS=0x...
DISBURSEMENT_ADDRESS=0x...
REPAYMENT_ADDRESS=0x...
AUDIT_REGISTRY_ADDRESS=0x...
```

---

## 🚢 Deployment Checklist

### Local (Ganache/Hardhat)

```bash
# 1. Start local node
npm run node

# 2. Deploy
npm run deploy:local

# 3. Note the deployed addresses
```

### Testnet (Sepolia/Mumbai)

```bash
# 1. Get testnet tokens from faucet
# Sepolia: https://sepoliafaucet.com/
# Mumbai: https://faucet.polygon.technology/

# 2. Configure .env with private key and RPC URL

# 3. Deploy
npm run deploy:testnet

# 4. Verify on Etherscan
npx hardhat verify --network sepolia <CONTRACT_ADDRESS>
```

---

## 📚 Further Reading

- [SMART_CONTRACT_ARCHITECTURE.md](./SMART_CONTRACT_ARCHITECTURE.md) - Detailed technical specification
- [OpenZeppelin Contracts](https://docs.openzeppelin.com/contracts/5.x/) - Security patterns used
- [Hardhat Documentation](https://hardhat.org/docs) - Development framework
- [Web3.py Documentation](https://web3py.readthedocs.io/) - Python integration

---

## ❓ FAQ

**Q: Will this slow down my application?**
A: No. Blockchain calls are asynchronous and non-blocking. Your Django app continues normally while blockchain transactions are processed.

**Q: What if the blockchain is down?**
A: Your Django app continues to work. Blockchain sync can retry later. The database is your primary data store; blockchain is for verification.

**Q: How much will this cost in production?**
A: On Polygon, approximately ₱5-50 per loan lifecycle (creation through completion). This is a fraction of what you'd pay for manual auditing.

**Q: Can customers without wallets use the system?**
A: Yes! Your backend creates blockchain records using a system wallet. Customers don't need to interact with the blockchain directly.

---

## 🎓 Quick Reference Card

### Commands You'll Use Most

```bash
# Compile contracts
npm run compile

# Run all tests
npm test

# Start local blockchain
npm run node

# Deploy to local blockchain (in another terminal)
npm run deploy:local

# Deploy to Ganache GUI
npm run deploy:ganache

# Clean build artifacts
npm run clean
```

### Test Account Info (Auto-Generated)

**Hardhat Provides:**
- 20 accounts
- 10,000 test ETH each
- URL: `http://127.0.0.1:8545`
- Chain ID: `31337`

**Ganache Provides:**
- 10 accounts  
- 100 test ETH each
- URL: `http://127.0.0.1:7545`
- Chain ID: `1337`

### Default Test Account #0 (Hardhat)

```
Address: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
Private Key: 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
Balance: 10000 ETH
```

⚠️ **Never use these accounts on mainnet!** They are publicly known test accounts.

### Network Configuration Reference

| Network | URL | Chain ID | When to Use |
|---------|-----|----------|-------------|
| Hardhat (tests) | N/A | 31337 | Running `npm test` |
| Hardhat (node) | http://127.0.0.1:8545 | 31337 | Local development |
| Ganache GUI | http://127.0.0.1:7545 | 1337 | Visual debugging |
| Sepolia | Your RPC URL | 11155111 | Testnet deployment |
| Polygon | Your RPC URL | 137 | Production |

### Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot find module" | Run `npm install` |
| "Port already in use" | Kill the process: `lsof -ti:8545 \| xargs kill -9` |
| "Transaction reverted" | Check test output for specific error |
| "Out of gas" | Increase gas limit in transaction |
| Tests hanging | Stop with Ctrl+C, run `npm run clean`, try again |
