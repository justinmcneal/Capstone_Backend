"""
Service for DisbursementMethod + DisbursementExecution contract interactions.

Handles: setPreferredMethod, initiateDisbursement, completeDisbursement, getDisbursement
"""

import logging

from web3 import Web3

from loans.blockchain.client import get_contract, send_transaction, call_view

logger = logging.getLogger("blockchain")

# DisbursementMethod.Method enum mapping (Django string → Solidity uint)
DISBURSEMENT_METHOD_MAP = {
    "bank_transfer": 0,
    "gcash": 1,
    "cash": 2,
    "check": 3,
    "wallet": 4,
}


def _to_bytes32(value):
    """Convert a string to bytes32 (keccak256 hash)."""
    if isinstance(value, bytes) and len(value) == 32:
        return value
    return Web3.keccak(text=str(value))


def set_method_onchain(loan_id, method, details_hash=""):
    # No-op since method is now passed directly to initiateDisbursement
    return {"tx_hash": "0x", "gas_used": 0, "block_number": 0, "status": 1}


def initiate_disbursement_onchain(loan_id, amount, method="wallet"):
    """
    Initiate disbursement on-chain (creates a disbursement record).

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)
        amount: Disbursement amount in smallest unit (int)
        method: Disbursement method string

    Returns:
        dict with tx_hash, gas_used, block_number, status
    """
    contract = get_contract("disbursementExecution")
    loan_id_bytes = _to_bytes32(loan_id)
    method_enum = DISBURSEMENT_METHOD_MAP.get(method, 4)

    result = send_transaction(
        contract,
        "initiateDisbursement",
        loan_id_bytes,
        int(amount),
        method_enum,
    )

    logger.info(
        "initiateDisbursement on-chain: loan=%s amount=%d method=%s tx=%s",
        loan_id,
        amount,
        method,
        result["tx_hash"][:18],
    )
    return result


def complete_disbursement_onchain(loan_id, amount, method, reference_hash):
    """
    Complete disbursement on-chain (transitions to Disbursed status).

    Note: initiateDisbursement returns a disbursementId. This function
    initiates first if needed, then completes with the reference hash.

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)
        amount: Disbursement amount in smallest unit (int)
        method: Disbursement method string
        reference_hash: Hash of the bank/payment reference (string, hashed to bytes32)

    Returns:
        dict with keys:
            initiate_tx: tx result from initiateDisbursement
            complete_tx: tx result from completeDisbursement
    """
    contract_exec = get_contract("disbursementExecution")
    loan_id_bytes = _to_bytes32(loan_id)
    ref_bytes = _to_bytes32(reference_hash)
    method_enum = DISBURSEMENT_METHOD_MAP.get(method, 4)

    # Step 1: Initiate
    initiate_result = send_transaction(
        contract_exec,
        "initiateDisbursement",
        loan_id_bytes,
        int(amount),
        method_enum,
    )

    # Step 2: Get the disbursementId via getDisbursementByLoan
    disbursement_record = call_view(
        contract_exec, "getDisbursementByLoan", loan_id_bytes
    )
    disbursement_id = disbursement_record[0]  # First field is disbursementId

    # Step 3: Complete
    complete_result = send_transaction(
        contract_exec,
        "completeDisbursement",
        disbursement_id,
        ref_bytes,
    )

    logger.info(
        "completeDisbursement on-chain: loan=%s tx=%s",
        loan_id,
        complete_result["tx_hash"][:18],
    )

    return {
        "initiate_tx": initiate_result,
        "complete_tx": complete_result,
    }


def get_disbursement_onchain(disbursement_id):
    """
    Read disbursement record from chain (view call, no gas).

    Args:
        disbursement_id: Disbursement identifier (bytes32)

    Returns:
        Tuple of disbursement fields as returned by the contract
    """
    contract = get_contract("disbursementExecution")
    return call_view(contract, "getDisbursement", disbursement_id)
