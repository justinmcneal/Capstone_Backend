"""Collect bounded operational backlog measurements for Loans."""

from datetime import datetime, timezone

from django.conf import settings

from loans.metrics import (
    LOAN_BACKLOG,
    LOAN_INTEGRITY_GAPS,
    LOAN_JOB_LAST_SUCCESS,
    LOAN_OLDEST_AGE,
    set_gauge,
)


def _oldest_age(collection, query, field):
    row = collection.find_one(query, {field: 1}, sort=[(field, 1), ("_id", 1)])
    value = (row or {}).get(field)
    if not value:
        return 0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - value).total_seconds()))


def collect_loan_operational_metrics():
    db = settings.MONGODB
    definitions = {
        ("review", "pending"): (
            "loan_applications",
            {"status": {"$in": ["submitted", "under_review"]}},
            "submitted_at",
        ),
        ("disbursement", "pending"): (
            "loan_applications",
            {"disbursement_status": "pending"},
            "disbursement_requested_at",
        ),
        ("payment", "verification"): (
            "loan_payments",
            {"payment_status": {"$in": ["pending_verification", "posting"]}},
            "recorded_at",
        ),
        ("wallet", "reconciliation"): (
            "loan_applications",
            {"disbursement_method": "wallet", "disbursement_status": "pending"},
            "disbursement_requested_at",
        ),
        ("notification", "retryable"): (
            "loan_notification_deliveries",
            {"status": {"$in": ["pending", "retry_wait", "sending"]}},
            "created_at",
        ),
        ("notification", "failed"): (
            "loan_notification_deliveries",
            {"status": "failed"},
            "created_at",
        ),
        ("audit", "unresolved"): (
            "audit_write_failures",
            {"domain": "loans", "resolved_at": None},
            "occurred_at",
        ),
        ("blockchain", "pending"): (
            "blockchain_transactions",
            {"status": "pending"},
            "created_at",
        ),
        ("blockchain", "failed"): (
            "blockchain_transactions",
            {"status": "failed"},
            "created_at",
        ),
    }
    summary = {"backlog": {}, "oldest_age_seconds": {}}
    by_queue = {}
    for (queue, status), (collection_name, query, date_field) in definitions.items():
        count = int(db[collection_name].count_documents(query))
        age = _oldest_age(db[collection_name], query, date_field)
        summary["backlog"][f"{queue}:{status}"] = count
        by_queue[queue] = max(by_queue.get(queue, 0), age)
        set_gauge(LOAN_BACKLOG, count, queue=queue, status=status)
    for queue, age in by_queue.items():
        summary["oldest_age_seconds"][queue] = age
        set_gauge(LOAN_OLDEST_AGE, age, queue=queue)

    job_names = {
        "overdue": "check_overdue_installments",
        "repayment_lifecycle": "reconcile_repayment_lifecycle",
        "wallet": "reconcile_wallet_disbursements",
    }
    summary["job_last_success_timestamp"] = {}
    for label, state_id in job_names.items():
        state = db["loan_operational_state"].find_one(
            {"_id": state_id}, {"completed_at": 1}
        )
        completed_at = (state or {}).get("completed_at")
        timestamp = float(completed_at.timestamp()) if completed_at else 0.0
        summary["job_last_success_timestamp"][label] = timestamp
        set_gauge(LOAN_JOB_LAST_SUCCESS, timestamp, job=label)

    scan_limit = max(
        1,
        min(
            int(getattr(settings, "LOAN_OPERATIONAL_INTEGRITY_SCAN_LIMIT", 1000)),
            10_000,
        ),
    )
    application_status = {
        str(row["_id"]): row.get("status")
        for row in db["loan_applications"]
        .find({}, {"status": 1})
        .sort("_id", 1)
        .limit(scan_limit)
    }
    orphan_schedules = 0
    state_mismatches = 0
    for schedule in (
        db["repayment_schedules"]
        .find({}, {"loan_id": 1, "status": 1})
        .sort("_id", 1)
        .limit(scan_limit)
    ):
        app_status = application_status.get(str(schedule.get("loan_id")))
        if app_status is None:
            orphan_schedules += 1
        elif app_status == "completed" and schedule.get("status") != "paid_off":
            state_mismatches += 1
        elif app_status == "disbursed" and schedule.get("status") == "paid_off":
            state_mismatches += 1
    summary["integrity_gaps"] = {
        "orphan_schedule": orphan_schedules,
        "application_schedule_state": state_mismatches,
    }
    for kind, value in summary["integrity_gaps"].items():
        set_gauge(LOAN_INTEGRITY_GAPS, value, kind=kind)
    return summary
