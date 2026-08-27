"""Local lease, checkpoint, Beat, and worker-loss recovery evidence for Loans."""

from datetime import timedelta

import mongomock
import pytest
from bson import ObjectId
from cryptography.fernet import Fernet

from config.celery import app as celery_app
from loans.models import LoanApplication
from loans.services.job_control import acquire_job_lease, run_bounded_scan
from loans.utils.time import utcnow


@pytest.fixture
def worker_recovery_db(settings):
    database = mongomock.MongoClient()["loans_worker_recovery"]
    settings.MONGODB = database
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.LOAN_JOB_BATCH_SIZE = 10
    settings.LOAN_JOB_MAX_BATCHES = 1
    settings.LOAN_JOB_LEASE_SECONDS = 60
    return database


def test_expired_job_lease_is_reclaimed_but_live_lease_is_not(worker_recovery_db):
    now = utcnow()
    state = worker_recovery_db["loan_operational_state"]
    state.insert_one(
        {
            "_id": "expired-job",
            "lease_owner": "dead-worker",
            "lease_expires_at": now - timedelta(seconds=1),
            "checkpoint": None,
        }
    )

    assert acquire_job_lease("expired-job", owner="replacement-worker") == (
        "replacement-worker"
    )
    assert acquire_job_lease("expired-job", owner="competing-worker") is None


def test_handler_failure_releases_lease_and_retries_from_last_checkpoint(
    worker_recovery_db,
):
    rows = worker_recovery_db["recovery_rows"]
    rows.insert_many([{"value": value} for value in range(4)])
    first_seen = []

    def fail_on_two(row):
        if row["value"] == 2:
            raise RuntimeError("simulated worker loss")
        first_seen.append(row["value"])

    with pytest.raises(RuntimeError, match="simulated worker loss"):
        run_bounded_scan("recovery-job", "recovery_rows", {}, fail_on_two)

    state = worker_recovery_db["loan_operational_state"].find_one(
        {"_id": "recovery-job"}
    )
    assert first_seen == [0, 1]
    assert state["checkpoint"] == rows.find_one({"value": 1})["_id"]
    assert "lease_owner" not in state

    recovered = []
    result = run_bounded_scan(
        "recovery-job",
        "recovery_rows",
        {},
        lambda row: recovered.append(row["value"]),
    )
    assert recovered == [2, 3]
    assert result == {"processed": 2, "complete": True, "lease_acquired": True}


def test_expired_wallet_worker_claim_is_recoverable_once(worker_recovery_db):
    now = utcnow()
    application = LoanApplication(
        customer_id=str(ObjectId()),
        product_id=str(ObjectId()),
        requested_amount=1_000,
        approved_amount=1_000,
        term_months=1,
        status="approved",
        disbursement_status="pending",
        disbursement_method="wallet",
        disbursement_worker_owner="dead-worker",
        disbursement_worker_lease_expires_at=now - timedelta(seconds=1),
    ).save()

    claimed = LoanApplication.claim_wallet_disbursement(
        application.id,
        "replacement-worker",
        now + timedelta(minutes=5),
        now,
    )
    competing = LoanApplication.claim_wallet_disbursement(
        application.id,
        "competing-worker",
        now + timedelta(minutes=5),
        now,
    )
    assert claimed.disbursement_worker_owner == "replacement-worker"
    assert competing is None


def test_every_loan_beat_job_has_dedicated_recoverable_worker_configuration(settings):
    scheduled_tasks = {
        entry["task"]
        for entry in celery_app.conf.beat_schedule.values()
        if entry["task"].startswith("loans.")
    }
    expected = {
        "loans.tasks.check_overdue_installments_task",
        "loans.reconcile_repayment_lifecycle",
        "loans.reconcile_wallet_disbursements_task",
        "loans.reconcile_notification_deliveries",
        "loans.enforce_retention",
        "loans.collect_operational_metrics",
    }
    assert scheduled_tasks == expected
    for task_name in expected:
        assert settings.CELERY_TASK_ROUTES[task_name]["queue"] == "loans"
        annotation = settings.CELERY_TASK_ANNOTATIONS[task_name]
        assert annotation["acks_late"] is True
        assert annotation["reject_on_worker_lost"] is True
        assert annotation["soft_time_limit"] < annotation["time_limit"]
        assert annotation["time_limit"] <= settings.LOAN_JOB_LEASE_SECONDS
