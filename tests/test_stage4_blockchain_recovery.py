"""Stage 4 saga, reconciliation, and operator recovery regression tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import mongomock
import pytest
from bson import ObjectId
from web3 import Web3

from loans.blockchain.tasks import (
    reconcile_blockchain_domain_state,
    sync_application_to_chain,
)
from loans.models import LoanApplication
from loans.views.officer.wallet_recovery import WalletDisbursementRecoveryView


def test_prepared_transfer_rebroadcast_preserves_exact_hash(settings, monkeypatch):
    from loans.blockchain.client import send_prepared_eth_transfer

    settings.BLOCKCHAIN_ENABLED = True
    raw = b"\x01\x02\x03"
    expected_hash = "0x" + Web3.keccak(raw).hex().removeprefix("0x")
    receipt = {
        "transactionHash": Web3.keccak(raw),
        "status": 1,
        "gasUsed": 21000,
        "effectiveGasPrice": 1,
        "blockNumber": 4,
    }
    eth = SimpleNamespace(
        send_raw_transaction=lambda payload: Web3.keccak(payload),
        wait_for_transaction_receipt=lambda tx_hash, timeout: receipt,
    )
    monkeypatch.setattr(
        "loans.blockchain.client.get_web3", lambda: SimpleNamespace(eth=eth)
    )

    result = send_prepared_eth_transfer(
        "0x" + raw.hex(), expected_hash, "0x" + "1" * 40, 123
    )

    assert result["tx_hash"].lower() == expected_hash.lower()


def test_application_saga_resumes_after_confirmed_create_step(
    settings, monkeypatch
):
    settings.BLOCKCHAIN_ENABLED = True
    settings.BLOCKCHAIN_CONTRACT_ADDRESSES = {"accessControl": "0x1"}
    application = SimpleNamespace(
        product_id="product-1",
        requested_amount=10000,
        term_months=3,
        ai_recommendation={"interest_rate": 0.01},
        eligibility_score=80,
        risk_category="low",
    )
    monkeypatch.setattr(
        "loans.models.application.LoanApplication.find_by_id",
        lambda loan_id: application,
    )
    create = MagicMock(side_effect=AssertionError("confirmed step must not repeat"))
    submit = MagicMock(
        return_value={
            "tx_hash": "0xsubmit",
            "gas_used": 10,
            "gas_price": 1,
            "block_number": 2,
        }
    )
    monkeypatch.setattr(
        "loans.blockchain.services.application_service.create_application_onchain",
        create,
    )
    monkeypatch.setattr(
        "loans.blockchain.services.application_service.submit_application_onchain",
        submit,
    )
    transaction = MagicMock(status="pending")
    transaction.confirmed_step_result.side_effect = lambda step: (
        {"tx_hash": "0xcreate", "gas_used": 5, "block_number": 1}
        if step == "create_application"
        else None
    )
    monkeypatch.setattr(
        "loans.blockchain.models.BlockchainTransaction.create_pending",
        lambda **kwargs: transaction,
    )
    monkeypatch.setattr(
        "loans.blockchain.tasks._update_application_tx", lambda *args: None
    )

    result = sync_application_to_chain("loan-1")

    assert result["tx_hash"] == "0xsubmit"
    create.assert_not_called()
    submit.assert_called_once()
    transaction.mark_step_confirmed.assert_called_once()


def test_reconciliation_derives_missing_jobs_from_domain_state(settings, monkeypatch):
    db = mongomock.MongoClient()["stage4_reconciliation"]
    settings.MONGODB = db
    settings.BLOCKCHAIN_ENABLED = True
    submit_id = ObjectId()
    approve_id = ObjectId()
    disburse_id = ObjectId()
    schedule_loan_id = ObjectId()
    loan_id = ObjectId()
    payment_id = ObjectId()
    db["loan_applications"].insert_many(
        [
            {"_id": submit_id, "status": "submitted", "blockchain_tx_hashes": {}},
            {
                "_id": approve_id,
                "status": "approved",
                "blockchain_tx_hashes": {"submit": "0xsubmit"},
            },
            {
                "_id": disburse_id,
                "status": "disbursed",
                "blockchain_tx_hashes": {
                    "submit": "0xsubmit",
                    "approve": "0xapprove",
                },
            },
            {
                "_id": schedule_loan_id,
                "status": "disbursed",
                "blockchain_tx_hashes": {
                    "submit": "0xsubmit",
                    "approve": "0xapprove",
                    "disburse": "0xdisburse",
                },
            },
            {
                "_id": loan_id,
                "status": "disbursed",
                "blockchain_tx_hashes": {
                    "submit": "0xsubmit",
                    "approve": "0xapprove",
                    "disburse": "0xdisburse",
                },
            },
        ]
    )
    db["repayment_schedules"].insert_one(
        {"_id": ObjectId(), "loan_id": str(loan_id), "blockchain_schedule_tx": "0xschedule"}
    )
    db["repayment_schedules"].insert_one(
        {"_id": ObjectId(), "loan_id": str(disburse_id), "blockchain_schedule_tx": ""}
    )
    db["repayment_schedules"].insert_one(
        {"_id": ObjectId(), "loan_id": str(schedule_loan_id), "blockchain_schedule_tx": ""}
    )
    db["loan_payments"].insert_one(
        {
            "_id": payment_id,
            "loan_id": str(loan_id),
            "payment_status": "posted",
            "blockchain_tx_hash": "",
        }
    )
    queued = []

    def capture(task_name):
        return lambda args, retry: queued.append((task_name, args, retry))

    for task_name in (
        "sync_application_to_chain",
        "sync_approval_to_chain",
        "sync_disbursement_to_chain",
        "sync_schedule_to_chain",
        "sync_payment_to_chain",
    ):
        monkeypatch.setattr(
            f"loans.blockchain.tasks.{task_name}.apply_async", capture(task_name)
        )

    result = reconcile_blockchain_domain_state()

    assert result["enqueued"] == 5
    assert {item[0] for item in queued} == {
        "sync_application_to_chain",
        "sync_approval_to_chain",
        "sync_disbursement_to_chain",
        "sync_schedule_to_chain",
        "sync_payment_to_chain",
    }


@pytest.fixture
def recoverable_wallet(settings):
    settings.MONGODB = mongomock.MongoClient()["wallet_recovery_api"]
    return LoanApplication(
        customer_id=str(ObjectId()),
        product_id=str(ObjectId()),
        requested_amount=10000,
        approved_amount=10000,
        status="approved",
        assigned_officer="officer-1",
        disbursed_amount=10000,
        disbursement_method="wallet",
        disbursement_status="failed",
        disbursement_idempotency_key="wallet-recovery-key",
        eth_disbursement_tx_hash="0xreverted",
        eth_disbursement_tx_status="reverted",
    ).save()


def test_officer_can_retry_reverted_wallet_safely(
    recoverable_wallet, monkeypatch
):
    actor = SimpleNamespace(customer_id="officer-1")
    monkeypatch.setattr(
        WalletDisbursementRecoveryView,
        "check_officer_permission",
        lambda self, request: (True, actor),
    )
    monkeypatch.setattr(
        WalletDisbursementRecoveryView,
        "check_application_scope",
        lambda self, request, application, allow_unassigned: (True, None),
    )
    queued = MagicMock()
    monkeypatch.setattr(
        "loans.views.officer.wallet_recovery.execute_wallet_disbursement_task.apply_async",
        queued,
    )
    monkeypatch.setattr(
        "loans.views.officer.wallet_recovery.AuditLog.log_action", lambda **kwargs: None
    )
    request = MagicMock(
        data={"action": "retry"}, META={"REMOTE_ADDR": "127.0.0.1"}
    )

    response = WalletDisbursementRecoveryView().post(
        request, recoverable_wallet.id
    )

    recovered = LoanApplication.find_by_id(recoverable_wallet.id)
    assert response.status_code == 202
    assert recovered.disbursement_status == "pending"
    assert recovered.eth_disbursement_tx_hash is None
    assert recovered.eth_disbursement_recovery_history[-1]["action"] == "retry"
    queued.assert_called_once_with(args=[recoverable_wallet.id], retry=False)


def test_officer_can_cancel_only_before_transaction_preparation(
    settings, monkeypatch
):
    settings.MONGODB = mongomock.MongoClient()["wallet_cancel_api"]
    application = LoanApplication(
        customer_id=str(ObjectId()),
        product_id=str(ObjectId()),
        requested_amount=10000,
        approved_amount=10000,
        status="approved",
        assigned_officer="officer-1",
        disbursed_amount=10000,
        disbursement_method="wallet",
        disbursement_status="pending",
        disbursement_idempotency_key="wallet-cancel-key",
    ).save()
    actor = SimpleNamespace(customer_id="officer-1")
    monkeypatch.setattr(
        WalletDisbursementRecoveryView,
        "check_officer_permission",
        lambda self, request: (True, actor),
    )
    monkeypatch.setattr(
        WalletDisbursementRecoveryView,
        "check_application_scope",
        lambda self, request, application, allow_unassigned: (True, None),
    )
    monkeypatch.setattr(
        "loans.views.officer.wallet_recovery.AuditLog.log_action", lambda **kwargs: None
    )
    request = MagicMock(data={"action": "cancel", "reason": "Customer request"}, META={})

    response = WalletDisbursementRecoveryView().post(request, application.id)

    cancelled = LoanApplication.find_by_id(application.id)
    assert response.status_code == 200
    assert cancelled.disbursement_status == "cancelled"
    assert cancelled.eth_disbursement_recovery_history[-1]["action"] == "cancel"
