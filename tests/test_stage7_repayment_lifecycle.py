"""Stage 7 exact-money, normalized-state, and paid-off lifecycle tests."""

from datetime import timedelta
from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from loans.models import LoanApplication, LoanPayment, RepaymentSchedule
from loans.services.payment import post_verified_early_payoff, post_verified_payment
from loans.utils.money import from_centavos, to_centavos
from loans.utils.time import utcnow
from loans.views.officer.payoff import EarlyPayoffView
from loans.tasks import reconcile_repayment_lifecycle_task


@pytest.fixture
def stage7_db(settings):
    db = mongomock.MongoClient()["stage7"]
    settings.MONGODB = db
    LoanPayment.create_indexes()
    return db


def _installment(number, amount, *, due_date=None):
    amount_centavos = to_centavos(amount)
    return {
        "number": number,
        "due_date": due_date or utcnow() + timedelta(days=30 * number),
        "principal": from_centavos(amount_centavos),
        "principal_centavos": amount_centavos,
        "interest": 0,
        "interest_centavos": 0,
        "total_amount": from_centavos(amount_centavos),
        "total_amount_centavos": amount_centavos,
        "paid_amount": 0,
        "paid_amount_centavos": 0,
        "status": "pending",
        "penalty_status": None,
        "penalty_amount": 0,
        "penalty_amount_centavos": 0,
    }


def _persisted_loan_and_schedule(stage7_db, amounts=(500, 500)):
    application = LoanApplication(
        customer_id=str(ObjectId()),
        product_id=str(ObjectId()),
        requested_amount=sum(amounts),
        approved_amount=sum(amounts),
        disbursed_amount=sum(amounts),
        status="disbursed",
        repayment_status="active",
    ).save()
    total_centavos = sum(to_centavos(amount) for amount in amounts)
    schedule = RepaymentSchedule(
        loan_id=application.id,
        customer_id=application.customer_id,
        principal=from_centavos(total_centavos),
        principal_centavos=total_centavos,
        total_amount=from_centavos(total_centavos),
        total_amount_centavos=total_centavos,
        term_months=len(amounts),
        installments=[
            _installment(index, amount) for index, amount in enumerate(amounts, start=1)
        ],
    ).save()
    return application, schedule


def test_money_conversion_uses_half_up_integer_centavos():
    assert to_centavos("10.005") == 1001
    assert to_centavos(0.1 + 0.2) == 30
    assert from_centavos(1001) == 10.01


def test_generation_reconciles_principal_remainder_in_final_installment(
    stage7_db,
):
    application = SimpleNamespace(
        id=str(ObjectId()),
        customer_id=str(ObjectId()),
        disbursed_amount=100,
        approved_amount=100,
        term_months=3,
        disbursed_at=utcnow(),
    )
    product = SimpleNamespace(interest_rate=0)

    schedule = RepaymentSchedule.generate_for_loan(application, product)

    principal_parts = [item["principal_centavos"] for item in schedule.installments]
    assert principal_parts == [3333, 3333, 3334]
    assert sum(principal_parts) == schedule.principal_centavos == 10_000
    assert (
        sum(item["total_amount_centavos"] for item in schedule.installments)
        == schedule.total_amount_centavos
    )


def test_partial_overdue_state_is_preserved_and_is_next_payment(stage7_db):
    _, schedule = _persisted_loan_and_schedule(stage7_db, amounts=(100, 100))
    first = schedule.installments[0]
    first["due_date"] = utcnow() - timedelta(days=1)
    first["paid_amount"] = 25
    first["paid_amount_centavos"] = 2500
    first["status"] = "partial"
    schedule.save()

    assert schedule.mark_overdue_installments() == [1]
    assert schedule.get_next_payment()["status"] == "partial_overdue"
    assert schedule.get_next_payment()["number"] == 1


def test_penalty_waiver_normalizes_partial_payment_and_records_credit(stage7_db):
    _, schedule = _persisted_loan_and_schedule(stage7_db, amounts=(100,))
    schedule.apply_penalty(1, 20, "Late", "officer-1")
    schedule.record_payment(1, 110)

    waived = schedule.waive_penalty(1, "Approved waiver", "officer-2")

    assert waived["status"] == "paid"
    assert waived["paid_amount_centavos"] == 10_000
    assert waived["waiver_credit_centavos"] == 1_000
    assert waived["waiver_credit_amount"] == 10
    assert schedule.get_remaining_balance() == 0


def test_final_installment_payment_marks_schedule_and_application_paid_off(stage7_db):
    application, schedule = _persisted_loan_and_schedule(stage7_db, amounts=(100,))

    payment, installment, replayed = post_verified_payment(
        schedule=schedule,
        installment_number=1,
        amount=100,
        payment_method="cash",
        reference="CASH-FINAL",
        notes="",
        recorded_by="officer-1",
        idempotency_key="officer:final-payment-1",
        verification_source="officer_manual",
    )

    reloaded_schedule = RepaymentSchedule.find_by_loan(application.id)
    reloaded_application = LoanApplication.find_by_id(application.id)
    assert replayed is False
    assert payment.payment_status == "posted"
    assert installment["status"] == "paid"
    assert reloaded_schedule.status == "paid_off"
    assert reloaded_schedule.paid_off_at is not None
    assert reloaded_application.status == "completed"
    assert reloaded_application.repayment_status == "paid_off"
    assert reloaded_application.paid_off_at is not None


