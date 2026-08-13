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
    collected_at = inventory.get("collected_at")
    inventory_age = None
    if collected_at:
        if collected_at.tzinfo is None:
            collected_at = collected_at.replace(tzinfo=timezone.utc)
        inventory_age = max(
            0, int((datetime.now(timezone.utc) - collected_at).total_seconds())
        )
    inventory_fresh = inventory_age is not None and inventory_age <= int(
        getattr(settings, "ANALYTICS_INTEGRITY_INVENTORY_MAX_AGE_SECONDS", 90000)
    )
    invalid = int(inventory.get("invalid_integrity", 0) or 0)
    missing = int(inventory.get("missing_integrity", 0) or 0)
    threshold = int(getattr(settings, "ANALYTICS_AUDIT_BACKLOG_ALERT_THRESHOLD", 1))
    ready = unresolved < threshold and invalid == 0 and missing == 0 and inventory_fresh
    return {
        "ready": ready,
        "status": "ready" if ready else "degraded",
        "audit_backlog": unresolved,
        "oldest_backlog_age_seconds": oldest_age,
        "integrity_findings": invalid + missing,
        "inventory_available": collected_at is not None,
        "inventory_fresh": inventory_fresh,
        "inventory_age_seconds": inventory_age,
    }


def analytics_release_readiness(db):
    """Collect read-only, non-secret release checks for an operator."""
    expected_indexes = {
        "event_id_1",
        "audit_officer_event_scope",
        "audit_actor_filter_sort",
        "audit_action_filter_sort",
        "audit_resource_filter_sort",
        "audit_retention_cleanup",
    }
    db.command("ping")
    indexes = set(db["audit_logs"].index_information())
    validator_present = False
    try:
        result = db.command(
            {"listCollections": 1, "filter": {"name": "audit_logs"}}
        )
        batches = result.get("cursor", {}).get("firstBatch", [])
        validator_present = bool(
            batches and batches[0].get("options", {}).get("validator")
        )
    except (KeyError, TypeError, NotImplementedError, PyMongoError):
        validator_present = False
    health = analytics_health_summary(db)
    checks = {
        "debug_disabled": not bool(settings.DEBUG),
        "field_encryption_configured": bool(
            getattr(settings, "FIELD_ENCRYPTION_KEY", "")
        ),
        "strict_decryption_enabled": bool(
            getattr(settings, "FIELD_ENCRYPTION_STRICT_DECRYPTION", False)
        ),
        "shared_redis_cache_enabled": bool(
            getattr(settings, "USE_REDIS_CACHE", False)
        ),
        "mongodb_connected": True,
        "required_indexes_present": expected_indexes.issubset(indexes),
        "validator_present": validator_present,
        "analytics_health_ready": health["ready"],
    }
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "health": health,
    }
