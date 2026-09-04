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
    _is_enabled,
    _monthly_rate_to_annual_bps,
    _risk_category_to_int,
    _update_application_tx,
)
from loans.blockchain.sync_common import (
    sync_payment as _sync_payment_common,
)
from loans.blockchain.sync_common import (
    sync_schedule as _sync_schedule_common,
)

logger = logging.getLogger("blockchain")


def _confirmed_step_or_run(tx_record, step_name, callback):
    """Resume a saga from its last durably confirmed step."""
    existing = tx_record.confirmed_step_result(step_name)
    if isinstance(existing, dict):
        return existing
    result = callback()
    tx_record.mark_step_confirmed(step_name, result)
    return result


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    name="blockchain.sync_application_to_chain",
)
def sync_application_to_chain(self, loan_id, transition_id=None):
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
        details={"transition_id": transition_id} if transition_id else None,
    )
    if tx_record.status == BlockchainTransaction.STATUS_CONFIRMED:
        return {"tx_hash": tx_record.tx_hash, "status": "confirmed", "replayed": True}
    if tx_record.status == BlockchainTransaction.STATUS_FAILED:
        tx_record.reopen_for_reconciliation()

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
        create_result = _confirmed_step_or_run(
            tx_record,
            "create_application",
            lambda: create_application_onchain(
                loan_id=loan_id,
                borrower_addr=settings.BLOCKCHAIN_CONTRACT_ADDRESSES.get(
                    "accessControl", ""
                ),
                product_id=str(app.product_id),
                amount=int(app.requested_amount),
                term_months=int(app.term_months),
                interest_rate_bps=interest_bps,
            ),
        )

        # Step 2: Submit application on-chain
        eligibility_score = int(app.eligibility_score or 0)
        risk_category = _risk_category_to_int(app.risk_category)
        ai_hash = str(app.ai_recommendation) if app.ai_recommendation else "none"

        submit_result = _confirmed_step_or_run(
            tx_record,
            "submit_application",
            lambda: submit_application_onchain(
                loan_id=loan_id,
                eligibility_score=eligibility_score,
                risk_category=risk_category,
                ai_recommendation_hash=ai_hash,
            ),
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
def sync_approval_to_chain(self, loan_id, transition_id=None):
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
        details={"transition_id": transition_id} if transition_id else None,
    )
    if tx_record.status == BlockchainTransaction.STATUS_CONFIRMED:
        return {"tx_hash": tx_record.tx_hash, "status": "confirmed", "replayed": True}
    if tx_record.status == BlockchainTransaction.STATUS_FAILED:
        tx_record.reopen_for_reconciliation()

    try:
        app = LoanApplication.find_by_id(loan_id)
        if not app:
            raise ValueError(f"LoanApplication {loan_id} not found")

        result = _confirmed_step_or_run(
            tx_record,
            "approve_loan",
            lambda: approve_loan_onchain(
                loan_id=loan_id,
                approved_amount=int(app.approved_amount or app.requested_amount),
                notes_hash=str(app.officer_notes or "approved"),
            ),
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
        complete_existing_disbursement_onchain,
        initiate_disbursement_onchain,
        set_method_onchain,
    )
    from loans.models.application import LoanApplication

    tx_record = BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action="disburse",
        contract_name="DisbursementExecution",
        method="completeDisbursement",
    )
    if tx_record.status == BlockchainTransaction.STATUS_CONFIRMED:
        return {"tx_hash": tx_record.tx_hash, "status": "confirmed", "replayed": True}
    if tx_record.status == BlockchainTransaction.STATUS_FAILED:
        tx_record.reopen_for_reconciliation()

    try:
        app = LoanApplication.find_by_id(loan_id)
        if not app:
            raise ValueError(f"LoanApplication {loan_id} not found")

        # Step 1: Set disbursement method
        method_str = (
            app.disbursement_method or app.preferred_disbursement_method or "other"
        )
        _confirmed_step_or_run(
            tx_record,
            "set_method",
            lambda: set_method_onchain(loan_id=loan_id, method=method_str),
        )

        # Step 2: Initiate + complete disbursement
        amount = int(
            app.disbursed_amount or app.approved_amount or app.requested_amount
        )
        ref_str = str(app.disbursement_reference or f"DISB_{loan_id}")

        _confirmed_step_or_run(
            tx_record,
            "initiate_disbursement",
            lambda: initiate_disbursement_onchain(loan_id=loan_id, amount=amount),
        )
        complete_tx = _confirmed_step_or_run(
            tx_record,
            "complete_disbursement",
            lambda: complete_existing_disbursement_onchain(
                loan_id=loan_id,
                reference_hash=ref_str,
            ),
        )
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


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    name="blockchain.sync_rejection_to_chain",
)
def sync_rejection_to_chain(self, loan_id, transition_id=None):
    from loans.blockchain.sync import _sync_rejection_impl

    try:
        return _sync_rejection_impl(
            loan_id, raise_errors=True, transition_id=transition_id
        )
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    name="blockchain.sync_overdue_to_chain",
)
def sync_overdue_to_chain(self, loan_id, installment_number):
    from loans.blockchain.sync import _sync_overdue_impl

    try:
        return _sync_overdue_impl(loan_id, installment_number, raise_errors=True)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    name="blockchain.sync_penalty_to_chain",
)
def sync_penalty_to_chain(self, loan_id, installment_number, amount, action, reason=""):
    from loans.blockchain.sync import _sync_penalty_impl

    try:
        return _sync_penalty_impl(
            loan_id,
            installment_number,
            amount,
            action,
            reason,
            raise_errors=True,
        )
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    name="blockchain.sync_consent_to_chain",
)
def sync_consent_to_chain(
    self,
    user_id,
    user_type,
    data_consent,
    ai_consent,
    consent_version,
    consent_timestamp,
    previous_state=None,
):
    from loans.blockchain.sync import _sync_consent_impl

    try:
        return _sync_consent_impl(
            user_id,
            user_type,
            data_consent,
            ai_consent,
            consent_version,
            consent_timestamp,
            previous_state,
            raise_errors=True,
        )
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(name="blockchain.poll_audit_events")
def poll_audit_events():
    """Poll once; Celery Beat supplies durable scheduling and crash recovery."""
    if not _is_enabled():
        return {"skipped": True, "reason": "blockchain disabled"}
    from loans.blockchain.event_listener import AuditEventListener

    listener = AuditEventListener()
    listener._ensure_connection()
    return listener._poll_events()