def test_verified_early_payoff_allocates_all_open_installments_once(stage7_db):
    application, schedule = _persisted_loan_and_schedule(
        stage7_db, amounts=(100, 200, 300)
    )
    schedule.record_payment(1, 25)
    payoff_amount = schedule.get_early_payoff_amount()
    kwargs = {
        "schedule": schedule,
        "amount": payoff_amount,
        "payment_method": "check",
        "reference": "CHECK-PAYOFF-1",
        "notes": "Early settlement",
        "recorded_by": "officer-1",
        "idempotency_key": "officer-payoff:request-1",
        "verification_source": "officer_manual_payoff",
    }

    payment, allocations, replayed = post_verified_early_payoff(**kwargs)
    replay_payment, replay_allocations, second_replayed = post_verified_early_payoff(
        **kwargs
    )

    completed = LoanApplication.find_by_id(application.id)
    settled = RepaymentSchedule.find_by_loan(application.id)
    assert replayed is False
    assert second_replayed is True
    assert replay_payment.id == payment.id
    assert replay_allocations == allocations
    assert sum(item["amount_centavos"] for item in allocations) == to_centavos(
        payoff_amount
    )
    assert settled.get_remaining_balance_centavos() == 0
    assert settled.status == "paid_off"
    assert completed.status == "completed"
    assert payment.blockchain_sync_status == "not_applicable"


def test_officer_early_payoff_endpoint_quotes_and_posts(stage7_db, monkeypatch):
    application, schedule = _persisted_loan_and_schedule(stage7_db, amounts=(100, 200))
    monkeypatch.setattr(
        EarlyPayoffView,
        "check_officer_permission",
        lambda self, request: (True, request.user),
    )
    monkeypatch.setattr(
        EarlyPayoffView,
        "check_application_scope",
        lambda self, request, app, **kwargs: (True, request.user),
    )
    monkeypatch.setattr(
        "loans.views.officer.payoff.AuditLog.log_action", lambda **kwargs: None
    )
    user = AuthenticatedUser(
        customer_id=str(ObjectId()),
        email="officer@example.com",
        verified=True,
        role="loan_officer",
    )
    url = reverse(
        "loans:officer-early-payoff",
        kwargs={"application_id": application.id},
    )

    quote_request = APIRequestFactory().get(url)
    force_authenticate(quote_request, user=user)
    quote = EarlyPayoffView.as_view()(quote_request, application_id=application.id)

    post_request = APIRequestFactory().post(
        url,
        {
            "amount": quote.data["data"]["payoff_amount"],
            "payment_method": "cash",
            "reference": "CASH-PAYOFF-ENDPOINT",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="payoff-endpoint-request-1",
    )
    force_authenticate(post_request, user=user)
    posted = EarlyPayoffView.as_view()(post_request, application_id=application.id)

    assert quote.status_code == 200
    assert quote.data["data"]["payoff_amount_centavos"] == 30_000
    assert posted.status_code == 200
    assert posted.data["data"]["status"] == "completed"
    assert posted.data["data"]["remaining_balance"] == 0
    assert RepaymentSchedule.find_by_loan(schedule.loan_id).status == "paid_off"


def test_early_payoff_recovers_after_schedule_update_before_posting(
    stage7_db, monkeypatch
):
    application, schedule = _persisted_loan_and_schedule(stage7_db, amounts=(125, 275))
    original_mark_posted = LoanPayment.mark_posted
    calls = {"count": 0}

    def interrupt_once(self, verification_source):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("interrupted after payoff schedule update")
        return original_mark_posted(self, verification_source)

    monkeypatch.setattr(LoanPayment, "mark_posted", interrupt_once)
    kwargs = {
        "schedule": schedule,
        "amount": 400,
        "payment_method": "cash",
        "reference": "CASH-PAYOFF-RECOVERY",
        "notes": "",
        "recorded_by": "officer-1",
        "idempotency_key": "officer-payoff:recovery-1",
        "verification_source": "officer_manual_payoff",
    }

    with pytest.raises(RuntimeError, match="interrupted"):
        post_verified_early_payoff(**kwargs)

    payment, allocations, replayed = post_verified_early_payoff(**kwargs)

    assert replayed is True
    assert payment.payment_status == "posted"
    assert len(allocations) == 2
    assert LoanApplication.find_by_id(application.id).status == "completed"


def test_reconciliation_closes_legacy_zero_balance_schedule(stage7_db):
    application, schedule = _persisted_loan_and_schedule(stage7_db, amounts=(100,))
    schedule.installments[0].update(
        {
            "paid_amount": 100,
            "paid_amount_centavos": 10_000,
            "status": "paid",
        }
    )
    schedule.status = "active"
    schedule.save()

    result = reconcile_repayment_lifecycle_task()

    assert result == {"paid_off_reconciled": 1}
    assert RepaymentSchedule.find_by_loan(application.id).status == "paid_off"
    assert LoanApplication.find_by_id(application.id).status == "completed"
