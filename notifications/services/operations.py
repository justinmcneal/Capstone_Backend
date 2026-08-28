"""Bounded, identifier-free Notifications health and release summaries."""

from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from pymongo.errors import PyMongoError

from notifications.metrics import (
    NOTIFICATION_DELIVERY_BACKLOG,
    NOTIFICATION_DELIVERY_OLDEST_AGE,
    NOTIFICATION_METRICS_LAST_SUCCESS,
    set_gauge,
)
from notifications.models.delivery import NotificationDelivery
from notifications.services.persistence import (
    NOTIFICATION_VALIDATORS,
    inventory_notification_data,
)

RETRYABLE_STATES = ("pending", "retry_wait", "sending")
EXPECTED_NOTIFICATION_INDEXES = {
    "notifications": {
        "notification_owner_created_page",
        "notification_owner_read_page",
        "notification_owner_channel_page",
        "notification_retention_due",
        "unique_notification_idempotency_hash",
    },
    "device_tokens": {
        "token_hash_1",
        "user_id_1_user_type_1_is_active_1_expires_at_1",
        "user_id_1_user_type_1_session_id_1_is_active_1",
        "device_token_expiry_cleanup",
        "device_token_inactive_cleanup",
    },
    "notification_deliveries": {
        "unique_notification_delivery",
        "notification_delivery_due",
        "notification_delivery_stale_lease",
        "notification_delivery_owner_history",
        "notification_delivery_retention",
    },
}

INVENTORY_BLOCKERS = {
    "legacy_read_status",
    "missing_user_type",
    "invalid_user_type",
    "missing_read_state",
    "missing_retention",
    "missing_idempotency_hash",
    "plaintext_sensitive_fields",
    "invalid_notification_timestamps",
    "duplicate_idempotency_hash_groups",
    "plaintext_device_tokens",
    "missing_token_hash",
    "missing_token_session",
    "invalid_token_owner_type",
    "invalid_token_platform",
    "missing_token_expiry",
    "duplicate_token_hash_groups",
    "plaintext_delivery_event_keys",
}


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


def _validator_present(db, collection_name):
    try:
        result = db.command({"listCollections": 1, "filter": {"name": collection_name}})
        rows = result.get("cursor", {}).get("firstBatch", [])
        return bool(rows and rows[0].get("options", {}).get("validator"))
    except (KeyError, TypeError, NotImplementedError, PyMongoError, RuntimeError):
        return False


def _tasks_configured():
    required = {
        "notifications.deliver",
        "notifications.reconcile_deliveries",
        "notifications.enforce_retention",
        "notifications.collect_operational_metrics",
    }
    routes = getattr(settings, "CELERY_TASK_ROUTES", {})
    annotations = getattr(settings, "CELERY_TASK_ANNOTATIONS", {})
    return all(
        routes.get(task, {}).get("queue") == "notifications"
        and annotations.get(task, {}).get("acks_late") is True
        and annotations.get(task, {}).get("reject_on_worker_lost") is True
        for task in required
    )


