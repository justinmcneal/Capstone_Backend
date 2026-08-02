"""
Loan-related background tasks.
"""

import logging
import uuid
from datetime import timedelta

from celery import shared_task
from django.conf import settings

from loans.utils.time import utcnow

logger = logging.getLogger(__name__)


class WalletReceiptPending(Exception):
    """The transfer was broadcast but does not have a receipt yet."""


@shared_task
def check_overdue_installments_task():
    """Mark overdue installments and sync them to the blockchain."""
    db = getattr(settings, "MONGODB", None)
    if db is None:
        logger.warning("Overdue check skipped: MONGODB not configured")
        return {"overdue_marked": 0}

    from loans.blockchain.sync import sync_overdue
    from loans.models import RepaymentSchedule

    now = utcnow()
    updated_count = 0

    for doc in db["repayment_schedules"].find({}):
        schedule = RepaymentSchedule.from_dict(doc)
        if not schedule:
            continue

        overdue_installments = schedule.mark_overdue_installments(as_of=now)
        for installment_number in overdue_installments:
            try:
                sync_overdue(schedule.loan_id, installment_number)
            except Exception as exc:
                logger.warning(
                    "Blockchain sync skipped for overdue loan=%s installment=%s: %s",
                    schedule.loan_id,
                    installment_number,
                    exc,
                )

        updated_count += len(overdue_installments)

    if updated_count:
        logger.info("Marked %s overdue installments", updated_count)

    return {"overdue_marked": updated_count}


def _wallet_receipt(w3, tx_hash):
    """Return (state, receipt) without treating node failures as not-found."""
    from web3.exceptions import TransactionNotFound

    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        return ("confirmed" if receipt.get("status") == 1 else "reverted"), receipt
    except TransactionNotFound:
        try:
            w3.eth.get_transaction(tx_hash)
            return "pending", None
        except TransactionNotFound:
            return "missing", None


def _complete_wallet_disbursement(application, owner):
    """Execute or resume one claimed wallet disbursement."""
    from bson import ObjectId
    from loans.blockchain.client import (
        get_web3,
        send_eth_transfer,
        send_prepared_eth_transfer,
    )
    from loans.blockchain.exceptions import BlockchainTransactionFailed
    from loans.blockchain.services.eth_price_service import php_to_eth
    from loans.models import LoanApplication, LoanProduct, RepaymentSchedule
    from profiles.models.profile_models import CustomerProfile

    w3 = get_web3()
    result = None
    if application.eth_disbursement_tx_hash:
        chain_state, receipt = _wallet_receipt(
            w3, application.eth_disbursement_tx_hash
        )
        LoanApplication.update_eth_disbursement(
            ObjectId(application.id),
            last_checked_at=utcnow(),
            tx_status=chain_state,
        )
        if chain_state == "reverted":
            raise BlockchainTransactionFailed(
                "Wallet disbursement transaction reverted",
                tx_hash=application.eth_disbursement_tx_hash,
                receipt=receipt,
            )
        if chain_state == "confirmed":
            result = {
                "tx_hash": application.eth_disbursement_tx_hash,
                "gas_used": receipt.get("gasUsed", 0),
                "gas_price": receipt.get("effectiveGasPrice", 0),
                "block_number": receipt.get("blockNumber"),
                "status": receipt.get("status"),
                "amount_wei": int(application.eth_disbursement_amount_wei),
            }
        elif chain_state == "pending":
            raise WalletReceiptPending(
                f"Wallet transaction {application.eth_disbursement_tx_hash} is pending"
            )
        elif application.eth_disbursement_raw_transaction:
            LoanApplication.record_eth_rebroadcast(application.id)
            result = send_prepared_eth_transfer(
                application.eth_disbursement_raw_transaction,
                application.eth_disbursement_tx_hash,
                application.eth_disbursement_recipient,
                int(application.eth_disbursement_amount_wei),
                on_broadcast=lambda tx_hash: LoanApplication.update_eth_disbursement(
                    ObjectId(application.id),
                    tx_hash=tx_hash,
                    broadcast_at=utcnow(),
                    tx_status="broadcast",
                ),
            )
        else:
            LoanApplication.update_eth_disbursement(
                ObjectId(application.id), tx_status="dropped"
            )
            raise WalletReceiptPending(
                "Wallet transaction is missing and its prepared payload is unavailable"
            )
    else:
        profile = CustomerProfile.find_by_customer(application.customer_id)
        recipient = application.eth_disbursement_recipient or (
            profile.wallet_address if profile else None
        )
        if not recipient:
            raise ValueError("Customer has no wallet address for wallet disbursement")
        if application.eth_disbursement_amount_wei:
            amount_wei = int(application.eth_disbursement_amount_wei)
        else:
            php_amount = float(
                application.disbursed_amount
                or application.approved_amount
                or application.requested_amount
            )
            conversion = php_to_eth(php_amount)
            amount_wei = int(w3.to_wei(conversion["eth_amount"], "ether"))
            LoanApplication.update_eth_disbursement(
                ObjectId(application.id),
                amount=str(conversion["eth_amount"]),
                amount_wei=str(amount_wei),
                rate=conversion["rate"],
                rate_source=conversion["source"],
                recipient=recipient,
            )

        def persist_prepared(tx_hash, nonce, raw_transaction):
            LoanApplication.update_eth_disbursement(
                ObjectId(application.id),
                tx_hash=tx_hash,
                nonce=nonce,
                raw_transaction=raw_transaction,
                prepared_at=utcnow(),
                tx_status="prepared",
                recipient=recipient,
            )

        def persist_broadcast(tx_hash, nonce):
            LoanApplication.update_eth_disbursement(
                ObjectId(application.id),
                tx_hash=tx_hash,
                nonce=nonce,
                broadcast_at=utcnow(),
                tx_status="broadcast",
            )

        result = send_eth_transfer(
            recipient,
            amount_wei,
            on_broadcast=persist_broadcast,
            on_prepared=persist_prepared,
        )

    LoanApplication.update_eth_disbursement(
        ObjectId(application.id),
        tx_hash=result["tx_hash"],
        block_number=result.get("block_number"),
        last_checked_at=utcnow(),
        tx_status="confirmed",
    )
    LoanApplication.clear_eth_disbursement_fields(
        application.id, "raw_transaction"
    )

    product = LoanProduct.find_by_id(application.product_id)
    if not product:
        raise ValueError("Loan product not found; repayment schedule cannot be created")
    schedule = RepaymentSchedule.find_by_loan(application.id)
    if not schedule:
        schedule = RepaymentSchedule.generate_for_loan(application, product)

    refreshed = LoanApplication.find_by_id(application.id)
    completed, replayed = refreshed.complete_disbursement(
        refreshed.disbursement_idempotency_key
    )
    LoanApplication.release_wallet_disbursement(completed.id, owner)

    if not replayed and getattr(settings, "BLOCKCHAIN_ENABLED", False):
        from loans.blockchain.sync import sync_disbursement

        sync_disbursement(completed.id, include_schedule=True)
    return {
        "loan_id": completed.id,
        "status": completed.disbursement_status,
        "tx_hash": result["tx_hash"],
        "replayed": replayed,
    }


