"""Complete isolated cash/check lifecycle release smoke test."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import mongomock
import pytest
from bson import ObjectId
from cryptography.fernet import Fernet

from loans.models import (
    LoanApplication,
    LoanNotificationDelivery,
    LoanPayment,
    LoanProduct,
    LoanTransitionConflict,
    RepaymentSchedule,
)
from loans.services.disbursement import (
    disbursement_idempotency_key,
    execute_manual_disbursement,
)
from loans.services.notifications import queue_customer_loan_notification
from loans.services.payment import (
    post_verified_early_payoff,
    post_verified_payment,
    scoped_idempotency_key,
)


@pytest.fixture
def cash_check_release_db(settings):
    database = mongomock.MongoClient()["loans_cash_check_release_smoke"]
    settings.MONGODB = database
    settings.BLOCKCHAIN_ENABLED = False
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    LoanProduct.create_indexes()
    LoanApplication.create_indexes()
    RepaymentSchedule.create_indexes()
    LoanPayment.create_indexes()
    LoanNotificationDelivery.create_indexes()
    return database


def test_complete_cash_check_lifecycle_is_scoped_idempotent_and_recoverable(
    cash_check_release_db, monkeypatch
):
    customer_id = str(ObjectId())
    other_customer_id = str(ObjectId())
    officer_id = str(ObjectId())
    other_officer_id = str(ObjectId())
    customer = SimpleNamespace(
        id=customer_id,
        email="synthetic-release-customer@example.test",
        full_name="Synthetic Release Customer",
    )
    enqueue = MagicMock()
    monkeypatch.setattr("loans.tasks.deliver_loan_notification_task.delay", enqueue)

    product = LoanProduct(
        name="Cash Check Release Product",
        code="CASH-CHECK-RELEASE",
        min_amount=1_000,
        max_amount=50_000,
        interest_rate=0.01,
        min_term_months=1,
        max_term_months=12,
        active=True,
    ).save()
    application = LoanApplication(
        customer_id=customer_id,
        product_id=product.id,
        requested_amount=10_000,
        term_months=2,
        purpose="Synthetic working-capital release test",
        status="draft",
    ).save()

    application.submit()
    submitted_transition = application.last_transition_id
    queue_customer_loan_notification(
        loan_id=application.id,
        event_type="submitted",
        event_key=submitted_transition,
        customer=customer,
        payload={"product_name": product.name, "amount": 10_000},
    )
    application.assign_officer(
        officer_id,
        actor_id="release-admin",
        actor_type="admin",
    )

    with pytest.raises(LoanTransitionConflict):
        LoanApplication.find_by_id(application.id).approve(other_officer_id, 10_000)
    assert LoanApplication.find({"customer_id": other_customer_id}) == []
    assert LoanApplication.find_by_officer(other_officer_id) == []
    assert [item.id for item in LoanApplication.find_by_officer(officer_id)] == [
        application.id
    ]

    application.approve(officer_id, 10_000, notes="Approved synthetic case")
    approved_transition = application.last_transition_id
    queue_customer_loan_notification(
        loan_id=application.id,
        event_type="approved",
        event_key=approved_transition,
        customer=customer,
        payload={"approved_amount": 10_000},
    )
    # Repeating a delivery event reuses the same durable outbox record.
    queue_customer_loan_notification(
        loan_id=application.id,
        event_type="approved",
        event_key=approved_transition,
        customer=customer,
        payload={"approved_amount": 10_000},
    )

    disbursement_key = disbursement_idempotency_key(
        officer_id, "cash-release-disbursement"
    )
    application, schedule, replayed = execute_manual_disbursement(
        application=application,
        amount=10_000,
        method="cash",
        reference="CASH-RELEASE-001",
        actor_id=officer_id,
        actor_type="loan_officer",
        idempotency_key=disbursement_key,
    )
    replay_application, replay_schedule, second_replayed = execute_manual_disbursement(
        application=application,
        amount=10_000,
        method="cash",
        reference="CASH-RELEASE-001",
        actor_id=officer_id,
        actor_type="loan_officer",
        idempotency_key=disbursement_key,
    )
    assert replayed is False
    assert second_replayed is True
    assert replay_application.status == "disbursed"
    assert replay_schedule.id == schedule.id
    assert (
        cash_check_release_db[RepaymentSchedule.collection_name].count_documents(
            {"loan_id": application.id}
        )
        == 1
    )

    queue_customer_loan_notification(
        loan_id=application.id,
        event_type="disbursed",
        event_key=application.last_transition_id,
        customer=customer,
        payload={
            "amount": 10_000,
            "method": "cash",
            "reference": "CASH-RELEASE-001",
        },
    )
    first_due = schedule.get_installment(1)["total_amount"]
    first_payment_key = scoped_idempotency_key(
        "officer-payment", officer_id, "check-release-payment"
    )
    payment, installment, payment_replayed = post_verified_payment(
        schedule=schedule,
        installment_number=1,
        amount=first_due,
        payment_method="check",
        reference="CHECK-RELEASE-001",
        notes="Synthetic first installment",
        recorded_by=officer_id,
        recorded_by_type="loan_officer",
        idempotency_key=first_payment_key,
        verification_source="officer_manual",
    )
    replay_payment, replay_installment, payment_second_replayed = post_verified_payment(
        schedule=schedule,
        installment_number=1,
        amount=first_due,
        payment_method="check",
        reference="CHECK-RELEASE-001",
        notes="Synthetic first installment",
        recorded_by=officer_id,
        recorded_by_type="loan_officer",
        idempotency_key=first_payment_key,
        verification_source="officer_manual",
    )
    assert payment_replayed is False
    assert payment_second_replayed is True
    assert replay_payment.id == payment.id
    assert installment["status"] == replay_installment["status"] == "paid"

    schedule = RepaymentSchedule.find_by_loan(application.id)
    payoff_amount = schedule.get_early_payoff_amount()
    payoff_key = scoped_idempotency_key(
        "officer-payoff", officer_id, "cash-release-payoff"
    )
    payoff, allocations, payoff_replayed = post_verified_early_payoff(
        schedule=schedule,
        amount=payoff_amount,
        payment_method="cash",
        reference="CASH-RELEASE-PAYOFF",
        notes="Synthetic exact payoff",
        recorded_by=officer_id,
        recorded_by_type="loan_officer",
        idempotency_key=payoff_key,
        verification_source="officer_manual_payoff",
    )
    replay_payoff, replay_allocations, payoff_second_replayed = (
        post_verified_early_payoff(
            schedule=schedule,
            amount=payoff_amount,
            payment_method="cash",
            reference="CASH-RELEASE-PAYOFF",
            notes="Synthetic exact payoff",
            recorded_by=officer_id,
            recorded_by_type="loan_officer",
            idempotency_key=payoff_key,
            verification_source="officer_manual_payoff",
        )
    )
    completed = LoanApplication.find_by_id(application.id)
    settled = RepaymentSchedule.find_by_loan(application.id)
    assert payoff_replayed is False
    assert payoff_second_replayed is True
    assert replay_payoff.id == payoff.id
    assert replay_allocations == allocations
    assert settled.status == "paid_off"
    assert settled.get_remaining_balance_centavos() == 0
    assert completed.status == "completed"
    assert completed.repayment_status == "paid_off"
    assert LoanPayment.count({"loan_id": application.id}) == 2

    delivery_count = cash_check_release_db[
        LoanNotificationDelivery.collection_name
    ].count_documents({"loan_id": application.id})
    assert delivery_count == 3
    assert enqueue.call_count == 4
    actions = [item["action"] for item in completed.lifecycle_transitions]
    assert actions == [
        "loan_submitted",
        "loan_assigned",
        "loan_approved",
    ]
    audit_documents = list(cash_check_release_db["audit_logs"].find({}))
    audit_actions = {item["action"] for item in audit_documents}
    assert {
        "loan_assigned",
        "loan_disbursement_pending",
        "loan_disbursed",
        "loan_paid_off",
    } <= audit_actions
