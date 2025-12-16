"""
Celery configuration for Capstone Backend
"""
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('capstone_backend')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Celery Beat Schedule - runs cleanup every 30 minutes
app.conf.beat_schedule = {
    'cleanup-unverified-accounts-every-30-minutes': {
        'task': 'accounts.tasks.cleanup_unverified_accounts_task',
        'schedule': crontab(minute='*/30'),
    },
}
