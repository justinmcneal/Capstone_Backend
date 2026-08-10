"""Read-only, count-only storage/database consistency inventory."""

from datetime import datetime, timezone

from accounts.models import Customer
from documents.models import Document, DocumentStorageCleanup, DocumentUploadSession


def inventory_document_storage(db, storage):
    """Return aggregate findings without logging filenames, paths, or customer PII."""
    now = datetime.now(timezone.utc)
    database_keys = set()
    missing = 0
    contradictory = 0
    lifecycle_contradictions = 0
    missing_retention_metadata = 0
    incomplete_legal_holds = 0
    deleted_customer_records = 0
    deleted_ids = {
        str(row["_id"])
        for row in db[Customer.collection_name].find(
            {"account_state": "deleted"}, {"_id": 1}
        )
    }
    for row in db[Document.collection_name].find({}):
        document = Document.from_dict(row)
        if document.file_path:
            database_keys.add(document.file_path)
            if document.storage_state in ("available", None) and not storage.object_exists(document.file_path):
                missing += 1
        if document.storage_state in ("delete_pending", "delete_failed") and not document.deletion_requested_at:
            contradictory += 1
        if (
            (document.status == "approved" and not document.verified)
            or (document.verified and document.status != "approved")
            or (document.status == "rejected" and document.verified_at is not None)
            or (document.reupload_requested and document.status != "needs_review")
        ):
            lifecycle_contradictions += 1
        if document.storage_state in ("available", None) and (
            not document.retention_expires_at
            or not document.retention_policy_version
        ):
            missing_retention_metadata += 1
        if document.legal_hold and (
            not document.legal_hold_reason
            or not document.legal_hold_set_at
            or not document.legal_hold_set_by
        ):
            incomplete_legal_holds += 1
        if str(document.customer_id) in deleted_ids and not document.legal_hold:
            deleted_customer_records += 1

    quarantine_keys = set()
    for row in db[DocumentUploadSession.collection_name].find(
        {"status": {"$in": ["issued", "finalizing", "failed"]}}
    ):
        session = DocumentUploadSession.from_dict(row)
        if session.object_key:
            quarantine_keys.add(session.object_key)

    queued_cleanup_keys = {
        cleanup.file_path
        for cleanup in (
            DocumentStorageCleanup.from_dict(row)
            for row in db[DocumentStorageCleanup.collection_name].find(
                {"status": "pending"}
            )
        )
        if cleanup.file_path
    }

    storage_keys = set(storage.list_keys("documents"))
    storage_keys.update(storage.list_keys("document-uploads/quarantine"))
    known_keys = database_keys | quarantine_keys | queued_cleanup_keys
    return {
        "database_objects": len(database_keys),
        "storage_objects": len(storage_keys),
        "missing_objects": missing,
        "orphan_objects": len(storage_keys - known_keys),
        "expired_upload_sessions": db[DocumentUploadSession.collection_name].count_documents(
            {"status": {"$in": ["issued", "finalizing", "failed"]}, "expires_at": {"$lte": now}}
        ),
        "contradictory_states": contradictory,
        "lifecycle_contradictions": lifecycle_contradictions,
        "missing_retention_metadata": missing_retention_metadata,
        "incomplete_legal_holds": incomplete_legal_holds,
        "deleted_customer_records": deleted_customer_records,
        "retention_due": db[Document.collection_name].count_documents(
            {"retention_expires_at": {"$lte": now}, "legal_hold": {"$ne": True}}
        ),
        "legal_holds": db[Document.collection_name].count_documents({"legal_hold": True}),
    }
