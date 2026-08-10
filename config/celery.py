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
    "finalize-scheduled-customer-deletions-every-30-minutes": {
        "task": "accounts.tasks.finalize_scheduled_customer_deletions_task",
        "schedule": crontab(minute="*/30"),
    },
    "reconcile-password-reset-email-deliveries-every-minute": {
        "task": "accounts.tasks.reconcile_password_reset_email_deliveries_task",
        "schedule": crontab(minute="*"),
    },
    "reconcile-profile-risk-scores-every-minute": {
        "task": "profiles.reconcile_risk_scores",
        "schedule": crontab(minute="*"),
    },
    "reconcile-profile-audit-failures-every-minute": {
        "task": "profiles.reconcile_audit_failures",
        "schedule": crontab(minute="*"),
    },
    "collect-profile-operational-metrics-every-15-minutes": {
        "task": "profiles.collect_operational_metrics",
        "schedule": crontab(minute="*/15"),
    },
    "cleanup-expired-document-upload-sessions-every-10-minutes": {
        "task": "documents.cleanup_expired_upload_sessions",
        "schedule": crontab(minute="*/10"),
    },
    "reconcile-document-storage-operations-every-5-minutes": {
        "task": "documents.reconcile_storage_operations",
        "schedule": crontab(minute="*/5"),
    },
    "reconcile-document-audit-failures-every-minute": {
        "task": "documents.reconcile_audit_failures",
        "schedule": crontab(minute="*"),
    },
    "reconcile-document-ai-analyses-every-minute": {
        "task": "documents.reconcile_ai_analyses",
        "schedule": crontab(minute="*"),
    },
    "reconcile-document-reviewer-notifications-every-minute": {
        "task": "documents.reconcile_reviewer_notifications",
        "schedule": crontab(minute="*"),
    },
    "enforce-document-retention-daily": {
        "task": "documents.enforce_retention",
        "schedule": crontab(hour=1, minute=0),
    },
    "collect-document-operational-metrics-every-15-minutes": {
        "task": "documents.collect_operational_metrics",
        "schedule": crontab(minute="*/15"),
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
