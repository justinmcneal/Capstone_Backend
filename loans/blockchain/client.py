"""
Web3 client for interacting with deployed smart contracts.

Provides cached connections, contract loading, and transaction helpers.
All functions check BLOCKCHAIN_ENABLED before executing.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from .exceptions import (
    BlockchainConnectionError,
    BlockchainDisabledError,
    BlockchainTransactionFailed,
    ContractNotFoundError,
)

logger = logging.getLogger("blockchain")

# Maps settings key → contract name in ABI files
CONTRACT_NAME_MAP = {
    "auditRegistry": "AuditRegistry",
    "accessControl": "LoanAccessControl",
    "loanCore": "LoanCore",
    "loanApplication": "LoanApplication",
    "loanReview": "LoanReview",
    "loanApproval": "LoanApproval",
    "disbursementMethod": "DisbursementMethod",
    "disbursementExecution": "DisbursementExecution",
    "repaymentSchedule": "RepaymentSchedule",
    "paymentRecording": "PaymentRecording",
}


def _check_enabled():
    """Raise if blockchain integration is disabled."""
    if not getattr(settings, "BLOCKCHAIN_ENABLED", False):
        raise BlockchainDisabledError(
            "Blockchain integration is disabled. Set BLOCKCHAIN_ENABLED=True"
        )


@lru_cache(maxsize=1)
def get_web3():
    """
    Return a cached Web3 instance connected to the configured RPC provider.
    Raises BlockchainConnectionError if the node is unreachable.
    """
    _check_enabled()
    rpc_url = settings.BLOCKCHAIN_RPC_URL

    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        # Support PoA chains (Ganache, Polygon, etc.)
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    except Exception as exc:
        raise BlockchainConnectionError(
            f"Failed to create Web3 provider for {rpc_url}: {exc}"
        ) from exc

    if not w3.is_connected():
        raise BlockchainConnectionError(f"Cannot connect to blockchain node at {rpc_url}")

    logger.debug("Connected to blockchain at %s (chain %s)", rpc_url, w3.eth.chain_id)
    return w3


@lru_cache(maxsize=1)
def get_account():
    """
    Return the backend service Account object derived from the configured private key.
    """
    _check_enabled()
    w3 = get_web3()
    key = settings.BLOCKCHAIN_WALLET_KEY
    if not key:
        raise BlockchainConnectionError("BLOCKCHAIN_WALLET_KEY is not configured")
    # Ensure 0x prefix
    if not key.startswith("0x"):
        key = "0x" + key
    return w3.eth.account.from_key(key)


def _load_abi(contract_name):
    """Load ABI JSON for a contract from the abis/ directory."""
    abi_dir = Path(settings.BLOCKCHAIN_ABI_DIR)
    abi_path = abi_dir / f"{contract_name}.json"
    if not abi_path.exists():
        raise ContractNotFoundError(contract_name)
    with open(abi_path, "r") as f:
        return json.load(f)


_contract_cache = {}


def get_contract(key):
    """
    Return a web3 Contract instance for the given settings key.

    Args:
        key: Contract key from BLOCKCHAIN_CONTRACT_ADDRESSES
             (e.g. 'loanApplication', 'paymentRecording')

    Returns:
        web3.eth.Contract instance
    """
    _check_enabled()

    if key in _contract_cache:
        return _contract_cache[key]

    addresses = settings.BLOCKCHAIN_CONTRACT_ADDRESSES
    address = addresses.get(key)
    if not address:
        raise ContractNotFoundError(key)

    contract_name = CONTRACT_NAME_MAP.get(key)
    if not contract_name:
        raise ContractNotFoundError(key)

    abi = _load_abi(contract_name)
    w3 = get_web3()
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(address),
        abi=abi,
    )

    _contract_cache[key] = contract
    return contract


def send_transaction(contract, method_name, *args):
    """
    Build, sign, send, and wait for a state-changing transaction.

    Args:
        contract: web3 Contract instance
        method_name: Name of the contract function to call
        *args: Arguments to pass to the function

    Returns:
        dict with keys: tx_hash (hex str), gas_used (int), block_number (int), status (int)

    Raises:
        BlockchainTransactionFailed: If the transaction reverts
    """
    _check_enabled()
    w3 = get_web3()
    account = get_account()

    fn = contract.functions[method_name](*args)

    # Auto-estimate gas; fall back to configured limit if estimation fails
    try:
        estimated_gas = fn.estimate_gas({"from": account.address})
        gas = min(int(estimated_gas * 1.2), settings.BLOCKCHAIN_GAS_LIMIT)  # 20% buffer, capped
    except Exception:
        gas = settings.BLOCKCHAIN_GAS_LIMIT

    # Use network gas price if available (EIP-1559 or legacy), else fall back to configured value
    try:
        gas_price = w3.eth.gas_price
    except Exception:
        gas_price = Web3.to_wei(settings.BLOCKCHAIN_GAS_PRICE_GWEI, "gwei")

    tx = fn.build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": gas,
        "gasPrice": gas_price,
        "chainId": settings.BLOCKCHAIN_CHAIN_ID,
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    tx_hash_hex = "0x" + receipt["transactionHash"].hex()

    if receipt["status"] != 1:
        logger.error(
            "Transaction REVERTED: %s.%s(%s) tx=%s",
            contract.address, method_name, args, tx_hash_hex,
        )
        raise BlockchainTransactionFailed(
            f"{method_name} reverted on-chain",
            tx_hash=tx_hash_hex,
            receipt=receipt,
        )

    logger.info(
        "Transaction OK: %s.%s() tx=%s gas=%d",
        contract.address[:10], method_name, tx_hash_hex[:18], receipt["gasUsed"],
    )

    return {
        "tx_hash": tx_hash_hex,
        "gas_used": receipt["gasUsed"],
        "block_number": receipt["blockNumber"],
        "status": receipt["status"],
    }


def call_view(contract, method_name, *args):
    """
    Execute a read-only (view/pure) contract call. No gas cost.

    Args:
        contract: web3 Contract instance
        method_name: Name of the contract function to call
        *args: Arguments to pass to the function

    Returns:
        The return value from the contract function
    """
    _check_enabled()
    fn = contract.functions[method_name](*args)
    return fn.call()


def send_eth_transfer(to_address, amount_wei):
    """
    Send ETH from the system wallet to a target address.

    This is a direct value transfer (not a contract call).
    Used for wallet-based loan disbursements.

    Args:
        to_address: Recipient Ethereum address
        amount_wei: Amount in Wei (int)

    Returns:
        dict with keys: tx_hash, gas_used, block_number, status, amount_wei
    """
    _check_enabled()
    w3 = get_web3()
    account = get_account()

    tx = {
        "from": account.address,
        "to": Web3.to_checksum_address(to_address),
        "value": int(amount_wei),
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 21000,  # Standard ETH transfer gas
        "gasPrice": w3.eth.gas_price,
        "chainId": settings.BLOCKCHAIN_CHAIN_ID,
    }

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    tx_hash_hex = "0x" + receipt["transactionHash"].hex()

    if receipt["status"] != 1:
        logger.error("ETH transfer FAILED: to=%s amount=%s tx=%s", to_address, amount_wei, tx_hash_hex)
        raise BlockchainTransactionFailed(
            f"ETH transfer to {to_address} failed",
            tx_hash=tx_hash_hex,
            receipt=receipt,
        )

    logger.info(
        "ETH transfer OK: tx=%s amount=%s wei to=%s",
        tx_hash_hex[:18], amount_wei, to_address[:10],
    )

    return {
        "tx_hash": tx_hash_hex,
        "gas_used": receipt["gasUsed"],
        "block_number": receipt["blockNumber"],
        "status": receipt["status"],
        "amount_wei": int(amount_wei),
    }


def clear_cache():
    """Clear all cached Web3 instances and contracts. Useful for testing."""
    get_web3.cache_clear()
    get_account.cache_clear()
    _contract_cache.clear()
