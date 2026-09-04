"""Bounded Analytics lifecycle and recovery tasks."""

from celery import shared_task


@shared_task(name="analytics.reconcile_audit_failures")
def reconcile_audit_failures_task(limit=100):
    from analytics.services.audit_writer import reconcile_audit_failures

    return reconcile_audit_failures(limit=limit)


@shared_task(name="analytics.enforce_audit_retention")
def enforce_audit_retention_task(limit=500):
    from analytics.services.lifecycle import enforce_audit_retention

    return enforce_audit_retention(limit=limit)


@shared_task(name="analytics.audit_integrity_inventory")
def audit_integrity_inventory_task(limit=10000):
    from datetime import datetime, timezone

    from django.conf import settings

    from analytics.services.lifecycle import audit_integrity_inventory

    result = audit_integrity_inventory(limit=limit)
    settings.MONGODB["analytics_operational_state"].update_one(
        {"_id": "audit_integrity_inventory"},
        {"$set": {**result, "collected_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return result


@shared_task(name="analytics.collect_operational_metrics")
def collect_operational_metrics_task():
    from datetime import datetime, timezone

    from django.conf import settings

    from analytics.metrics import (
        ANALYTICS_AUDIT_BACKLOG,
        ANALYTICS_AUDIT_OLDEST_AGE,
        ANALYTICS_INTEGRITY_GAPS,
        set_gauge,
    )
    from analytics.services.operations import analytics_health_summary

    summary = analytics_health_summary(settings.MONGODB)
    set_gauge(ANALYTICS_AUDIT_BACKLOG, summary["audit_backlog"])
    set_gauge(
        ANALYTICS_AUDIT_OLDEST_AGE, summary["oldest_backlog_age_seconds"]
    )
    inventory = settings.MONGODB["analytics_operational_state"].find_one(
        {"_id": "audit_integrity_inventory"}
    ) or {}
    for kind in (
        "missing_integrity",
        "invalid_integrity",
        "missing_retention",
        "plaintext_sensitive_fields",
    ):
        set_gauge(ANALYTICS_INTEGRITY_GAPS, int(inventory.get(kind, 0)), kind=kind)
    settings.MONGODB["analytics_operational_state"].update_one(
        {"_id": "operational_metrics"},
        {"$set": {**summary, "collected_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return summary
