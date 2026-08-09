"""Durable background work for versioned profile risk scoring."""

import logging
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from celery import shared_task
from django.conf import settings
from pymongo import ReturnDocument

from analytics.models import AuditLog
from profiles.models import AlternativeData
from profiles.services.risk_scoring import (
    RISK_SCORE_USE,
    RISK_SCORING_POLICY_VERSION,
    calculate_risk_score,
)

logger = logging.getLogger("profiles")

RISK_SCORE_RECONCILE_STALE_SECONDS = 300


def _customer_id_query(customer_id):
    value = str(customer_id or "").strip()
    variants = [value]
    if ObjectId.is_valid(value):
        variants.insert(0, ObjectId(value))
    return {"$in": variants}


def _audit_score_event(action, customer_id, *, details):
    try:
        AuditLog.log_action(
            action=action,
            user_id=customer_id,
            user_type="system",
            description="Profile risk-scoring lifecycle event",
            resource_type="alternative_data",
            resource_id=customer_id,
            details=details,
            ip_address="",
        )
    except Exception:
        logger.exception("Risk score audit failed for customer %s", customer_id)


def _mark_stale_task(collection, alternative, expected_revision):
    now = datetime.now(timezone.utc)
    collection.update_one(
        {"_id": alternative._id},
        {
            "$set": {
                "risk_score_last_task_status": "stale",
                "risk_score_last_stale_revision": expected_revision,
                "risk_score_stale_at": now,
            }
        },
    )
    _audit_score_event(
        "risk_score_stale",
        alternative.customer_id,
        details={
            "attempted_revision": expected_revision,
            "current_revision": alternative.risk_input_revision,
            "policy_version": RISK_SCORING_POLICY_VERSION,
        },
    )


