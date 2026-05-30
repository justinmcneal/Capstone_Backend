"""
Synchronous blockchain sync — no Celery/Redis required.

Each function is called directly from Django views after a successful
database operation. Blockchain failures are caught and logged but never
block the API response.
"""

import logging
import threading

from django.conf import settings

from loans.utils.time import utcnow

logger = logging.getLogger("blockchain")


def _is_enabled():
    return getattr(settings, "BLOCKCHAIN_ENABLED", False)


def _run_in_thread(fn, *args):
    """Run blockchain sync in a background thread so the API response isn't delayed."""

    def wrapper():
        try:
            fn(*args)
        except Exception as exc:
            logger.error(
                "Blockchain sync error in %s: %s", getattr(fn, "__name__", str(fn)), exc
            )

    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()


def _monthly_rate_to_annual_bps(monthly_rate):
    return int(round(monthly_rate * 12 * 10_000))


def _risk_category_to_int(risk_str):
    mapping = {"low": 0, "medium": 1, "high": 2}
    if risk_str is None:
        return 0
    return mapping.get(str(risk_str).lower(), 0)


def _update_application_tx(loan_id, action, tx_hash):
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


# ---------------------------------------------------------------------------
# Public API — called from views
# ---------------------------------------------------------------------------


def sync_application(loan_id):
    """Sync a submitted loan application to the blockchain."""
    if not _is_enabled():
        return
    _run_in_thread(_sync_application_impl, loan_id)


def sync_approval(loan_id):
    """Sync a loan approval to the blockchain."""
    if not _is_enabled():
        return
    _run_in_thread(_sync_approval_impl, loan_id)


def sync_rejection(loan_id):
    """Sync a loan rejection to the blockchain."""
    if not _is_enabled():
        return
    _run_in_thread(_sync_rejection_impl, loan_id)


def sync_disbursement(loan_id, include_schedule=True):
    """Sync a loan disbursement (and schedule) to the blockchain."""
    if not _is_enabled():
        return
    _run_in_thread(_sync_disbursement_impl, loan_id, include_schedule)


def sync_schedule(loan_id):
    """Sync a repayment schedule to the blockchain."""
    if not _is_enabled():
        return
    _run_in_thread(_sync_schedule_impl, loan_id)


def sync_payment(loan_id, payment_id):
    """Sync a payment recording to the blockchain."""
    if not _is_enabled():
        return
    _run_in_thread(_sync_payment_impl, loan_id, payment_id)


def sync_overdue(loan_id, installment_number):
    """Sync an overdue installment marking to the blockchain."""
    if not _is_enabled():
        return
    _run_in_thread(_sync_overdue_impl, loan_id, installment_number)


def sync_penalty(loan_id, installment_number, amount, action, reason=""):
    """Sync a penalty apply/waive audit log to the blockchain."""
    if not _is_enabled():
        return
    _run_in_thread(
        _sync_penalty_impl, loan_id, installment_number, amount, action, reason
    )


def sync_consent(
    user_id,
    user_type,
    data_consent,
    ai_consent,
    consent_version,
    consent_timestamp,
    previous_state=None,
):
    """Sync a consent record to the blockchain."""
    if not _is_enabled():
        return
    _run_in_thread(
        _sync_consent_impl,
        user_id,
        user_type,
        data_consent,
        ai_consent,
        consent_version,
        consent_timestamp,
        previous_state,
    )


# ---------------------------------------------------------------------------
# Implementation (runs in background thread)
# ---------------------------------------------------------------------------


