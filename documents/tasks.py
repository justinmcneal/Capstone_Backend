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


@shared_task(name="documents.reconcile_audit_failures")
def reconcile_document_audit_failures_task(limit=100):
    """Replay allowlisted document audit events that failed inline."""

    from documents.services.audit import reconcile_document_audit_failures

    return reconcile_document_audit_failures(limit=limit)


@shared_task
def notify_reviewers_document_pending_task(document_id: str):
    """Notify active officers/admins that a document needs review."""
    try:
        from documents.models import Document

        document = Document.find_by_id(document_id)
        if not document:
            logger.warning("Document not found for reviewer notification: %s", document_id)
            return

        notify_reviewers_document_pending(document)
    except Exception as exc:
        logger.error("Failed to notify reviewers for document %s: %s", document_id, exc)
        raise
