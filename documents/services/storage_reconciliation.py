"""Idempotent recovery for document/database storage inconsistencies."""

import logging

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
        try:
            if storage.delete(document.file_path):
                if document.complete_deletion():
                    result["document_deletions_completed"] += 1
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