def notification_release_readiness(db):
    """Return a non-secret, read-only, fail-closed Stage 6 report."""
    mongodb_connected = False
    index_checks = {name: False for name in EXPECTED_NOTIFICATION_INDEXES}
    validator_checks = {name: False for name in NOTIFICATION_VALIDATORS}
    inventory = {"complete": False, "status": "not_checked"}
    try:
        db.command("ping")
        mongodb_connected = True
    except Exception:  # noqa: BLE001 - report a safe verdict, not target details
        inventory["status"] = "mongodb_unavailable"

    if mongodb_connected:
        for collection, required in EXPECTED_NOTIFICATION_INDEXES.items():
            try:
                index_checks[collection] = required.issubset(
                    set(db[collection].index_information())
                )
            except Exception:  # noqa: BLE001 - fail closed per collection
                index_checks[collection] = False
        validator_checks = {
            collection: _validator_present(db, collection)
            for collection in NOTIFICATION_VALIDATORS
        }
        try:
            inventory = inventory_notification_data(
                db=db,
                limit=int(settings.NOTIFICATIONS_RELEASE_INVENTORY_LIMIT),
            )
            clean = inventory.get("complete") and all(
                int(inventory.get(key, 0)) == 0 for key in INVENTORY_BLOCKERS
            )
            inventory["status"] = "clean" if clean else "findings"
        except Exception:  # noqa: BLE001 - fail closed without secret output
            inventory = {"complete": False, "status": "inventory_failed"}

    monitoring = Path(settings.BASE_DIR) / "monitoring" / "notifications"
    broker = str(getattr(settings, "CELERY_BROKER_URL", "") or "")
    backend = str(getattr(settings, "CELERY_RESULT_BACKEND", "") or "")
    channel_backend = str(
        getattr(settings, "CHANNEL_LAYERS", {}).get("default", {}).get("BACKEND", "")
    )
    allowed_hosts = {str(item).strip() for item in settings.ALLOWED_HOSTS}
    health = (
        notification_health_summary(db)
        if mongodb_connected
        else {
            "ready": False,
            "status": "unavailable",
        }
    )
    checks = {
        "debug_disabled": not bool(settings.DEBUG),
        "field_encryption_configured": bool(
            getattr(settings, "FIELD_ENCRYPTION_KEY", "")
        ),
        "strict_decryption_enabled": bool(
            getattr(settings, "FIELD_ENCRYPTION_STRICT_DECRYPTION", False)
        ),
        "redis_celery_configured": broker.startswith("redis")
        and backend.startswith("redis"),
        "redis_channel_layer_configured": channel_backend
        == "channels_redis.core.RedisChannelLayer",
        "websocket_enabled": bool(getattr(settings, "WEBSOCKET_ENABLED", False)),
        "notification_tasks_recoverable_and_routed": _tasks_configured(),
        "prometheus_metrics_enabled": bool(
            getattr(settings, "PROMETHEUS_METRICS_ENABLED", False)
        ),
        "notification_metrics_middleware_enabled": (
            "notifications.middleware.NotificationRequestMetricsMiddleware"
            in getattr(settings, "MIDDLEWARE", ())
        ),
        "monitoring_assets_present": all(
            (monitoring / filename).is_file()
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
        "secure_cookie_transport_configured": all(
            bool(getattr(settings, name, False))
            for name in (
                "AUTH_COOKIE_SECURE",
                "AUTH_COOKIE_HTTPONLY",
                "SESSION_COOKIE_SECURE",
                "SESSION_COOKIE_HTTPONLY",
                "CSRF_COOKIE_SECURE",
            )
        ),
        "restricted_hosts_and_cors_configured": bool(allowed_hosts)
        and "*" not in allowed_hosts
        and not bool(getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False)),
        "smtp_backend_configured": (
            getattr(settings, "EMAIL_BACKEND", "")
            == "django.core.mail.backends.smtp.EmailBackend"
            and bool(getattr(settings, "EMAIL_HOST", ""))
            and bool(getattr(settings, "EMAIL_HOST_USER", ""))
            and bool(getattr(settings, "DEFAULT_FROM_EMAIL", ""))
        ),
        "mongodb_connected": mongodb_connected,
        "required_indexes_present": all(index_checks.values()),
        "validators_present": all(validator_checks.values()),
        "inventory_clean_and_complete": inventory.get("status") == "clean",
        "notification_health_ready": bool(health.get("ready")),
        "retention_and_preference_policy_approved": bool(
            getattr(settings, "NOTIFICATIONS_RETENTION_POLICY_APPROVED", False)
        ),
        "deployment_mongodb_verified": bool(
            getattr(settings, "NOTIFICATIONS_DEPLOYMENT_MONGODB_VERIFIED", False)
        ),
        "redis_channels_celery_verified": bool(
            getattr(settings, "NOTIFICATIONS_REDIS_CHANNELS_CELERY_VERIFIED", False)
        ),
        "smtp_verified": bool(getattr(settings, "NOTIFICATIONS_SMTP_VERIFIED", False)),
        "firebase_verified": bool(
            getattr(settings, "NOTIFICATIONS_FIREBASE_VERIFIED", False)
        ),
        "https_wss_and_load_verified": bool(
            getattr(settings, "NOTIFICATIONS_HTTPS_WSS_LOAD_VERIFIED", False)
        ),
        "backup_restore_verified": bool(
            getattr(settings, "NOTIFICATIONS_BACKUP_RESTORE_VERIFIED", False)
        ),
        "secret_rotation_verified": bool(
            getattr(settings, "NOTIFICATIONS_SECRET_ROTATION_VERIFIED", False)
        ),
        "incident_rollback_approved": bool(
            getattr(settings, "NOTIFICATIONS_INCIDENT_ROLLBACK_APPROVED", False)
        ),
        "monitoring_and_alert_delivery_verified": bool(
            getattr(settings, "NOTIFICATIONS_MONITORING_ALERTS_VERIFIED", False)
        ),
        "full_suite_and_smoke_verified": bool(
            getattr(settings, "NOTIFICATIONS_FULL_SUITE_SMOKE_VERIFIED", False)
        ),
    }
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "index_checks": index_checks,
        "validator_checks": validator_checks,
        "inventory": inventory,
        "health": health,
    }
