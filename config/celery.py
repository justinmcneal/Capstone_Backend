"""
Celery configuration for Capstone Backend
"""

import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("capstone_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Celery Beat Schedule - runs cleanup every 30 minutes
app.conf.beat_schedule = {
    "cleanup-unverified-accounts-every-30-minutes": {
        "task": "accounts.tasks.cleanup_unverified_accounts_task",
        "schedule": crontab(minute="*/30"),
    },
    "check-overdue-daily": {
        "task": "loans.tasks.check_overdue_installments_task",
        "schedule": crontab(hour=0, minute=0),
    },
    "reconcile-repayment-lifecycle-daily": {
        "task": "loans.reconcile_repayment_lifecycle",
        "schedule": crontab(hour=0, minute=15),
    },
    "reconcile-wallet-disbursements-every-5-minutes": {
        "task": "loans.reconcile_wallet_disbursements_task",
        "schedule": crontab(minute="*/5"),
    },
    "poll-blockchain-audit-events-every-minute": {
        "task": "blockchain.poll_audit_events",
        "schedule": crontab(minute="*"),
    },
    "reconcile-blockchain-domain-state-every-5-minutes": {
        "task": "blockchain.reconcile_domain_state",
        "schedule": crontab(minute="*/5"),
    },
}
