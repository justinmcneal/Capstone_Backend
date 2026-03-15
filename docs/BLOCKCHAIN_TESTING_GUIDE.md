# Blockchain Testing Guide

Test the blockchain audit trail using Ganache (local Ethereum).

**Prerequisites:** Ganache 2.7+, Python 3.9+, Node.js 18+, MongoDB (running)

---

## Understanding the Two `.env` Files

There are **two separate `.env` files** — each used by a different tool:

| File | Used by | Fill it when |
|------|---------|--------------|
| `smartcontracts/.env` | **Hardhat** (Node.js) | Deploying contracts to Ganache |
| `.env` (project root) | **Django** (Python) | Running the backend server |

Fill `smartcontracts/.env` first → deploy → then fill root `.env` with the resulting contract addresses.

---

## Step 1 — Start Ganache

1. Open **Ganache** desktop app → select or create a workspace
2. Confirm: **RPC** `http://127.0.0.1:7545` · **Network ID** `1337` · **Gas Limit** `6721975`
3. You will need **two pieces of info** from the Accounts tab:

| What | Where in Ganache | Used for |
|------|-----------------|----------|
| **Account address** (`0x...`) | Listed directly on the Accounts tab | `BACKEND_WALLET` in the deploy command |
| **Private key** (64 hex chars) | Click the **🔑 key icon** next to an account | `PRIVATE_KEY` in `smartcontracts/.env` and `BLOCKCHAIN_WALLET_KEY` in root `.env` |

> Use the same Ganache account for both the deployer and backend wallet during local testing, or use two separate accounts.

---

## Step 2 — Deploy Smart Contracts (first time only)

### 2a. Fill `smartcontracts/.env`

Create `smartcontracts/.env` (copy from `smartcontracts/.env.example`) and set the minimum required value:

```env
# smartcontracts/.env  — used by Hardhat for deployment
PRIVATE_KEY=your_ganache_private_key_here
```

> **Where:** Ganache → Accounts tab → **🔑 key icon** on the account you want to deploy from → copy the private key.

### 2b. Run Deployment

```bash
cd smartcontracts
npm install
BACKEND_WALLET=0xYourGanacheAccountAddress npx hardhat run scripts/deploy-v2.js --network ganache
```

- `BACKEND_WALLET` = the **address** (not private key) of the Ganache account Django will use to sign transactions.
- Deploys 10 contracts, wires cross-contract roles, and grants `BACKEND_WALLET` SYSTEM_ROLE.
- Saves results to `smartcontracts/deployments/v2-ganache-<timestamp>.json`.

### 2c. Validate (recommended)

```bash
npx hardhat run scripts/validate-deployment.js --network ganache
```

---

## Step 3 — Fill Root `.env`

Open `.env` in the **project root** (used by Django). Set the blockchain fields:

```env
# .env (project root) — used by Django
BLOCKCHAIN_ENABLED=True
BLOCKCHAIN_RPC_URL=http://127.0.0.1:7545
BLOCKCHAIN_CHAIN_ID=1337
BLOCKCHAIN_WALLET_KEY=<private_key_of_BACKEND_WALLET_account>
BLOCKCHAIN_CONTRACT_ADDRESSES={"auditRegistry":"0x...","accessControl":"0x...","loanCore":"0x...","loanApplication":"0x...","loanReview":"0x...","loanApproval":"0x...","disbursementMethod":"0x...","disbursementExecution":"0x...","repaymentSchedule":"0x...","paymentRecording":"0x..."}
BLOCKCHAIN_GAS_LIMIT=6721975
BLOCKCHAIN_GAS_PRICE_GWEI=20
```

### Where to get each value

#### `BLOCKCHAIN_WALLET_KEY`

> ⚠️ This is the **private key**, NOT the address. The address (e.g. `0x79Af1cD4...`) shown in the deploy output as "Backend service wallet" is just for reference — Django needs the **private key** of that same account.

1. Open Ganache → **Accounts tab**
2. Find the account whose address matches what you used as `BACKEND_WALLET` in Step 2
3. Click the **🔑 key icon** on that row
4. Copy the **Private Key** (64 hex characters) — this goes into `BLOCKCHAIN_WALLET_KEY`

#### `BLOCKCHAIN_CONTRACT_ADDRESSES`

After deployment succeeds, a JSON file is saved at:
```
smartcontracts/deployments/v2-ganache-<timestamp>.json
```

