"""
Service for LoanApplication contract interactions.

Handles: createApplication, submitApplication, getApplication
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


def create_application_onchain(
    loan_id, borrower_addr, product_id, amount, term_months, interest_rate_bps
):
    """
    Create a loan application on-chain.

    Args:
        loan_id: Unique loan identifier (string, will be hashed to bytes32)
        borrower_addr: Borrower's Ethereum address (not used directly — contract uses msg.sender context)
        product_id: Loan product identifier (string, hashed to bytes32)
        amount: Requested amount in smallest unit (int)
        term_months: Loan term in months (int)
        interest_rate_bps: Interest rate in basis points (int, e.g. 1200 = 12%)

    Returns:
        dict with tx_hash, gas_used, block_number, status
    """
    contract = get_contract("loanApplication")
    loan_id_bytes = _to_bytes32(loan_id)
    product_id_bytes = _to_bytes32(product_id)

    result = send_transaction(
        contract,
        "createApplication",
        loan_id_bytes,
        product_id_bytes,
        int(amount),
        int(term_months),
        int(interest_rate_bps),
    )

    logger.info(
        "createApplication on-chain: loan=%s tx=%s", loan_id, result["tx_hash"][:18]
    )
    return result


def submit_application_onchain(
    loan_id, eligibility_score, risk_category, ai_recommendation_hash
):
    """
    Submit a loan application on-chain (transitions Draft → Submitted).

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)
        eligibility_score: AI eligibility score (0-100)
        risk_category: Risk level (0=Low, 1=Medium, 2=High)
        ai_recommendation_hash: Hash of AI recommendation text (string, hashed to bytes32)

    Returns:
        dict with tx_hash, gas_used, block_number, status
    """
    contract = get_contract("loanApplication")
    loan_id_bytes = _to_bytes32(loan_id)
    ai_hash_bytes = _to_bytes32(ai_recommendation_hash)

    result = send_transaction(
        contract,
        "submitApplication",
        loan_id_bytes,
        int(eligibility_score),
        int(risk_category),
        ai_hash_bytes,
    )

    logger.info(
        "submitApplication on-chain: loan=%s tx=%s", loan_id, result["tx_hash"][:18]
    )
    return result


def get_application_onchain(loan_id):
    """
    Read application data from chain (view call, no gas).

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)

    Returns:
        Tuple of application fields as returned by the contract
    """
    contract = get_contract("loanApplication")
    loan_id_bytes = _to_bytes32(loan_id)
    return call_view(contract, "getApplication", loan_id_bytes)
