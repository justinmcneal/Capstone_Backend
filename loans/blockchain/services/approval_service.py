"""
Service for LoanApproval contract interactions.

Handles: approveLoan, rejectLoan
"""

import logging

from web3 import Web3

from loans.blockchain.client import get_contract, send_transaction

logger = logging.getLogger("blockchain")


def _to_bytes32(value):
    """Convert a string to bytes32 (keccak256 hash)."""
    if isinstance(value, bytes) and len(value) == 32:
        return value
    return Web3.keccak(text=str(value))


def approve_loan_onchain(loan_id, approved_amount, notes_hash):
    """
    Approve a loan on-chain (transitions UnderReview → Approved).

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)
        approved_amount: Approved amount in smallest unit (int)
        notes_hash: Hash of approval notes (string, hashed to bytes32)

    Returns:
        dict with tx_hash, gas_used, block_number, status
    """
    contract = get_contract("loanApproval")
    loan_id_bytes = _to_bytes32(loan_id)
    notes_bytes = _to_bytes32(notes_hash)

    result = send_transaction(
        contract,
        "approveLoan",
        loan_id_bytes,
        int(approved_amount),
        notes_bytes,
    )

    logger.info("approveLoan on-chain: loan=%s amount=%d tx=%s",
                loan_id, approved_amount, result["tx_hash"][:18])
    return result


def reject_loan_onchain(loan_id, rejection_reason_hash, notes_hash):
    """
    Reject a loan on-chain (transitions UnderReview → Rejected).

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)
        rejection_reason_hash: Hash of rejection reason (string, hashed to bytes32)
        notes_hash: Hash of rejection notes (string, hashed to bytes32)

    Returns:
        dict with tx_hash, gas_used, block_number, status
    """
    contract = get_contract("loanApproval")
    loan_id_bytes = _to_bytes32(loan_id)
    reason_bytes = _to_bytes32(rejection_reason_hash)
    notes_bytes = _to_bytes32(notes_hash)

    result = send_transaction(
        contract,
        "rejectLoan",
        loan_id_bytes,
        reason_bytes,
        notes_bytes,
    )

    logger.info("rejectLoan on-chain: loan=%s tx=%s", loan_id, result["tx_hash"][:18])
    return result
