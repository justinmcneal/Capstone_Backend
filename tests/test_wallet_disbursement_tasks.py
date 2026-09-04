"""Focused tests for durable wallet disbursement execution and recovery."""

from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId

from loans.models import LoanApplication, LoanProduct, RepaymentSchedule
from loans.services.disbursement import begin_disbursement
from loans.tasks import _complete_wallet_disbursement
from loans.utils.time import utcnow


@pytest.fixture
def pending_wallet(settings):
    settings.MONGODB = mongomock.MongoClient()["wallet_worker"]
    settings.BLOCKCHAIN_ENABLED = True
    LoanApplication.create_indexes()
    RepaymentSchedule.create_indexes()
    product = LoanProduct(
        name="Wallet Product", code=f"WAL-{ObjectId()}", interest_rate=0.01
    ).save()
    application = LoanApplication(
        customer_id=str(ObjectId()),
        product_id=product.id,
        requested_amount=10000,
        approved_amount=10000,
        term_months=3,
        status="approved",
    ).save()
    application, _ = begin_disbursement(
        application=application,
        amount=10000,
        method="wallet",
        reference="WALLET-TEST",
        actor_id="officer-1",
        idempotency_key="wallet-task-test",
    )
    claimed = LoanApplication.claim_wallet_disbursement(
        application.id, "worker-1", utcnow(), utcnow()
    )
    # These unit tests exercise the transfer worker itself, not the separate
    # post-completion contract-sync pipeline.
    settings.BLOCKCHAIN_ENABLED = False
    return claimed


def test_wallet_worker_persists_broadcast_and_completes(
    pending_wallet, monkeypatch, settings
):
    w3 = SimpleNamespace(to_wei=lambda amount, unit: 123456)
    monkeypatch.setattr("loans.blockchain.client.get_web3", lambda: w3)
    monkeypatch.setattr(
        "loans.blockchain.services.eth_price_service.php_to_eth",
        lambda amount: {
            "eth_amount": 0.01,
            "rate": 1_000_000,
            "source": "test",
        },
    )
    monkeypatch.setattr(
        "profiles.models.profile_models.CustomerProfile.find_by_customer",
        lambda customer_id: SimpleNamespace(wallet_address="0x" + "1" * 40),
    )

    def fake_send(recipient, amount_wei, on_broadcast, on_prepared):
        on_prepared("0xabc", 7, "0x01")
        prepared = LoanApplication.find_by_id(pending_wallet.id)
        assert prepared.eth_disbursement_tx_hash == "0xabc"
        assert prepared.eth_disbursement_raw_transaction == "0x01"
        stored = settings.MONGODB["loan_applications"].find_one(
            {"_id": ObjectId(pending_wallet.id)}
        )
        assert stored["eth_disbursement_raw_transaction"] != "0x01"
        on_broadcast("0xabc", 7)
        persisted = LoanApplication.find_by_id(pending_wallet.id)
        assert persisted.eth_disbursement_tx_hash == "0xabc"
        assert persisted.eth_disbursement_nonce == 7
        return {
            "tx_hash": "0xabc",
            "gas_used": 21000,
            "gas_price": 1,
            "block_number": 9,
            "status": 1,
            "amount_wei": amount_wei,
        }

    monkeypatch.setattr("loans.blockchain.client.send_eth_transfer", fake_send)

    result = _complete_wallet_disbursement(pending_wallet, "worker-1")

    completed = LoanApplication.find_by_id(pending_wallet.id)
    assert result["status"] == "executed"
    assert completed.status == "disbursed"
    assert completed.eth_disbursement_tx_hash == "0xabc"
    assert completed.eth_disbursement_block_number == 9
    assert RepaymentSchedule.find_by_loan(pending_wallet.id) is not None


def test_wallet_worker_resumes_confirmed_hash_without_resending(
    pending_wallet, monkeypatch
):
    LoanApplication.update_eth_disbursement(
        ObjectId(pending_wallet.id),
        tx_hash="0xexisting",
        amount="0.01",
        amount_wei="123456",
        rate=1_000_000,
        rate_source="test",
        recipient="0x" + "1" * 40,
    )
    pending_wallet = LoanApplication.find_by_id(pending_wallet.id)
    receipt = {
        "gasUsed": 21000,
        "effectiveGasPrice": 1,
        "blockNumber": 10,
        "status": 1,
    }
    w3 = SimpleNamespace(
        eth=SimpleNamespace(get_transaction_receipt=lambda tx_hash: receipt)
    )
    monkeypatch.setattr("loans.blockchain.client.get_web3", lambda: w3)
    monkeypatch.setattr(
        "loans.blockchain.client.send_eth_transfer",
        lambda *args, **kwargs: pytest.fail("transfer must not be sent twice"),
    )
    monkeypatch.setattr(
        "profiles.models.profile_models.CustomerProfile.find_by_customer",
        lambda customer_id: SimpleNamespace(wallet_address="0x" + "1" * 40),
    )

    result = _complete_wallet_disbursement(pending_wallet, "worker-1")

    assert result["tx_hash"] == "0xexisting"
    assert LoanApplication.find_by_id(pending_wallet.id).status == "disbursed"


def test_wallet_worker_rebroadcasts_exact_prepared_transaction(
    pending_wallet, monkeypatch
):
    from web3.exceptions import TransactionNotFound

    recipient = "0x" + "2" * 40
    LoanApplication.update_eth_disbursement(
        ObjectId(pending_wallet.id),
        tx_hash="0xprepared",
        raw_transaction="0x0102",
        amount="0.01",
        amount_wei="123456",
        rate=1_000_000,
        rate_source="test",
        recipient=recipient,
        nonce=8,
        tx_status="prepared",
    )
    pending_wallet = LoanApplication.find_by_id(pending_wallet.id)

    class MissingEth:
        @staticmethod
        def get_transaction_receipt(tx_hash):
            raise TransactionNotFound(tx_hash)

        @staticmethod
        def get_transaction(tx_hash):
            raise TransactionNotFound(tx_hash)

    monkeypatch.setattr(
        "loans.blockchain.client.get_web3", lambda: SimpleNamespace(eth=MissingEth())
    )

    def fake_rebroadcast(raw, expected_hash, to_address, amount_wei, on_broadcast):
        assert raw == "0x0102"
        assert expected_hash == "0xprepared"
        assert to_address == recipient
        on_broadcast(expected_hash)
        return {
            "tx_hash": expected_hash,
            "gas_used": 21000,
            "gas_price": 1,
            "block_number": 12,
            "status": 1,
            "amount_wei": amount_wei,
        }

    monkeypatch.setattr(
        "loans.blockchain.client.send_prepared_eth_transfer", fake_rebroadcast
    )

    result = _complete_wallet_disbursement(pending_wallet, "worker-1")
    completed = LoanApplication.find_by_id(pending_wallet.id)

    assert result["tx_hash"] == "0xprepared"
    assert completed.eth_disbursement_rebroadcast_count == 1
    assert completed.eth_disbursement_tx_status == "confirmed"
    assert completed.eth_disbursement_raw_transaction == ""