Open it — it looks like this:
```json
{
  "contracts": {
    "auditRegistry": "0xABC...",
    "accessControl": "0xDEF...",
    "loanCore": "0x123...",
    ...
  }
}
```

Copy the entire `contracts` object and paste it as a **single-line JSON string** into `BLOCKCHAIN_CONTRACT_ADDRESSES`. Example:
```
BLOCKCHAIN_CONTRACT_ADDRESSES={"auditRegistry":"0xABC...","accessControl":"0xDEF...","loanCore":"0x123...","loanApplication":"0x...","loanReview":"0x...","loanApproval":"0x...","disbursementMethod":"0x...","disbursementExecution":"0x...","repaymentSchedule":"0x...","paymentRecording":"0x..."}
```

### Copy ABIs (required once, or after recompiling contracts)

```bash
# From project root
pip install -r requirements.txt
python scripts/copy_abis.py
```

This copies ABI files from `smartcontracts/artifacts/` into `loans/blockchain/abis/` (10 files). Django loads these to interact with deployed contracts.

### Verify connection

```bash
python manage.py shell -c "from loans.blockchain.client import get_web3; print('connected:', get_web3().is_connected())"
```

Must print `connected: True`.

---

## Step 4 — Start Django & Test

```bash
python manage.py runserver
```

Normal startup output looks like:
```
System check identified no issues (0 silenced).
Starting development server at http://0.0.0.0:8000/
```

To confirm blockchain is enabled, run this quick check:
```bash
python manage.py shell -c "from django.conf import settings; print('BLOCKCHAIN_ENABLED:', settings.BLOCKCHAIN_ENABLED)"
```

Should print `BLOCKCHAIN_ENABLED: True`.

### Full Loan Lifecycle Test

Each action in the app triggers background blockchain transactions written to Ganache. The **TX Count** is how many on-chain contract calls are made per step.

| Step | Action | Where | TX Count | What's written on-chain |
|------|--------|-------|----------|------------------------|
| **Submit** | Customer applies for a loan | Mobile app | +4 | `createApplication()` + `submitApplication()` on LoanApplication and LoanCore |
| **Approve** | Officer approves the application | Web app | +4 | `assignOfficer()` on LoanReview + `approveLoan()` on LoanApproval and LoanCore |
| **Disburse** | Officer disburses the loan | Web app | +5 | `setPreferredMethod()` + `initiateDisbursement()` + `completeDisbursement()` + `markDisbursed()` + `createSchedule()` |
| **Pay** | Customer makes a payment | Mobile app | +1 per payment | `recordPayment()` on PaymentRecording |

**Total for a 3-month loan with 3 payments: 16 transactions**

**How to confirm each step worked:**

1. **Django console** — after each action you should see:
   ```
   INFO Transaction OK: 0xABC123.createApplication() tx=... gas=...
   INFO sync_application OK: loan=... tx=...
   ```
   `Transaction OK` = the contract call succeeded on-chain. `sync_* OK` = Django finished syncing that step.

2. **Ganache → Transactions tab** — TX count increases by the expected number after each action.

> If you see no logs, blockchain sync runs in a background thread — wait 1–2 seconds after the action before checking the console.

---

## Step 5 — Verify Audit Trail

- **Web app (officer):** Open a non-pending application → scroll to **"Blockchain Audit Trail"** card. Each entry shows tx hash, block number, gas, timestamp, and a green **"Confirmed"** badge.
- **Mobile app (customer):** Open loan detail → **"Blockchain Verification"** card shows a green **Verified** badge with all transactions listed.
- **Ganache:** Copy a tx hash from the UI → paste in Ganache search bar (add `0x` prefix if missing) to verify on-chain.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| No blockchain logs | Check `BLOCKCHAIN_ENABLED=True` in root `.env` |
| `insufficient funds for gas` | `PRIVATE_KEY` missing in `smartcontracts/.env` — set it to a Ganache account's private key (🔑 icon) |
| Wallet key not configured | Set `BLOCKCHAIN_WALLET_KEY` in root `.env` — copy from Ganache (🔑 icon on the `BACKEND_WALLET` account) |
| `ContractNotFoundError` / ABI error | Run `python scripts/copy_abis.py` from project root |
| Cannot connect to node | Ensure Ganache is running on port 7545 |
| Role/access `revert` | Redeploy with `BACKEND_WALLET=0xAddress` set in the deploy command |
| `NOTHING FOUND` in Ganache | Add `0x` prefix to the tx hash |
| `web3` module not found | Run `pip install -r requirements.txt` |
