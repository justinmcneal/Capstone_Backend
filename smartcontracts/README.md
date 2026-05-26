# MSME Pathways Smart Contract System

## Overview

This smart contract system provides **immutable, auditable** record-keeping for the MSME Pathways Loan Management System. It complements the Django backend by adding blockchain-based verification and tamper-proof records.

### Contracts

| Contract | Purpose |
|----------|---------|
| **LoanAccessControl** | Role-based access control (Admin, Officer, Borrower) |
| **LoanCore** | Loan lifecycle management (create, approve, reject, disburse) |
| **Disbursement** | Fund release tracking and verification |
| **Repayment** | Payment recording and schedule management |
| **AuditRegistry** | Immutable event logging and state verification |

### Interfaces

| Interface | Description |
|-----------|-------------|
| **ILoanAccessControl** | Access control interface |
| **ILoanCore** | Loan operations interface |
| **IAuditRegistry** | Audit logging interface |

---

## Project Structure

```
smartcontracts/
├── contracts/
│   ├── LoanAccessControl.sol
│   ├── LoanCore.sol
│   ├── Disbursement.sol
│   ├── Repayment.sol
│   ├── AuditRegistry.sol
│   └── interfaces/
│       ├── ILoanAccessControl.sol
│       ├── ILoanCore.sol
│       └── IAuditRegistry.sol
├── scripts/
│   └── deploy.js
├── test/
│   ├── LoanAccessControl.test.js
│   ├── LoanCore.test.js
│   ├── Disbursement.test.js
│   ├── Repayment.test.js
│   └── AuditRegistry.test.js
├── docs/
│   ├── CONTRACT_FUNCTIONS.md
│   ├── TESTING_GUIDE.md
│   ├── MANUAL_TESTING_GUIDE.md
│   └── BACKEND_ALIGNMENT_ANALYSIS.md
├── hardhat.config.js
└── package.json
```

---

## Quick Start

### Prerequisites

- Node.js 18+
- npm

### Installation

```bash
cd smartcontracts
npm install
```

### Compile Contracts

```bash
npm run compile
```

### Run Tests

```bash
npm test
```

**Output:**
```
  AuditRegistry
    ✓ Should set correct version
    ✓ Should log audit entry
    ...

  Disbursement
    ✓ Should initiate disbursement
    ✓ Should complete disbursement
    ...

  LoanAccessControl
    ✓ Should set deployer as admin
    ✓ Should register officer successfully
    ...

  LoanCore
    ✓ Should create loan
    ✓ Should approve loan
    ...

  Repayment
    ✓ Should create repayment schedule
    ✓ Should record payment successfully
    ...

  100 passing (3s)
```

---

## Local Development

### Option 1: Run Tests Only (Fastest)

```bash
npm test
```

- Creates temporary blockchain in memory
- Auto-generates 20 test accounts with 10,000 ETH each
- No setup required

### Option 2: Local Blockchain Node

**Terminal 1 - Start Node:**
```bash
npm run node
```

**Terminal 2 - Deploy:**
```bash
npm run deploy:local
```

**Deployment Output:**
```
Deploying contracts with account: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266

1. Deploying LoanAccessControl...
   LoanAccessControl deployed to: 0x5FbDB2315678afecb367f032d93F642f64180aa3

2. Deploying AuditRegistry...
   AuditRegistry deployed to: 0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512

3. Deploying LoanCore...
   LoanCore deployed to: 0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0

4. Deploying Disbursement...
   Disbursement deployed to: 0xCf7Ed3AccA5a467e9e704C703E8D87F634fB0Fc9

5. Deploying Repayment...
   Repayment deployed to: 0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9

✅ DEPLOYMENT COMPLETE!
```

### Option 3: Ganache GUI

```bash
npm run deploy:ganache
```

---

## Backend Alignment

### Django Model → Smart Contract Mapping

| Django Model | Smart Contract | On-Chain Data |
|--------------|----------------|---------------|
| `LoanApplication` | `LoanCore.sol` | loan_id, borrower, amount, status, timestamps |
| `LoanPayment` | `Repayment.sol` | payment_id, amount, method, reference |
| `RepaymentSchedule` | `Repayment.sol` | installment details, due dates |
| `LoanOfficer` | `LoanAccessControl.sol` | officer address, employee_id_hash |
| `Customer` | `LoanAccessControl.sol` | customer address, customer_id_hash |
| `AuditLog` | `AuditRegistry.sol` | action_hash, actor, entity_id |

### Status Flow Mapping

```
Django Status      →    Smart Contract Status
───────────────────────────────────────────────
'draft'            →    Draft (0)
'submitted'        →    Submitted (1)
'under_review'     →    UnderReview (2)
'approved'         →    Approved (3)
'rejected'         →    Rejected (4)
'disbursed'        →    Disbursed (5)
'active'           →    Active (6)
'completed'        →    Completed (7)
'defaulted'        →    Defaulted (8)
```

### Payment Methods

```solidity
enum PaymentMethod { BankTransfer, Cash, GCash, Other }
```

---

## Contract Functions

### LoanAccessControl

| Function | Description |
|----------|-------------|
| `registerOfficer(address, bytes32)` | Register loan officer |
| `registerBorrower(address, bytes32)` | Register borrower |
| `deactivateOfficer(address)` | Deactivate officer |
| `deactivateBorrower(address)` | Deactivate borrower |
| `pause()` / `unpause()` | Emergency controls |