@shared_task(name="blockchain.reconcile_domain_state")
def reconcile_blockchain_domain_state():
    """Derive missing durable sync jobs from authoritative MongoDB state."""
    if not _is_enabled():
        return {"skipped": True, "reason": "blockchain disabled"}
    db = getattr(settings, "MONGODB", None)
    if db is None:
        return {"enqueued": 0}

    limit = int(getattr(settings, "BLOCKCHAIN_RECONCILIATION_BATCH_SIZE", 250))
    enqueued = 0

    def enqueue(task, *args):
        nonlocal enqueued
        task.apply_async(args=list(args), retry=False)
        enqueued += 1

    applications = (
        db["loan_applications"]
        .find(
            {
                "status": {
                    "$in": [
                        "submitted",
                        "under_review",
                        "approved",
                        "rejected",
                        "disbursed",
                        "completed",
                        "written_off",
                    ]
                }
            },
            {"_id": 1, "status": 1, "blockchain_tx_hashes": 1},
        )
        .limit(limit)
    )
    for application in applications:
        loan_id = str(application["_id"])
        lifecycle_status = application.get("status")
        hashes = application.get("blockchain_tx_hashes") or {}
        if not hashes.get("submit"):
            enqueue(sync_application_to_chain, loan_id)
            continue
        if lifecycle_status in {
            "approved",
            "disbursed",
            "completed",
            "written_off",
        } and not hashes.get("approve"):
            enqueue(sync_approval_to_chain, loan_id)
            continue
        if lifecycle_status == "rejected" and not hashes.get("reject"):
            enqueue(sync_rejection_to_chain, loan_id)
            continue
        if lifecycle_status in {
            "disbursed",
            "completed",
            "written_off",
        } and not hashes.get("disburse"):
            enqueue(sync_disbursement_to_chain, loan_id)

    schedules = (
        db["repayment_schedules"]
        .find({"blockchain_schedule_tx": {"$in": [None, ""]}}, {"loan_id": 1})
        .limit(limit)
    )
    for schedule in schedules:
        loan_id = str(schedule["loan_id"])
        application = db["loan_applications"].find_one(
            {"_id": __import__("bson").ObjectId(loan_id)},
            {"blockchain_tx_hashes": 1},
        )
        if (application or {}).get("blockchain_tx_hashes", {}).get("disburse"):
            enqueue(sync_schedule_to_chain, loan_id)

    payments = (
        db["loan_payments"]
        .find(
            {
                "payment_status": "posted",
                "blockchain_tx_hash": {"$in": [None, ""]},
                "blockchain_sync_status": {"$ne": "not_applicable"},
            },
            {"_id": 1, "loan_id": 1},
        )
        .limit(limit)
    )
    for payment in payments:
        schedule = db["repayment_schedules"].find_one(
            {"loan_id": str(payment["loan_id"])}, {"blockchain_schedule_tx": 1}
        )
        if schedule and schedule.get("blockchain_schedule_tx"):
            enqueue(
                sync_payment_to_chain,
                str(payment["loan_id"]),
                str(payment["_id"]),
            )

    return {"enqueued": enqueued}
