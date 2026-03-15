# Blockchain Integration Testing Guide

A step-by-step guide to test the blockchain audit trail feature using Ganache.

## Implementation Notes

This guide reflects the current backend implementation in this repository.

- Blockchain sync is triggered from Django views in background threads via `loans.blockchain.sync`.
- The backend signs on-chain transactions with the configured service wallet (`BLOCKCHAIN_WALLET_KEY`).
- Because transactions are backend-signed, on-chain actor fields that depend on `msg.sender` reflect the backend wallet, not the authenticated mobile/web user.
- Backend verification endpoints are implemented in this repo. Web/mobile audit UI cards described in the Phase 2 plan are not part of this backend repository and should not be treated as required for backend verification.

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| **Ganache** (GUI) | 2.7+ | Local Ethereum blockchain |
| **Python** | 3.9+ | Django backend |
| **Node.js** | 18+ | Smart contract deployment |
| **MongoDB** | Running | Application database |

---

## Step 0 — Install/Update Backend Dependencies

Before running blockchain tests, make sure backend dependencies are installed (including `web3` from `requirements.txt`).

```bash
cd /path/to/Capstone_Backend
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Step 0.5 — Configure Blockchain Env + ABIs (Essential)

Before starting Django, make sure blockchain settings are complete:

1. In `.env`, set these values:
   - `BLOCKCHAIN_ENABLED=True`
   - `BLOCKCHAIN_RPC_URL=http://127.0.0.1:7545`
   - `BLOCKCHAIN_CHAIN_ID=1337`
   - `BLOCKCHAIN_WALLET_KEY=<ganache_private_key>`
   - `BLOCKCHAIN_CONTRACT_ADDRESSES=<json_from_deployment_file>`
2. Copy ABIs into `loans/blockchain/abis`:

```bash
cd /path/to/Capstone_Backend
source .venv/bin/activate
python scripts/copy_abis.py
```

3. Quick sanity check (must print `connected: True`):

```bash
python manage.py shell -c "from loans.blockchain.client import get_web3; print('connected:', get_web3().is_connected())"
```

---

## Step 1 — Start Ganache

1. Open **Ganache** desktop app
2. Select workspace **MSME-PATHWAYS** (or create new)
3. Verify settings:
   - **RPC Server:** `http://127.0.0.1:7545`
   - **Network ID:** `1337`
   - **Gas Limit:** `6721975`
4. Note the **current block number** and **TX COUNT** — you'll compare these later

---

## Step 2 — Deploy Smart Contracts (first time only)

If contracts are not yet deployed:

```bash
cd smartcontracts
npm install
BACKEND_WALLET=<backend_wallet_address> npx hardhat run scripts/deploy-v2.js --network ganache
```

This deploys 10 contracts, wires cross-contract roles, and (if `BACKEND_WALLET` is set) grants backend wallet roles.

Then copy contract addresses from the generated `smartcontracts/deployments/v2-ganache-*.json` file into `.env` under `BLOCKCHAIN_CONTRACT_ADDRESSES`.

---

## Step 3 — Validate Deployment + Roles (recommended)

Run validation to catch missing roles/wiring before app testing:

```bash
cd smartcontracts
npx hardhat run scripts/validate-deployment.js --network ganache
```

If this script fails on role/access checks, fix deployment first before continuing.

---

## Step 4 — Start the Django Backend

```bash
cd /path/to/Capstone_Backend
source .venv/bin/activate
python manage.py runserver
```

Recommended sanity check after startup:

```bash
python manage.py shell -c "from django.conf import settings; print('BLOCKCHAIN_ENABLED:', settings.BLOCKCHAIN_ENABLED)"
```

Expected output:
```
BLOCKCHAIN_ENABLED: True
```

---

## Step 5 — Test the Full Loan Lifecycle

### 5a. Submit a Loan Application (Mobile App — Customer)

1. Log in as a **customer** on the mobile app
2. Go to **Apply for Loan**
3. Select a loan product and submit

