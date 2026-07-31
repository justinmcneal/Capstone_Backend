"""
Web3 client for interacting with deployed smart contracts.

Provides cached connections, contract loading, transaction helpers,
and a lightweight circuit breaker with retry/backoff for node calls.
All functions check BLOCKCHAIN_ENABLED before executing.
"""

import json
import logging
import threading
import time
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

# Circuit breaker configuration
_CB_FAILURE_THRESHOLD = 5
_CB_RECOVERY_TIMEOUT = 60  # seconds
_CB_MAX_RETRIES = 3
_CB_RETRY_BACKOFF_BASE = 1  # seconds


class _CircuitBreaker:
    """Thread-safe circuit breaker for blockchain node availability."""

    def __init__(self, failure_threshold, recovery_timeout):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failures = 0
        self._opened_at = 0
        self._lock = threading.Lock()

    def allow_request(self):
        """Return True if the circuit allows an attempt."""
        with self._lock:
            if self._failures >= self._failure_threshold:
                if time.time() - self._opened_at < self._recovery_timeout:
                    return False
                self._failures = 0
            return True

    def record_failure(self):
        """Record a failure and trip the circuit if threshold is reached."""
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = time.time()
                logger.warning(
                    "Blockchain circuit breaker OPEN after %d failures", self._failures
                )

    def record_success(self):
        """Reset failure count on success."""
        with self._lock:
            self._failures = 0


_node_circuit_breaker = _CircuitBreaker(
    failure_threshold=_CB_FAILURE_THRESHOLD,
    recovery_timeout=_CB_RECOVERY_TIMEOUT,
)


def _check_enabled():
    """Raise if blockchain integration is disabled."""
    if not getattr(settings, "BLOCKCHAIN_ENABLED", False):
        raise BlockchainDisabledError(
            "Blockchain integration is disabled. Set BLOCKCHAIN_ENABLED=True"
        )


def _with_retry(fn, *args, **kwargs):
    """
    Call fn(*args, **kwargs) with circuit breaker + exponential backoff retry.

    Returns the result, or raises the last exception after exhausting retries.
    """
    last_exc = None
    for attempt in range(1, _CB_MAX_RETRIES + 1):
        if not _node_circuit_breaker.allow_request():
            logger.warning(
                "Blockchain circuit breaker OPEN; skipping %s attempt %d/%d",
                fn.__name__,
                attempt,
                _CB_MAX_RETRIES,
            )
            last_exc = BlockchainConnectionError(
                "Blockchain node unavailable (circuit breaker open)"
            )
            continue

        try:
            result = fn(*args, **kwargs)
            _node_circuit_breaker.record_success()
            return result
        except (BlockchainConnectionError, TimeoutError, OSError) as exc:
            _node_circuit_breaker.record_failure()
            last_exc = exc
            logger.warning(
                "Blockchain call %s failed (attempt %d/%d): %s",
                fn.__name__,
                attempt,
                _CB_MAX_RETRIES,
                exc,
            )
            if attempt < _CB_MAX_RETRIES:
                backoff = _CB_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                time.sleep(backoff)

    raise last_exc or BlockchainConnectionError("Blockchain call failed after retries")


def _normalize_tx_hash(tx_hash):
    """Return a hex transaction hash without any 0x prefix."""
    if hasattr(tx_hash, "hex"):
        value = tx_hash.hex()
    else:
        value = str(tx_hash)
    return value[2:] if value.startswith("0x") else value


def _format_tx_hash(tx_hash, with_prefix=False):
    """Normalize a transaction hash and optionally prefix it with 0x."""
    normalized = _normalize_tx_hash(tx_hash)
    return f"0x{normalized}" if with_prefix else normalized


