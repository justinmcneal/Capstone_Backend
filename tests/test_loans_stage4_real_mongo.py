"""Opt-in Stage 4 validator, index, and query-plan proof on isolated MongoDB."""

import os
import uuid

import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, OperationFailure

from loans.blockchain.models import BlockchainTransaction
from loans.models import (
    LoanApplication,
    LoanNotificationDelivery,
    LoanPayment,
    LoanProduct,
    RepaymentSchedule,
)
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


def _plan_uses_index(plan, index_name):
    if isinstance(plan, dict):
        return plan.get("indexName") == index_name or any(
            _plan_uses_index(value, index_name) for value in plan.values()
        )
    if isinstance(plan, list):
        return any(_plan_uses_index(value, index_name) for value in plan)
    return False


def _assert_indexed_plan(database, collection, query, sort, index_name, limit=20):
    explain = database.command(
        "explain",
        {"find": collection, "filter": query, "sort": sort, "limit": limit},
        verbosity="executionStats",
    )
    assert _plan_has_stage(explain["queryPlanner"]["winningPlan"], "IXSCAN")
    assert _plan_uses_index(explain["queryPlanner"]["winningPlan"], index_name)
    return explain


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
    monkeypatch.setattr(
        settings, "FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    for collection_name in LOAN_VALIDATORS:
        database.create_collection(collection_name)
    LoanProduct.create_indexes()
    LoanApplication.create_indexes()
    RepaymentSchedule.create_indexes()
    LoanPayment.create_indexes()
    BlockchainTransaction.create_indexes()
    LoanNotificationDelivery.create_indexes()
    install_loan_validators()
    try:
        yield database
    finally:
        client.drop_database(database_name)
        client.close()


def test_stage4_real_mongo_validators_indexes_and_reference_plan(
    loans_stage4_real_mongo,
):
    database = loans_stage4_real_mongo
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

    invalid_documents = {
        LoanProduct.collection_name: {"name": 1, "code": "INVALID"},
        LoanApplication.collection_name: {
            "customer_id": application.customer_id,
            "status": "not-valid",
        },
        RepaymentSchedule.collection_name: {
            "loan_id": application.id,
            "status": "not-valid",
        },
        LoanPayment.collection_name: {
            "loan_id": application.id,
            "payment_status": "not-valid",
        },
        BlockchainTransaction.collection_name: {
            "loan_id": application.id,
            "status": "not-valid",
        },
    }
    for collection_name, invalid in invalid_documents.items():
        with pytest.raises(OperationFailure):
            database[collection_name].insert_one(invalid)

    query = {"reference_search_index": LoanPayment.blind_index_reference("STAGE4-321")}
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

    plan_matrix = (
        (
            LoanApplication.collection_name,
            {"customer_id": application.customer_id, "status": "disbursed"},
            {"created_at": -1, "_id": -1},
            "application_customer_status_page",
        ),
        (
            LoanApplication.collection_name,
            {"assigned_officer": "officer-stage4", "status": "disbursed"},
            {"submitted_at": -1, "_id": -1},
            "application_officer_status_page",
        ),
        (
            LoanApplication.collection_name,
            {
                "status": "disbursed",
                "disbursement_status": "executed",
                "disbursement_method": "cash",
            },
            {"_id": 1},
            "application_disbursement_reconcile",
        ),
        (
            LoanApplication.collection_name,
            {
                "legal_hold": False,
                "retention_expires_at": {"$lte": utcnow()},
                "status": "disbursed",
            },
            {"_id": 1},
            "loan_retention_cleanup",
        ),
        (
            RepaymentSchedule.collection_name,
            {"status": "active"},
            {"_id": 1},
            "schedule_status_job_scan",
        ),
        (
            RepaymentSchedule.collection_name,
            {"customer_id": application.customer_id},
            {"created_at": -1, "_id": -1},
            "schedule_customer_created_page",
        ),
        (
            LoanPayment.collection_name,
            {"scope_officer_id": "officer-stage4"},
            {"recorded_at": -1, "_id": -1},
            "payment_officer_scope_sort",
        ),
        (
            LoanPayment.collection_name,
            {"loan_id": application.id, "payment_status": "posted"},
            {"recorded_at": -1},
            "payment_loan_status_sort",
        ),
        (
            LoanPayment.collection_name,
            {"loan_disbursed": True, "timing_status": "on_time"},
            {"recorded_at": -1},
            "payment_lifecycle_timing_sort",
        ),
        (
            BlockchainTransaction.collection_name,
            {"status": "pending"},
            {"created_at": 1, "_id": 1},
            "blockchain_status_reconcile",
        ),
        (
            LoanNotificationDelivery.collection_name,
            {"status": "pending", "next_attempt_at": {"$lte": utcnow()}},
            {"next_attempt_at": 1, "_id": 1},
            "loan_notification_due",
        ),
    )
    for collection_name, query, sort, index_name in plan_matrix:
        _assert_indexed_plan(database, collection_name, query, sort, index_name)

    with pytest.raises(DuplicateKeyError):
        LoanProduct(name="Duplicate", code="STAGE4").save()
    with pytest.raises(DuplicateKeyError):
        RepaymentSchedule(
            loan_id=application.id,
            customer_id=application.customer_id,
            principal=1,
            total_amount=1,
            installments=[],
        ).save()
    duplicate = documents[0].copy()
    duplicate.pop("_id", None)
    duplicate["reference_search_index"] = ""
    with pytest.raises(DuplicateKeyError):
        database[LoanPayment.collection_name].insert_one(duplicate)