**Expected in Django console:**
```
INFO Transaction OK: 0x8944fCF9.createApplication() tx=... gas=...
INFO createApplication on-chain: loan=<LOAN_ID> tx=...
INFO Transaction OK: 0x8944fCF9.submitApplication() tx=... gas=...
INFO submitApplication on-chain: loan=<LOAN_ID> tx=...
INFO LoanCore createLoan+submitLoan OK: loan=<LOAN_ID>
INFO sync_application OK: loan=<LOAN_ID> tx=...
```

**Verify in Ganache:** TX COUNT increased by 4

---

### 5b. Approve the Loan (Web App — Loan Officer)

1. Log in as a **loan officer** on the web app
2. Go to **Pending Applications**
3. Open the application and click **Approve**

**Expected in Django console:**
```
INFO Transaction OK: 0xc7db39D5.assignOfficer() tx=... gas=...
INFO Transaction OK: 0x1343045a.approveLoan() tx=... gas=...
INFO LoanCore assignOfficer+approveLoan OK: loan=<LOAN_ID>
INFO sync_approval OK: loan=<LOAN_ID> tx=...
```

**Verify in Ganache:** TX COUNT increased by 4

Note: the approval sync performs both `LoanReview.assignOfficer()` and `LoanApproval.approveLoan()` before mirroring the state in `LoanCore`.

---

### 5c. Set Disbursement Method (Mobile App — Customer)

1. On the mobile app, the approved loan will prompt to **select disbursement method**
2. Choose **GCash** or **Bank Transfer**

