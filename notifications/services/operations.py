"""Bounded, identifier-free Notifications health and metrics summaries."""

from datetime import datetime, timezone

from django.conf import settings

from notifications.metrics import (
    NOTIFICATION_DELIVERY_BACKLOG,
    NOTIFICATION_DELIVERY_OLDEST_AGE,
    NOTIFICATION_METRICS_LAST_SUCCESS,
    set_gauge,
)
from notifications.models.delivery import NotificationDelivery

RETRYABLE_STATES = ("pending", "retry_wait", "sending")


def _aware(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def notification_operational_summary(db=None):
    """Collect bounded backlog gauges without exposing recipient identifiers."""
    database = db if db is not None else settings.MONGODB
    collection = database[NotificationDelivery.collection_name]
    backlog = {}
    for state in (*RETRYABLE_STATES, "failed"):
        count = int(collection.count_documents({"status": state}))
        backlog[state] = count
        set_gauge(NOTIFICATION_DELIVERY_BACKLOG, count, status=state)
    oldest = collection.find_one(
        {"status": {"$in": list(RETRYABLE_STATES)}},
        {"created_at": 1},
        sort=[("created_at", 1), ("_id", 1)],
    )
    created_at = _aware((oldest or {}).get("created_at"))
    oldest_age = (
        max(0, int((datetime.now(timezone.utc) - created_at).total_seconds()))
        if created_at
        else 0
    )
    set_gauge(NOTIFICATION_DELIVERY_OLDEST_AGE, oldest_age)
    set_gauge(
        NOTIFICATION_METRICS_LAST_SUCCESS,
        datetime.now(timezone.utc).timestamp(),
    )
    return {"backlog": backlog, "oldest_age_seconds": oldest_age}


def notification_health_summary(db=None):
    """Return an identifier-free readiness component for the shared outbox."""
    try:
        summary = notification_operational_summary(db)
    except Exception:  # noqa: BLE001 - readiness must return a safe verdict
        return {"ready": False, "status": "unavailable"}
    failed_limit = int(
        getattr(settings, "NOTIFICATIONS_HEALTH_FAILED_DELIVERY_LIMIT", 0)
    )
    oldest_limit = int(
        getattr(settings, "NOTIFICATIONS_HEALTH_OLDEST_PENDING_SECONDS", 900)
    )
    ready = (
        summary["backlog"]["failed"] <= failed_limit
        and summary["oldest_age_seconds"] <= oldest_limit
    )
    return {
        "ready": ready,
        "status": "ready" if ready else "degraded",
        **summary,
    }
