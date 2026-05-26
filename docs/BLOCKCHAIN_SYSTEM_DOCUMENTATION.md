# Blockchain System Documentation

Complete documentation of how smart contracts integrate with the backend, web app, and mobile app.

---

## Architecture Overview

```
┌──────────────┐     ┌──────────────┐     ┌───────────────────────┐     ┌──────────────┐
│  Mobile App  │     │   Web App    │     │    Django Backend      │     │   Ganache /  │
│  (Customer)  │────▶│ (Officer /   │────▶│                       │────▶│  Blockchain  │
│              │     │  Admin)      │     │  loans/blockchain/    │     │              │
└──────┬───────┘     └──────┬───────┘     │  ├── client.py        │     │  10 Smart    │
       │                    │             │  ├── sync.py           │     │  Contracts   │
       │   REST API         │  REST API   │  ├── services/         │     │              │
       │   (read only)      │  (read only)│  └── models.py        │     └──────────────┘
       │                    │             └───────────────────────┘
       ▼                    ▼                        │
  GET /api/loans/      GET /api/loans/officer/       │ Web3.py
  applications/        applications/                 │ (background thread)
  {id}/blockchain/     {id}/blockchain/              ▼
                                              Smart Contracts
```

**Key principle:** Only the Django backend talks to the blockchain. The web and mobile apps read blockchain data through REST API endpoints — they do NOT need Web3 or ethers.js.

---

## Do I Need to Change the Web or Mobile App?

### Web App (Capstone-Web) — Loan Officers & Admins

| Feature | Status | Details |
|---------|--------|---------|
| **BlockchainAuditCard** (officer) | ✅ Already built | Shows tx hash, status, block number, gas, timestamp for each loan action |
| **useBlockchainStatus hook** | ✅ Already built | Calls `GET /api/loans/officer/applications/{id}/blockchain/` |
| **BlockchainTransaction types** | ✅ Already defined | TypeScript interfaces match backend response |
| **Conditional rendering** | ✅ Working | Card only shown when application status ≠ "draft" |
| **Admin blockchain view** | ✅ Built | Admin can view application details + blockchain audit trail at `/admin/applications/:id` |

**Verdict: No changes needed for the officer view.** The `BlockchainAuditCard` is already integrated into `OfficerApplicationDetailPage` and calls the correct backend endpoint.

**Optional improvement:** Add a blockchain audit card to the admin application detail page (currently admin can only see standard audit logs, not on-chain data).

### Mobile App (Customer) — Separate Repository

The backend already exposes `GET /api/loans/applications/{id}/blockchain/` for customers. Your mobile app just needs to call this endpoint and display the data. The backend handles all blockchain interaction.

**What the endpoint returns:**
```json
{
  "application_id": "...",
  "blockchain_enabled": true,
  "explorer_url": "",
  "tx_hashes": {
    "submit": "0xabc...",
    "approve": "0xdef...",
    "disburse": "0x123..."
  },
  "transactions": [
    {
      "tx_hash": "0xabc...",
      "contract_name": "LoanApplication",
      "method": "createApplication",
      "action": "submit",
      "status": "confirmed",
      "gas_used": 245000,
      "block_number": 15,
      "created_at": "2026-03-15T07:30:00Z"
    }
  ],
  "audit_trail": [...]
}
```

---

## Backend ↔ Smart Contract Alignment

### Contract-by-Contract Mapping

Each backend service class maps to a specific smart contract:

| Backend Service | Smart Contract | Functions Called |
|----------------|---------------|-----------------|
| `application_service.py` | `LoanApplication.sol` | `createApplication()`, `submitApplication()`, `getApplication()` |
| `review_service.py` | `LoanReview.sol` | `assignOfficer()`, `getAssignedOfficer()` |
| `approval_service.py` | `LoanApproval.sol` | `approveLoan()`, `rejectLoan()` |
| `disbursement_service.py` | `DisbursementMethod.sol` + `DisbursementExecution.sol` | `setPreferredMethod()`, `initiateDisbursement()`, `completeDisbursement()` |
| `repayment_service.py` | `RepaymentSchedule.sol` + `PaymentRecording.sol` | `createSchedule()`, `recordPayment()`, `markOverdue()` |
| `audit_service.py` | `AuditRegistry.sol` | `log()`, `getFullAuditTrail()`, `getEntry()` |

