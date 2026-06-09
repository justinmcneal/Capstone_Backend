"""
Service for RepaymentSchedule + PaymentRecording contract interactions.

Handles: createSchedule, recordPayment, getSchedule, getRemainingBalance, markOverdue
"""

import logging
import time

from web3 import Web3

from loans.blockchain.client import get_contract, send_transaction, call_view

logger = logging.getLogger("blockchain")

# PaymentRecording.PaymentMethod enum mapping
PAYMENT_METHOD_MAP = {
    "cash": 0,
    "bank_transfer": 1,
    "gcash": 2,
    "check": 3,
    "wallet": 4,
}


def _to_bytes32(value):
    """Convert a string to bytes32 (keccak256 hash)."""
    if isinstance(value, bytes) and len(value) == 32:
        return value
    return Web3.keccak(text=str(value))


def create_schedule_onchain(
    loan_id,
    borrower_address,
    principal,
    interest_rate_bps,
    term_months,
    start_date=None,
):
    """
    Create a repayment schedule on-chain.

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)
        borrower_address: Borrower's Ethereum address
        principal: Loan principal in smallest unit (int)
        interest_rate_bps: Interest rate in basis points (int, e.g. 1200 = 12%)
        term_months: Number of monthly installments (int)
        start_date: Unix timestamp for first installment calculation (default: now)

    Returns:
        dict with tx_hash, gas_used, block_number, status
    """
    contract = get_contract("repaymentSchedule")
    loan_id_bytes = _to_bytes32(loan_id)
    borrower_addr = Web3.to_checksum_address(borrower_address)

    if start_date is None:
        start_date = int(time.time())

    result = send_transaction(
        contract,
        "createSchedule",
        loan_id_bytes,
        borrower_addr,
        int(principal),
        int(interest_rate_bps),
        int(term_months),
        int(start_date),
    )

    logger.info(
        "createSchedule on-chain: loan=%s term=%d tx=%s",
        loan_id,
        term_months,
        result["tx_hash"][:18],
    )
    return result


def record_payment_onchain(
    loan_id, installment_number, amount, payment_method, reference_hash
):
    """
    Record a payment on-chain.

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)
        installment_number: 1-based installment number (int)
        amount: Payment amount in smallest unit (int)
        payment_method: Payment method string ('cash', 'gcash', 'bank_transfer', 'check', 'wallet')
        reference_hash: Unique payment reference (string, hashed to bytes32)

    Returns:
        dict with tx_hash, gas_used, block_number, status
    """
    contract = get_contract("paymentRecording")
    loan_id_bytes = _to_bytes32(loan_id)
    method_enum = PAYMENT_METHOD_MAP.get(payment_method, 4)  # Default to Other
    ref_bytes = _to_bytes32(reference_hash)

    result = send_transaction(
        contract,
        "recordPayment",
        loan_id_bytes,
        int(installment_number),
        int(amount),
        method_enum,
        ref_bytes,
    )

    logger.info(
        "recordPayment on-chain: loan=%s installment=%d amount=%d tx=%s",
        loan_id,
        installment_number,
        amount,
        result["tx_hash"][:18],
    )
    return result


def mark_overdue_onchain(loan_id, installment_number):
    """
    Mark an installment as overdue on-chain.

    Args:
        loan_id: Loan identifier (string, hashed to bytes32)
        installment_number: 1-based installment number (int)

    Returns:
        dict with tx_hash, gas_used, block_number, status
    """
    contract = get_contract("paymentRecording")
    loan_id_bytes = _to_bytes32(loan_id)

    result = send_transaction(
        contract,
        "markOverdue",
        loan_id_bytes,
        int(installment_number),
    )

    logger.info(
        "markOverdue on-chain: loan=%s installment=%d tx=%s",
        loan_id,
        installment_number,
        result["tx_hash"][:18],
    )
    return result


def get_schedule_onchain(loan_id):
    """
    Read schedule data from chain (view call, no gas).

    Returns:
        Tuple of schedule fields as returned by the contract
    """
    contract = get_contract("repaymentSchedule")
    loan_id_bytes = _to_bytes32(loan_id)
    return call_view(contract, "getSchedule", loan_id_bytes)


def get_installment_onchain(loan_id, installment_number):
    """
    Read a single installment from chain (view call, no gas).

    Returns:
        Tuple of installment fields as returned by the contract
    """
    contract = get_contract("repaymentSchedule")
    loan_id_bytes = _to_bytes32(loan_id)
    return call_view(contract, "getInstallment", loan_id_bytes, int(installment_number))


def get_all_installments_onchain(loan_id):
    """
    Read all installments for a loan from chain (view call, no gas).

    Returns:
        List of installment tuples as returned by the contract
    """
    contract = get_contract("repaymentSchedule")
    loan_id_bytes = _to_bytes32(loan_id)
    return call_view(contract, "getAllInstallments", loan_id_bytes)


def get_remaining_balance_onchain(loan_id):
    """
    Read remaining balance from chain (view call, no gas).

    Returns:
        Remaining balance (int)
    """
    contract = get_contract("repaymentSchedule")
    loan_id_bytes = _to_bytes32(loan_id)
    return call_view(contract, "getRemainingBalance", loan_id_bytes)
