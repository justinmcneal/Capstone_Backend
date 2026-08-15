"""Integrity tests for durable disbursement state transitions."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import mongomock
import pytest
from bson import ObjectId

from loans.models import LoanApplication, LoanProduct, RepaymentSchedule
from loans.services.disbursement import (
    begin_disbursement,
    execute_manual_disbursement,
)
from loans.views.officer.disburse import DisburseView


@pytest.fixture
def disbursement_db(settings):
    db = mongomock.MongoClient()["disbursement_integrity"]
    settings.MONGODB = db
    LoanApplication.create_indexes()
    RepaymentSchedule.create_indexes()
    return db


@pytest.fixture
def approved_application(disbursement_db):
    product = LoanProduct(
        name="Integrity Product",
        code=f"INT-{ObjectId()}",
        interest_rate=0.01,
    ).save()
    application = LoanApplication(
        customer_id=str(ObjectId()),
        product_id=product.id,
        requested_amount=20000,
        approved_amount=18000,
        term_months=6,
        status="approved",
        assigned_officer="officer-1",
    ).save()
    return application


def test_disbursement_amount_must_equal_approved_amount(approved_application):
    with pytest.raises(ValueError, match="must equal approved amount"):
        execute_manual_disbursement(
            application=approved_application,
            amount=20000,
            method="cash",
            reference="CASH-WRONG-AMOUNT",
            actor_id="officer-1",
            idempotency_key="disbursement:wrong-amount",
        )

    reloaded = LoanApplication.find_by_id(approved_application.id)
    assert reloaded.status == "approved"
    assert reloaded.disbursement_status == "not_started"
    assert RepaymentSchedule.find_by_loan(approved_application.id) is None


def test_manual_disbursement_creates_schedule_before_completion(approved_application):
    application, schedule, replayed = execute_manual_disbursement(
        application=approved_application,
        amount=18000,
        method="cash",
        reference="CASH-EXECUTED-1",
        actor_id="officer-1",
        idempotency_key="disbursement:manual-success",
    )

    assert replayed is False
    assert schedule is not None
    assert application.status == "disbursed"
    assert application.disbursement_status == "executed"
    assert application.disbursed_amount == 18000
    assert application.disbursed_at is not None


def test_manual_disbursement_replay_does_not_duplicate_schedule(approved_application):
    kwargs = {
        "application": approved_application,
        "amount": 18000,
        "method": "check",
        "reference": "CHECK-REPLAY-1",
        "actor_id": "officer-1",
        "idempotency_key": "disbursement:manual-replay",
    }
    _first_app, first_schedule, first_replay = execute_manual_disbursement(**kwargs)
    second_app, second_schedule, second_replay = execute_manual_disbursement(**kwargs)

    assert first_replay is False
    assert second_replay is True
    assert second_app.status == "disbursed"
    assert second_schedule.id == first_schedule.id
    assert RepaymentSchedule.find_by_customer(approved_application.customer_id)
    assert len(RepaymentSchedule.find_by_customer(approved_application.customer_id)) == 1


def test_schedule_failure_keeps_application_approved(approved_application, monkeypatch):
    monkeypatch.setattr(
        RepaymentSchedule,
        "generate_for_loan",
        lambda application, product: (_ for _ in ()).throw(
            RuntimeError("schedule storage unavailable")
        ),
    )

    with pytest.raises(RuntimeError, match="schedule storage unavailable"):
        execute_manual_disbursement(
            application=approved_application,
            amount=18000,
            method="cash",
            reference="CASH-FAIL-1",
            actor_id="officer-1",
            idempotency_key="disbursement:schedule-failure",
        )

    reloaded = LoanApplication.find_by_id(approved_application.id)
    assert reloaded.status == "approved"
    assert reloaded.disbursement_status == "failed"
    assert "schedule storage unavailable" in reloaded.disbursement_error
    assert reloaded.disbursed_at is None


def test_incomplete_provider_disbursement_is_disabled(approved_application):
    with pytest.raises(ValueError, match="provider integration"):
        begin_disbursement(
            application=approved_application,
            amount=18000,
            method="bank_transfer",
            reference="BANK-PENDING-1",
            actor_id="officer-1",
            idempotency_key="disbursement:bank-pending",
        )

    application = LoanApplication.find_by_id(approved_application.id)
    assert application.status == "approved"
    assert application.disbursement_status == "not_started"
    assert RepaymentSchedule.find_by_loan(application.id) is None


def test_disbursement_idempotency_rejects_changed_payload(
    approved_application, settings
):
    settings.BLOCKCHAIN_ENABLED = True
    begin_disbursement(
        application=approved_application,
        amount=18000,
        method="wallet",
        reference="WALLET-PENDING-1",
        actor_id="officer-1",
        idempotency_key="disbursement:wallet-pending",
    )

    with pytest.raises(ValueError, match="different disbursement"):
        begin_disbursement(
            application=approved_application,
            amount=18000,
            method="wallet",
            reference="WALLET-CHANGED",
            actor_id="officer-1",
            idempotency_key="disbursement:wallet-pending",
        )


def test_external_disbursement_endpoint_returns_202_pending(
    approved_application, monkeypatch, settings
):
    settings.BLOCKCHAIN_ENABLED = True
    actor = SimpleNamespace(customer_id="officer-1")
    monkeypatch.setattr(
        DisburseView,
        "check_officer_permission",
        lambda self, request: (True, actor),
    )
    monkeypatch.setattr(
        DisburseView,
        "check_application_scope",
        lambda self, request, application, allow_unassigned: (True, None),
    )
    monkeypatch.setattr(
        "loans.views.officer.disburse.AuditLog.log_action", lambda **kwargs: None
    )
    enqueue = MagicMock()
    monkeypatch.setattr(
        "loans.tasks.execute_wallet_disbursement_task.delay", enqueue
    )
    request = MagicMock(
        data={"method": "wallet", "amount": 18000},
        headers={"Idempotency-Key": "wallet-endpoint-request"},
        META={"REMOTE_ADDR": "127.0.0.1"},
    )

    response = DisburseView().post(request, approved_application.id)

    assert response.status_code == 202
    assert response.data["data"]["status"] == "approved"
    assert response.data["data"]["disbursement_status"] == "pending"
    assert response.data["data"]["eth_disbursement_tx_hash"] is None
    assert RepaymentSchedule.find_by_loan(approved_application.id) is None
    enqueue.assert_called_once_with(approved_application.id)


def test_disbursement_endpoint_requires_idempotency_key(
    approved_application, monkeypatch
):
    actor = SimpleNamespace(customer_id="officer-1")
    monkeypatch.setattr(
        DisburseView,
        "check_officer_permission",
        lambda self, request: (True, actor),
    )
    monkeypatch.setattr(
        DisburseView,
        "check_application_scope",
        lambda self, request, application, allow_unassigned: (True, None),
    )
    request = MagicMock(data={"method": "cash"}, headers={}, META={})

    response = DisburseView().post(request, approved_application.id)

    assert response.status_code == 400
    assert LoanApplication.find_by_id(approved_application.id).status == "approved"
