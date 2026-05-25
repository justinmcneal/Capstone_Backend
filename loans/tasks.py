"""
Loan-related background tasks.
"""
import logging

from celery import shared_task
from django.conf import settings

from loans.models.repayment import RepaymentSchedule
from loans.blockchain.sync import sync_overdue

logger = logging.getLogger("loans")


@shared_task
def check_overdue_installments_task():
    """Mark overdue installments and sync to blockchain."""
    db = getattr(settings, "MONGODB", None)
    if db is None:
        return {"skipped": True, "reason": "mongodb not configured"}

    schedules = db["repayment_schedules"].find({})
    updated_installments = 0
    synced = 0

    for doc in schedules:
        schedule = RepaymentSchedule.from_dict(doc)
        if not schedule:
            continue

        updated = schedule.mark_overdue_installments()
        if not updated:
            continue

        updated_installments += len(updated)
        for installment_number in updated:
            try:
                sync_overdue(schedule.loan_id, installment_number)
                synced += 1
            except Exception as exc:
                logger.warning(
                    "Blockchain sync skipped for overdue loan=%s installment=%s error=%s",
                    schedule.loan_id,
                    installment_number,
                    exc,
                )

    return {"updated_installments": updated_installments, "synced": synced}