def _sync_application_impl(loan_id):
    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.application_service import (
        create_application_onchain,
        submit_application_onchain,
    )
    from loans.blockchain.client import get_contract, send_transaction
    from loans.models.application import LoanApplication
    from web3 import Web3

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

        submit_result = submit_application_onchain(
            loan_id=loan_id,
            eligibility_score=int(app.eligibility_score or 0),
            risk_category=_risk_category_to_int(app.risk_category),
            ai_recommendation_hash=(
                str(app.ai_recommendation) if app.ai_recommendation else "none"
            ),
        )

        # Mirror in LoanCore: createLoan + submitLoan
        loan_id_bytes = Web3.keccak(text=str(loan_id))
        product_bytes = Web3.keccak(text=str(app.product_id))
        ai_hash_bytes = Web3.keccak(
            text=str(app.ai_recommendation) if app.ai_recommendation else "none"
        )
        lc = get_contract("loanCore")
        send_transaction(
            lc,
            "createLoan",
            loan_id_bytes,
            product_bytes,
            int(app.requested_amount),
            int(app.term_months),
            interest_bps,
        )
        send_transaction(
            lc,
            "submitLoan",
            loan_id_bytes,
            min(int(app.eligibility_score or 0), 255),
            _risk_category_to_int(app.risk_category),
            ai_hash_bytes,
        )
        logger.info("LoanCore createLoan+submitLoan OK: loan=%s", loan_id)

        tx_record.mark_confirmed(
            tx_hash=submit_result["tx_hash"],
            gas_used=create_result["gas_used"] + submit_result["gas_used"],
            block_number=submit_result["block_number"],
        )
        _update_application_tx(loan_id, "submit", submit_result["tx_hash"])
        logger.info(
            "sync_application OK: loan=%s tx=%s", loan_id, submit_result["tx_hash"][:18]
        )

    except Exception as exc:
        logger.error("sync_application FAILED: loan=%s error=%s", loan_id, exc)
        tx_record.mark_failed(str(exc))


def _sync_approval_impl(loan_id):
    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.approval_service import approve_loan_onchain
    from loans.blockchain.services.review_service import assign_officer_onchain
    from loans.blockchain.client import get_account, get_contract, send_transaction
    from loans.models.application import LoanApplication
    from web3 import Web3

    tx_record = BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action="approve",
        contract_name="LoanApproval",
        method="assignOfficer+approveLoan",
    )

    try:
        app = LoanApplication.find_by_id(loan_id)
        if not app:
            raise ValueError(f"LoanApplication {loan_id} not found")

        acct = get_account()

        # Step 1: Assign officer (moves loan to UnderReview status)
        assign_officer_onchain(loan_id=loan_id, officer_address=acct.address)

        # Step 2: Approve loan
        approved_amount = int(app.approved_amount or app.requested_amount)
        notes_str = str(app.officer_notes or "approved")
        result = approve_loan_onchain(
            loan_id=loan_id,
            approved_amount=approved_amount,
            notes_hash=notes_str,
        )

        # Mirror in LoanCore: assignOfficer + approveLoan
        loan_id_bytes = Web3.keccak(text=str(loan_id))
        notes_bytes = Web3.keccak(text=notes_str)
        lc = get_contract("loanCore")
        send_transaction(lc, "assignOfficer", loan_id_bytes, acct.address)
        send_transaction(lc, "approveLoan", loan_id_bytes, approved_amount, notes_bytes)
        logger.info("LoanCore assignOfficer+approveLoan OK: loan=%s", loan_id)

        tx_record.mark_confirmed(
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
        )
        _update_application_tx(loan_id, "approve", result["tx_hash"])
        logger.info("sync_approval OK: loan=%s tx=%s", loan_id, result["tx_hash"][:18])

    except Exception as exc:
        logger.error("sync_approval FAILED: loan=%s error=%s", loan_id, exc)
        tx_record.mark_failed(str(exc))


