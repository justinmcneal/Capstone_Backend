import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task

from accounts.models import Customer
from accounts.services.account_lifecycle_service import AccountLifecycleService
from analytics.models import AuditLog

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
def finalize_scheduled_customer_deletions_task():
    """Finalize customer deletion requests whose retention period has elapsed."""
    now = datetime.now(timezone.utc)
    customers = Customer.find(
        {
            "account_state": "pending_deletion",
            "deletion_scheduled_for": {"$lte": now},
        }
    )

    finalized = 0
    for customer in customers:
        original_email = customer.email
        try:
            updated = AccountLifecycleService.finalize_deletion(
                customer,
                reason="Retention period elapsed",
            )
            if not updated:
                continue

            AuditLog.log_action(
                action="account_deleted",
                user_id=updated.id,
                user_type="system",
                user_email=original_email,
                description="Finalized scheduled customer account deletion",
                resource_type="customer",
                resource_id=updated.id,
                details={"automated": True, "retention_period_elapsed": True},
                ip_address="",
            )
            finalized += 1
        except Exception as exc:  # noqa: BLE001 - one record must not stop the batch
            logger.error(
                "Scheduled customer deletion failed for %s: %s", customer.id, exc
            )

    logger.info("Scheduled customer deletion task finalized %s account(s)", finalized)
    return f"Finalized {finalized} scheduled customer deletion(s)"


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