Additionally, `sync.py` calls **LoanCore.sol** as a mirror for: `createLoan()`, `submitLoan()`, `assignOfficer()`, `approveLoan()`, `markDisbursed()`.

### Data Conversion Rules

The backend converts Django/MongoDB data into Solidity-compatible formats:

| Data | Python (Backend) | Solidity (Contract) | Conversion |
|------|-----------------|--------------------|----|
| Loan ID | `"507f1f77bcf86cd799439011"` | `bytes32` | `keccak256(loan_id_string)` |
| Product ID | `"product_001"` | `bytes32` | `keccak256(product_id_string)` |
| Interest Rate | `0.015` (monthly) | `uint16` (annual bps) | `monthly_rate × 12 × 10,000` → e.g. `1800` |
| Risk Category | `"low"` / `"medium"` / `"high"` | `uint8` | `0` / `1` / `2` |
| Disbursement Method | `"gcash"` | `uint8` | `bank_transfer=0, gcash=1, cash=2, maya=3, other=4` |
| Payment Method | `"gcash"` | `uint8` | `cash=0, bank_transfer=1, gcash=2, maya=3, other=4` |
| Borrower Address | MongoDB user ID | `address` | Uses deployer address as proxy (no real wallet) |
| Notes / Reasons | Free text | `bytes32` | `keccak256(text)` |
| Reference Numbers | `"PAY-20260315-000001"` | `bytes32` | `keccak256(reference_string)` |

### Transaction Flow (What Happens at Each Loan Stage)

#### 1. Customer Submits Application → 4 blockchain transactions

```
Django View (LoanApplyView)
  └→ Background Thread (sync_application)
      ├→ LoanApplication.createApplication(loanId, productId, amount, term, rateBps)
      ├→ LoanApplication.submitApplication(loanId, score, riskCategory, aiHash)
      ├→ LoanCore.createLoan(loanId, productId, amount, term, rateBps)
      └→ LoanCore.submitLoan(loanId, score, riskCategory, aiHash)
```

#### 2. Officer Approves Loan → 4 blockchain transactions

```
Django View (OfficerReviewView)
  └→ Background Thread (sync_approval)
      ├→ LoanReview.assignOfficer(loanId, officerAddress)
      ├→ LoanApproval.approveLoan(loanId, approvedAmount, notesHash)
      ├→ LoanCore.assignOfficer(loanId, officerAddress)
      └→ LoanCore.approveLoan(loanId, approvedAmount, notesHash)
```

#### 2b. Officer Rejects Loan → 4 blockchain transactions

```
Django View (OfficerReviewView — reject)
  └→ Background Thread (sync_rejection)
      ├→ LoanReview.assignOfficer(loanId, officerAddress)
      ├→ LoanApproval.rejectLoan(loanId, reasonHash, notesHash)
      ├→ LoanCore.assignOfficer(loanId, officerAddress)
      └→ LoanCore.rejectLoan(loanId, reasonHash, notesHash)
```

#### 3. Officer Disburses Loan → 5 blockchain transactions

```
Django View (DisburseView)
  └→ Background Thread (sync_disbursement)
      ├→ DisbursementMethod.setPreferredMethod(loanId, methodEnum)
      ├→ DisbursementExecution.initiateDisbursement(loanId, amount)
      ├→ DisbursementExecution.completeDisbursement(disbursementId, refHash)
      ├→ LoanCore.markDisbursed(loanId, amount)
      └→ RepaymentSchedule.createSchedule(loanId, borrower, principal, rate, term, startDate)
```

#### 4. Customer Makes Payment → 1 blockchain transaction

```
Django View (PaymentRecordingView)
  └→ Background Thread (sync_payment)
      └→ PaymentRecording.recordPayment(loanId, installmentNum, amount, method, refHash)
```

#### 5. Overdue Installment Sync → 1 blockchain transaction per overdue installment

```
Celery Task (check_overdue_installments_task)
  └→ Background Thread (sync_overdue)
      └→ PaymentRecording.markOverdue(loanId, installmentNum)
```

#### 6. Penalty Apply/Waive → 1 blockchain transaction

```
Django Views (ApplyPenaltyView / WaivePenaltyView)
  └→ Background Thread (sync_penalty)
      └→ AuditRegistry.log(resourceType=penalty, action=PenaltyApplied/PenaltyWaived, ...)
```

#### 7. Consent Record → 1 blockchain transaction

