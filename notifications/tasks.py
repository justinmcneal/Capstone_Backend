"""Canonical Celery tasks for shared notification delivery."""

from celery import shared_task


@shared_task(name="notifications.deliver")
def deliver_notification_task(delivery_id):
    from notifications.services.delivery import deliver_notification

    return deliver_notification(delivery_id)


@shared_task(name="notifications.reconcile_deliveries")
def reconcile_notification_deliveries_task(limit=100):
    from notifications.services.delivery import reconcile_notification_deliveries

    return reconcile_notification_deliveries(limit=max(1, min(int(limit), 1000)))


@shared_task(name="notifications.enforce_retention")
def enforce_notification_retention_task(limit=1000):
    from notifications.services.lifecycle import enforce_notification_retention

    return enforce_notification_retention(limit=max(1, min(int(limit), 10_000)))


@shared_task(name="notifications.collect_operational_metrics")
def collect_notification_operational_metrics_task():
    from notifications.services.operations import notification_operational_summary

    return notification_operational_summary()
