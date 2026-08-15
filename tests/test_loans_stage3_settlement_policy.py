"""Stage 3 regressions for settlement scope and accounting policy."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from bson import ObjectId
from rest_framework.test import APIRequestFactory, force_authenticate

from loans.models import LoanApplication, RepaymentSchedule
from loans.serializers import LoanApplicationSerializer
from loans.services.settlement_policy import (
    LOAN_ACCOUNTING_POLICY_VERSION,
    LOAN_SETTLEMENT_POLICY_VERSION,
    SettlementRailUnavailable,
    public_settlement_policy,
    require_disbursement_method,
)
from loans.views.customer.applications import SetDisbursementMethodView


def _application(**overrides):
    values = {
        "customer_id": str(ObjectId()),
        "product_id": str(ObjectId()),
        "requested_amount": 10_000,
        "approved_amount": 10_000,
        "term_months": 2,
        "status": "approved",
    }
    values.update(overrides)
    return LoanApplication(**values).save()


def _schedule(amounts=(100, 100)):
    return RepaymentSchedule(
        loan_id=str(ObjectId()),
        customer_id=str(ObjectId()),
        principal=sum(amounts),
        total_amount=sum(amounts),
        installments=[
            {
                "number": index,
                "principal": amount,
                "interest": 0,
                "total_amount": amount,
                "paid_amount": 0,
                "status": "pending",
                "penalty_status": None,
                "penalty_amount": 0,
            }
            for index, amount in enumerate(amounts, start=1)
        ],
    ).save()


def test_public_policy_exposes_only_completed_rails(settings):
    settings.BLOCKCHAIN_ENABLED = False
    baseline = public_settlement_policy()
    assert baseline["policy_version"] == LOAN_SETTLEMENT_POLICY_VERSION
    assert baseline["accounting_policy_version"] == LOAN_ACCOUNTING_POLICY_VERSION
    assert baseline["available_disbursement_methods"] == ["cash", "check"]
    assert baseline["available_customer_payment_methods"] == [
        "office_cash",
        "office_check",
    ]
    assert baseline["provider_payment_submission_enabled"] is False

    settings.BLOCKCHAIN_ENABLED = True
    blockchain = public_settlement_policy()
    assert blockchain["available_disbursement_methods"] == [
        "cash",
        "check",
        "wallet",
    ]
    assert blockchain["available_customer_payment_methods"][-1] == "wallet"


@pytest.mark.parametrize("method", ["gcash", "bank_transfer"])
def test_incomplete_provider_rails_are_rejected_at_service_and_serializer(method):
    with pytest.raises(SettlementRailUnavailable):
        require_disbursement_method(method)

    serializer = LoanApplicationSerializer(
        data={
            "product_id": str(ObjectId()),
            "requested_amount": 10_000,
            "term_months": 2,
            "preferred_disbursement_method": method,
        }
    )
    assert serializer.is_valid() is False
    assert "preferred_disbursement_method" in serializer.errors


def test_unavailable_customer_preference_returns_stable_503(monkeypatch):
    application = _application()
    user = SimpleNamespace(
        customer_id=application.customer_id,
        email="stage3@example.com",
        is_authenticated=True,
    )
    monkeypatch.setattr(
        SetDisbursementMethodView,
        "check_customer_permission",
        lambda self, request: (True, request.user),
    )
    request = APIRequestFactory().post(
        "/api/loans/applications/id/set-disbursement-method/",
        {"disbursement_method": "gcash"},
        format="json",
    )
    force_authenticate(request, user=user)

    response = SetDisbursementMethodView.as_view()(
        request, application_id=application.id
    )

    assert response.status_code == 503
    assert response.data["code"] == "SETTLEMENT_RAIL_UNAVAILABLE"
    assert (
        LoanApplication.find_by_id(application.id).preferred_disbursement_method is None
    )


def test_concurrent_penalty_application_has_one_winner():
    schedule = _schedule()

    def apply(amount):
        copy = RepaymentSchedule.find_one({"_id": schedule._id})
        try:
            copy.apply_penalty(1, amount, "Late", "officer-a")
            return "won"
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(apply, (10, 20)))

    stored = RepaymentSchedule.find_one({"_id": schedule._id})
    assert sorted(results) == ["conflict", "won"]
    assert stored.get_installment(1)["penalty_amount"] in {10, 20}
    assert stored.accounting_version == 1


def test_collected_waiver_credit_is_carried_to_next_installment():
    schedule = _schedule()
    schedule.apply_penalty(1, 20, "Late", "officer-a")
    schedule.record_payment(1, 110)

    waived = schedule.waive_penalty(1, "Approved", "officer-b")

    assert waived["waiver_credit_centavos"] == 1_000
    assert waived["waiver_credit_remaining_centavos"] == 0
    assert waived["waiver_credit_allocations"] == [
        {"installment_number": 2, "amount_centavos": 1_000, "amount": 10.0}
    ]
    assert schedule.get_installment(2)["paid_amount"] == 10


def test_waiver_that_requires_external_refund_is_rejected_without_mutation():
    schedule = _schedule(amounts=(100,))
    schedule.apply_penalty(1, 20, "Late", "officer-a")
    schedule.record_payment(1, 110)

    with pytest.raises(ValueError, match="unsupported external refund"):
        schedule.waive_penalty(1, "Approved", "officer-b")

    stored = RepaymentSchedule.find_one({"_id": schedule._id})
    installment = stored.get_installment(1)
    assert installment["penalty_status"] == "applied"
    assert installment["paid_amount"] == 110
