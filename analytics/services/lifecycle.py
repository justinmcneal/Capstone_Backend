"""Audit retention, legal hold, privacy, export, and integrity operations."""

import hashlib
from datetime import datetime, timedelta, timezone

from django.conf import settings

from analytics.models import AuditLog
from analytics.models.audit_log import AUDIT_ACTION_REGISTRY
from config.field_encryption import encrypt_fields, is_encrypted_value


def _subject_query(customer_id):
    value = str(customer_id or "").strip()
    if not value:
        raise ValueError("customer_id is required")
    return {
        "$or": [
            {"subject_index": {"$in": AuditLog.blind_index_candidates(value)}},
            {"user_id": value},
            {"details.customer_id": value},  # legacy plaintext records only
        ]
    }


def enforce_audit_retention(limit=500):
    """Delete one bounded batch of expired, non-held audit events."""
    collection = settings.MONGODB[AuditLog.collection_name]
    now = datetime.now(timezone.utc)
    ids = [
        row["_id"]
        for row in collection.find(
            {
                "retention_expires_at": {"$lte": now},
                "legal_hold": {"$ne": True},
            },
            {"_id": 1},
            sort=[("retention_expires_at", 1), ("_id", 1)],
            limit=max(1, min(int(limit), 5000)),
        )
    ]
    if not ids:
        return {"deleted": 0}
    result = collection.delete_many(
        {"_id": {"$in": ids}, "legal_hold": {"$ne": True}}
    )
    return {"deleted": int(result.deleted_count)}


def _lifecycle_update(raw, updates):
    collection = settings.MONGODB[AuditLog.collection_name]
    encrypted = encrypt_fields(updates, AuditLog.encrypted_fields)
    candidate = {**raw, **encrypted}
    candidate["integrity_hash"] = AuditLog._hash_document(candidate)
    encrypted["integrity_hash"] = candidate["integrity_hash"]
    result = collection.update_one(
        {"_id": raw["_id"], "integrity_hash": raw.get("integrity_hash")},
        {"$set": encrypted},
    )
    return result.modified_count == 1


def set_audit_legal_hold(event_id, *, reason, set_by):
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("A legal-hold reason is required")
    collection = settings.MONGODB[AuditLog.collection_name]
    raw = collection.find_one({"event_id": str(event_id), "legal_hold": {"$ne": True}})
    if not raw:
        return False
    now = datetime.now(timezone.utc)
    return _lifecycle_update(
        raw,
        {
            "legal_hold": True,
            "legal_hold_reason": reason,
            "legal_hold_set_at": now,
            "legal_hold_set_by": str(set_by),
        },
    )


def release_audit_legal_hold(event_id, *, released_by):
    collection = settings.MONGODB[AuditLog.collection_name]
    raw = collection.find_one({"event_id": str(event_id), "legal_hold": True})
    if not raw:
        return False
    return _lifecycle_update(
        raw,
        {
            "legal_hold": False,
            "legal_hold_reason": "",
            "legal_hold_set_at": None,
            "legal_hold_set_by": None,
            "legal_hold_released_at": datetime.now(timezone.utc),
            "legal_hold_released_by": str(released_by),
        },
    )


def pseudonymize_customer_audit_data(db, customer_id, *, limit=5000):
    """Remove subject PII while preserving held evidence and event semantics."""
    customer_id = str(customer_id or "").strip()
    collection = db[AuditLog.collection_name]
    pseudonym = f"deleted:{AuditLog.blind_index(customer_id)[:24]}"
    query = {"$and": [_subject_query(customer_id), {"pseudonymized_at": None}]}
    changed = 0
    held = 0
    for raw in collection.find(
        query,
        sort=[("timestamp", 1), ("_id", 1)],
        limit=max(1, min(int(limit), 10000)),
    ):
        if raw.get("legal_hold") is True:
            held += 1
            continue
        event = AuditLog.from_dict(raw)
        updates = {
            "user_email": "",
            "ip_address": "",
            "details": {},
            "description": "Audit event retained after account deletion",
            "pseudonymized_at": datetime.now(timezone.utc),
        }
        if str(event.user_id or "") == customer_id:
            updates["user_id"] = pseudonym
        if str(event.resource_id or "") == customer_id:
            updates["resource_id"] = pseudonym
        if _lifecycle_update(raw, updates):
            changed += 1
    remaining = collection.count_documents(
        {"$and": [_subject_query(customer_id), {"pseudonymized_at": None}, {"legal_hold": {"$ne": True}}]}
    )
    queued = db["audit_write_failures"].delete_many(
        {
            "subject_index": {
                "$in": AuditLog.blind_index_candidates(customer_id)
            },
            "resolved_at": None,
        }
    )
    return {
        "pseudonymized": changed,
        "held": held,
        "remaining": remaining,
        "queued_failures_removed": int(queued.deleted_count),
    }


