from celery import shared_task
from datetime import datetime, timedelta
from accounts.models import Customer
import logging

logger = logging.getLogger(__name__)


@shared_task
def cleanup_unverified_accounts_task():
    hours = 12
    cutoff_time = datetime.utcnow() - timedelta(hours=hours)

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
