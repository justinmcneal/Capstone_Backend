"""
Background tasks for document processing.
"""
import logging

from celery import shared_task

from documents.services.notification import notify_reviewers_document_pending

logger = logging.getLogger("documents")


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