def _sync_rejection_impl(loan_id):
    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.approval_service import reject_loan_onchain
    from loans.blockchain.services.review_service import assign_officer_onchain
    from loans.blockchain.client import get_account, get_contract, send_transaction
    from loans.models.application import LoanApplication
    from web3 import Web3

    tx_record = BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action="reject",
        contract_name="LoanApproval",
        method="assignOfficer+rejectLoan",
    )

    try:
        app = LoanApplication.find_by_id(loan_id)
        if not app:
            raise ValueError(f"LoanApplication {loan_id} not found")

        acct = get_account()

        # Step 1: Assign officer (moves loan to UnderReview status)
        assign_officer_onchain(loan_id=loan_id, officer_address=acct.address)

        # Step 2: Reject loan
        reason_str = str(app.rejection_reason or "rejected")
        notes_str = str(app.officer_notes or "")
        result = reject_loan_onchain(
            loan_id=loan_id,
            rejection_reason_hash=reason_str,
            notes_hash=notes_str or "rejected",
        )

        # Mirror in LoanCore: assignOfficer + rejectLoan
        loan_id_bytes = Web3.keccak(text=str(loan_id))
        reason_bytes = Web3.keccak(text=reason_str)
        notes_bytes = Web3.keccak(text=notes_str or "rejected")
        lc = get_contract("loanCore")
        send_transaction(lc, "assignOfficer", loan_id_bytes, acct.address)
        send_transaction(lc, "rejectLoan", loan_id_bytes, reason_bytes, notes_bytes)
        logger.info("LoanCore assignOfficer+rejectLoan OK: loan=%s", loan_id)

        tx_record.mark_confirmed(
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
        )
        _update_application_tx(loan_id, "reject", result["tx_hash"])
        logger.info("sync_rejection OK: loan=%s tx=%s", loan_id, result["tx_hash"][:18])

    except Exception as exc:
        logger.error("sync_rejection FAILED: loan=%s error=%s", loan_id, exc)
        tx_record.mark_failed(str(exc))


def _sync_disbursement_impl(loan_id, include_schedule=True):
    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.disbursement_service import (
        complete_disbursement_onchain,
        set_method_onchain,
    )
    from loans.blockchain.client import get_contract, send_transaction
    from loans.models.application import LoanApplication
    from web3 import Web3

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

        method_str = (
            app.disbursement_method or app.preferred_disbursement_method or "other"
        )

        # ETH transfer for wallet disbursements
        if method_str == "wallet":
            _execute_eth_disbursement(loan_id, app)

        set_method_onchain(loan_id=loan_id, method=method_str)

        amount = int(
            app.disbursed_amount or app.approved_amount or app.requested_amount
        )
        ref_str = str(app.disbursement_reference or f"DISB_{loan_id}")

        result = complete_disbursement_onchain(
            loan_id=loan_id,
            amount=amount,
            reference_hash=ref_str,
        )

        # Mirror in LoanCore: markDisbursed
        loan_id_bytes = Web3.keccak(text=str(loan_id))
        lc = get_contract("loanCore")
        send_transaction(lc, "markDisbursed", loan_id_bytes, amount)
        logger.info("LoanCore markDisbursed OK: loan=%s", loan_id)

        complete_tx = result["complete_tx"]
        tx_record.mark_confirmed(
            tx_hash=complete_tx["tx_hash"],
            gas_used=complete_tx["gas_used"],
            block_number=complete_tx["block_number"],
        )
        _update_application_tx(loan_id, "disburse", complete_tx["tx_hash"])
        logger.info(
            "sync_disbursement OK: loan=%s tx=%s", loan_id, complete_tx["tx_hash"][:18]
        )

        # Schedule must run AFTER disbursement (contract requires Disbursed status)
        if include_schedule:
            _sync_schedule_impl(loan_id)

    except Exception as exc:
        logger.error("sync_disbursement FAILED: loan=%s error=%s", loan_id, exc)
        tx_record.mark_failed(str(exc))


