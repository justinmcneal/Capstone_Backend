import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task

from accounts.models import Customer

logger = logging.getLogger(__name__)


@shared_task
def cleanup_unverified_accounts_task():
    hours = 12
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    unverified_customers = Customer.find(
        {"verified": False, "created_at": {"$lte": cutoff_time}}
    )

    count = len(unverified_customers)

    if count == 0:
        logger.info("Cleanup task: No unverified accounts to delete")
        return f"No unverified accounts older than {hours} hours found"

    deleted_emails = [c.email for c in unverified_customers]

    # Delete each customer
    for customer in unverified_customers:
        customer.delete()

    logger.info(
        f'Cleanup task: Deleted {count} unverified accounts: {", ".join(deleted_emails)}'
    )
    return f"Successfully deleted {count} unverified accounts"


@shared_task
def invalidate_ai_consent_cache(user_id: str) -> str:
    """
    Clear the Redis-cached AI consent entry for a user.

    Dispatched by ConsentService.update_consent() whenever a customer
    revokes ai_consent (True → False), ensuring the AI assistant cannot
    serve a stale cached 'allowed' value.

    Safe even if nothing is cached — cache.delete() is a no-op on a miss.
    """
    from django.core.cache import cache

    cache_key = f"ai_consent:{user_id}"
    cache.delete(cache_key)
    logger.info("AI consent cache invalidated for user %s", user_id)
    return f"Invalidated ai_consent cache for user {user_id}"
