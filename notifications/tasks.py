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
