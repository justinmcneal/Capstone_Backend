"""Opt-in Stage 4 validator, index, and query-plan proof on isolated MongoDB."""

import os
import uuid

import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from pymongo import MongoClient
from pymongo.errors import OperationFailure

from loans.blockchain.models import BlockchainTransaction
from loans.models import LoanApplication, LoanPayment, LoanProduct, RepaymentSchedule
from loans.services.persistence import LOAN_VALIDATORS, install_loan_validators
from loans.utils.time import utcnow

pytestmark = [pytest.mark.deployment_integration, pytest.mark.real_mongo]


def _plan_has_stage(plan, stage):
    if isinstance(plan, dict):
        return plan.get("stage") == stage or any(
            _plan_has_stage(value, stage) for value in plan.values()
        )
    if isinstance(plan, list):
        return any(_plan_has_stage(value, stage) for value in plan)
    return False


@pytest.fixture
def loans_stage4_real_mongo(settings, monkeypatch):
    uri = os.getenv("REAL_MONGO_TEST_URI")
    approved = os.getenv("RUN_LOANS_STAGE4_REAL_MONGO_TESTS") == "1"
    if not uri or not approved:
        pytest.skip(
            "Set REAL_MONGO_TEST_URI and RUN_LOANS_STAGE4_REAL_MONGO_TESTS=1 "
            "for an explicitly approved isolated MongoDB target"
        )
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    database_name = f"loans_stage4_{uuid.uuid4().hex[:18]}_isolated"
    database = client[database_name]
    monkeypatch.setattr(settings, "MONGODB", database)
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    for collection_name in LOAN_VALIDATORS:
        database.create_collection(collection_name)
    try:
        yield database
    finally:
        client.drop_database(database_name)
        client.close()


def test_stage4_real_mongo_validators_indexes_and_reference_plan(
    loans_stage4_real_mongo,
):
    database = loans_stage4_real_mongo
    LoanProduct.create_indexes()
    LoanApplication.create_indexes()
    RepaymentSchedule.create_indexes()
    LoanPayment.create_indexes()
    BlockchainTransaction.create_indexes()
    install_loan_validators()

    product = LoanProduct(name="Stage 4", code="STAGE4").save()
    application = LoanApplication(
        customer_id=str(ObjectId()),
        product_id=product.id,
        requested_amount=10_000,
        approved_amount=10_000,
        term_months=2,
        status="disbursed",
        assigned_officer="officer-stage4",
    ).save()
    schedule = RepaymentSchedule(
        loan_id=application.id,
        customer_id=application.customer_id,
        principal=10_000,
        total_amount=10_000,
        installments=[
            {
                "number": 1,
                "principal": 5_000,
                "interest": 0,
                "total_amount": 5_000,
                "paid_amount": 0,
                "status": "pending",
                "due_date": utcnow(),
            },
            {
                "number": 2,
                "principal": 5_000,
                "interest": 0,
                "total_amount": 5_000,
                "paid_amount": 0,
                "status": "pending",
                "due_date": utcnow(),
            },
        ],
    ).save()

    documents = []
    for index in range(500):
        payment = LoanPayment(
            loan_id=application.id,
            schedule_id=schedule.id,
            customer_id=application.customer_id,
            installment_number=1,
            amount=index + 1,
            payment_method="cash",
            payment_status="posted",
            reference=f"STAGE4-{index}",
            idempotency_key=f"stage4-payment-{index}",
            reference_fingerprint=LoanPayment.fingerprint_reference(
                "cash", f"STAGE4-{index}"
            ),
            timing_status="on_time",
            scope_officer_id="officer-stage4",
            loan_disbursed=True,
            recorded_at=utcnow(),
        )
        documents.append(payment.to_dict())
    database[LoanPayment.collection_name].insert_many(documents)

    with pytest.raises(OperationFailure):
        database[LoanPayment.collection_name].insert_one(
            {"loan_id": application.id, "payment_status": "not-valid"}
        )

    query = {
        "reference_search_index": LoanPayment.blind_index_reference("STAGE4-321")
    }
    explain = database.command(
        "explain",
        {
            "find": LoanPayment.collection_name,
            "filter": query,
            "sort": {"recorded_at": -1, "_id": -1},
            "limit": 20,
        },
        verbosity="executionStats",
    )
    assert explain["executionStats"]["nReturned"] == 1
    assert explain["executionStats"]["totalDocsExamined"] <= 2
    assert _plan_has_stage(explain["queryPlanner"]["winningPlan"], "IXSCAN")
