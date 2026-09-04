"""Collect bounded operational metrics and read-only release evidence for Loans."""

from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from pymongo.errors import PyMongoError

from loans.metrics import (
    LOAN_BACKLOG,
    LOAN_INTEGRITY_GAPS,
    LOAN_JOB_LAST_SUCCESS,
    LOAN_OLDEST_AGE,
    set_gauge,
)
from loans.services.persistence import LOAN_VALIDATORS, loan_data_inventory

EXPECTED_LOAN_INDEXES = {
    "loan_products": {"code_1", "product_active_name_page"},
    "loan_applications": {
        "application_customer_status_page",
        "application_officer_status_page",
        "application_disbursement_reconcile",
        "disbursement_idempotency_key_1",
        "loan_retention_cleanup",
    },
    "repayment_schedules": {
        "loan_id_1",
        "schedule_status_job_scan",
        "schedule_customer_created_page",
    },
    "loan_payments": {
        "payment_reference_search",
        "payment_officer_scope_sort",
        "payment_lifecycle_timing_sort",
        "payment_loan_status_sort",
        "idempotency_key_1",
        "reference_fingerprint_1",
        "eth_tx_hash_1",
    },
    "blockchain_transactions": {
        "blockchain_status_reconcile",
        "blockchain_loan_action_status",
        "idempotency_key_1",
    },
    "loan_notification_deliveries": {
        "unique_loan_notification_delivery",
        "loan_notification_due",
        "loan_notification_stale_lease",
        "loan_notification_history",
    },
}


def _validator_present(db, collection_name):
    try:
        result = db.command({"listCollections": 1, "filter": {"name": collection_name}})
        batches = result.get("cursor", {}).get("firstBatch", [])
        return bool(batches and batches[0].get("options", {}).get("validator"))
    except (KeyError, TypeError, NotImplementedError, PyMongoError, RuntimeError):
        return False


def _task_runtime_configured():
    required_tasks = {
        "loans.tasks.check_overdue_installments_task",
        "loans.reconcile_repayment_lifecycle",
        "loans.reconcile_wallet_disbursements_task",
        "loans.reconcile_notification_deliveries",
        "loans.deliver_notification",
        "loans.enforce_retention",
        "loans.collect_operational_metrics",
    }
    routes = getattr(settings, "CELERY_TASK_ROUTES", {})
    annotations = getattr(settings, "CELERY_TASK_ANNOTATIONS", {})
    return all(
        routes.get(task, {}).get("queue") == "loans"
        and annotations.get(task, {}).get("acks_late") is True
        and annotations.get(task, {}).get("reject_on_worker_lost") is True
        for task in required_tasks
    )


def loan_release_readiness(db):
    """Return a non-secret, read-only Stage 6 release report."""
    inventory_limit = max(
        1,
        min(int(getattr(settings, "LOANS_RELEASE_INVENTORY_LIMIT", 10_000)), 1_000_000),
    )
    mongodb_connected = False
    index_checks = {collection: False for collection in EXPECTED_LOAN_INDEXES}
    validator_checks = {collection: False for collection in LOAN_VALIDATORS}
    inventory = {
        "limit": inventory_limit,
        "collections": {},
        "complete": False,
        "status": "not_checked",
    }
    try:
        db.command("ping")
        mongodb_connected = True
    except Exception:
        inventory["status"] = "mongodb_unavailable"

    if mongodb_connected:
        for collection, required in EXPECTED_LOAN_INDEXES.items():
            try:
                index_checks[collection] = required.issubset(
                    set(db[collection].index_information())
                )
            except Exception:
                index_checks[collection] = False
        validator_checks = {
            collection: _validator_present(db, collection)
            for collection in LOAN_VALIDATORS
        }
        try:
            inventory = loan_data_inventory(limit=inventory_limit, db=db)
            inventory["status"] = "complete" if inventory["complete"] else "findings"
        except Exception:
            inventory = {
                "limit": inventory_limit,
                "collections": {},
                "complete": False,
                "status": "inventory_failed",
            }
    monitoring_root = Path(settings.BASE_DIR) / "monitoring" / "loans"
    broker = str(getattr(settings, "CELERY_BROKER_URL", "") or "")
    result_backend = str(getattr(settings, "CELERY_RESULT_BACKEND", "") or "")
    blockchain_enabled = bool(getattr(settings, "BLOCKCHAIN_ENABLED", False))

    checks = {
        "debug_disabled": not bool(settings.DEBUG),
        "field_encryption_configured": bool(
            getattr(settings, "FIELD_ENCRYPTION_KEY", "")
        ),
        "strict_decryption_enabled": bool(
            getattr(settings, "FIELD_ENCRYPTION_STRICT_DECRYPTION", False)
        ),
        "redis_celery_configured": broker.startswith("redis")
        and result_backend.startswith("redis"),
        "loan_task_routes_and_recovery_configured": _task_runtime_configured(),
        "prometheus_metrics_enabled": bool(
            getattr(settings, "PROMETHEUS_METRICS_ENABLED", False)
        ),
        "loan_metrics_middleware_enabled": (
            "loans.middleware.LoanRequestMetricsMiddleware"
            in getattr(settings, "MIDDLEWARE", ())
        ),
        "monitoring_assets_present": all(
            (monitoring_root / filename).is_file()
            for filename in (
                "prometheus-rules.yml",
                "prometheus-rules.test.yml",
                "prometheus-smoke.yml",
                "grafana-dashboard.json",
            )
        ),
        "secure_proxy_header_configured": bool(
            getattr(settings, "SECURE_PROXY_SSL_HEADER", None)
        ),
        "mongodb_connected": mongodb_connected,
        "required_indexes_present": all(index_checks.values()),
        "validators_present": all(validator_checks.values()),
        "inventory_clean_and_complete": bool(inventory.get("complete")),
        "retention_policy_approved": bool(
            getattr(settings, "LOANS_RETENTION_POLICY_APPROVED", False)
        ),
        "deployment_mongodb_verified": bool(
            getattr(settings, "LOANS_DEPLOYMENT_MONGODB_VERIFIED", False)
        ),
        "multi_worker_redis_celery_verified": bool(
            getattr(settings, "LOANS_REDIS_CELERY_VERIFIED", False)
        ),
        "blockchain_baseline_verified_or_disabled": (
            not blockchain_enabled
            or bool(getattr(settings, "LOANS_BLOCKCHAIN_VERIFIED", False))
        ),
        "https_api_and_load_verified": bool(
            getattr(settings, "LOANS_HTTPS_API_LOAD_VERIFIED", False)
        ),
        "backup_restore_verified": bool(
            getattr(settings, "LOANS_BACKUP_RESTORE_VERIFIED", False)
        ),
        "secret_rotation_verified": bool(
            getattr(settings, "LOANS_SECRET_ROTATION_VERIFIED", False)
        ),
        "incident_rollback_approved": bool(
            getattr(settings, "LOANS_INCIDENT_ROLLBACK_APPROVED", False)
        ),
        "monitoring_and_alert_delivery_verified": bool(
            getattr(settings, "LOANS_MONITORING_ALERTS_VERIFIED", False)
        ),
        "full_suite_and_smoke_verified": bool(
            getattr(settings, "LOANS_FULL_SUITE_SMOKE_VERIFIED", False)
        ),
    }
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "index_checks": index_checks,
        "validator_checks": validator_checks,
        "inventory": inventory,
        "blockchain_enabled": blockchain_enabled,
    }


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
