"""Opt-in Stage 2 concurrency proof against an isolated real MongoDB."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from pymongo import MongoClient

from loans.models import LoanApplication, LoanTransitionConflict, RepaymentSchedule

pytestmark = [pytest.mark.deployment_integration, pytest.mark.real_mongo]


@pytest.fixture
def loans_real_mongo(settings, monkeypatch):
    uri = os.getenv("REAL_MONGO_TEST_URI")
    approved = os.getenv("RUN_LOANS_REAL_MONGO_TESTS") == "1"
    if not uri or not approved:
        pytest.skip(
            "Set REAL_MONGO_TEST_URI and RUN_LOANS_REAL_MONGO_TESTS=1 for an "
            "explicitly approved isolated MongoDB target"
        )

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    database_name = f"loans_stage2_{uuid.uuid4().hex[:18]}_isolated"
    database = client[database_name]
    monkeypatch.setattr(settings, "MONGODB", database)
    monkeypatch.setattr(
        settings, "FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    try:
        yield database
    finally:
        client.drop_database(database_name)
        client.close()


def _real_application(**overrides):
    values = {
        "customer_id": str(ObjectId()),
        "product_id": str(ObjectId()),
        "requested_amount": 10_000,
        "term_months": 1,
        "status": "under_review",
        "assigned_officer": "officer-a",
    }
    values.update(overrides)
    return LoanApplication(**values).save()


def test_real_mongo_review_assignment_and_notes_are_atomic(loans_real_mongo):
    review = _real_application()

    def decide(action):
        copy = LoanApplication.find_by_id(review.id)
        try:
            if action == "approve":
                copy.approve("officer-a", 9_000)
            else:
                copy.reject("officer-a", "declined")
            return "won"
        except LoanTransitionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(decide, ("approve", "reject"))) == [
            "conflict",
            "won",
        ]

    assignment = _real_application(status="submitted", assigned_officer=None)

    def assign(officer):
        copy = LoanApplication.find_by_id(assignment.id)
        try:
            copy.assign_officer(officer, actor_type="system")
            return "won"
        except LoanTransitionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(assign, ("officer-a", "officer-b"))) == [
            "conflict",
            "won",
        ]

    notes = _real_application()

    def append(index):
        copy = LoanApplication.find_by_id(notes.id)
        copy.add_internal_note("officer-a", "loan_officer", f"note-{index}")

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(append, range(12)))
    stored = LoanApplication.find_by_id(notes.id)
    assert len(stored.internal_notes) == 12


def test_real_mongo_schedule_payment_and_payoff_tokens_are_once_only(
    loans_real_mongo,
):
    schedule = RepaymentSchedule(
        loan_id=str(ObjectId()),
        customer_id=str(ObjectId()),
        principal=1_000,
        total_amount=1_000,
        installments=[
            {
                "number": 1,
                "principal": 1_000,
                "interest": 0,
                "total_amount": 1_000,
                "paid_amount": 0,
                "status": "pending",
            }
        ],
    ).save()

    def apply_payment(_index):
        copy = RepaymentSchedule.find_one({"_id": schedule._id})
        return copy.apply_payment_atomic(1, 400, "payment-once-token")[1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        replay_flags = list(executor.map(apply_payment, range(2)))
    stored = RepaymentSchedule.find_one({"_id": schedule._id})
    assert sorted(replay_flags) == [False, True]
    assert stored.get_installment(1)["paid_amount"] == 400

    def apply_payoff(_index):
        copy = RepaymentSchedule.find_one({"_id": schedule._id})
        return copy.apply_early_payoff_atomic(600, "payoff-once-token")[1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        replay_flags = list(executor.map(apply_payoff, range(2)))
    stored = RepaymentSchedule.find_one({"_id": schedule._id})
    assert sorted(replay_flags) == [False, True]
    assert stored.status == "paid_off"


def test_real_mongo_disbursement_claim_has_one_winner(loans_real_mongo):
    application = _real_application(
        status="approved",
        assigned_officer="officer-a",
        approved_amount=10_000,
    )

    def claim(index):
        copy = LoanApplication.find_by_id(application.id)
        try:
            copy.begin_disbursement(
                amount=10_000,
                method="cash",
                reference=f"STAGE2-{index}",
                processed_by="officer-a",
                processed_by_type="loan_officer",
                idempotency_key=f"stage2-disbursement-{index}",
            )
            return "won"
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, range(2)))
    stored = LoanApplication.find_by_id(application.id)
    assert sorted(results) == ["conflict", "won"]
    assert stored.disbursement_status == "pending"