@lru_cache(maxsize=1)
def get_web3():
    """
    Return a cached Web3 instance connected to the configured RPC provider.
    Raises BlockchainConnectionError if the node is unreachable.
    """
    _check_enabled()
    rpc_url = settings.BLOCKCHAIN_RPC_URL

    def _connect():
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception as exc:
            raise BlockchainConnectionError(
                f"Failed to create Web3 provider for {rpc_url}: {exc}"
            ) from exc

        if not w3.is_connected():
            raise BlockchainConnectionError(
                f"Cannot connect to blockchain node at {rpc_url}"
            )

        logger.debug("Connected to blockchain at %s (chain %s)", rpc_url, w3.eth.chain_id)
        return w3

    return _with_retry(_connect)


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
        dict with keys: tx_hash (hex str), gas_used (int), gas_price (int), block_number (int), status (int)

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
        gas = min(
            int(estimated_gas * 1.2), settings.BLOCKCHAIN_GAS_LIMIT
        )
    except Exception:
        gas = settings.BLOCKCHAIN_GAS_LIMIT

    gas_price_fallback = Web3.to_wei(settings.BLOCKCHAIN_GAS_PRICE_GWEI, "gwei")

    def _build_tx():
        try:
            latest_block = w3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas")
        except Exception:
            base_fee = None

        tx_params = {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gas": gas,
            "chainId": settings.BLOCKCHAIN_CHAIN_ID,
        }

        if base_fee is not None and base_fee > 0:
            max_priority_fee = Web3.to_wei(2, "gwei")
            max_fee = (base_fee * 2) + max_priority_fee
            if max_fee < gas_price_fallback:
                max_fee = gas_price_fallback
            tx_params["maxFeePerGas"] = max_fee
            tx_params["maxPriorityFeePerGas"] = max_priority_fee
        else:
            tx_params["gasPrice"] = gas_price_fallback

        return fn.build_transaction(tx_params)

    tx = _with_retry(_build_tx)

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    tx_hash_hex = _format_tx_hash(receipt["transactionHash"])

    if receipt["status"] != 1:
        logger.error(
            "Transaction REVERTED: %s.%s(%s) tx=0x%s",
            contract.address,
            method_name,
            args,
            tx_hash_hex,
        )
        raise BlockchainTransactionFailed(
            f"{method_name} reverted on-chain",
            tx_hash=tx_hash_hex,
            receipt=receipt,
        )

    effective_gas_price = receipt.get("effectiveGasPrice", gas_price_fallback)

    logger.info(
        "Transaction OK: %s.%s() tx=0x%s gas=%d",
        contract.address[:10],
        method_name,
        tx_hash_hex[:16],
        receipt["gasUsed"],
    )

    return {
        "tx_hash": tx_hash_hex,
        "gas_used": receipt["gasUsed"],
        "gas_price": effective_gas_price,
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
    return _with_retry(fn.call)


def send_eth_transfer(to_address, amount_wei):
    """
    Send ETH from the system wallet to a target address.

    This is a direct value transfer (not a contract call).
    Used for wallet-based loan disbursements.

    Args:
        to_address: Recipient Ethereum address
        amount_wei: Amount in Wei (int)

    Returns:
        dict with keys: tx_hash, gas_used, gas_price, block_number, status, amount_wei
    """
    _check_enabled()
    w3 = get_web3()
    account = get_account()

    def _get_gas_price():
        try:
            gas_price_fallback = w3.eth.gas_price
        except Exception:
            gas_price_fallback = Web3.to_wei(20, "gwei")
        return gas_price_fallback

    def _get_base_fee():
        try:
            latest_block = w3.eth.get_block("latest")
            return latest_block.get("baseFeePerGas")
        except Exception:
            return None

    gas_price_fallback = _with_retry(_get_gas_price)
    base_fee = _with_retry(_get_base_fee)

    tx = {
        "from": account.address,
        "to": Web3.to_checksum_address(to_address),
        "value": int(amount_wei),
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 21000,
        "chainId": settings.BLOCKCHAIN_CHAIN_ID,
    }

    if base_fee is not None and base_fee > 0:
        max_priority_fee = Web3.to_wei(2, "gwei")
        max_fee = (base_fee * 2) + max_priority_fee
        tx["maxFeePerGas"] = max_fee
        tx["maxPriorityFeePerGas"] = max_priority_fee
    else:
        tx["gasPrice"] = gas_price_fallback

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    tx_hash_hex = _format_tx_hash(receipt["transactionHash"], with_prefix=True)

    if receipt["status"] != 1:
        logger.error(
            "ETH transfer FAILED: to=%s amount=%s tx=%s",
            to_address,
            amount_wei,
            tx_hash_hex,
        )
        raise BlockchainTransactionFailed(
            f"ETH transfer to {to_address} failed",
            tx_hash=tx_hash_hex,
            receipt=receipt,
        )

    effective_gas_price = receipt.get("effectiveGasPrice", gas_price_fallback)

    logger.info(
        "ETH transfer OK: tx=%s amount=%s wei to=%s",
        tx_hash_hex[:18],
        amount_wei,
        to_address[:10],
    )

    return {
        "tx_hash": tx_hash_hex,
        "gas_used": receipt["gasUsed"],
        "gas_price": effective_gas_price,
        "block_number": receipt["blockNumber"],
        "status": receipt["status"],
        "amount_wei": int(amount_wei),
    }


def clear_cache():
    """Clear all cached Web3 instances and contracts. Useful for testing."""
    get_web3.cache_clear()
    get_account.cache_clear()
    _contract_cache.clear()