### LoanCore

| Function | Description |
|----------|-------------|
| `createLoan(...)` | Create new loan application |
| `submitLoan(bytes32)` | Submit for review |
| `assignOfficer(bytes32, address)` | Assign reviewing officer |
| `approveLoan(bytes32, uint256)` | Approve with amount |
| `rejectLoan(bytes32, string)` | Reject with reason |
| `getLoan(bytes32)` | Get loan details |

### Disbursement

| Function | Description |
|----------|-------------|
| `initiateDisbursement(...)` | Start disbursement |
| `completeDisbursement(bytes32)` | Complete disbursement |
| `getDisbursement(bytes32)` | Get disbursement record |

### Repayment

| Function | Description |
|----------|-------------|
| `createSchedule(...)` | Create repayment schedule |
| `recordPayment(...)` | Record payment |
| `getSchedule(bytes32)` | Get schedule details |
| `getInstallment(bytes32, uint256)` | Get installment |

### AuditRegistry

| Function | Description |
|----------|-------------|
| `log(...)` | Log audit entry |
| `verifyState(bytes32, bytes32)` | Verify state hash |
| `getEntry(bytes32)` | Get audit entry |

---

## Security Features

| Feature | Purpose |
|---------|---------|
| **UUPS Upgradeable** | Contract upgrades without data loss |
| **Access Control** | Role-based permissions |
| **Reentrancy Guard** | Prevent reentrancy attacks |
| **Pausable** | Emergency stop capability |
| **Check-Effects-Interactions** | Secure state changes |

---

## Django Integration

### Web3.py Service

```python
from web3 import Web3
import json
import os

class BlockchainService:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(
            os.getenv('BLOCKCHAIN_RPC_URL', 'http://127.0.0.1:8545')
        ))
        self.contracts = self._load_contracts()
    
    def _load_contracts(self):
        contracts = {}
        artifact_path = 'smartcontracts/artifacts/contracts'
        
        for name in ['LoanCore', 'Disbursement', 'Repayment', 'AuditRegistry']:
            with open(f'{artifact_path}/{name}.sol/{name}.json') as f:
                artifact = json.load(f)
                contracts[name] = self.w3.eth.contract(
                    address=os.getenv(f'{name.upper()}_ADDRESS'),
                    abi=artifact['abi']
                )
        return contracts
    
    def create_loan(self, loan_id, borrower, amount, term_months, interest_rate_bps):
        loan_id_bytes = Web3.keccak(text=loan_id)
        product_id = Web3.keccak(text="default")
        
        return self.contracts['LoanCore'].functions.createLoan(
            loan_id_bytes, product_id, amount, term_months, interest_rate_bps
        )
    
    def record_payment(self, loan_id, amount, method, reference):
        loan_id_bytes = Web3.keccak(text=loan_id)
        reference_bytes = Web3.keccak(text=reference)
        
        return self.contracts['Repayment'].functions.recordPayment(
            loan_id_bytes, amount, method, reference_bytes
        )
```

---

## Environment Variables

```env
# Local Development
BLOCKCHAIN_RPC_URL=http://127.0.0.1:8545

# Contract Addresses (after deployment)
LOAN_ACCESS_CONTROL_ADDRESS=0x...
LOAN_CORE_ADDRESS=0x...
DISBURSEMENT_ADDRESS=0x...
REPAYMENT_ADDRESS=0x...
AUDIT_REGISTRY_ADDRESS=0x...

# Testnet/Mainnet (optional)
PRIVATE_KEY=your_deployer_private_key
SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/your-key
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/your-key
```

---

## Commands

| Command | Description |
|---------|-------------|
| `npm install` | Install dependencies |
| `npm run compile` | Compile contracts |
| `npm test` | Run all tests |
| `npm run node` | Start local blockchain |
| `npm run deploy:local` | Deploy to local node |
| `npm run deploy:ganache` | Deploy to Ganache |
| `npm run clean` | Clean build artifacts |

---

## Network Configuration

| Network | URL | Chain ID |
|---------|-----|----------|
| Hardhat (tests) | In-memory | 31337 |
| Hardhat (node) | http://127.0.0.1:8545 | 31337 |
| Ganache | http://127.0.0.1:7545 | 1337 |
| Sepolia | Your RPC URL | 11155111 |
| Polygon | Your RPC URL | 137 |

---

## Test Accounts (Auto-Generated)

**Hardhat provides:**
- 20 accounts with 10,000 test ETH each

**Default Account #0:**
```
Address: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
Private Key: 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
```

⚠️ **Never use test accounts on mainnet!**

---

## Documentation

| Document | Description |
|----------|-------------|
| [CONTRACT_FUNCTIONS.md](docs/CONTRACT_FUNCTIONS.md) | Complete function reference |
| [TESTING_GUIDE.md](docs/TESTING_GUIDE.md) | Testing instructions |
| [MANUAL_TESTING_GUIDE.md](docs/MANUAL_TESTING_GUIDE.md) | Step-by-step manual testing |
| [BACKEND_ALIGNMENT_ANALYSIS.md](docs/BACKEND_ALIGNMENT_ANALYSIS.md) | Backend integration details |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot find module" | Run `npm install` |
| "Port already in use" | `lsof -ti:8545 \| xargs kill -9` |
| "Transaction reverted" | Check test output for error message |
| Tests hanging | `Ctrl+C`, then `npm run clean` |
