"""
Shared blockchain sync helpers used by both thread-based sync.py
and Celery-based tasks.py. Prevents drift between the two implementations.
"""

import logging

from django.conf import settings

from loans.blockchain.models import BlockchainTransaction

logger = logging.getLogger("blockchain")


def _is_enabled():
    """Check if blockchain sync is enabled."""
    return getattr(settings, "BLOCKCHAIN_ENABLED", False)


def _monthly_rate_to_annual_bps(monthly_rate):
    """Convert monthly decimal rate (e.g. 0.015) to annual basis points (e.g. 1800)."""
    return int(round(monthly_rate * 12 * 10_000))


def _risk_category_to_int(risk_str):
    """Convert Django risk category string to Solidity enum int."""
    mapping = {"low": 0, "medium": 1, "high": 2}
    if risk_str is None:
        return 0
    return mapping.get(str(risk_str).lower(), 0)


def _update_application_tx(loan_id, action, tx_hash):
    """Store a tx_hash in the application's blockchain_tx_hashes dict."""
    try:
        from loans.models.application import LoanApplication
        LoanApplication.update_blockchain_tx_hash(
            __import__("bson").ObjectId(loan_id), action, tx_hash
        )
    except Exception as exc:
        logger.warning("Failed to store tx_hash for %s.%s: %s", loan_id, action, exc)


def _create_tx_record(loan_id, action, contract_name, method, details=None):
    """Create a pending BlockchainTransaction record."""
    return BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action=action,
        contract_name=contract_name,
        method=method,
        details=details or {},
    )


def _finalize_tx(tx_record, tx_hash, gas_used, block_number, gas_price=0,
                 loan_id=None, action=None):
    """Mark transaction confirmed and optionally update application tx hash."""
    tx_record.mark_confirmed(
        tx_hash=tx_hash,
        gas_used=gas_used,
        block_number=block_number,
        gas_price=gas_price,
    )
    if loan_id and action:
        _update_application_tx(loan_id, action, tx_hash)


def _fail_tx(tx_record, exc, loan_id=None):
    """Mark transaction failed and log error."""
    logger.error(
        "sync FAILED: loan=%s error=%s", loan_id or "unknown", exc
    )
    tx_record.mark_failed(str(exc))


def sync_schedule(loan_id):
    """
    Sync a repayment schedule to the blockchain.

    Shared implementation used by both sync.py and tasks.py.
    """
    if not _is_enabled():
        return

    from loans.blockchain.services.repayment_service import create_schedule_onchain
    from loans.models.application import LoanApplication
    from loans.models.repayment import RepaymentSchedule

    tx_record = _create_tx_record(
        loan_id=loan_id,
        action="schedule",
        contract_name="RepaymentSchedule",
        method="createSchedule",
    )

    try:
        app = LoanApplication.find_by_id(loan_id)
        if not app:
            raise ValueError(f"LoanApplication {loan_id} not found")

        schedule = RepaymentSchedule.find_one({"loan_id": loan_id})
        if not schedule:
            raise ValueError(f"RepaymentSchedule for loan {loan_id} not found")

        interest_bps = _monthly_rate_to_annual_bps(schedule.interest_rate)

        borrower_addr = settings.BLOCKCHAIN_CONTRACT_ADDRESSES.get("accessControl", "")
        if not borrower_addr:
            from loans.blockchain.client import get_account
            borrower_addr = get_account().address

        start_timestamp = (
            int(schedule.start_date.timestamp())
            if hasattr(schedule.start_date, "timestamp")
            else int(schedule.start_date)
        )

        result = create_schedule_onchain(
            loan_id=loan_id,
            borrower_address=borrower_addr,
            principal=int(schedule.principal),
            interest_rate_bps=interest_bps,
            term_months=int(schedule.term_months),
            start_date=start_timestamp,
        )

        _finalize_tx(
            tx_record,
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
            gas_price=result.get("gas_price", 0),
        )

        RepaymentSchedule.update_blockchain_schedule_tx(
            schedule._id, result["tx_hash"]
        )

        logger.info(
            "sync_schedule OK: loan=%s tx=%s", loan_id, result["tx_hash"][:18]
        )
        return {"tx_hash": result["tx_hash"], "status": "confirmed"}

    except Exception as exc:
        _fail_tx(tx_record, exc, loan_id=loan_id)
        raise


def sync_payment(loan_id, payment_id):
    """
    Sync a payment recording to the blockchain.

    Shared implementation used by both sync.py and tasks.py.
    """
    if not _is_enabled():
        return

    from bson import ObjectId
    from loans.blockchain.services.repayment_service import record_payment_onchain
    from loans.models.payment import LoanPayment

    tx_record = _create_tx_record(
        loan_id=loan_id,
        action="payment",
        contract_name="PaymentRecording",
        method="recordPayment",
        details={"payment_id": payment_id},
    )

    payment_obj = None
    try:
        payment = LoanPayment.find_one({"_id": ObjectId(str(payment_id))})
        if not payment:
            raise ValueError(f"LoanPayment {payment_id} not found")
        payment_obj = payment

        ref_str = payment.reference or f"PAY_{payment_id}_{loan_id}"

        result = record_payment_onchain(
            loan_id=loan_id,
            installment_number=int(payment.installment_number),
            amount=int(payment.amount),
            payment_method=payment.payment_method or "other",
            reference_hash=ref_str,
        )

        _finalize_tx(
            tx_record,
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
        )

        LoanPayment.set_sync_result(payment._id, result["tx_hash"])

        logger.info(
            "sync_payment OK: loan=%s payment=%s tx=%s",
            loan_id,
            payment_id,
            result["tx_hash"][:18],
        )
        return {"tx_hash": result["tx_hash"], "status": "confirmed"}

    except Exception as exc:
        _fail_tx(tx_record, exc, loan_id=loan_id)
        if payment_obj is not None:
            LoanPayment.set_sync_failed(payment_obj._id, exc)
        raise
