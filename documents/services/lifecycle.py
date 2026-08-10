"""Document-domain participation in account export and irreversible deletion."""

from datetime import datetime, timezone

from bson import ObjectId

from accounts.models import Customer
from documents.models import Document

ACTIVE_UPLOAD_STATUSES = ("issued", "finalizing", "failed")


def _customer_candidates(customer_id):
    value = str(customer_id)
    candidates = [value]
    if ObjectId.is_valid(value):
        candidates.insert(0, ObjectId(value))
    return candidates


def _customer_filter(customer_id):
    candidates = _customer_candidates(customer_id)
    return candidates[0] if len(candidates) == 1 else {"$in": candidates}


def schedule_customer_document_cleanup(db, customer_id):
    """Claim customer objects for durable deletion and expire upload sessions."""
    now = datetime.now(timezone.utc)
    customer_filter = _customer_filter(customer_id)
    documents = db[Document.collection_name]
    claimed = documents.update_many(
        {
            "customer_id": customer_filter,
            "legal_hold": {"$ne": True},
            "$or": [
                {"storage_state": "available"},
                {"storage_state": {"$exists": False}},
            ],
        },
        {
            "$set": {
                "storage_state": "delete_pending",
                "deletion_requested_at": now,
                "deletion_reason_code": "account_deletion",
                "deletion_last_error": "",
                "updated_at": now,
            },
            "$inc": {"revision": 1},
        },
    )
    expired_sessions = db["document_upload_sessions"].update_many(
        {"customer_id": str(customer_id), "status": {"$in": ACTIVE_UPLOAD_STATUSES}},
        {"$set": {"expires_at": now, "failure_code": "account_deletion"}},
    )
    counts = refresh_customer_document_cleanup(db, customer_id, update_customer=False)
    counts.update(
        {
            "documents_claimed": int(claimed.modified_count),
            "upload_sessions_expired": int(expired_sessions.modified_count),
        }
    )
    return counts


def refresh_customer_document_cleanup(db, customer_id, *, update_customer=True):
    """Recompute the durable account marker after each reconciliation pass."""
    customer_filter = _customer_filter(customer_id)
    documents = db[Document.collection_name]
    pending_documents = documents.count_documents(
        {
            "customer_id": customer_filter,
            "legal_hold": {"$ne": True},
            "storage_state": {"$in": ["available", "delete_pending", "delete_failed"]},
        }
    )
    held_documents = documents.count_documents(
        {"customer_id": customer_filter, "legal_hold": True}
    )
    active_sessions = db["document_upload_sessions"].count_documents(
        {"customer_id": str(customer_id), "status": {"$in": ACTIVE_UPLOAD_STATUSES}}
    )
    complete = pending_documents == 0 and active_sessions == 0
    counts = {
        "pending_documents": pending_documents,
        "held_documents_retained": held_documents,
        "active_upload_sessions": active_sessions,
        "status": "complete" if complete else "pending",
    }
    if update_customer:
        now = datetime.now(timezone.utc)
        update = {
            "document_cleanup_status": counts["status"],
            "document_cleanup_counts": counts,
            "document_cleanup_last_error": "",
            "updated_at": now,
        }
        if complete:
            update["document_cleanup_completed_at"] = now
        db[Customer.collection_name].update_one(
            {"_id": ObjectId(str(customer_id)), "account_state": "deleted"},
            {"$set": update},
        )
    return counts


def export_customer_documents(db, customer_id):
    """Return metadata a customer can understand without storage secrets/URLs."""
    projection = {
        "document_type": 1,
        "file_size": 1,
        "mime_type": 1,
        "status": 1,
        "verified": 1,
        "uploaded_at": 1,
        "updated_at": 1,
        "retention_expires_at": 1,
        "retention_policy_version": 1,
        "legal_hold": 1,
        "ai_analysis_status": 1,
        "superseded_at": 1,
    }
    rows = db[Document.collection_name].find(
        {"customer_id": _customer_filter(customer_id)}, projection
    ).sort("uploaded_at", -1)
    return [{**{k: v for k, v in row.items() if k != "_id"}, "id": str(row["_id"])} for row in rows]