```
Django View (ConsentView POST/PUT)
  └→ Background Thread (sync_consent)
      └→ AuditRegistry.log(resourceType=consent, action=ConsentRecorded, ...)
```

---

## Smart Contract Roles and Permissions

### Role Hierarchy

```
DEFAULT_ADMIN_ROLE (deployer)
├── ADMIN_ROLE          → Deploy scripts grant to deployer
├── LOAN_OFFICER_ROLE   → Registered via LoanAccessControl
├── BORROWER_ROLE       → Registered via LoanAccessControl
├── SYSTEM_ROLE         → Granted to contracts and BACKEND_WALLET
├── ORACLE_ROLE         → For external data feeds
├── LOGGER_ROLE         → Granted to contracts that log to AuditRegistry
├── UPGRADER_ROLE       → For UUPS proxy upgrades
└── PAUSER_ROLE         → Emergency pause
```

### What Each Role Can Do

| Action | Required Role | Who Has It |
|--------|--------------|------------|
| Create/submit application | Borrower or SYSTEM | Backend wallet (SYSTEM) |
| Assign officer | ADMIN or SYSTEM | Backend wallet (SYSTEM) |
| Approve/reject loan | Assigned officer or ADMIN | Backend wallet (via SYSTEM) |
| Set disbursement method | Borrower | Backend wallet (via SYSTEM) |
| Initiate/complete disbursement | OFFICER, ADMIN, or SYSTEM | Backend wallet (SYSTEM) |
| Create repayment schedule | SYSTEM, ADMIN, or OFFICER | Backend wallet (SYSTEM) |
| Record payment | OFFICER or SYSTEM | Backend wallet (SYSTEM) |
| Mark overdue | SYSTEM or ADMIN | Backend wallet (SYSTEM) |
| Log to AuditRegistry | LOGGER | All contracts (granted at deploy) |
| Pause contracts | ADMIN or PAUSER | Deployer |
| Upgrade contracts | UPGRADER | Deployer |

> **Important:** The backend wallet (`BACKEND_WALLET` from deployment) has SYSTEM_ROLE, which allows it to perform all loan operations on behalf of users. This is by design — users don't have Ethereum wallets; the backend signs all transactions using a single service account.

---

## Known Issues and Mismatches

### ⚠️ Issue 1: Payment Method Enum Ordering Differs Between Contracts

**DisbursementMethod.sol:**
```
enum Method { BankTransfer=0, GCash=1, Cash=2, Maya=3, Other=4 }
```

**PaymentRecording.sol:**
```
enum PaymentMethod { Cash=0, BankTransfer=1, GCash=2, Maya=3, Other=4 }
```

**Backend mapping (disbursement_service.py):**
```python
METHOD_MAP = {"bank_transfer": 0, "gcash": 1, "cash": 2, "maya": 3, "other": 4}
```

**Backend mapping (repayment_service.py):**
```python
METHOD_MAP = {"cash": 0, "bank_transfer": 1, "gcash": 2, "maya": 3, "other": 4}
```

**Status:** ✅ Backend correctly maps different orderings for each contract. No bug here — just different enum definitions across contracts.

### ⚠️ Issue 2: LoanCore Duplication

Both `LoanApplication` (modular) and `LoanCore` (monolith) contracts are called for the same operations. The sync layer writes to both:
- `LoanApplication.createApplication()` AND `LoanCore.createLoan()`
- `LoanApproval.approveLoan()` AND `LoanCore.approveLoan()`

**Why:** `RepaymentSchedule` depends on `LoanCore` (not `LoanApplication`) to verify loan status. So `LoanCore` must be kept in sync.

**Risk:** If one write succeeds and the other fails, state becomes inconsistent. The backend logs failures but does not roll back.

### ⚠️ Issue 3: No Real User Wallets

Borrowers and officers don't have Ethereum wallets. The backend uses the deployer/service wallet address as a proxy for all users. This means:
- `msg.sender` is always the backend wallet, not the actual user
- On-chain borrower/officer addresses don't map to real identities
- Identity verification relies on MongoDB, not the blockchain

**This is acceptable** for an audit trail system where the blockchain provides immutability, not identity.

### ⚠️ Issue 4: Admin Has No Blockchain View

The admin section (web app) can see standard audit logs but NOT blockchain audit trail data. The backend has the endpoint ready (`BlockchainStatusView` works for officers), but the admin frontend doesn't call it.

---

## File Reference

### Backend Files (Django)

