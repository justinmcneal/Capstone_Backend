"""Blockchain sync implementations and durable Celery dispatch facade."""

import logging

from django.conf import settings

from loans.blockchain.sync_common import (
    _create_tx_record,
    _fail_tx,
    _finalize_tx,
    _monthly_rate_to_annual_bps,
    _risk_category_to_int,
    sync_schedule as _sync_schedule_common,
)

logger = logging.getLogger("blockchain")


def _is_enabled():
    return getattr(settings, "BLOCKCHAIN_ENABLED", False)


# ---------------------------------------------------------------------------
# Public API — called from views
# ---------------------------------------------------------------------------


def sync_application(loan_id):
    """Sync a submitted loan application to the blockchain."""
    if not _is_enabled():
        return
    from loans.blockchain.tasks import sync_application_to_chain
    return sync_application_to_chain.delay(loan_id)


def sync_approval(loan_id):
    """Sync a loan approval to the blockchain."""
    if not _is_enabled():
        return
    from loans.blockchain.tasks import sync_approval_to_chain
    return sync_approval_to_chain.delay(loan_id)


def sync_rejection(loan_id):
    """Sync a loan rejection to the blockchain."""
    if not _is_enabled():
        return
    from loans.blockchain.tasks import sync_rejection_to_chain
    return sync_rejection_to_chain.delay(loan_id)


def sync_disbursement(loan_id, include_schedule=True):
    """Sync a loan disbursement (and schedule) to the blockchain."""
    if not _is_enabled():
        return
    from loans.blockchain.tasks import sync_disbursement_to_chain
    if include_schedule:
        from celery import chain
        from loans.blockchain.tasks import sync_schedule_to_chain
        return chain(
            sync_disbursement_to_chain.s(loan_id),
            sync_schedule_to_chain.si(loan_id),
        ).apply_async()
    return sync_disbursement_to_chain.delay(loan_id)


def sync_schedule(loan_id):
    """Sync a repayment schedule to the blockchain."""
    if not _is_enabled():
        return
    from loans.blockchain.tasks import sync_schedule_to_chain
    return sync_schedule_to_chain.delay(loan_id)


def sync_payment(loan_id, payment_id):
    """Sync a payment recording to the blockchain."""
    if not _is_enabled():
        return
    from loans.blockchain.tasks import sync_payment_to_chain
    return sync_payment_to_chain.delay(loan_id, payment_id)


def sync_overdue(loan_id, installment_number):
    """Sync an overdue installment marking to the blockchain."""
    if not _is_enabled():
        return
    from loans.blockchain.tasks import sync_overdue_to_chain
    return sync_overdue_to_chain.delay(loan_id, installment_number)