*(No blockchain transaction for this step — it's stored in MongoDB only)*

---

### 5d. Disburse the Loan (Web App — Loan Officer)

1. On the web app, open the approved application
2. Click **Disburse**

**Expected in Django console:**
```
INFO Transaction OK: 0x9394e573.setPreferredMethod() tx=... gas=...
INFO Transaction OK: 0xe02c566C.initiateDisbursement() tx=... gas=...
INFO Transaction OK: 0xe02c566C.completeDisbursement() tx=... gas=...
INFO LoanCore markDisbursed OK: loan=<LOAN_ID>
INFO sync_disbursement OK: loan=<LOAN_ID> tx=...
INFO Transaction OK: 0x11766655.createSchedule() tx=... gas=...
INFO sync_schedule OK: loan=<LOAN_ID> tx=...
```

**Verify in Ganache:** TX COUNT increased by 5

---

### 5e. Make a Payment (Mobile App — Customer)

1. On the mobile app, go to **My Loans** → open the disbursed loan
2. Go to **Repayment** tab and click **Pay**
3. Submit the payment

**Expected in Django console:**
```
INFO Transaction OK: 0x5368131a.recordPayment() tx=... gas=...
INFO recordPayment on-chain: loan=<LOAN_ID> installment=1 amount=... tx=...
INFO sync_payment OK: loan=<LOAN_ID> payment=... tx=...
```

**Verify in Ganache:** TX COUNT increased by 1

---

## Step 6 — Verify Blockchain Audit Trail

The backend repository implements API endpoints for blockchain verification. Use those as the source of truth for testing this repo.

### Officer API

Call:

```text
GET /api/loans/officer/applications/<LOAN_ID>/blockchain/
```

Expected response fields:
- `application_id`
- `blockchain_enabled`
- `tx_hashes`
- `transactions`
- `audit_trail`

Verify that `transactions` contains confirmed entries for the actions that have already been synced:
- `submit`
- `approve`
- `disburse`
- `schedule`
- `payment` (one per payment made)

Each confirmed transaction should include:
- `tx_hash`
- `contract_name`
- `method`
- `status`
- `gas_used`
- `block_number`

### Customer API

Call:

```text
GET /api/loans/applications/<LOAN_ID>/blockchain/
```

Expected response fields are the same as the officer endpoint for the authenticated customer who owns the application.

### Optional UI Verification

If your separate web/mobile frontends already implemented the planned audit components, you may also verify those screens. Those UI components are not required to validate the backend in this repository.

---

## Step 7 — Verify Transaction Hashes in Ganache

1. Copy a transaction hash from the blockchain status API response or from any implemented web/mobile UI
2. In Ganache, paste it in the **search bar** (top right)
   - ⚠️ **Add `0x` prefix** if the hash doesn't start with it
3. Ganache will show the full transaction details: sender, contract, gas used, block number

---

## What Each Transaction Proves

| Action | Contracts Called | What's Immutable |
|--------|----------------|-----------------|
| Submit Application | LoanApplication + LoanCore | Loan amount, term, interest rate, borrower |
| Approve Loan | LoanReview + LoanApproval + LoanCore | Officer assignment, approved amount, approval decision |
| Disburse | DisbursementMethod + DisbursementExecution + LoanCore | Preferred method, disbursement amount, completion reference, timestamp |
| Create Schedule | RepaymentSchedule | Monthly payment, term, due dates |
| Record Payment | PaymentRecording | Payment amount, installment number, timestamp |

**Key point:** Once recorded on the blockchain, these records **cannot be altered or deleted** — this provides an immutable audit trail for loan transparency.

**Important implementation detail:** in the current backend architecture, transactions are submitted by the backend service wallet. That means on-chain actor identity is the backend signer unless you introduce direct user-wallet signing in a frontend/mobile client.

---

## Expected Transaction Count per Loan

| Lifecycle Step | # of Transactions |
|---------------|-------------------|
| Submit application | 4 |
| Approve loan | 4 |
| Disburse + schedule | 5 |
| Each payment | 1 |
| **Total (3-month loan, 3 payments)** | **16** |

---

## Troubleshooting

| Issue | Solution |
|-------|---------|
| No blockchain logs in console | Check `BLOCKCHAIN_ENABLED=True` in `.env` |
| `BLOCKCHAIN_WALLET_KEY is not configured` | Set backend wallet key in `.env` (Ganache private key) |
| `ContractNotFoundError` or ABI load failure | Run `python scripts/copy_abis.py` and verify `loans/blockchain/abis/*.json` exist |
| `Cannot connect to blockchain node at http://127.0.0.1:7545` | Ensure Ganache is running on port 7545 and RPC URL matches `.env` |
| Role/access `revert` from contracts | Redeploy with `BACKEND_WALLET=<address> npx hardhat run scripts/deploy-v2.js --network ganache` |
| `VM Exception: revert` on approve | Ensure `assignOfficer` is called before `approveLoan` (automatic) |
| `VM Exception: revert` on schedule | Loan must be in `Disbursed` status in LoanCore |
| Audit UI cards are missing | Use the blockchain status API endpoints; frontend/mobile audit components are planned separately |
| `NOTHING FOUND` in Ganache search | Add `0x` prefix to the transaction hash |
| `web3` module not found | Activate backend venv and run `pip install -r requirements.txt` |

---

## Quick Smoke Test Checklist

- [ ] Ganache is running on port 7545
- [ ] `.env` has `BLOCKCHAIN_ENABLED=True`, wallet key, and contract addresses
- [ ] ABI files exist in `loans/blockchain/abis/` (after `python scripts/copy_abis.py`)
- [ ] `validate-deployment.js` passes on Ganache
- [ ] Django sanity check confirms `BLOCKCHAIN_ENABLED: True`
- [ ] Submit loan → see 4 blockchain INFO logs
- [ ] Approve loan → see 4 blockchain INFO logs
- [ ] Disburse loan → see 5 blockchain INFO logs
- [ ] Make payment → see 1 blockchain INFO log
- [ ] Officer blockchain endpoint returns confirmed transactions and audit trail
- [ ] Customer blockchain endpoint returns confirmed transactions and audit trail
- [ ] TX hash from API response or UI matches in Ganache search (with `0x` prefix)
- [ ] Ganache TX COUNT matches expected total
