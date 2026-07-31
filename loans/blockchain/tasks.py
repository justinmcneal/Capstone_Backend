"""
Celery tasks for asynchronous blockchain synchronization.

Each task is triggered after a successful Django operation and sends the
corresponding transaction to the blockchain. On success, the tx_hash is
stored back in the Django model and in the BlockchainTransaction log.

Shared implementations are imported from sync_common.py to prevent drift
between the thread-based and Celery-based sync paths.

All tasks are gated by settings.BLOCKCHAIN_ENABLED — they no-op when disabled.
"""

import logging

from celery import shared_task
from django.conf import settings

from loans.blockchain.sync_common import (
    _finalize_tx,
    _is_enabled,
    _monthly_rate_to_annual_bps,
    _risk_category_to_int,
    _update_application_tx,
    sync_payment as _sync_payment_common,
    sync_schedule as _sync_schedule_common,
)

logger = logging.getLogger("blockchain")


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
    from loans.blockchain.client import get_contract, send_transaction
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
            app.ai_recommendation.get("interest_rate", 0)
            if isinstance(app.ai_recommendation, dict)
            else 0
        )

        # Step 1: Create application on-chain
        create_result = create_application_onchain(
            loan_id=loan_id,
            borrower_addr=settings.BLOCKCHAIN_CONTRACT_ADDRESSES.get(
                "accessControl", ""
            ),
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
        # Prepare mark_confirmed args; include gas_price only if present in result
        mc_kwargs = {
            "tx_hash": submit_result["tx_hash"],
            "gas_used": create_result["gas_used"] + submit_result["gas_used"],
            "block_number": submit_result["block_number"],
        }
        if "gas_price" in submit_result:
            mc_kwargs["gas_price"] = submit_result["gas_price"]
        tx_record.mark_confirmed(**mc_kwargs)

        _update_application_tx(loan_id, "submit", submit_result["tx_hash"])

        logger.info(
            "sync_application_to_chain OK: loan=%s tx=%s",
            loan_id,
            submit_result["tx_hash"][:18],
        )
        return {"tx_hash": submit_result["tx_hash"], "status": "confirmed"}

    except Exception as exc:
        logger.error("sync_application_to_chain FAILED: loan=%s error=%s", loan_id, exc)
        if self.request.retries >= self.max_retries:
            tx_record.mark_failed(str(exc))
            logger.error(
                "sync_application_to_chain FAILED permanently: loan=%s error=%s",
                loan_id,
                exc,
            )
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

        mc_kwargs = {
            "tx_hash": result["tx_hash"],
            "gas_used": result["gas_used"],
            "block_number": result["block_number"],
        }
        if "gas_price" in result:
            mc_kwargs["gas_price"] = result["gas_price"]
        tx_record.mark_confirmed(**mc_kwargs)

        _update_application_tx(loan_id, "approve", result["tx_hash"])

        logger.info(
            "sync_approval_to_chain OK: loan=%s tx=%s",
            loan_id,
            result["tx_hash"][:18],
        )
        return {"tx_hash": result["tx_hash"], "status": "confirmed"}

    except Exception as exc:
        logger.error("sync_approval_to_chain FAILED: loan=%s error=%s", loan_id, exc)
        if self.request.retries >= self.max_retries:
            tx_record.mark_failed(str(exc))
            logger.error(
                "sync_approval_to_chain FAILED permanently: loan=%s error=%s",
                loan_id,
                exc,
            )
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
        method_str = (
            app.disbursement_method or app.preferred_disbursement_method or "other"
        )
        set_method_onchain(loan_id=loan_id, method=method_str)

        # Step 2: Initiate + complete disbursement
        amount = int(
            app.disbursed_amount or app.approved_amount or app.requested_amount
        )
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

        logger.info(
            "sync_disbursement_to_chain OK: loan=%s tx=%s",
            loan_id,
            complete_tx["tx_hash"][:18],
        )
        return {"tx_hash": complete_tx["tx_hash"], "status": "confirmed"}

    except Exception as exc:
        logger.error(
            "sync_disbursement_to_chain FAILED: loan=%s error=%s", loan_id, exc
        )
        if self.request.retries >= self.max_retries:
            tx_record.mark_failed(str(exc))
            logger.error(
                "sync_disbursement_to_chain FAILED permanently: loan=%s error=%s",
                loan_id,
                exc,
            )
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
    Delegates to the shared implementation in sync_common.py.
    """
    if not _is_enabled():
        return {"skipped": True, "reason": "blockchain disabled"}

    try:
        result = _sync_schedule_common(loan_id)
        return result
    except Exception as exc:
        logger.error("sync_schedule_to_chain FAILED: loan=%s error=%s", loan_id, exc)
        if self.request.retries >= self.max_retries:
            logger.error(
                "sync_schedule_to_chain FAILED permanently: loan=%s error=%s",
                loan_id,
                exc,
            )
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
    Delegates to the shared implementation in sync_common.py.
    """
    if not _is_enabled():
        return {"skipped": True, "reason": "blockchain disabled"}

    try:
        result = _sync_payment_common(loan_id, payment_id)
        return result
    except Exception as exc:
        logger.error(
            "sync_payment_to_chain FAILED: loan=%s payment=%s error=%s",
            loan_id,
            payment_id,
            exc,
        )
        if self.request.retries >= self.max_retries:
            logger.error(
                "sync_payment_to_chain FAILED permanently: loan=%s payment=%s error=%s",
                loan_id,
                payment_id,
                exc,
            )
        raise self.retry(exc=exc)


def _update_application_tx(loan_id, action, tx_hash):
    """Helper to store a tx_hash in the application's blockchain_tx_hashes dict."""
    try:
        db = getattr(settings, "MONGODB", None)
        if db is None:
            return
        db["loan_applications"].update_one(
            {"_id": __import__("bson").ObjectId(loan_id)},
            {"$set": {f"blockchain_tx_hashes.{action}": tx_hash}},
        )
    except Exception as exc:
        logger.warning("Failed to store tx_hash for %s.%s: %s", loan_id, action, exc)