def export_customer_audit_data(db, customer_id, *, limit=1000):
    """Export bounded subject-related event metadata without other actors' PII."""
    collection = db[AuditLog.collection_name]
    query = _subject_query(customer_id)
    total = collection.count_documents(query)
    cursor = collection.find(query).sort([("timestamp", -1), ("_id", -1)]).limit(
        max(1, min(int(limit), 5000))
    )
    items = []
    for raw in cursor:
        event = AuditLog.from_dict(raw)
        items.append(
            {
                "event_id": event.event_id,
                "action": event.action,
                "action_group": event.action_group,
                "resource_type": event.resource_type,
                "resource_id": str(event.resource_id) if event.resource_id else None,
                "timestamp": event.timestamp,
                "retention_expires_at": event.retention_expires_at,
                "legal_hold": event.legal_hold,
            }
        )
    return {"items": items, "total": total, "truncated": total > len(items)}


def audit_integrity_inventory(*, limit=10000):
    """Return a read-only bounded inventory of protection and integrity gaps."""
    collection = settings.MONGODB[AuditLog.collection_name]
    counters = {
        "scanned": 0,
        "missing_integrity": 0,
        "invalid_integrity": 0,
        "missing_retention": 0,
        "plaintext_sensitive_fields": 0,
    }
    for raw in collection.find({}, limit=max(1, min(int(limit), 100000))):
        counters["scanned"] += 1
        if not raw.get("integrity_hash"):
            counters["missing_integrity"] += 1
        elif not AuditLog.verify_integrity_document(raw):
            counters["invalid_integrity"] += 1
        if not raw.get("retention_expires_at") or not raw.get(
            "retention_policy_version"
        ):
            counters["missing_retention"] += 1
        for field in AuditLog.encrypted_fields:
            value = raw.get(field)
            if value not in (None, "", {}, []) and not is_encrypted_value(value):
                counters["plaintext_sensitive_fields"] += 1
    return counters


def prepare_legacy_audit_backfill(raw):
    """Build a protected v2 replacement without rewriting event semantics."""
    if raw.get("integrity_hash") and not AuditLog.verify_integrity_document(raw):
        raise ValueError("Existing audit integrity hash is invalid")
    event = AuditLog.from_dict(raw)
    if event.action not in AUDIT_ACTION_REGISTRY:
        raise ValueError(
            f"Legacy action '{event.action}' is not registered; review it manually"
        )
    event.event_schema_version = 2
    event.action_group = AUDIT_ACTION_REGISTRY[event.action]
    event.event_id = raw.get("event_id") or f"evt_legacy_{raw['_id']}"
    if not event.retention_expires_at:
        days = int(getattr(settings, "ANALYTICS_AUDIT_RETENTION_DAYS", 2555))
        event.retention_expires_at = event.timestamp + timedelta(days=days)
    event.retention_policy_version = (
        event.retention_policy_version
        or getattr(
            settings,
            "ANALYTICS_AUDIT_RETENTION_POLICY_VERSION",
            "2026-08-12-v1",
        )
    )
    if not event.subject_index:
        subject_id = (event.details or {}).get("customer_id")
        if not subject_id and event.user_type == "customer":
            subject_id = event.user_id
        event.subject_index = AuditLog.blind_index(subject_id)
    event.payload_digest = event.payload_digest or hashlib.sha256(
        AuditLog._canonical_json(event._payload_for_digest())
    ).hexdigest()
    protected = event.to_storage_dict()
    protected.pop("_id", None)
    return protected