@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=8,
    default_retry_delay=15,
    retry_backoff=True,
    name="loans.execute_wallet_disbursement_task",
)
def execute_wallet_disbursement_task(self, application_id):
    """Durably execute an idempotent wallet-to-wallet loan disbursement."""
    from loans.blockchain.exceptions import BlockchainTransactionFailed
    from loans.models import LoanApplication

    application = LoanApplication.find_by_id(application_id)
    if not application:
        return {"skipped": True, "reason": "application not found"}
    if application.disbursement_status == "executed":
        return {"loan_id": application.id, "status": "executed", "replayed": True}
    if (
        application.disbursement_status != "pending"
        or application.disbursement_method != "wallet"
    ):
        return {"skipped": True, "reason": "wallet disbursement is not pending"}

    owner = f"celery:{self.request.id or uuid.uuid4().hex}"
    now = utcnow()
    claimed = LoanApplication.claim_wallet_disbursement(
        application.id,
        owner,
        now + timedelta(minutes=5),
        now,
    )
    if not claimed:
        raise self.retry(exc=RuntimeError("Wallet disbursement is claimed by another worker"))

    try:
        return _complete_wallet_disbursement(claimed, owner)
    except WalletReceiptPending as exc:
        LoanApplication.release_wallet_disbursement(application.id, owner)
        raise self.retry(exc=exc, countdown=20)
    except BlockchainTransactionFailed as exc:
        LoanApplication.update_eth_disbursement(
            __import__("bson").ObjectId(application.id), tx_status="reverted"
        )
        claimed.fail_disbursement(claimed.disbursement_idempotency_key, exc)
        LoanApplication.release_wallet_disbursement(application.id, owner)
        raise
    except Exception as exc:
        LoanApplication.release_wallet_disbursement(application.id, owner)
        if self.request.retries >= self.max_retries:
            # Never claim failure merely because a broadcast receipt is uncertain.
            refreshed = LoanApplication.find_by_id(application.id)
            if not refreshed.eth_disbursement_tx_hash:
                refreshed.fail_disbursement(
                    refreshed.disbursement_idempotency_key, exc
                )
            raise
        raise self.retry(exc=exc)


@shared_task(name="loans.reconcile_wallet_disbursements_task")
def reconcile_wallet_disbursements_task():
    """Re-enqueue pending wallet transfers left behind by worker/broker failures."""
    db = getattr(settings, "MONGODB", None)
    if db is None:
        return {"enqueued": 0}

    enqueued = 0
    cursor = db["loan_applications"].find(
        {
            "status": "approved",
            "disbursement_status": "pending",
            "disbursement_method": "wallet",
        },
        {"_id": 1},
    )
    for doc in cursor:
        execute_wallet_disbursement_task.delay(str(doc["_id"]))
        enqueued += 1
    return {"enqueued": enqueued}
