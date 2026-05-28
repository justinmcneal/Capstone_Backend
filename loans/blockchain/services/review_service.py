"""
Service for LoanReview contract interactions.

Handles: assignOfficer, getAssignedOfficer
"""

import logging

from web3 import Web3

from loans.blockchain.client import get_contract, send_transaction, call_view

logger = logging.getLogger("blockchain")


def _to_bytes32(value):
    """Convert a string to bytes32 (keccak256 hash)."""
    if isinstance(value, bytes) and len(value) == 32:
        return value
    return Web3.keccak(text=str(value))


def assign_officer_onchain(loan_id, officer_address):
    """
    Assign a loan officer to an application on-chain.

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)
        officer_address: Officer's Ethereum address (checksummed)

    Returns:
        dict with tx_hash, gas_used, block_number, status
    """
    contract = get_contract("loanReview")
    loan_id_bytes = _to_bytes32(loan_id)
    officer_addr = Web3.to_checksum_address(officer_address)

    result = send_transaction(
        contract,
        "assignOfficer",
        loan_id_bytes,
        officer_addr,
    )

    logger.info(
        "assignOfficer on-chain: loan=%s officer=%s tx=%s",
        loan_id,
        officer_addr[:10],
        result["tx_hash"][:18],
    )
    return result


def get_assigned_officer_onchain(loan_id):
    """
    Read the assigned officer address from chain (view call, no gas).

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)

    Returns:
        Officer's Ethereum address (str)
    """
    contract = get_contract("loanReview")
    loan_id_bytes = _to_bytes32(loan_id)
    return call_view(contract, "getAssignedOfficer", loan_id_bytes)
