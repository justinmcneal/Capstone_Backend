"""Bounded AI Assistant privacy-lifecycle tasks."""

from celery import shared_task


@shared_task(name='ai_assistant.enforce_retention')
def enforce_ai_retention_task(limit=500):
    from ai_assistant.services.lifecycle import enforce_ai_retention

    return enforce_ai_retention(limit=max(1, min(int(limit), 5000)))
