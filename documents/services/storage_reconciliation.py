"""Idempotent recovery for document/database storage inconsistencies."""

import logging

from django.conf import settings

from documents.models import Document, DocumentStorageCleanup

logger = logging.getLogger("documents")


def enqueue_storage_cleanup(file_path, *, reason, document_id=None):
    """Persist rollback work without exposing object paths in logs."""
    if not file_path:
        return
    try:
        DocumentStorageCleanup.enqueue(
            file_path, reason=reason, document_id=document_id
        )
    except Exception:
        logger.exception("Failed to persist document storage cleanup request")


def reconcile_storage_operations(*, storage, limit=100):
    """Retry document deletions and orphan-object cleanup."""
    limit = max(1, min(int(limit), 1000))
    result = {
        "document_deletions_completed": 0,
        "document_deletions_failed": 0,
        "orphan_cleanups_completed": 0,
        "orphan_cleanups_failed": 0,
    }

    for document in Document.find_deletion_candidates(limit=limit):
        customer_id = document.customer_id
        try:
            if storage.delete(document.file_path):
                from documents.models import DocumentNotificationDelivery

                settings.MONGODB[
                    DocumentNotificationDelivery.collection_name
                ].delete_many({"document_id": document.id})
                if document.complete_deletion():
                    from documents.services.lifecycle import (
                        refresh_customer_document_cleanup,
                    )

                    result["document_deletions_completed"] += 1
                    try:
                        refresh_customer_document_cleanup(
                            settings.MONGODB, customer_id
                        )
                    except Exception:
                        # The scheduled account lifecycle pass recomputes this
                        # marker; do not misreport a completed object deletion.
                        logger.exception(
                            "Document account-cleanup marker refresh failed"
                        )
            else:
                document.mark_deletion_failed("storage_delete_failed")
                result["document_deletions_failed"] += 1
        except Exception:
            document.mark_deletion_failed("storage_delete_exception")
            result["document_deletions_failed"] += 1
            logger.exception(
                "Document storage deletion reconciliation failed for %s", document.id
            )

    for cleanup in DocumentStorageCleanup.find_pending(limit=limit):
        try:
            if storage.delete(cleanup.file_path):
                cleanup.mark_completed()
                result["orphan_cleanups_completed"] += 1
            else:
                cleanup.mark_failed("storage_delete_failed")
                result["orphan_cleanups_failed"] += 1
        except Exception:
            cleanup.mark_failed("storage_delete_exception")
            result["orphan_cleanups_failed"] += 1
            logger.exception("Orphaned document storage cleanup failed")

    return result
