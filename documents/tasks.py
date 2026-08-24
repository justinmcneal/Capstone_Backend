"""
Background tasks for document processing.
"""

import logging

from celery import shared_task

from documents.services.notification import notify_reviewers_document_pending

logger = logging.getLogger("documents")


@shared_task(name="documents.cleanup_expired_upload_sessions")
def cleanup_expired_upload_sessions_task(limit=100):
    """Remove expired quarantined objects and close their upload sessions."""

    from documents.services.presigned_upload import cleanup_expired_upload_sessions
    from documents.storage import get_storage_backend

    return cleanup_expired_upload_sessions(
        storage=get_storage_backend(),
        limit=max(1, min(int(limit), 1000)),
    )


@shared_task(name="documents.reconcile_storage_operations")
def reconcile_storage_operations_task(limit=100):
    """Retry incomplete deletions and orphan-object rollbacks."""

    from documents.services.storage_reconciliation import (
        reconcile_storage_operations,
    )
    from documents.storage import get_storage_backend

    return reconcile_storage_operations(
        storage=get_storage_backend(),
        limit=max(1, min(int(limit), 1000)),
    )


@shared_task(name="documents.enforce_retention")
def enforce_document_retention_task(limit=100):
    """Claim a bounded batch of due, non-held documents for durable deletion."""
    from documents.services.retention import enforce_document_retention

    return enforce_document_retention(limit=max(1, min(int(limit), 1000)))


@shared_task(name="documents.collect_operational_metrics")
def collect_document_operational_metrics_task():
    """Refresh document workflow gauges without modifying domain records."""
    from documents.services.retention import collect_document_operational_metrics

    return collect_document_operational_metrics()


@shared_task(name="documents.reconcile_audit_failures")
def reconcile_document_audit_failures_task(limit=100):
    """Replay allowlisted document audit events that failed inline."""

    from documents.services.audit import reconcile_document_audit_failures

    return reconcile_document_audit_failures(limit=limit)


@shared_task(name="documents.analyze_document")
def analyze_document_task(document_id: str):
    """Run one idempotent, consent-aware document analysis attempt."""
    from documents.services.analysis import process_document_analysis

    return process_document_analysis(document_id)


@shared_task(name="documents.reconcile_ai_analyses")
def reconcile_document_ai_analyses_task(limit=100):
    """Republish due or retryable AI work after broker/worker failures."""
    from documents.services.analysis import reconcile_due_document_analyses

    return reconcile_due_document_analyses(limit=max(1, min(int(limit), 1000)))


@shared_task(name="documents.reconcile_reviewer_notifications")
def reconcile_reviewer_notifications_task(limit=100):
    """Retry a bounded batch of durable reviewer-notification deliveries."""
    from documents.services.notification import reconcile_reviewer_notifications

    return reconcile_reviewer_notifications(limit=max(1, min(int(limit), 1000)))


@shared_task(name="documents.deliver_reviewer_notification")
def deliver_reviewer_notification_task(delivery_id: str):
    """Deliver one claimed document notification outbox record."""
    from documents.services.notification import deliver_reviewer_notification

    return deliver_reviewer_notification(delivery_id)


@shared_task
def notify_reviewers_document_pending_task(document_id: str):
    """Notify the reviewers currently scoped to a pending document."""
    try:
        from documents.models import Document

        document = Document.find_by_id(document_id)
        if not document:
            logger.warning(
                "Document not found for reviewer notification: %s", document_id
            )
            return

        notify_reviewers_document_pending(document)
    except Exception as exc:
        logger.error("Failed to notify reviewers for document %s: %s", document_id, exc)
        raise
