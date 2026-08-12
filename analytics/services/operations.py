"""Analytics query limits, health summaries, and operational instrumentation."""

import json
import logging
import time
from datetime import datetime, timezone

from django.conf import settings
from pymongo.errors import PyMongoError
from rest_framework import status

from accounts.utils.response_helpers import error_response
from accounts.utils.throttles import AnalyticsReadRateThrottle
from analytics.metrics import (
    ANALYTICS_REQUEST_LATENCY,
    ANALYTICS_REQUESTS,
    ANALYTICS_RESPONSE_SIZE,
    increment,
    observe,
)

logger = logging.getLogger("analytics.operations")


def query_timeout_ms():
    return int(getattr(settings, "ANALYTICS_QUERY_TIMEOUT_MS", 3000))


def bounded_count(collection, query):
    try:
        return collection.count_documents(query, maxTimeMS=query_timeout_ms())
    except (TypeError, NotImplementedError):
        if settings.DEBUG:
            return collection.count_documents(query)
        raise


def db_count(db, collection_name, query):
    return bounded_count(db[collection_name], query)


def bounded_cursor(cursor):
    try:
        return cursor.max_time_ms(query_timeout_ms())
    except (AttributeError, TypeError, NotImplementedError):
        if settings.DEBUG:
            return cursor
        raise


def bounded_aggregate(collection, pipeline):
    try:
        return collection.aggregate(pipeline, maxTimeMS=query_timeout_ms())
    except (TypeError, NotImplementedError):
        if settings.DEBUG:
            return collection.aggregate(pipeline)
        raise


class AnalyticsOperationalMixin:
    """Normalize MongoDB outages and record sanitized request telemetry."""

    throttle_classes = (AnalyticsReadRateThrottle,)

    def dispatch(self, request, *args, **kwargs):
        endpoint = type(self).__name__
        started = time.monotonic()
        response = None
        outcome = "error"
        try:
            response = super().dispatch(request, *args, **kwargs)
            code = int(getattr(response, "status_code", 500))
            outcome = "success" if code < 400 else f"http_{code // 100}xx"
            return response
        except (PyMongoError, TimeoutError):
            outcome = "dependency_unavailable"
            logger.exception("Analytics dependency unavailable: endpoint=%s", endpoint)
            response = error_response(
                message="Analytics service is temporarily unavailable",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
            return response
        finally:
            increment(ANALYTICS_REQUESTS, endpoint=endpoint, outcome=outcome)
            observe(
                ANALYTICS_REQUEST_LATENCY,
                time.monotonic() - started,
                endpoint=endpoint,
            )
            if response is not None:
                size = len(
                    json.dumps(
                        getattr(response, "data", {}), default=str, separators=(",", ":")
                    ).encode("utf-8")
                )
                observe(ANALYTICS_RESPONSE_SIZE, size, endpoint=endpoint)


def analytics_health_summary(db):
    """Return a bounded, identifier-free readiness summary."""
    failures = db["audit_write_failures"]
    unresolved = bounded_count(failures, {"resolved_at": None})
    oldest = failures.find_one(
        {"resolved_at": None}, {"occurred_at": 1}, sort=[("occurred_at", 1)]
    )
    oldest_age = 0
    if oldest and oldest.get("occurred_at"):
        occurred = oldest["occurred_at"]
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        oldest_age = max(0, int((datetime.now(timezone.utc) - occurred).total_seconds()))
    inventory = db["analytics_operational_state"].find_one(
        {"_id": "audit_integrity_inventory"}
    ) or {}
    invalid = int(inventory.get("invalid_integrity", 0) or 0)
    missing = int(inventory.get("missing_integrity", 0) or 0)
    threshold = int(getattr(settings, "ANALYTICS_AUDIT_BACKLOG_ALERT_THRESHOLD", 1))
    ready = unresolved < threshold and invalid == 0 and missing == 0
    return {
        "ready": ready,
        "status": "ready" if ready else "degraded",
        "audit_backlog": unresolved,
        "oldest_backlog_age_seconds": oldest_age,
        "integrity_findings": invalid + missing,
        "inventory_available": bool(inventory.get("collected_at")),
    }
