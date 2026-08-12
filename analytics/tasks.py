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
    from analytics.services.lifecycle import audit_integrity_inventory

    return audit_integrity_inventory(limit=limit)
