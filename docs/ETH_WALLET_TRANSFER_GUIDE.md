# ETH Wallet Transfer — Implementation & Testing Guide

Implement real ETH transfers for the "Wallet (ETH)" disbursement and repayment method using MetaMask + WalletConnect.

**Prerequisites:** Ganache 2.7+, MetaMask (browser extension or mobile), Python 3.9+, Node.js 18+, Flutter 3.x, a WalletConnect Project ID (free at [cloud.walletconnect.com](https://cloud.walletconnect.com))

---

## Overview

Currently the "Wallet (ETH)" option in the app only **records** the choice — no ETH actually moves. This guide adds **real ETH transfers** to two money-moving operations:

| Operation | Direction | Who triggers | How |
|-----------|-----------|-------------|-----|
| **Disbursement** | System wallet → Customer wallet | Loan officer (web) | Backend sends ETH automatically |
| **Repayment** | Customer wallet → System wallet | Customer (mobile) | Customer approves in MetaMask via WalletConnect |

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SYSTEM WALLET                                │
│            (Backend Ganache account — one wallet for all)            │
│                                                                     │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│   │ Audit Trail  │    │ Disbursement │    │ Repayment Collection │  │
│   │ (existing)   │    │ ETH → Cust.  │    │ ETH ← Cust.         │  │
│   └──────────────┘    └──────────────┘    └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                              │                       ▲
                         ETH transfer            ETH transfer
                              ▼                       │
                   ┌──────────────────────┐
                   │   CUSTOMER WALLET    │
                   │ (MetaMask on Ganache)│
                   └──────────────────────┘
```

### ETH/PHP Conversion

Loan amounts are in PHP. ETH transfers need a conversion rate.

- **Source:** [CryptoCompare API](https://min-api.cryptocompare.com/data/price?fsym=ETH&tsyms=PHP) — free, no key required, 100k calls/month
- **No fallback:** If CryptoCompare is unreachable and no cached rate exists, wallet transactions are **blocked** until the rate can be fetched. This prevents disbursing or collecting incorrect ETH amounts due to stale exchange rates.
- **Caching:** Rate is cached for 5 minutes to reduce API calls
- **Formula:** `eth_amount = php_amount / eth_php_rate`
- **Caching:** Rate cached for 5 minutes to avoid excessive API calls

### What Does NOT Change

- **Smart contracts** — remain audit/record-keeping only, no redeployment
- **Existing flows** — cash, gcash, bank_transfer, check still work identically
- **On-chain audit trail** — still recorded for all methods including wallet

---

## Wallet Setup (Before You Start)

### Who Needs What

| Role | Wallet | MetaMask needed? | Why |
|------|--------|-----------------|-----|
| **Loan Officer (Web)** | System wallet — Ganache Account #1 (deployer) | ❌ No | Backend sends/receives ETH automatically using the private key in `.env`. Officer just clicks buttons. |
| **Customer (Mobile)** | Customer wallet — Ganache Account #2 | ✅ Yes | Customer approves repayment transfers in MetaMask via WalletConnect on their phone. |

> The MetaMask setup below is **only for the customer side** (or for you to simulate a customer during testing). The web app and backend never touch MetaMask.

### MetaMask → Ganache Connection (Customer / Testing)

Customers use MetaMask as their wallet. For local testing, MetaMask must connect to Ganache.

1. Open **MetaMask** (browser extension or mobile app)
2. Click the network dropdown → **Add Network** → **Add a network manually**
3. Fill in:

   | Field | Value |
   |-------|-------|
   | Network Name | `Ganache Local` |
   | New RPC URL | `http://127.0.0.1:7545` |
   | Chain ID | `1337` |
   | Currency Symbol | `ETH` |

4. Save and switch to **Ganache Local** network
5. **Import a Ganache account** into MetaMask:
   - Open Ganache → Accounts tab → click 🔑 on an account (NOT the system/deployer account)
   - In MetaMask → click account icon → **Import Account** → paste the private key
   - This account is now the **customer's wallet** for testing

> ⚠️ Use a **different** Ganache account than the system/deployer wallet. The system wallet is Ganache Account #1 (the first account, used during deployment). Pick Account #2 or later for the customer.

### Reown (WalletConnect) Project ID

Required for the mobile app to connect to MetaMask via WalletConnect.

1. Go to [cloud.reown.com](https://cloud.reown.com) (formerly cloud.walletconnect.com)
2. Sign up (free) → Create a new project
3. In the dashboard sidebar, click **"App ID"** → copy the **Project ID**

---

## Phase 1 — Backend Foundation

### What We're Building

| Task | File(s) | Description |
|------|---------|-------------|
| 1.1 | `profiles/models/profile_models.py` | Add `wallet_address` field to CustomerProfile |
| 1.2 | `profiles/serializers/profile_serializers.py` | Add `wallet_address` with ETH address validation |
| 1.3 | `loans/blockchain/services/eth_price_service.py` | New service: fetch ETH/PHP rate from CryptoCompare |
| 1.4 | `loans/blockchain/client.py` | New function: `send_eth_transfer()` for direct ETH sends |
| 1.5 | `config/settings.py` | _(removed — no fallback rate needed)_ |

### 1.1 — Wallet Address in Customer Profile

Add a `wallet_address` field to the `CustomerProfile` model. This stores the customer's Ethereum address (from MetaMask / Ganache).

**Model field:**
```python
# profiles/models/profile_models.py — CustomerProfile.__init__
self.wallet_address = kwargs.get('wallet_address')  # Ethereum address (0x + 40 hex)
```

**Validation rules:**
- Optional (not all customers use wallet)
- Format: `0x` followed by exactly 40 hexadecimal characters
- Checksum validation via `web3.Web3.is_address()`

### 1.2 — Profile Serializer Update

Add `wallet_address` to `CustomerProfileSerializer` and `CustomerProfileResponseSerializer`:

```python
wallet_address = serializers.CharField(
    required=False, allow_blank=True, allow_null=True, max_length=42,
)
```

Custom validation to ensure valid Ethereum address format.

### 1.3 — ETH Price Service

New file: `loans/blockchain/services/eth_price_service.py`

```python
def get_eth_php_rate() -> float:
    """
    Fetch current ETH/PHP exchange rate.
    Source: CryptoCompare API (cached 5 min)
    Raises ExchangeRateUnavailableError if unreachable.
    """
```

**API endpoint:** `https://min-api.cryptocompare.com/data/price?fsym=ETH&tsyms=PHP`

**Response format:** `{"PHP": 180000.00}`

### 1.4 — ETH Transfer Function

Add to `loans/blockchain/client.py`:

```python
def send_eth_transfer(to_address: str, amount_wei: int) -> dict:
    """
    Send ETH from system wallet to a target address.
    Returns: {tx_hash, gas_used, block_number, status, amount_wei}
    """
```

Key differences from existing `send_transaction()`:
- No contract interaction — direct value transfer
- Fixed gas: 21,000 (standard ETH transfer)
- Includes `value` field in transaction

### 1.5 — Environment Variable

Add to `.env`:
```env
# No ETH_PHP_RATE fallback — rate is always fetched live from CryptoCompare.
# If the API is unreachable, wallet transactions are blocked.
```

### Testing Phase 1

```bash
# 1. Verify wallet_address can be saved in profile
python manage.py shell -c "
from profiles.models.profile_models import CustomerProfile
p = CustomerProfile(customer_id='test', wallet_address='0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28')
print('wallet_address:', p.wallet_address)
"

# 2. Verify ETH price service
python manage.py shell -c "
from loans.blockchain.services.eth_price_service import get_eth_php_rate
rate = get_eth_php_rate()
print(f'ETH/PHP rate: {rate}')
print(f'50,000 PHP = {50000/rate:.6f} ETH')
"

# 3. Verify ETH transfer (Ganache must be running)
python manage.py shell -c "
from loans.blockchain.client import send_eth_transfer, get_web3
w3 = get_web3()
# Replace with a Ganache account address (NOT the system wallet)
customer_addr = '0xYOUR_GANACHE_ACCOUNT_2'
balance_before = w3.eth.get_balance(customer_addr)
result = send_eth_transfer(customer_addr, w3.to_wei(0.01, 'ether'))
balance_after = w3.eth.get_balance(customer_addr)
print(f'TX hash: {result[\"tx_hash\"]}')
print(f'Balance change: {w3.from_wei(balance_after - balance_before, \"ether\")} ETH')
"

# 4. Verify via Ganache UI
# Open Ganache → Transactions tab → you should see the ETH transfer transaction
```

**Expected results:**
- ✅ Profile saves and returns `wallet_address`
- ✅ Price service returns a numeric rate (e.g., `180000.0`)
- ✅ ETH transfer succeeds, balance changes in Ganache
- ✅ Transaction visible in Ganache Transactions tab

---

## Phase 2 — Backend Disbursement (System → Customer)

### What We're Building

| Task | File(s) | Description |
|------|---------|-------------|
| 2.1 | `loans/blockchain/sync.py`, `disbursement_service.py` | Send ETH when method="wallet" during disbursement |
| 2.2 | `loans/models/application.py` | Store ETH transfer details (tx_hash, amount, rate) |
| 2.3 | `loans/views/officer_views.py` | Include customer wallet_address in detail response |

### 2.1 — ETH Transfer in Disbursement Sync

Modify `_sync_disbursement_impl()` in `loans/blockchain/sync.py`:

```
Current flow:
  1. set_method_onchain()          ← records method on smart contract
  2. complete_disbursement_onchain() ← records disbursement on smart contract
  3. markDisbursed() on LoanCore   ← records status change
  4. sync schedule                 ← records repayment schedule

New flow (when method="wallet"):
  0. NEW — send_eth_transfer() to customer's wallet_address  ← ACTUAL ETH MOVES
  1. set_method_onchain()          ← audit trail (unchanged)
  2. complete_disbursement_onchain() ← audit trail (unchanged)
  3. markDisbursed() on LoanCore   ← audit trail (unchanged)
  4. sync schedule                 ← audit trail (unchanged)
```

The ETH transfer happens **before** the audit trail, so if it fails, the audit doesn't record a false disbursement.

### 2.2 — ETH Transfer Details Storage

Add fields to the loan application document in MongoDB:

```python
# New fields stored after wallet disbursement
{
    "eth_disbursement_tx_hash": "0xabc123...",   # ETH transfer transaction hash
    "eth_disbursement_amount": "0.277778",        # ETH amount sent
    "eth_disbursement_rate": 180000.0,            # ETH/PHP rate used
    "eth_disbursement_rate_source": "cryptocompare", # Rate source
}
```

### 2.3 — Officer Detail Response

Add `wallet_address` to the customer data returned in `GET /api/loans/officer/applications/<id>/`:

```json
{
  "customer": {
    "personal_profile": {
      "wallet_address": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28",
      ...
    }
  },
  "eth_disbursement_tx_hash": "0xabc...",
  "eth_disbursement_amount": "0.277778",
  "eth_disbursement_rate": 180000.0
}
```

### Testing Phase 2

**Prerequisites:**
- Ganache running with deployed contracts
- A customer account with `preferred_disbursement_method = "wallet"` and a valid `wallet_address` in their profile
- An approved loan application

```bash
# 1. Set up test data — set wallet_address on a customer profile
python manage.py shell -c "
from django.conf import settings
db = settings.MONGODB
# Replace CUSTOMER_ID with actual customer ID from your test loan
db['customer_profiles'].update_one(
    {'customer_id': 'CUSTOMER_ID'},
    {'\$set': {'wallet_address': '0xYOUR_GANACHE_ACCOUNT_2'}}
)
print('Wallet address set')
"

# 2. Disburse the loan via API (use httpie, curl, or Postman)
curl -X POST http://localhost:8000/api/loans/officer/applications/LOAN_ID/disburse/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer OFFICER_TOKEN" \
  -d '{"amount": 50000, "reference": "DSB-ETH-001"}'

# 3. Verify in Django console output — look for:
#    "ETH transfer OK: tx=0x... amount=0.277778 ETH to=0x..."
#    "Transaction OK: 0x....setPreferredMethod() tx=..."
#    "sync_disbursement OK: loan=..."

# 4. Verify customer balance in Ganache
python manage.py shell -c "
from loans.blockchain.client import get_web3
w3 = get_web3()
balance = w3.eth.get_balance('0xYOUR_GANACHE_ACCOUNT_2')
print(f'Customer balance: {w3.from_wei(balance, \"ether\")} ETH')
"

# 5. Check stored ETH details
python manage.py shell -c "
from django.conf import settings
from bson import ObjectId
app = settings.MONGODB['loan_applications'].find_one({'_id': ObjectId('LOAN_ID')})
print('ETH tx:', app.get('eth_disbursement_tx_hash'))
print('ETH amount:', app.get('eth_disbursement_amount'))
print('Rate used:', app.get('eth_disbursement_rate'))
"
```

**Expected results:**
- ✅ Customer's Ganache/MetaMask balance increases by the correct ETH amount
- ✅ Loan status changes to `disbursed`
- ✅ ETH transfer tx_hash stored in MongoDB
- ✅ Audit trail transactions also recorded (existing smart contract flow)
- ✅ Ganache → Transactions tab shows BOTH the ETH transfer AND the contract calls

---

## Phase 3 — Backend Repayment (Customer → System)

### What We're Building

| Task | File(s) | Description |
|------|---------|-------------|
| 3.1 | `loans/views/customer_views.py` + `loans/urls.py` | New endpoint: verify wallet payment |
| 3.2 | `loans/views/customer_views.py` + `loans/urls.py` | New endpoint: get system wallet info |

### 3.1 — Wallet Payment Verification Endpoint

**`POST /api/loans/applications/<id>/wallet-payment/`**

The mobile app sends the tx_hash after the customer approves in MetaMask. The backend verifies the transaction on-chain.

**Request:**
```json
{
    "tx_hash": "0xabc123...",
    "installment_number": 1
}
```

**Backend verification steps:**
1. Fetch transaction from Ganache using `w3.eth.get_transaction(tx_hash)`
2. Fetch receipt using `w3.eth.get_transaction_receipt(tx_hash)`
3. Verify:
   - `tx.to` == system wallet address (correct recipient)
   - `tx.from` == customer's `wallet_address` in profile (correct sender)
   - `tx.value` >= expected ETH amount for the installment (correct amount, with tolerance)
   - `receipt.status` == 1 (transaction succeeded)
4. If valid → record payment (same as existing `RecordPaymentView` logic)
5. Trigger `sync_payment()` for blockchain audit trail

**Response (success):**
```json
{
    "status": "verified",
    "installment_number": 1,
    "amount_php": 5000.00,
    "amount_eth": "0.027778",
    "tx_hash": "0xabc123...",
    "block_number": 42
}
```

**Response (failure):**
```json
{
    "error": "Transaction recipient does not match system wallet"
}
```

### 3.2 — System Wallet Info Endpoint

**`GET /api/loans/system-wallet/`**

Mobile app needs to know where to send ETH and how much.

**Response:**
```json
{
    "wallet_address": "0x79Af1cD4Ffb33b8D9cbBC53d276e88Fbd05bA163",
    "chain_id": 1337,
    "rpc_url": "http://127.0.0.1:7545",
    "eth_php_rate": 180000.00,
    "rate_source": "cryptocompare",
    "rate_updated_at": "2026-03-16T16:00:00Z"
}
```

### Testing Phase 3

**Prerequisites:**
- A disbursed loan with `preferred_disbursement_method = "wallet"`
- Customer's Ganache account has ETH (received from disbursement or default Ganache balance)

```bash
# 1. Get system wallet info
curl http://localhost:8000/api/loans/system-wallet/ \
  -H "Authorization: Bearer CUSTOMER_TOKEN"

# Expected: {"wallet_address": "0x79Af...", "eth_php_rate": 180000, ...}

# 2. Simulate customer sending ETH manually (for testing without WalletConnect)
python manage.py shell -c "
from loans.blockchain.client import get_web3
from eth_account import Account

w3 = get_web3()

# Customer's private key (from Ganache — NOT the system wallet)
customer_key = 'CUSTOMER_PRIVATE_KEY_FROM_GANACHE'
customer = Account.from_key(customer_key)

# System wallet address
system_addr = '0x79Af1cD4Ffb33b8D9cbBC53d276e88Fbd05bA163'

# Send 0.027 ETH (simulating a repayment)
tx = {
    'to': system_addr,
    'value': w3.to_wei(0.027, 'ether'),
    'gas': 21000,
    'gasPrice': w3.eth.gas_price,
    'nonce': w3.eth.get_transaction_count(customer.address),
    'chainId': 1337,
}
signed = customer.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
print(f'TX hash: {tx_hash.hex()}')
print(f'Status: {receipt.status}')  # 1 = success
"

# 3. Verify the payment via API (using the tx_hash from step 2)
curl -X POST http://localhost:8000/api/loans/applications/LOAN_ID/wallet-payment/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer CUSTOMER_TOKEN" \
  -d '{"tx_hash": "0xTX_HASH_FROM_STEP_2", "installment_number": 1}'

# Expected: {"status": "verified", "installment_number": 1, "amount_php": 5000, ...}

# 4. Verify payment was recorded
curl http://localhost:8000/api/loans/applications/LOAN_ID/payments/ \
  -H "Authorization: Bearer CUSTOMER_TOKEN"

# Expected: Payment with method="wallet" and blockchain_tx_hash set
```

**Expected results:**
- ✅ System wallet info endpoint returns address and rate
- ✅ Manual ETH transfer succeeds on Ganache
- ✅ Verification endpoint confirms the tx and records the payment
- ✅ Payment appears in payment history with method `wallet`
- ✅ Invalid tx_hash or wrong amount/recipient returns clear error

---

## Phase 4 — Mobile: Profile & Wallet Address

### What We're Building

| Task | File(s) | Description |
|------|---------|-------------|
| 4.1 | `lib/domain/entities/customer_profile_entity.dart`, `lib/data/models/customer_profile_model.dart` | Add `walletAddress` field |
| 4.2 | Personal info edit screen | Add wallet address input with validation |
| 4.3 | `lib/data/datasources/remote/profile_api_service.dart` | Include wallet_address in API calls |

### 4.1 — Data Model Updates

**Entity:** `CustomerProfileEntity`
```dart
final String? walletAddress;  // Ethereum wallet address (0x...)
```

**Model:** `CustomerProfileModel`
```dart
@JsonKey(name: 'wallet_address')
final String? walletAddress;
```

### 4.2 — Profile Edit Screen

Add a wallet address input field in the personal information edit screen:

- **Label:** "Wallet Address (ETH)"
- **Hint:** "0x..."
- **Icon:** `Icons.account_balance_wallet`
- **Validation:** Must start with `0x`, exactly 42 characters, valid hex
- **Helper text:** "Your Ethereum wallet address for receiving loan disbursements"

### 4.3 — API Integration

Include `wallet_address` in the `PUT /api/profile/` request body when updating profile.

### Testing Phase 4

1. Open mobile app → **Profile** → **Personal Information**
2. Scroll to the wallet address field
3. Enter a valid Ganache account address: `0x...` (42 chars)
4. Save profile
5. Verify:
   - ✅ Field validates format (rejects invalid addresses)
   - ✅ Address saves successfully
   - ✅ Address persists after reopening the screen
   - ✅ Backend MongoDB has `wallet_address` in `customer_profiles` collection

---

## Phase 5 — Mobile: WalletConnect Repayment

### What We're Building

| Task | File(s) | Description |
|------|---------|-------------|
| 5.1 | `pubspec.yaml` | Add WalletConnect package |
| 5.2 | `lib/data/services/walletconnect_service.dart` | WalletConnect session & tx management |
| 5.3 | Payment bottom sheet / repayment screen | Wallet payment flow with MetaMask |

### 5.1 — Package Installation

```yaml
# pubspec.yaml
dependencies:
  walletconnect_flutter_v2: ^2.x.x   # or web3modal_flutter
```

### 5.2 — WalletConnect Service

Handles the full lifecycle:

```
┌─────────────────────────────────────────────────────┐
│                 WalletConnect Flow                    │
│                                                      │
│  1. Initialize with Project ID                       │
│  2. Create pairing URI → show QR / deep link         │
│  3. User opens MetaMask → approves connection         │
│  4. Session established → get connected wallet addr   │
│  5. Request ETH transfer (to system wallet, amount)   │
│  6. MetaMask shows approval prompt                    │
│  7. User approves → tx sent to Ganache                │
│  8. Receive tx_hash → send to backend for verify      │
│  9. Disconnect session                                │
└─────────────────────────────────────────────────────┘
```

### 5.3 — Payment Flow Modification

When `payment_method == "wallet"` in the payment bottom sheet:

**Instead of** the current simple form submission:
1. Show "Connect Wallet" button
2. On tap → initialize WalletConnect → open MetaMask (deep link on mobile)
3. Once connected → show payment summary:
   ```
   ┌────────────────────────────────┐
   │  Pay Installment #1            │
   │                                │
   │  Amount:    ₱5,000.00          │
   │  ETH Rate:  1 ETH = ₱180,000  │
   │  ETH Amount: 0.027778 ETH     │
   │                                │
   │  To: 0x79Af...63 (System)     │
   │  From: 0x742d...28 (You)      │
   │                                │
   │  [Pay with MetaMask]           │
   └────────────────────────────────┘
   ```
4. On "Pay with MetaMask" → WalletConnect sends ETH transfer request to MetaMask
5. Customer approves in MetaMask
6. App receives tx_hash → calls `POST /api/loans/applications/<id>/wallet-payment/`
7. Backend verifies → show success or error

### Testing Phase 5

**Prerequisites:**
- MetaMask mobile installed and connected to Ganache network
- WalletConnect Project ID configured in the app
- A disbursed loan with wallet payment method
- Customer's MetaMask has ETH (from disbursement or Ganache default)

**Test Steps:**

1. Open mobile app → navigate to a disbursed loan → **Repayment** tab
2. Tap **Make Payment** on an upcoming installment
3. Select **Wallet (ETH)** as payment method
4. Tap **Connect Wallet** → MetaMask should open (or show QR code)
5. In MetaMask → approve the connection
6. Back in app → verify the payment summary shows correct amounts
7. Tap **Pay with MetaMask** → MetaMask opens with transfer prompt
8. Verify in MetaMask:
   - ✅ Recipient matches system wallet address
   - ✅ Amount matches the ETH equivalent of the installment
9. Approve the transaction in MetaMask
10. Back in app → wait for confirmation
11. Verify:
    - ✅ Success message shown with tx_hash
    - ✅ Installment status changes to `paid`
    - ✅ Payment appears in payment history
    - ✅ Ganache Transactions tab shows the ETH transfer
    - ✅ System wallet balance increased

**Edge Case Tests:**

| Test | Action | Expected Result |
|------|--------|-----------------|
| Reject in MetaMask | Tap "Reject" on the transfer prompt | App shows "Payment cancelled" — no payment recorded |
| Wrong amount | N/A (amount is pre-filled by app) | Should not be possible |
| Insufficient funds | Customer wallet has < required ETH | MetaMask shows "Insufficient funds" error |
| Disconnect mid-flow | Close MetaMask during connection | App shows "Connection lost" — retry option |
| Double payment | Try paying same installment twice | Backend rejects: "Installment already paid" |

---

## Phase 6 — Web: Officer UI Updates

### What We're Building

| Task | File(s) | Description |
|------|---------|-------------|
| 6.1 | `OfficerApplicationDetailPage.tsx` | Show customer wallet address |
| 6.2 | `DisbursementReceiptModal.tsx` | Show ETH transfer details in receipt |
| 6.3 | `DisbursementModal.tsx` | Show ETH equivalent amount |

### 6.1 — Customer Wallet Address Display

In the application detail page, when `preferred_disbursement_method == "wallet"`:

```
┌─ Customer Profile ─────────────────────────────┐
│  Name: Juan Dela Cruz                           │
│  Email: juan@email.com                          │
│  Phone: 09171234567                             │
│  ...                                            │
│  Wallet Address: 0x742d35Cc6634C0532925a...     │  ← NEW
└─────────────────────────────────────────────────┘
```

### 6.2 — Disbursement Receipt with ETH Details

After disbursing a wallet loan, the receipt shows:

```
┌─ Disbursement Receipt ──────────────────────────┐
│  Loan ID:        APP-001                        │
│  Amount (PHP):   ₱50,000.00                     │
│  Amount (ETH):   0.277778 ETH         ← NEW    │
│  Exchange Rate:  1 ETH = ₱180,000.00  ← NEW    │
│  Method:         Wallet (ETH)                   │
│  Reference:      DSB-20260316-000001            │
│  ETH TX Hash:    0xabc123...          ← NEW     │
│  Date:           March 16, 2026                 │
└─────────────────────────────────────────────────┘
```

### 6.3 — ETH Amount Preview in Disbursement Modal

When the method is `wallet`, show the ETH equivalent before confirming:

```
┌─ Disburse Loan ─────────────────────────────────┐
│  Amount:     ₱50,000.00                         │
│  Method:     Wallet (ETH) [locked]              │
│  Reference:  DSB-20260316-000001                │
│                                                  │
│  ┌─ ETH Transfer Preview ────────────────────┐  │
│  │  Rate:   1 ETH = ₱180,000.00 (live)      │  │  ← NEW
│  │  Send:   0.277778 ETH                     │  │  ← NEW
│  │  To:     0x742d35Cc6634C0532925a3b...     │  │  ← NEW
│  └───────────────────────────────────────────┘  │
│                                                  │
│  [Cancel]                    [Confirm Disburse]  │
└─────────────────────────────────────────────────┘
```

### Testing Phase 6

1. Log in as loan officer on web app
2. Open an approved application where `preferred_disbursement_method == "wallet"`
3. Verify:
   - ✅ Customer wallet address is visible in the profile section
4. Click **Disburse Loan**
5. Verify in the modal:
   - ✅ Method shows "Wallet (ETH)" and is locked
   - ✅ ETH Transfer Preview section appears with rate, ETH amount, and recipient address
6. Click **Confirm Disburse**
7. Verify receipt:
   - ✅ Shows both PHP and ETH amounts
   - ✅ Shows exchange rate used
   - ✅ Shows ETH transaction hash (clickable or copyable)

---

## End-to-End Test — Full Loan Lifecycle with Wallet

This is the complete happy path to verify everything works together.

### Setup

| What | Value |
|------|-------|
| System wallet | Ganache Account #1 (deployer) |
| Customer wallet | Ganache Account #2 (imported into MetaMask) |
| Loan amount | ₱50,000 |
| Term | 3 months |
| ETH/PHP rate | Live from CryptoCompare |

### Steps

| # | Who | Action | Where | Verify |
|---|-----|--------|-------|--------|
| 1 | Customer | Set wallet address in profile | Mobile app → Profile → Personal Info | MongoDB `customer_profiles` has `wallet_address` |
| 2 | Customer | Apply for loan with `wallet` disbursement | Mobile app → Apply | Application created with `preferred_disbursement_method: "wallet"` |
| 3 | Officer | Review and approve | Web app → Applications | Status: `approved` |
| 4 | Officer | Disburse loan | Web app → Disburse button | ETH sent to customer. Ganache shows transfer. Receipt shows ETH details |
| 5 | Customer | Verify ETH received | MetaMask | Balance increased by ~0.277 ETH |
| 6 | Customer | Pay installment #1 via wallet | Mobile app → Pay → MetaMask | MetaMask prompts, customer approves |
| 7 | System | Backend verifies payment | Automatic | Installment #1 marked `paid`. Blockchain audit recorded |
| 8 | Customer | Pay installment #2 via wallet | Mobile app → Pay → MetaMask | Same flow |
| 9 | Customer | Pay installment #3 via wallet | Mobile app → Pay → MetaMask | Loan fully paid. All installments `paid` |

### Verification Checklist

After completing all steps:

- [ ] **Ganache Transactions tab** — shows: 1 ETH disbursement + 3 ETH repayments + audit trail contract calls
- [ ] **System wallet balance** — decreased by disbursement, increased by 3 repayments (net ≈ 0)
- [ ] **Customer wallet balance** — increased by disbursement, decreased by 3 repayments (net ≈ 0)
- [ ] **MongoDB `loan_applications`** — has `eth_disbursement_tx_hash`, `eth_disbursement_amount`, `eth_disbursement_rate`
- [ ] **MongoDB `loan_payments`** — 3 payments with `payment_method: "wallet"` and `blockchain_tx_hash` set
- [ ] **Web app audit trail** — all blockchain transactions show green "Confirmed" badges
- [ ] **Mobile app blockchain card** — all transactions listed with tx hashes

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `insufficient funds for gas * price + value` | System wallet doesn't have enough ETH | Check Ganache account balance. Each new workspace starts with 100 ETH |
| MetaMask not connecting | Wrong network in MetaMask | Ensure MetaMask is on Ganache network (Chain ID 1337, RPC 127.0.0.1:7545) |
| WalletConnect QR not working | Invalid Project ID | Get a valid Project ID from cloud.walletconnect.com |
| CryptoCompare returns error | Rate limit or no internet | Wallet transactions are blocked until rate is available. Other disbursement methods (cash, gcash, etc.) still work. |
| `Transaction recipient does not match` | Customer sent ETH to wrong address | Ensure mobile app fetches system wallet from `/api/loans/system-wallet/` |
| `Transaction amount too low` | Rate changed between preview and send | Backend uses a tolerance (±2%) when verifying amounts |
| Wallet address not showing for officer | Profile not updated | Customer must save wallet address in Profile before applying |
| ETH transfer succeeds but audit fails | Contract call reverted | Check Ganache logs. Audit failure doesn't affect the ETH transfer |
| MetaMask shows 0 ETH | Account not imported or wrong network | Re-import Ganache private key into MetaMask on the Ganache network |

---

## File Change Summary

### Backend (Capstone_Backend)

| File | Change Type | Description |
|------|------------|-------------|
| `profiles/models/profile_models.py` | Modified | Add `wallet_address` field |
| `profiles/serializers/profile_serializers.py` | Modified | Add `wallet_address` with validation |
| `loans/blockchain/services/eth_price_service.py` | **New** | CryptoCompare ETH/PHP rate service |
| `loans/blockchain/client.py` | Modified | Add `send_eth_transfer()` |
| `loans/blockchain/sync.py` | Modified | ETH transfer in disbursement sync |
| `loans/blockchain/services/disbursement_service.py` | Modified | ETH disbursement logic |
| `loans/views/customer_views.py` | Modified | Wallet payment verification endpoint |
| `loans/views/officer_views.py` | Modified | Include wallet_address in detail response |
| `loans/urls.py` | Modified | Add wallet-payment and system-wallet routes |
| `config/settings.py` | Modified | _(no changes needed for ETH rate)_ |

### Mobile (MSME-Pathways-Mobile)

| File | Change Type | Description |
|------|------------|-------------|
| `lib/domain/entities/customer_profile_entity.dart` | Modified | Add `walletAddress` |
| `lib/data/models/customer_profile_model.dart` | Modified | Add `walletAddress` with JSON mapping |
| Personal info edit screen | Modified | Add wallet address input field |
| `lib/data/datasources/remote/profile_api_service.dart` | Modified | Include in API calls |
| `pubspec.yaml` | Modified | Add WalletConnect package |
| `lib/data/services/walletconnect_service.dart` | **New** | WalletConnect session management |
| Payment bottom sheet | Modified | Wallet payment flow with MetaMask |

### Web (Capstone-Web)

| File | Change Type | Description |
|------|------------|-------------|
| `OfficerApplicationDetailPage.tsx` | Modified | Show customer wallet address |
| `DisbursementModal.tsx` | Modified | ETH amount preview |
| `DisbursementReceiptModal.tsx` | Modified | ETH transfer details |
| `applicationsApi.ts` | Modified | Updated response types |