```
loans/blockchain/
├── __init__.py
├── client.py              # Web3 connection, contract loading, send_transaction(), call_view()
├── exceptions.py          # BlockchainError, BlockchainConnectionError, etc.
├── models.py              # BlockchainTransaction MongoDB model
├── sync.py                # Background thread sync (non-blocking)
├── tasks.py               # Celery task alternative
├── abis/                  # Contract ABI JSON files (10 files)
│   ├── AuditRegistry.json
│   ├── LoanAccessControl.json
│   ├── LoanCore.json
│   ├── LoanApplication.json
│   ├── LoanReview.json
│   ├── LoanApproval.json
│   ├── DisbursementMethod.json
│   ├── DisbursementExecution.json
│   ├── RepaymentSchedule.json
│   └── PaymentRecording.json
└── services/
    ├── application_service.py   # LoanApplication contract
    ├── approval_service.py      # LoanApproval contract
    ├── audit_service.py         # AuditRegistry (read-only)
    ├── disbursement_service.py  # DisbursementMethod + DisbursementExecution
    ├── repayment_service.py     # RepaymentSchedule + PaymentRecording
    └── review_service.py        # LoanReview contract
```

### Smart Contract Files (Hardhat)

```
smartcontracts/contracts/
├── AuditRegistry.sol           # Immutable audit log
├── LoanAccessControl.sol       # Role management
├── LoanCore.sol                # Monolith loan lifecycle (legacy, kept for RepaymentSchedule)
├── core/
│   ├── LoanApplication.sol     # Create/submit applications
│   ├── LoanApproval.sol        # Approve/reject loans
│   └── LoanReview.sol          # Officer assignment
├── disbursement/
│   ├── DisbursementMethod.sol  # Borrower selects payout method
│   └── DisbursementExecution.sol # Initiate/complete/cancel disbursement
├── interfaces/
│   ├── IAuditRegistry.sol
│   ├── ILoanAccessControl.sol
│   ├── ILoanApplication.sol
│   └── ILoanCore.sol
└── repayment/
    ├── RepaymentSchedule.sol   # Monthly installment schedule
    └── PaymentRecording.sol    # Record individual payments
```

### Web App Files (Capstone-Web)

```
src/features/loan-officer/
├── api/applicationsApi.ts              # getBlockchainStatus() + types
├── hooks/useApplications.ts            # useBlockchainStatus() hook
├── components/BlockchainAuditCard.tsx   # Displays on-chain transaction list
└── pages/OfficerApplicationDetailPage.tsx  # Renders BlockchainAuditCard
```

### API Endpoints

| Endpoint | Method | Auth | Returns |
|----------|--------|------|---------|
| `/api/loans/applications/{id}/blockchain/` | GET | Customer | Blockchain status for own loan |
| `/api/loans/officer/applications/{id}/blockchain/` | GET | Officer | Blockchain status for any loan |

### Environment Configuration

All blockchain config is in the **root `.env`** file (single source of truth):

```env
# Hardhat deployment
PRIVATE_KEY=<deployer_private_key_from_ganache>

# Django blockchain integration
BLOCKCHAIN_ENABLED=True
BLOCKCHAIN_RPC_URL=http://127.0.0.1:7545
BLOCKCHAIN_CHAIN_ID=1337
BLOCKCHAIN_WALLET_KEY=<backend_wallet_private_key_from_ganache>
BLOCKCHAIN_CONTRACT_ADDRESSES={"auditRegistry":"0x...","accessControl":"0x...", ...}
BLOCKCHAIN_GAS_LIMIT=6721975
BLOCKCHAIN_GAS_PRICE_GWEI=20
```

> `hardhat.config.js` reads from `../.env` (project root), so only one `.env` file is needed.

---

## Summary

| Question | Answer |
|----------|--------|
| **Are smart contracts aligned to the backend?** | ✅ Yes — all 10 contracts have matching backend service classes with correct function signatures and data conversions |
| **Do I need to change the web app?** | ❌ No — `BlockchainAuditCard` is already built and working for officers |
| **Do I need to change the mobile app?** | Only if not already calling `GET /api/loans/applications/{id}/blockchain/` — backend endpoint is ready |
| **Does the frontend need Web3/ethers.js?** | ❌ No — all blockchain interaction happens in the backend; frontend reads results via REST API |
| **What about the admin section?** | Optional: admin currently has no blockchain view; you could add `BlockchainAuditCard` to admin pages too |
