"""Financial-integrity tests for payment submission and posting."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import mongomock
import pytest
from bson import ObjectId

from loans.models import LoanPayment, RepaymentSchedule
from loans.services.payment import (
    PaymentConflictError,
    create_pending_submission,
    post_verified_payment,
)
from loans.utils.time import utcnow
from loans.views.customer_views import PaymentHistoryView, WalletPaymentView
from loans.views.officer.payments import RecordPaymentView


@pytest.fixture
def payment_db(settings):
    db = mongomock.MongoClient()["payment_integrity"]
    settings.MONGODB = db
    LoanPayment.create_indexes()
    return db


@pytest.fixture
def schedule(payment_db):
    schedule = RepaymentSchedule(
        loan_id=str(ObjectId()),
        customer_id=str(ObjectId()),
        principal=1000,
        total_amount=1000,
        installments=[
            {
                "number": 1,
                "due_date": utcnow(),
                "principal": 1000,
                "interest": 0,
                "total_amount": 1000,
                "paid_amount": 0,
                "status": "pending",
            }
        ],
    )
    schedule.save()
    return schedule


def test_customer_submission_is_pending_and_does_not_change_balance(schedule):
    payment, replayed = create_pending_submission(
        schedule=schedule,
        installment_number=1,
        amount=400,
        payment_method="gcash",
        reference="GCASH-123",
        notes="customer evidence",
        customer_id=schedule.customer_id,
        idempotency_key="customer-request-123",
    )

    reloaded = RepaymentSchedule.find_by_loan(schedule.loan_id)
    assert replayed is False
    assert payment.payment_status == "pending_verification"
    assert payment.blockchain_sync_status == "not_started"
    assert reloaded.get_installment(1)["paid_amount"] == 0


def test_pending_submission_replay_returns_same_record(schedule):
    kwargs = {
        "schedule": schedule,
        "installment_number": 1,
        "amount": 400,
        "payment_method": "bank_transfer",
        "reference": "BANK-123",
        "notes": "",
        "customer_id": schedule.customer_id,
        "idempotency_key": "customer-request-456",
    }
    first, first_replay = create_pending_submission(**kwargs)
    second, second_replay = create_pending_submission(**kwargs)

    assert first_replay is False
    assert second_replay is True
    assert second.id == first.id
    assert LoanPayment.count({}) == 1


def test_idempotency_key_cannot_be_reused_for_different_amount(schedule):
    kwargs = {
        "schedule": schedule,
        "installment_number": 1,
        "amount": 400,
        "payment_method": "gcash",
        "reference": "GCASH-456",
        "notes": "",
        "customer_id": schedule.customer_id,
        "idempotency_key": "customer-request-789",
    }
    create_pending_submission(**kwargs)

    with pytest.raises(PaymentConflictError, match="different payment"):
        create_pending_submission(**{**kwargs, "amount": 500})


def test_external_reference_cannot_be_submitted_twice(schedule):
    base = {
        "schedule": schedule,
        "installment_number": 1,
        "amount": 400,
        "payment_method": "gcash",
        "reference": "GCASH-DUPLICATE",
        "notes": "",
        "customer_id": schedule.customer_id,
    }
    create_pending_submission(**base, idempotency_key="customer-request-one")

    with pytest.raises(PaymentConflictError, match="external payment reference"):
        create_pending_submission(**base, idempotency_key="customer-request-two")


def test_verified_payment_posts_once_when_replayed(schedule):
    kwargs = {
        "schedule": schedule,
        "installment_number": 1,
        "amount": 400,
        "payment_method": "cash",
        "reference": "CASH-001",
        "notes": "",
        "recorded_by": "officer-1",
        "idempotency_key": "officer:officer-1:request-001",
        "verification_source": "officer_manual",
    }
    first, first_installment, first_replay = post_verified_payment(**kwargs)
    second, second_installment, second_replay = post_verified_payment(**kwargs)

    assert first_replay is False
    assert second_replay is True
    assert second.id == first.id
    assert first.payment_status == "posted"
    assert first_installment["paid_amount"] == 400
    assert second_installment["paid_amount"] == 400
    assert LoanPayment.count({}) == 1


def test_verified_payment_initializes_missing_legacy_accounting_version(
    schedule, payment_db
):
    payment_db[RepaymentSchedule.collection_name].update_one(
        {"_id": schedule._id},
        {"$unset": {"accounting_version": ""}},
    )
    legacy_schedule = RepaymentSchedule.find_by_loan(schedule.loan_id)

    payment, installment, replayed = post_verified_payment(
        schedule=legacy_schedule,
        installment_number=1,
        amount=100,
        payment_method="cash",
        reference="CASH-LEGACY-VERSION",
        notes="",
        recorded_by="officer-1",
        idempotency_key="officer:officer-1:legacy-version-1",
        verification_source="officer_manual",
    )

    stored = payment_db[RepaymentSchedule.collection_name].find_one(
        {"_id": schedule._id}
    )
    assert replayed is False
    assert payment.payment_status == "posted"
    assert installment["paid_amount"] == 100
    assert stored["accounting_version"] == 1


def test_second_payment_cannot_overpay_after_first_post(schedule):
    common = {
        "schedule": schedule,
        "installment_number": 1,
        "payment_method": "cash",
        "notes": "",
        "recorded_by": "officer-1",
        "verification_source": "officer_manual",
    }
    post_verified_payment(
        **common,
        amount=800,
        reference="CASH-800",
        idempotency_key="officer:officer-1:request-800",
    )

    with pytest.raises(ValueError, match="exceeds remaining balance"):
        post_verified_payment(
            **common,
            amount=300,
            reference="CASH-300",
            idempotency_key="officer:officer-1:request-300",
        )

    reloaded = RepaymentSchedule.find_by_loan(schedule.loan_id)
    assert reloaded.get_installment(1)["paid_amount"] == 800
    failed = LoanPayment.find_one({"idempotency_key": "officer:officer-1:request-300"})
    assert failed.payment_status == "failed"


def test_retry_recovers_after_schedule_update_before_payment_status(
    schedule, monkeypatch
):
    original_mark_posted = LoanPayment.mark_posted
    calls = {"count": 0}

    def fail_once(self, verification_source):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("interrupted after schedule update")
        return original_mark_posted(self, verification_source)

    monkeypatch.setattr(LoanPayment, "mark_posted", fail_once)
    kwargs = {
        "schedule": schedule,
        "installment_number": 1,
        "amount": 500,
        "payment_method": "check",
        "reference": "CHECK-RECOVERY",
        "notes": "",
        "recorded_by": "officer-1",
        "idempotency_key": "officer:officer-1:recovery-1",
        "verification_source": "officer_manual",
    }

    with pytest.raises(RuntimeError, match="interrupted"):
        post_verified_payment(**kwargs)

    payment, installment, replayed = post_verified_payment(**kwargs)
    assert replayed is True
    assert payment.payment_status == "posted"
    assert installment["paid_amount"] == 500


def test_total_paid_excludes_unverified_and_failed_records(schedule):
    for payment_status, amount in [
        ("posted", 200),
        ("pending_verification", 300),
        ("failed", 400),
    ]:
        LoanPayment(
            loan_id=schedule.loan_id,
            amount=amount,
            payment_status=payment_status,
        ).save()

    assert LoanPayment.get_total_paid(schedule.loan_id) == 200


def test_atomic_update_retries_stale_schedule_write(schedule, monkeypatch):
    original_find_one = RepaymentSchedule.find_one
    spy = MagicMock(side_effect=original_find_one)
    monkeypatch.setattr(RepaymentSchedule, "find_one", spy)

    payment, installment, _ = post_verified_payment(
        schedule=schedule,
        installment_number=1,
        amount=100,
        payment_method="cash",
        reference="CASH-SPY",
        notes="",
        recorded_by="officer-1",
        idempotency_key="officer:officer-1:request-spy",
        verification_source="officer_manual",
    )

    assert payment.payment_status == "posted"
    assert installment["paid_amount"] == 100
    assert spy.call_count >= 2


def test_incomplete_customer_provider_payment_endpoint_is_disabled(
    schedule, monkeypatch
):
    app = SimpleNamespace(customer_id=schedule.customer_id, status="disbursed")
    monkeypatch.setattr(
        "loans.views.customer.repayment.LoanApplication.find_by_id", lambda _id: app
    )
    monkeypatch.setattr(
        PaymentHistoryView,
        "check_customer_permission",
        lambda self, request: (True, None),
    )
    request = MagicMock(
        data={
            "installment_number": 1,
            "amount": 250,
            "payment_method": "gcash",
            "reference": "GCASH-ENDPOINT-1",
        },
        headers={"Idempotency-Key": "customer-endpoint-1"},
        user=SimpleNamespace(customer_id=schedule.customer_id),
        META={"REMOTE_ADDR": "127.0.0.1"},
    )

    response = PaymentHistoryView().post(request, schedule.loan_id)

    assert response.status_code == 503
    assert response.data["code"] == "SETTLEMENT_RAIL_UNAVAILABLE"
    reloaded = RepaymentSchedule.find_by_loan(schedule.loan_id)
    assert reloaded.get_installment(1)["paid_amount"] == 0
    assert LoanPayment.count({}) == 0


def test_customer_payment_endpoint_rejects_wallet_bypass(schedule, monkeypatch):
    app = SimpleNamespace(customer_id=schedule.customer_id, status="disbursed")
    monkeypatch.setattr(
        "loans.views.customer.repayment.LoanApplication.find_by_id", lambda _id: app
    )
    monkeypatch.setattr(
        PaymentHistoryView,
        "check_customer_permission",
        lambda self, request: (True, None),
    )
    request = MagicMock(
        data={
            "installment_number": 1,
            "amount": 250,
            "payment_method": "wallet",
            "reference": "UNVERIFIED-WALLET",
        },
        headers={"Idempotency-Key": "wallet-bypass-1"},
        user=SimpleNamespace(customer_id=schedule.customer_id),
        META={},
    )

    response = PaymentHistoryView().post(request, schedule.loan_id)

    assert response.status_code == 400
    assert LoanPayment.count({}) == 0


def test_officer_payment_endpoint_is_idempotent(schedule, monkeypatch):
    actor = SimpleNamespace(customer_id="officer-1")
    app = SimpleNamespace(id=schedule.loan_id)
    monkeypatch.setattr(
        RecordPaymentView,
        "check_officer_permission",
        lambda self, request: (True, actor),
    )
    monkeypatch.setattr(
        RecordPaymentView,
        "check_application_scope",
        lambda self, request, application, allow_unassigned: (True, None),
    )
    monkeypatch.setattr(
        "loans.views.officer.payments.LoanApplication.find_by_id", lambda _id: app
    )
    monkeypatch.setattr(
        "loans.views.officer.payments.AuditLog.log_action", lambda **kwargs: None
    )
    monkeypatch.setattr("loans.blockchain.sync.sync_payment", lambda *args: None)
    request = MagicMock(
        data={
            "loan_id": schedule.loan_id,
            "installment_number": 1,
            "amount": 1000,
            "payment_method": "cash",
            "reference": "CASH-ENDPOINT-1",
        },
        headers={"Idempotency-Key": "officer-endpoint-1"},
        user=actor,
        META={"REMOTE_ADDR": "127.0.0.1"},
    )
    view = RecordPaymentView()

    first = view.post(request)
    second = view.post(request)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["data"]["replayed"] is True
    assert LoanPayment.count({}) == 1
    reloaded = RepaymentSchedule.find_by_loan(schedule.loan_id)
    assert reloaded.get_installment(1)["paid_amount"] == 1000
    assert reloaded.get_installment(1)["status"] == "paid"


def test_wallet_replay_returns_stored_rate_without_blockchain_lookup(
    schedule, monkeypatch
):
    tx_hash = "0x" + "a" * 64
    payment = LoanPayment(
        loan_id=schedule.loan_id,
        schedule_id=schedule.id,
        customer_id=schedule.customer_id,
        installment_number=1,
        amount=1000,
        payment_method="wallet",
        payment_status="posted",
        eth_tx_hash=tx_hash,
        eth_amount="0.005",
        eth_rate=200000,
        eth_block_number=100,
    )
    payment.save()
    app = SimpleNamespace(customer_id=schedule.customer_id, status="disbursed")
    monkeypatch.setattr(
        "loans.views.customer.blockchain.LoanApplication.find_by_id", lambda _id: app
    )
    monkeypatch.setattr(
        WalletPaymentView,
        "check_customer_permission",
        lambda self, request: (True, None),
    )
    request = MagicMock(
        data={"tx_hash": tx_hash, "installment_number": 1},
        user=SimpleNamespace(customer_id=schedule.customer_id),
        META={},
    )

    response = WalletPaymentView().post(request, schedule.loan_id)

    assert response.status_code == 200
    assert response.data["data"]["replayed"] is True
    assert response.data["data"]["eth_rate"] == 200000
