"""
send_eth_test.py — Send ETH from a Ganache customer account to the system wallet.

Usage:
    python send_eth_test.py

This script:
1. Connects to Ganache at http://127.0.0.1:7545
2. Sends 0.0816 ETH (≈ ₱7,166.67) from CUSTOMER_PRIVATE_KEY → SYSTEM_WALLET
3. Prints the transaction hash so you can paste it into the wallet-payment API

REQUIRED: Edit the CUSTOMER_PRIVATE_KEY below to be any Ganache account
          that is NOT the system wallet (Account 0).
          Use the private key from the Ganache UI (click the key icon).
"""

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# ─── CONFIG ──────────────────────────────────────────────────────────────────

GANACHE_URL = "http://127.0.0.1:7545"

# System wallet (Account 0 in Ganache — this is the RECIPIENT)
SYSTEM_WALLET = "0x076471434efa1038e91613244751bFd5aE5E7E47"

# ⚠️  PASTE YOUR CUSTOMER ACCOUNT PRIVATE KEY HERE (Account 1, 2, etc. from Ganache)
# Click the key icon next to any account in Ganache to get its private key.
CUSTOMER_PRIVATE_KEY = "0x13962fa76812b6982ec53dcc642d447f16602ed3799896530941911e51ce0458"

# ETH amount to send: 7166.67 / 87830.39 = 0.081597 ETH → use 0.0816 ETH
# This equals ≈ ₱7,166.96 which is within ±2% of ₱7,166.67
ETH_AMOUNT = 0.0816

# ─── SCRIPT ──────────────────────────────────────────────────────────────────

def main():
    w3 = Web3(Web3.HTTPProvider(GANACHE_URL))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        print("❌ Cannot connect to Ganache at", GANACHE_URL)
        print("   Make sure Ganache is running.")
        return

    print(f"✅ Connected to Ganache  (chain_id={w3.eth.chain_id})")

    customer_account = w3.eth.account.from_key(CUSTOMER_PRIVATE_KEY)
    customer_address = customer_account.address
    amount_wei = w3.to_wei(ETH_AMOUNT, "ether")

    balance_wei = w3.eth.get_balance(customer_address)
    balance_eth = w3.from_wei(balance_wei, "ether")

    print(f"\n📤 Sender (Customer):  {customer_address}")
    print(f"   Balance: {balance_eth:.4f} ETH")
    print(f"\n📥 Recipient (System): {SYSTEM_WALLET}")
    print(f"\n💸 Sending: {ETH_AMOUNT} ETH  (≈ ₱7,166.67)\n")

    if balance_eth < ETH_AMOUNT + 0.001:
        print("❌ Insufficient balance in customer account!")
        return

    tx = {
        "from": customer_address,
        "to": Web3.to_checksum_address(SYSTEM_WALLET),
        "value": amount_wei,
        "nonce": w3.eth.get_transaction_count(customer_address),
        "gas": 21000,
        "gasPrice": w3.to_wei(20, "gwei"),
        "chainId": w3.eth.chain_id,
    }

    signed = customer_account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

    tx_hash_hex = "0x" + receipt["transactionHash"].hex()

    if receipt["status"] == 1:
        print("=" * 60)
        print("✅ ETH SENT SUCCESSFULLY!")
        print("=" * 60)
        print(f"\n🔑 TRANSACTION HASH (copy this):\n")
        print(f"   {tx_hash_hex}\n")
        print(f"   Block:    #{receipt['blockNumber']}")
        print(f"   Gas used: {receipt['gasUsed']}")
        print()
        print("─" * 60)
        print("📋 Now use this tx_hash in Insomnia:")
        print(f"""
  POST http://localhost:8000/api/loans/applications/6a238d80f4e99447b8bf0165/wallet-payment/
  Authorization: Bearer <customer_access_token>

  {{
    "tx_hash": "{tx_hash_hex}",
    "installment_number": 1
  }}
""")
        print(f"⚠️  Make sure your customer profile wallet_address is set to:")
        print(f"   {customer_address}")
    else:
        print("❌ Transaction FAILED on-chain!")
        print(f"   tx_hash: {tx_hash_hex}")


if __name__ == "__main__":
    main()
