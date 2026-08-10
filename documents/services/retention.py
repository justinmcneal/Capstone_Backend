"""Versioned document retention enforcement and operational measurements."""

from datetime import datetime, timezone

from django.conf import settings

from documents.metrics import (
    DOCUMENT_BACKLOG,
    DOCUMENT_OLDEST_AGE_SECONDS,
    set_gauge,
)
from documents.models import Document


def enforce_document_retention(limit=100):
    claimed = 0
    skipped = 0
    for document_id in Document.find_due_retention_ids(limit=limit):
        if Document.claim_retention_deletion(document_id):
            claimed += 1
        else:
            skipped += 1
    return {"claimed": claimed, "skipped_concurrent": skipped}


def _oldest_age(collection, query, date_field):
    row = collection.find_one(query, {date_field: 1}, sort=[(date_field, 1)])
    value = row.get(date_field) if row else None
    if not isinstance(value, datetime):
        return 0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - value).total_seconds()))


def collect_document_operational_metrics():
    db = settings.MONGODB
    documents = db[Document.collection_name]
    queue_queries = {
        ("storage", "pending"): {"storage_state": "delete_pending"},
        ("storage", "failed"): {"storage_state": "delete_failed"},
        ("review", "pending"): {"status": {"$in": ["pending", "needs_review"]}},
        ("ai", "pending"): {"ai_analysis_status": {"$in": ["pending", "retry_wait", "processing"]}},
        ("ai", "failed"): {"ai_analysis_status": "failed"},
        ("retention", "due"): {"retention_expires_at": {"$lte": datetime.now(timezone.utc)}, "legal_hold": {"$ne": True}},
        ("retention", "legal_hold"): {"legal_hold": True},
    }
    results = {}
    for (queue, status), query in queue_queries.items():
        count = documents.count_documents(query)
        results[f"{queue}_{status}"] = count
        set_gauge(DOCUMENT_BACKLOG, count, queue=queue, status=status)

    auxiliary = {
        ("notification", "pending"): ("document_notification_deliveries", {"status": {"$in": ["pending", "retry_wait", "processing"]}}),
        ("notification", "failed"): ("document_notification_deliveries", {"status": "failed"}),
        ("audit", "pending"): ("audit_write_failures", {"domain": "documents", "resolved_at": None}),
        ("upload_session", "expired"): ("document_upload_sessions", {"status": {"$in": ["issued", "finalizing", "failed"]}, "expires_at": {"$lte": datetime.now(timezone.utc)}}),
    }
    for (queue, status), (collection_name, query) in auxiliary.items():
        count = db[collection_name].count_documents(query)
        results[f"{queue}_{status}"] = count
        set_gauge(DOCUMENT_BACKLOG, count, queue=queue, status=status)

    ages = {
        "review": _oldest_age(documents, queue_queries[("review", "pending")], "uploaded_at"),
        "storage": _oldest_age(documents, {"storage_state": {"$in": ["delete_pending", "delete_failed"]}}, "deletion_requested_at"),
        "notification": _oldest_age(db["document_notification_deliveries"], auxiliary[("notification", "pending")][1], "created_at"),
        "ai": _oldest_age(documents, queue_queries[("ai", "pending")], "uploaded_at"),
    }
    for queue, age in ages.items():
        set_gauge(DOCUMENT_OLDEST_AGE_SECONDS, age, queue=queue)
    results["oldest_age_seconds"] = ages
    return results
