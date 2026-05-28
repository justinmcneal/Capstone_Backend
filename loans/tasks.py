"""
Loan-related background tasks.
"""

from datetime import datetime
import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task
def check_overdue_installments_task():
    """Mark overdue installments and sync them to the blockchain."""
    db = getattr(settings, "MONGODB", None)
    if db is None:
        logger.warning("Overdue check skipped: MONGODB not configured")
        return {"overdue_marked": 0}

    from loans.models import RepaymentSchedule
    from loans.blockchain.sync import sync_overdue

    now = datetime.utcnow()
    updated_count = 0

    for doc in db["repayment_schedules"].find({}):
        schedule = RepaymentSchedule.from_dict(doc)
        if not schedule:
            continue

        overdue_installments = schedule.mark_overdue_installments(as_of=now)
        for installment_number in overdue_installments:
            try:
                sync_overdue(schedule.loan_id, installment_number)
            except Exception as exc:
                logger.warning(
                    "Blockchain sync skipped for overdue loan=%s installment=%s: %s",
                    schedule.loan_id,
                    installment_number,
                    exc,
                )

        updated_count += len(overdue_installments)

    if updated_count:
        logger.info("Marked %s overdue installments", updated_count)

    return {"overdue_marked": updated_count}