def _execute_eth_disbursement(loan_id, app):
    """Send actual ETH to the customer's wallet for wallet-based disbursements."""
    from loans.blockchain.client import send_eth_transfer, get_web3
    from loans.blockchain.services.eth_price_service import php_to_eth
    from profiles.models.profile_models import CustomerProfile

    profile = CustomerProfile.find_by_customer(app.customer_id)
    if not profile or not profile.wallet_address:
        raise ValueError(
            f"Customer {app.customer_id} has no wallet address. "
            "Cannot disburse via wallet without a valid Ethereum address."
        )

    php_amount = float(
        app.disbursed_amount or app.approved_amount or app.requested_amount
    )
    conversion = php_to_eth(php_amount)

    w3 = get_web3()
    amount_wei = w3.to_wei(conversion["eth_amount"], "ether")

    eth_result = send_eth_transfer(profile.wallet_address, amount_wei)

    # Store ETH transfer details in the loan document
    db = getattr(settings, "MONGODB", None)
    if db is not None:
        from bson import ObjectId as BsonObjectId

        db["loan_applications"].update_one(
            {"_id": BsonObjectId(loan_id)},
            {
                "$set": {
                    "eth_disbursement_tx_hash": eth_result["tx_hash"],
                    "eth_disbursement_amount": str(conversion["eth_amount"]),
                    "eth_disbursement_amount_wei": str(amount_wei),
                    "eth_disbursement_rate": conversion["rate"],
                    "eth_disbursement_rate_source": conversion["source"],
                    "eth_disbursement_recipient": profile.wallet_address,
                }
            },
        )

    logger.info(
        "ETH disbursement OK: loan=%s amount=%.6f ETH to=%s tx=%s",
        loan_id,
        conversion["eth_amount"],
        profile.wallet_address[:10],
        eth_result["tx_hash"][:18],
    )


def _sync_schedule_impl(loan_id):
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

        schedule_doc = settings.MONGODB["repayment_schedules"].find_one(
            {"loan_id": loan_id}
        )
        if not schedule_doc:
            raise ValueError(f"RepaymentSchedule for loan {loan_id} not found")

        schedule = RepaymentSchedule.from_dict(schedule_doc)
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

        tx_record.mark_confirmed(
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
        )

        settings.MONGODB["repayment_schedules"].update_one(
            {"_id": schedule_doc["_id"]},
            {"$set": {"blockchain_schedule_tx": result["tx_hash"]}},
        )
        logger.info("sync_schedule OK: loan=%s tx=%s", loan_id, result["tx_hash"][:18])

    except Exception as exc:
        logger.error("sync_schedule FAILED: loan=%s error=%s", loan_id, exc)
        tx_record.mark_failed(str(exc))


def _sync_payment_impl(loan_id, payment_id):
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
        payment_doc = settings.MONGODB["loan_payments"].find_one(
            {"_id": ObjectId(payment_id)}
        )
        if not payment_doc:
            raise ValueError(f"LoanPayment {payment_id} not found")

        payment = LoanPayment.from_dict(payment_doc)
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
        )

        settings.MONGODB["loan_payments"].update_one(
            {"_id": ObjectId(payment_id)},
            {
                "$set": {
                    "blockchain_tx_hash": result["tx_hash"],
                    "blockchain_sync_status": "synced",
                    "blockchain_synced_at": utcnow(),
                }
            },
        )
        logger.info(
            "sync_payment OK: loan=%s payment=%s tx=%s",
            loan_id,
            payment_id,
            result["tx_hash"][:18],
        )

    except Exception as exc:
        settings.MONGODB["loan_payments"].update_one(
            {"_id": ObjectId(payment_id)},
            {
                "$set": {
                    "blockchain_sync_status": "failed",
                    "blockchain_sync_error": str(exc)[:500],
                }
            },
        )
        logger.error(
            "sync_payment FAILED: loan=%s payment=%s error=%s", loan_id, payment_id, exc
        )
        tx_record.mark_failed(str(exc))


