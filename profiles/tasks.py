"""
Background tasks for profile risk scoring.
"""
import logging
from datetime import datetime, timezone

from celery import shared_task
from django.conf import settings

from profiles.models import AlternativeData
from profiles.services.risk_scoring import calculate_risk_score

logger = logging.getLogger("profiles")


@shared_task
def calculate_risk_score_task(customer_id: str):
    """Calculate and persist risk score for a customer's alternative data."""
    db = getattr(settings, "MONGODB", None)
    if db is None:
        logger.warning("Risk scoring skipped: MONGODB not configured")
        return {"customer_id": customer_id, "scored": False}

    alternative = AlternativeData.find_by_customer(customer_id)
    if not alternative:
        logger.warning("Risk scoring skipped: no alternative data for %s", customer_id)
        return {"customer_id": customer_id, "scored": False}

    result = calculate_risk_score(alternative)
    score = result.get("total_score", result.get("score"))
    category = result.get("category")
    alternative.risk_score = score
    alternative.risk_category = category
    alternative.score_calculated_at = datetime.now(timezone.utc)
    alternative.save()

    logger.info(
        "Risk score calculated for customer %s: %s (%s)",
        customer_id,
        score,
        category,
    )

    return {
        "customer_id": customer_id,
        "scored": True,
        "score": score,
        "category": category,
    }