def enqueue_risk_score_calculation(customer_id, expected_revision):
    """Publish one revision for scoring while retaining recoverable DB state."""

    collection = settings.MONGODB[AlternativeData.collection_name]
    try:
        result = calculate_risk_score_task.delay(
            str(customer_id), int(expected_revision)
        )
    except Exception as exc:
        now = datetime.now(timezone.utc)
        collection.update_one(
            {
                "customer_id": _customer_id_query(customer_id),
                "risk_input_revision": int(expected_revision),
            },
            {
                "$set": {
                    "risk_score_status": "failed",
                    "risk_score_error_code": f"enqueue_{type(exc).__name__}",
                    "risk_score_failed_at": now,
                    "risk_score_task_id": None,
                    "updated_at": now,
                }
            },
        )
        logger.exception("Risk score enqueue failed for customer %s", customer_id)
        return False

    task_id = str(getattr(result, "id", "") or "") or None
    collection.update_one(
        {
            "customer_id": _customer_id_query(customer_id),
            "risk_input_revision": int(expected_revision),
            "risk_score_status": {"$in": ["pending", "failed"]},
        },
        {
            "$set": {
                "risk_score_status": "pending",
                "risk_score_task_id": task_id,
                "risk_score_error_code": "",
                "risk_score_failed_at": None,
            }
        },
    )
    return True


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    name="profiles.calculate_risk_score",
)
def calculate_risk_score_task(
    self, customer_id: str, expected_revision: int | None = None
):
    """Calculate one input revision and publish only if it is still current."""

    db = getattr(settings, "MONGODB", None)
    if db is None:
        logger.warning("Risk scoring skipped: MONGODB not configured")
        return {"customer_id": customer_id, "scored": False}

    alternative = AlternativeData.find_by_customer(customer_id)
    if not alternative:
        logger.warning("Risk scoring skipped: no alternative data for %s", customer_id)
        return {"customer_id": customer_id, "scored": False}

    collection = db[AlternativeData.collection_name]
    revision = (
        alternative.risk_input_revision
        if expected_revision is None
        else int(expected_revision)
    )
    if alternative.risk_input_revision != revision:
        _mark_stale_task(collection, alternative, revision)
        return {
            "customer_id": customer_id,
            "scored": False,
            "stale": True,
            "revision": revision,
        }

    if (
        alternative.risk_score_status == "complete"
        and alternative.risk_calculated_revision == revision
        and alternative.risk_score_policy_version == RISK_SCORING_POLICY_VERSION
    ):
        return {
            "customer_id": customer_id,
            "scored": True,
            "idempotent": True,
            "score": alternative.risk_score,
            "category": alternative.risk_category,
            "revision": revision,
            "policy_version": RISK_SCORING_POLICY_VERSION,
        }

    task_id = str(getattr(self.request, "id", "") or "") or None
    collection.update_one(
        {"_id": alternative._id, "risk_input_revision": revision},
        {
            "$set": {
                "risk_score_status": "pending",
                "risk_score_task_id": task_id,
                "risk_score_error_code": "",
                "risk_score_failed_at": None,
                "risk_score_last_task_status": "running",
            }
        },
    )

    try:
        result = calculate_risk_score(alternative)
        score = result.get("total_score", result.get("score"))
        category = result.get("category")
        if score is None or category not in {"low", "medium", "high"}:
            raise ValueError("Risk scoring returned an invalid result")

        calculated_at = datetime.now(timezone.utc)
        document = collection.find_one_and_update(
            {"_id": alternative._id, "risk_input_revision": revision},
            {
                "$set": {
                    "risk_score": score,
                    "risk_category": category,
                    "score_calculated_at": calculated_at,
                    "risk_score_status": "complete",
                    "risk_score_policy_version": RISK_SCORING_POLICY_VERSION,
                    "risk_score_use": RISK_SCORE_USE,
                    "risk_score_manual_review_required": True,
                    "risk_calculated_revision": revision,
                    "risk_score_breakdown": result.get("dimensions", {}),
                    "risk_score_reason_codes": result.get("reason_codes", []),
                    "risk_score_error_code": "",
                    "risk_score_failed_at": None,
                    "risk_score_last_task_status": "complete",
                    "updated_at": calculated_at,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            current = AlternativeData.find_by_customer(customer_id)
            if current:
                _mark_stale_task(collection, current, revision)
            return {
                "customer_id": customer_id,
                "scored": False,
                "stale": True,
                "revision": revision,
            }
    except Exception as exc:
        failed_at = datetime.now(timezone.utc)
        collection.update_one(
            {"_id": alternative._id, "risk_input_revision": revision},
            {
                "$set": {
                    "risk_score_status": "failed",
                    "risk_score_error_code": type(exc).__name__,
                    "risk_score_failed_at": failed_at,
                    "risk_score_last_task_status": "failed",
                    "updated_at": failed_at,
                }
            },
        )
        _audit_score_event(
            "risk_score_failed",
            customer_id,
            details={
                "revision": revision,
                "policy_version": RISK_SCORING_POLICY_VERSION,
                "error_code": type(exc).__name__,
            },
        )
        raise

    _audit_score_event(
        "risk_score_calculated",
        customer_id,
        details={
            "revision": revision,
            "policy_version": RISK_SCORING_POLICY_VERSION,
            "category": category,
            "reason_codes": result.get("reason_codes", []),
        },
    )
    logger.info(
        "Risk score calculated for customer %s revision %s: %s (%s)",
        customer_id,
        revision,
        score,
        category,
    )
    return {
        "customer_id": customer_id,
        "scored": True,
        "score": score,
        "category": category,
        "revision": revision,
        "policy_version": RISK_SCORING_POLICY_VERSION,
    }


@shared_task(name="profiles.reconcile_risk_scores")
def reconcile_risk_scores_task():
    """Requeue failed or abandoned pending scoring revisions."""

    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=RISK_SCORE_RECONCILE_STALE_SECONDS)
    collection = settings.MONGODB[AlternativeData.collection_name]
    query = {
        "$or": [
            {"risk_score_status": "failed"},
            {
                "risk_score_status": "pending",
                "risk_score_requested_at": {"$lte": stale_before},
            },
        ]
    }
    queued = 0
    for document in collection.find(query, {"customer_id": 1, "risk_input_revision": 1}):
        customer_id = str(document.get("customer_id", "") or "")
        revision = int(document.get("risk_input_revision", 0) or 0)
        if not customer_id:
            continue
        collection.update_one(
            {"_id": document["_id"], "risk_input_revision": revision},
            {
                "$set": {
                    "risk_score_status": "pending",
                    "risk_score_requested_at": now,
                }
            },
        )
        if enqueue_risk_score_calculation(customer_id, revision):
            queued += 1

    logger.info("Requeued %s profile risk score(s)", queued)
    return queued