def _sync_overdue_impl(loan_id, installment_number):
    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.repayment_service import mark_overdue_onchain

    tx_record = BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action="overdue",
        contract_name="PaymentRecording",
        method="markOverdue",
        details={"installment_number": installment_number},
    )

    try:
        result = mark_overdue_onchain(
            loan_id=loan_id,
            installment_number=int(installment_number),
        )

        tx_record.mark_confirmed(
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
        )

        settings.MONGODB["repayment_schedules"].update_one(
            {"loan_id": loan_id},
            {
                "$set": {
                    f"blockchain_overdue_tx.{installment_number}": result["tx_hash"]
                }
            },
        )

        logger.info(
            "sync_overdue OK: loan=%s installment=%s tx=%s",
            loan_id,
            installment_number,
            result["tx_hash"][:18],
        )
    except Exception as exc:
        logger.error(
            "sync_overdue FAILED: loan=%s installment=%s error=%s",
            loan_id,
            installment_number,
            exc,
        )
        tx_record.mark_failed(str(exc))


def _sync_penalty_impl(loan_id, installment_number, amount, action, reason=""):
    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.audit_service import log_penalty_onchain

    action_key = "penalty_waived" if action == "waive" else "penalty_applied"
    db = getattr(settings, "MONGODB", None)
    existing = None
    if db is not None:
        existing = db["blockchain_transactions"].find_one(
            {
                "loan_id": loan_id,
                "action": action_key,
                "status": BlockchainTransaction.STATUS_CONFIRMED,
                "details.installment_number": installment_number,
                "details.amount": amount,
                "details.reason": reason,
            }
        )
    if existing:
        logger.info(
            "sync_penalty skipped existing confirmed tx: loan=%s installment=%s action=%s",
            loan_id,
            installment_number,
            action_key,
        )
        return

    tx_record = BlockchainTransaction.create_pending(
        loan_id=loan_id,
        action=action_key,
        contract_name="AuditRegistry",
        method="log",
        details={
            "installment_number": installment_number,
            "amount": amount,
            "reason": reason,
        },
    )

    try:
        result = log_penalty_onchain(
            loan_id=loan_id,
            installment_number=installment_number,
            amount=amount,
            reason=reason,
            waived=action == "waive",
        )

        tx_record.mark_confirmed(
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
        )

        settings.MONGODB["repayment_schedules"].update_one(
            {"loan_id": loan_id},
            {
                "$set": {
                    f"blockchain_penalty_tx.{installment_number}.{action_key}": result[
                        "tx_hash"
                    ]
                }
            },
        )

        logger.info(
            "sync_penalty OK: loan=%s installment=%s action=%s tx=%s",
            loan_id,
            installment_number,
            action_key,
            result["tx_hash"][:18],
        )
    except Exception as exc:
        logger.error(
            "sync_penalty FAILED: loan=%s installment=%s action=%s error=%s",
            loan_id,
            installment_number,
            action_key,
            exc,
        )
        tx_record.mark_failed(str(exc))


def _sync_consent_impl(
    user_id,
    user_type,
    data_consent,
    ai_consent,
    consent_version,
    consent_timestamp,
    previous_state,
):
    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.audit_service import log_consent_onchain

    tx_record = BlockchainTransaction.create_pending(
        loan_id=str(user_id),
        action="consent",
        contract_name="AuditRegistry",
        method="log",
        details={
            "user_type": user_type,
            "data_consent": data_consent,
            "ai_consent": ai_consent,
            "consent_version": consent_version,
        },
    )

    try:
        result = log_consent_onchain(
            user_id=user_id,
            user_type=user_type,
            data_consent=data_consent,
            ai_consent=ai_consent,
            consent_version=consent_version,
            consent_timestamp=consent_timestamp,
            previous_state=previous_state,
        )

        tx_record.mark_confirmed(
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
        )

        logger.info("sync_consent OK: user=%s tx=%s", user_id, result["tx_hash"][:18])
    except Exception as exc:
        logger.error("sync_consent FAILED: user=%s error=%s", user_id, exc)
        tx_record.mark_failed(str(exc))
