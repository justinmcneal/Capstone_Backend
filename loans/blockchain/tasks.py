"""
Celery tasks for asynchronous blockchain synchronization.

Each task is triggered after a successful Django operation and sends the
corresponding transaction to the blockchain. On success, the tx_hash is
stored back in the Django model and in the BlockchainTransaction log.

All tasks are gated by settings.BLOCKCHAIN_ENABLED — they no-op when disabled.
"""

import logging
import math

from celery import shared_task
from django.conf import settings

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


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    name="blockchain.sync_application_to_chain",
)
def sync_application_to_chain(self, loan_id):
    """
    Sync a submitted loan application to the blockchain.

    Called after LoanApplyView.post() succeeds.
    Performs: createApplication + submitApplication on LoanApplication contract.
    """
    if not _is_enabled():
        return {"skipped": True, "reason": "blockchain disabled"}

    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.application_service import (
        create_application_onchain,
        submit_application_onchain,
    )
    from loans.models.application import LoanApplication

    tx_record = BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action="submit",
        contract_name="LoanApplication",
        method="createApplication+submitApplication",
    )

    try:
        app = LoanApplication.find_by_id(loan_id)
        if not app:
            raise ValueError(f"LoanApplication {loan_id} not found")

        interest_bps = _monthly_rate_to_annual_bps(
            app.ai_recommendation.get("interest_rate", 0) if isinstance(app.ai_recommendation, dict) else 0
        )

        # Step 1: Create application on-chain
        create_result = create_application_onchain(
            loan_id=loan_id,
            borrower_addr=settings.BLOCKCHAIN_CONTRACT_ADDRESSES.get("accessControl", ""),
            product_id=str(app.product_id),
            amount=int(app.requested_amount),
            term_months=int(app.term_months),
            interest_rate_bps=interest_bps,
        )

        # Step 2: Submit application on-chain
        eligibility_score = int(app.eligibility_score or 0)
        risk_category = _risk_category_to_int(app.risk_category)
        ai_hash = str(app.ai_recommendation) if app.ai_recommendation else "none"

        submit_result = submit_application_onchain(
            loan_id=loan_id,
            eligibility_score=eligibility_score,
            risk_category=risk_category,
            ai_recommendation_hash=ai_hash,
        )

        # Record success
        tx_record.mark_confirmed(
            tx_hash=submit_result["tx_hash"],
            gas_used=create_result["gas_used"] + submit_result["gas_used"],
            block_number=submit_result["block_number"],
            gas_price=submit_result.get("gas_price", 0),
        )

        # Update application with tx hash
        _update_application_tx(loan_id, "submit", submit_result["tx_hash"])

        logger.info("sync_application_to_chain OK: loan=%s tx=%s", loan_id, submit_result["tx_hash"][:18])
        return {"tx_hash": submit_result["tx_hash"], "status": "confirmed"}

    except Exception as exc:
        logger.error("sync_application_to_chain FAILED: loan=%s error=%s", loan_id, exc)
        if self.request.retries >= self.max_retries:
            tx_record.mark_failed(str(exc))
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    name="blockchain.sync_approval_to_chain",
)
def sync_approval_to_chain(self, loan_id):
    """
    Sync a loan approval to the blockchain.

    Called after OfficerReviewView.put() approves.
    Performs: approveLoan on LoanApproval contract.
    """
    if not _is_enabled():
        return {"skipped": True, "reason": "blockchain disabled"}

    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.approval_service import approve_loan_onchain
    from loans.models.application import LoanApplication

    tx_record = BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action="approve",
        contract_name="LoanApproval",
        method="approveLoan",
    )

    try:
        app = LoanApplication.find_by_id(loan_id)
        if not app:
            raise ValueError(f"LoanApplication {loan_id} not found")

        result = approve_loan_onchain(
            loan_id=loan_id,
            approved_amount=int(app.approved_amount or app.requested_amount),
            notes_hash=str(app.officer_notes or "approved"),
        )

        tx_record.mark_confirmed(
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
            gas_price=result.get("gas_price", 0),
        )

        _update_application_tx(loan_id, "approve", result["tx_hash"])

        logger.info("sync_approval_to_chain OK: loan=%s tx=%s", loan_id, result["tx_hash"][:18])
        return {"tx_hash": result["tx_hash"], "status": "confirmed"}

    except Exception as exc:
        logger.error("sync_approval_to_chain FAILED: loan=%s error=%s", loan_id, exc)
        if self.request.retries >= self.max_retries:
            tx_record.mark_failed(str(exc))
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    name="blockchain.sync_disbursement_to_chain",
)
def sync_disbursement_to_chain(self, loan_id):
    """
    Sync a loan disbursement to the blockchain.

    Called after DisburseView.post() succeeds.
    Performs: setPreferredMethod + initiateDisbursement + completeDisbursement.
    """
    if not _is_enabled():
        return {"skipped": True, "reason": "blockchain disabled"}

    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.disbursement_service import (
        complete_disbursement_onchain,
        set_method_onchain,
    )
    from loans.models.application import LoanApplication

    tx_record = BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action="disburse",
        contract_name="DisbursementExecution",
        method="completeDisbursement",
    )

    try:
        app = LoanApplication.find_by_id(loan_id)
        if not app:
            raise ValueError(f"LoanApplication {loan_id} not found")

        # Step 1: Set disbursement method
        method_str = app.disbursement_method or app.preferred_disbursement_method or "other"
        set_method_onchain(loan_id=loan_id, method=method_str)

        # Step 2: Initiate + complete disbursement
        amount = int(app.disbursed_amount or app.approved_amount or app.requested_amount)
        ref_str = str(app.disbursement_reference or f"DISB_{loan_id}")

        result = complete_disbursement_onchain(
            loan_id=loan_id,
            amount=amount,
            reference_hash=ref_str,
        )

        complete_tx = result["complete_tx"]
        tx_record.mark_confirmed(
            tx_hash=complete_tx["tx_hash"],
            gas_used=complete_tx["gas_used"],
            block_number=complete_tx["block_number"],
            gas_price=complete_tx.get("gas_price", 0),
        )

        _update_application_tx(loan_id, "disburse", complete_tx["tx_hash"])

        logger.info("sync_disbursement_to_chain OK: loan=%s tx=%s", loan_id, complete_tx["tx_hash"][:18])
        return {"tx_hash": complete_tx["tx_hash"], "status": "confirmed"}

    except Exception as exc:
        logger.error("sync_disbursement_to_chain FAILED: loan=%s error=%s", loan_id, exc)
        if self.request.retries >= self.max_retries:
            tx_record.mark_failed(str(exc))
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    name="blockchain.sync_schedule_to_chain",
)
def sync_schedule_to_chain(self, loan_id):
    """
    Sync a repayment schedule to the blockchain.

    Called after RepaymentSchedule.generate_for_loan() succeeds.
    Performs: createSchedule on RepaymentSchedule contract.
    """
    if not _is_enabled():
        return {"skipped": True, "reason": "blockchain disabled"}

    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.repayment_service import create_schedule_onchain
    from loans.models.application import LoanApplication
    from loans.models.repayment import RepaymentSchedule

    tx_record = BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action="schedule",
        contract_name="RepaymentSchedule",
        method="createSchedule",
    )

    try:
        app = LoanApplication.find_by_id(loan_id)
        if not app:
            raise ValueError(f"LoanApplication {loan_id} not found")

        # Find the schedule
        schedule_doc = settings.MONGODB["repayment_schedules"].find_one({"loan_id": loan_id})
        if not schedule_doc:
            raise ValueError(f"RepaymentSchedule for loan {loan_id} not found")

        schedule = RepaymentSchedule.from_dict(schedule_doc)

        # Convert monthly rate to annual BPS for the smart contract
        interest_bps = _monthly_rate_to_annual_bps(schedule.interest_rate)

        # Borrower address — use the deployer/admin as proxy since we don't have real wallet addresses
        borrower_addr = settings.BLOCKCHAIN_CONTRACT_ADDRESSES.get("accessControl", "")
        if not borrower_addr:
            from loans.blockchain.client import get_account
            borrower_addr = get_account().address

        start_timestamp = int(schedule.start_date.timestamp()) if hasattr(schedule.start_date, 'timestamp') else int(schedule.start_date)

        result = create_schedule_onchain(
            loan_id=loan_id,
            borrower_address=borrower_addr,
            principal=int(schedule.principal),
            interest_rate_bps=interest_bps,
            term_months=int(schedule.term_months),
            start_date=start_timestamp,
        )

        tx_record.mark_confirmed(
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
            gas_price=result.get("gas_price", 0),
        )

        # Update schedule with tx hash
        settings.MONGODB["repayment_schedules"].update_one(
            {"_id": schedule_doc["_id"]},
            {"$set": {"blockchain_schedule_tx": result["tx_hash"]}},
        )

        logger.info("sync_schedule_to_chain OK: loan=%s tx=%s", loan_id, result["tx_hash"][:18])
        return {"tx_hash": result["tx_hash"], "status": "confirmed"}

    except Exception as exc:
        logger.error("sync_schedule_to_chain FAILED: loan=%s error=%s", loan_id, exc)
        if self.request.retries >= self.max_retries:
            tx_record.mark_failed(str(exc))
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    name="blockchain.sync_payment_to_chain",
)
def sync_payment_to_chain(self, loan_id, payment_id):
    """
    Sync a payment recording to the blockchain.

    Called after RecordPaymentView.post() succeeds.
    Performs: recordPayment on PaymentRecording contract.
    """
    if not _is_enabled():
        return {"skipped": True, "reason": "blockchain disabled"}

    from bson import ObjectId

    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.repayment_service import record_payment_onchain
    from loans.models.payment import LoanPayment

    tx_record = BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action="payment",
        contract_name="PaymentRecording",
        method="recordPayment",
        details={"payment_id": payment_id},
    )

    try:
        payment_doc = settings.MONGODB["loan_payments"].find_one({"_id": ObjectId(payment_id)})
        if not payment_doc:
            raise ValueError(f"LoanPayment {payment_id} not found")

        payment = LoanPayment.from_dict(payment_doc)

        # Create a unique reference hash for the blockchain
        ref_str = payment.reference or f"PAY_{payment_id}_{loan_id}"

        result = record_payment_onchain(
            loan_id=loan_id,
            installment_number=int(payment.installment_number),
            amount=int(payment.amount),
            payment_method=payment.payment_method or "other",
            reference_hash=ref_str,
        )

        tx_record.mark_confirmed(
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
            gas_price=result.get("gas_price", 0),
        )

        # Update payment with tx hash
        settings.MONGODB["loan_payments"].update_one(
            {"_id": ObjectId(payment_id)},
            {"$set": {"blockchain_tx_hash": result["tx_hash"]}},
        )

        logger.info("sync_payment_to_chain OK: loan=%s payment=%s tx=%s",
                     loan_id, payment_id, result["tx_hash"][:18])
        return {"tx_hash": result["tx_hash"], "status": "confirmed"}

    except Exception as exc:
        logger.error("sync_payment_to_chain FAILED: loan=%s payment=%s error=%s",
                     loan_id, payment_id, exc)
        if self.request.retries >= self.max_retries:
            tx_record.mark_failed(str(exc))
        raise self.retry(exc=exc)


def _update_application_tx(loan_id, action, tx_hash):
    """Helper to store a tx_hash in the application's blockchain_tx_hashes dict."""
    try:
        db = getattr(settings, 'MONGODB', None)
        if db is None:
            return
        db["loan_applications"].update_one(
            {"_id": __import__("bson").ObjectId(loan_id)},
            {"$set": {f"blockchain_tx_hashes.{action}": tx_hash}},
        )
    except Exception as exc:
        logger.warning("Failed to store tx_hash for %s.%s: %s", loan_id, action, exc)
