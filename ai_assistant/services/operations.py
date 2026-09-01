"""Read-only AI Assistant deployment release checks."""

import json
from pathlib import Path

from django.conf import settings
from pymongo.errors import PyMongoError

from ai_assistant.evaluation import (
    load_dataset,
    load_officer_phase6_matrix,
    validate_quality_report,
)

EXPECTED_INDEXES = {
    "ai_interactions": {
        "ai_history_by_customer",
        "ai_conversation_by_customer",
        "ai_retention_cleanup",
        "ai_history_search",
        "ai_exchange_idempotency",
    },
    "ai_chat_requests": {
        "ai_chat_request_idempotency",
        "ai_chat_request_recovery",
        "ai_chat_request_expiry",
    },
    "ai_activity_events": {
        "ai_activity_event_id",
        "ai_activity_by_subject",
        "ai_activity_retention_ttl",
    },
}


def _validator_present(db, collection_name):
    try:
        result = db.command(
            {"listCollections": 1, "filter": {"name": collection_name}}
        )
        batches = result.get("cursor", {}).get("firstBatch", [])
        return bool(batches and batches[0].get("options", {}).get("validator"))
    except (KeyError, TypeError, NotImplementedError, PyMongoError):
        return False


def _quality_report_check():
    report_path = str(
        getattr(settings, "AI_ASSISTANT_QUALITY_REPORT_PATH", "") or ""
    ).strip()
    if not report_path:
        return {"ready": False, "checks": {"report_configured": False}}
    path = Path(report_path)
    if not path.is_file():
        return {"ready": False, "checks": {"report_present": False}}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        return validate_quality_report(report, load_dataset())
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {"ready": False, "checks": {"report_valid": False}}


def _officer_phase6_matrix_check():
    """Ensure the checked-in officer release matrix remains exhaustive."""
    try:
        matrix = load_officer_phase6_matrix()
        return {
            "ready": True,
            "matrix_version": matrix["matrix_version"],
            "matrix_sha256": matrix["matrix_sha256"],
            "case_count": len(matrix["cases"]),
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {"ready": False}


def ai_release_readiness(db):
    """Collect non-secret, read-only AI release checks for an operator."""
    db.command("ping")
    index_checks = {
        collection: required.issubset(set(db[collection].index_information()))
        for collection, required in EXPECTED_INDEXES.items()
    }
    validator_checks = {
        collection: _validator_present(db, collection)
        for collection in EXPECTED_INDEXES
    }
    monitoring_root = Path(settings.BASE_DIR) / "monitoring" / "ai_assistant"
    quality = _quality_report_check()
    officer_phase6 = _officer_phase6_matrix_check()
    provider = str(getattr(settings, "LLM_PROVIDER", "") or "").strip()
    provider_configured = (
        bool(getattr(settings, "GROQ_API_KEY", ""))
        if provider == "groq"
        else bool(getattr(settings, "OLLAMA_BASE_URL", ""))
    )
    checks = {
        "ai_assistant_enabled": bool(
            getattr(settings, "AI_ASSISTANT_ENABLED", True)
        ),
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
        "provider_configured": provider_configured,
        "prometheus_metrics_enabled": bool(
            getattr(settings, "PROMETHEUS_METRICS_ENABLED", False)
        ),
        "monitoring_assets_present": all(
            (monitoring_root / filename).is_file()
            for filename in (
                "prometheus-rules.yml",
                "prometheus-smoke.yml",
                "grafana-dashboard.json",
            )
        ),
        "secure_proxy_header_configured": bool(
            getattr(settings, "SECURE_PROXY_SSL_HEADER", None)
        ),
        "mongodb_connected": True,
        "required_indexes_present": all(index_checks.values()),
        "validators_present": all(validator_checks.values()),
        "quality_report_approved": quality["ready"],
        "officer_phase6_matrix_approved": officer_phase6["ready"],
        "provider_privacy_approved": bool(
            getattr(settings, "AI_ASSISTANT_PROVIDER_PRIVACY_APPROVED", False)
        ),
        "real_provider_contract_verified": bool(
            getattr(settings, "AI_ASSISTANT_PROVIDER_CONTRACT_VERIFIED", False)
        ),
        "real_redis_verified": bool(
            getattr(settings, "AI_ASSISTANT_REDIS_VERIFIED", False)
        ),
        "proxy_streaming_verified": bool(
            getattr(settings, "AI_ASSISTANT_PROXY_STREAMING_VERIFIED", False)
        ),
        "load_test_verified": bool(
            getattr(settings, "AI_ASSISTANT_LOAD_TEST_VERIFIED", False)
        ),
        "backup_restore_verified": bool(
            getattr(settings, "AI_ASSISTANT_BACKUP_RESTORE_VERIFIED", False)
        ),
        "secret_rotation_verified": bool(
            getattr(settings, "AI_ASSISTANT_SECRET_ROTATION_VERIFIED", False)
        ),
        "incident_rollback_approved": bool(
            getattr(settings, "AI_ASSISTANT_INCIDENT_ROLLBACK_APPROVED", False)
        ),
    }
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "index_checks": index_checks,
        "validator_checks": validator_checks,
        "quality": quality,
        "officer_phase6": officer_phase6,
    }