def sync_penalty(loan_id, installment_number, amount, action, reason=""):
    """Sync a penalty apply/waive audit log to the blockchain."""
    if not _is_enabled():
        return
    from loans.blockchain.tasks import sync_penalty_to_chain
    return sync_penalty_to_chain.delay(
        loan_id, installment_number, amount, action, reason
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
    from loans.blockchain.tasks import sync_consent_to_chain
    return sync_consent_to_chain.delay(
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


def _ensure_application_synced_for_approval(loan_id):
    from loans.blockchain.client import call_view, get_contract
    from web3 import Web3

    loan_id_bytes = Web3.keccak(text=str(loan_id))
    contract = get_contract("loanApplication")

    try:
        exists = bool(call_view(contract, "exists", loan_id_bytes))
    except Exception as exc:
        logger.warning(
            "sync_approval: could not verify on-chain application for loan=%s: %s",
            loan_id,
            exc,
        )
        exists = False

    if exists:
        return

    logger.info(
        "sync_approval: on-chain application missing for loan=%s, rebuilding mirror first",
        loan_id,
    )
    _sync_application_impl(loan_id)

    try:
        exists = bool(call_view(contract, "exists", loan_id_bytes))
    except Exception as exc:
        raise RuntimeError(
            f"Failed to verify rebuilt on-chain application for loan {loan_id}: {exc}"
        ) from exc

    if not exists:
        raise RuntimeError(
            f"Failed to rebuild on-chain application mirror for loan {loan_id}"
        )


def _sync_application_impl(loan_id):
    from loans.blockchain.services.application_service import (
        create_application_onchain,
        submit_application_onchain,
    )
    from loans.blockchain.client import get_contract, send_transaction
    from loans.models.application import LoanApplication
    from web3 import Web3

    tx_record = _create_tx_record(
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

        _finalize_tx(
            tx_record,
            tx_hash=submit_result["tx_hash"],
            gas_used=create_result["gas_used"] + submit_result["gas_used"],
            block_number=submit_result["block_number"],
            loan_id=loan_id,
            action="submit",
        )
        logger.info(
            "sync_application OK: loan=%s tx=%s", loan_id, submit_result["tx_hash"][:18]
        )

    except Exception as exc:
        _fail_tx(tx_record, exc, loan_id=loan_id)


def _sync_approval_impl(loan_id):
    from loans.blockchain.services.approval_service import approve_loan_onchain
    from loans.blockchain.services.review_service import assign_officer_onchain
    from loans.blockchain.client import call_view, get_account, get_contract, send_transaction
    from loans.models.application import LoanApplication
    from web3 import Web3

    tx_record = _create_tx_record(
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
        approved_amount = int(app.approved_amount or app.requested_amount)
        notes_str = str(app.officer_notes or "approved")

        # Rebuild the on-chain application mirror first if it is missing.
        _ensure_application_synced_for_approval(loan_id)

        # Read the on-chain requestedAmount to ensure approved_amount does not
        # exceed it — the smart contract enforces approvedAmount <= requestedAmount
        # and will revert with AmountExceedsRequested if violated.
        loan_id_bytes = Web3.keccak(text=str(loan_id))
        la_contract = get_contract("loanApplication")
        try:
            onchain_app = call_view(la_contract, "getApplication", loan_id_bytes)
            onchain_requested = int(onchain_app[3])
            if approved_amount > onchain_requested:
                logger.warning(
                    "sync_approval: capping approved_amount from %d to on-chain "
                    "requestedAmount %d for loan=%s",
                    approved_amount, onchain_requested, loan_id,
                )
                approved_amount = onchain_requested
        except Exception as e:
            logger.warning(
                "sync_approval: could not read on-chain requestedAmount for loan=%s: %s, "
                "using DB requested_amount as fallback cap",
                loan_id, e,
            )
            db_requested = int(app.requested_amount)
            if approved_amount > db_requested:
                approved_amount = db_requested

        logger.info(
            "sync_approval STARTING: loan=%s wallet=%s approved_amount=%d notes=%s",
            loan_id, acct.address, approved_amount, notes_str,
        )

        # Step 1: Assign officer on LoanReview (moves loan to UnderReview status)
        logger.info("sync_approval step 1/4: LoanReview.assignOfficer ...")
        assign_officer_onchain(loan_id=loan_id, officer_address=acct.address)
        logger.info("sync_approval step 1/4: LoanReview.assignOfficer OK")

        # Step 2: Approve loan on LoanApproval
        logger.info("sync_approval step 2/4: LoanApproval.approveLoan ...")
        result = approve_loan_onchain(
            loan_id=loan_id,
            approved_amount=approved_amount,
            notes_hash=notes_str,
        )
        logger.info("sync_approval step 2/4: LoanApproval.approveLoan OK")

        # Mirror in LoanCore: assignOfficer + approveLoan
        notes_bytes = Web3.keccak(text=notes_str)
        lc = get_contract("loanCore")

        logger.info("sync_approval step 3/4: LoanCore.assignOfficer ...")
        send_transaction(lc, "assignOfficer", loan_id_bytes, acct.address)
        logger.info("sync_approval step 3/4: LoanCore.assignOfficer OK")

        logger.info("sync_approval step 4/4: LoanCore.approveLoan ...")
        send_transaction(lc, "approveLoan", loan_id_bytes, approved_amount, notes_bytes)
        logger.info("sync_approval step 4/4: LoanCore.approveLoan OK")

        _finalize_tx(
            tx_record,
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
            loan_id=loan_id,
            action="approve",
        )
        logger.info("sync_approval OK: loan=%s tx=%s", loan_id, result["tx_hash"][:18])

    except Exception as exc:
        _fail_tx(tx_record, exc, loan_id=loan_id)


def _sync_rejection_impl(loan_id, raise_errors=False):
    from loans.blockchain.services.approval_service import reject_loan_onchain
    from loans.blockchain.services.review_service import assign_officer_onchain
    from loans.blockchain.client import get_account, get_contract, send_transaction
    from loans.models.application import LoanApplication
    from web3 import Web3

    tx_record = _create_tx_record(
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

        _finalize_tx(
            tx_record,
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
            loan_id=loan_id,
            action="reject",
        )
        logger.info("sync_rejection OK: loan=%s tx=%s", loan_id, result["tx_hash"][:18])

    except Exception as exc:
        _fail_tx(tx_record, exc, loan_id=loan_id)
        if raise_errors:
            raise


def _sync_disbursement_impl(loan_id, include_schedule=True):
    from loans.blockchain.services.disbursement_service import (
        complete_disbursement_onchain,
        set_method_onchain,
    )
    from loans.blockchain.client import get_contract, send_transaction
    from loans.models.application import LoanApplication
    from web3 import Web3

    tx_record = _create_tx_record(
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
        _finalize_tx(
            tx_record,
            tx_hash=complete_tx["tx_hash"],
            gas_used=complete_tx["gas_used"],
            block_number=complete_tx["block_number"],
            loan_id=loan_id,
            action="disburse",
        )
        logger.info(
            "sync_disbursement OK: loan=%s tx=%s", loan_id, complete_tx["tx_hash"][:18]
        )

        # Schedule must run AFTER disbursement (contract requires Disbursed status)
        if include_schedule:
            _sync_schedule_common(loan_id)

    except Exception as exc:
        _fail_tx(tx_record, exc, loan_id=loan_id)


def _execute_eth_disbursement(loan_id, app):
    """Send actual ETH to the customer's wallet for wallet-based disbursements."""
    from bson import ObjectId
    from loans.blockchain.client import get_web3, send_eth_transfer
    from loans.blockchain.services.eth_price_service import php_to_eth
    from loans.models.application import LoanApplication
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

    LoanApplication.update_eth_disbursement(
        ObjectId(loan_id),
        tx_hash=eth_result["tx_hash"],
        amount=str(conversion["eth_amount"]),
        amount_wei=str(amount_wei),
        rate=conversion["rate"],
        rate_source=conversion["source"],
        recipient=profile.wallet_address,
    )

    logger.info(
        "ETH disbursement OK: loan=%s amount=%.6f ETH to=%s tx=%s",
        loan_id,
        conversion["eth_amount"],
        profile.wallet_address[:10],
        eth_result["tx_hash"][:18],
    )


def _sync_overdue_impl(loan_id, installment_number, raise_errors=False):
    from loans.blockchain.services.repayment_service import mark_overdue_onchain
    from loans.models.repayment import RepaymentSchedule

    tx_record = _create_tx_record(
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

        _finalize_tx(
            tx_record,
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
        )

        schedule = RepaymentSchedule.find_by_loan(loan_id)
        if not schedule:
            raise ValueError(f"RepaymentSchedule for loan {loan_id} not found")
        RepaymentSchedule.update_blockchain_overdue_tx(
            schedule._id, installment_number, result["tx_hash"]
        )

        logger.info(
            "sync_overdue OK: loan=%s installment=%s tx=%s",
            loan_id,
            installment_number,
            result["tx_hash"][:18],
        )
    except Exception as exc:
        _fail_tx(tx_record, exc, loan_id=loan_id)
        if raise_errors:
            raise


def _sync_penalty_impl(
    loan_id, installment_number, amount, action, reason="", raise_errors=False
):
    from loans.blockchain.models import BlockchainTransaction
    from loans.blockchain.services.audit_service import log_penalty_onchain
    from loans.models.repayment import RepaymentSchedule

    action_key = "penalty_waived" if action == "waive" else "penalty_applied"
    existing = BlockchainTransaction.find_confirmed(
        loan_id=loan_id,
        action=action_key,
        installment_number=installment_number,
        amount=amount,
        reason=reason,
    )
    if existing:
        logger.info(
            "sync_penalty skipped existing confirmed tx: loan=%s installment=%s action=%s",
            loan_id,
            installment_number,
            action_key,
        )
        return

    tx_record = _create_tx_record(
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

        _finalize_tx(
            tx_record,
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
        )

        schedule = RepaymentSchedule.find_by_loan(loan_id)
        if not schedule:
            raise ValueError(f"RepaymentSchedule for loan {loan_id} not found")
        RepaymentSchedule.update_blockchain_penalty_tx(
            schedule._id, installment_number, action, result["tx_hash"]
        )

        logger.info(
            "sync_penalty OK: loan=%s installment=%s action=%s tx=%s",
            loan_id,
            installment_number,
            action_key,
            result["tx_hash"][:18],
        )
    except Exception as exc:
        _fail_tx(tx_record, exc, loan_id=loan_id)
        if raise_errors:
            raise


def _sync_consent_impl(
    user_id,
    user_type,
    data_consent,
    ai_consent,
    consent_version,
    consent_timestamp,
    previous_state,
    raise_errors=False,
):
    from loans.blockchain.services.audit_service import log_consent_onchain

    tx_record = _create_tx_record(
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

        _finalize_tx(
            tx_record,
            tx_hash=result["tx_hash"],
            gas_used=result["gas_used"],
            block_number=result["block_number"],
        )

        logger.info("sync_consent OK: user=%s tx=%s", user_id, result["tx_hash"][:18])
    except Exception as exc:
        _fail_tx(tx_record, exc, loan_id=user_id)
        if raise_errors:
            raise
