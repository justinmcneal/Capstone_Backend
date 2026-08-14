"""AI conversation encryption, retention, export, and account cleanup."""

import hashlib
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from django.conf import settings

from ai_assistant.models import AIInteraction
from config.field_encryption import encrypt_fields, is_encrypted_value


def _customer_candidates(customer_id):
    value = str(customer_id or '').strip()
    if not value:
        raise ValueError('customer_id is required')
    candidates = [value]
    if ObjectId.is_valid(value):
        candidates.insert(0, ObjectId(value))
    return candidates


def _customer_query(customer_id):
    candidates = _customer_candidates(customer_id)
    value = candidates[0] if len(candidates) == 1 else {'$in': candidates}
    return {'customer_id': value}


def enforce_ai_retention(limit=500):
    """Delete one bounded batch of expired, non-held interactions."""
    collection = settings.MONGODB[AIInteraction.collection_name]
    now = datetime.now(timezone.utc)
    ids = [
        row['_id']
        for row in collection.find(
            {
                'retention_expires_at': {'$lte': now},
                'legal_hold': {'$ne': True},
            },
            {'_id': 1},
            sort=[('retention_expires_at', 1), ('_id', 1)],
            limit=max(1, min(int(limit), 5000)),
        )
    ]
    if not ids:
        return {'deleted': 0}
    result = collection.delete_many(
        {'_id': {'$in': ids}, 'legal_hold': {'$ne': True}}
    )
    return {'deleted': int(result.deleted_count)}


def export_customer_ai_history(db, customer_id, *, limit=5000):
    """Export an allowlisted, bounded copy of the customer's AI history."""
    collection = db[AIInteraction.collection_name]
    query = _customer_query(customer_id)
    total = collection.count_documents(query)
    cursor = collection.find(query).sort([('timestamp', 1), ('_id', 1)]).limit(
        max(1, min(int(limit), 10000))
    )
    items = []
    for raw in cursor:
        interaction = AIInteraction.from_dict(raw)
        items.append({
            'id': interaction.id,
            'conversation_id': interaction.conversation_id,
            'role': interaction.role,
            'content': (
                interaction.message
                if interaction.role == 'user'
                else interaction.response
            ),
            'language': interaction.language,
            'model_used': interaction.model_used or None,
            'timestamp': interaction.timestamp,
            'retention_expires_at': interaction.retention_expires_at,
            'retention_policy_version': interaction.retention_policy_version,
            'legal_hold': interaction.legal_hold,
        })
    return {'items': items, 'total': total, 'truncated': total > len(items)}


def delete_customer_ai_data(db, customer_id):
    """Delete ordinary history and pseudonymize records protected by legal hold."""
    collection = db[AIInteraction.collection_name]
    owner_query = _customer_query(customer_id)
    deleted = collection.delete_many(
        {**owner_query, 'legal_hold': {'$ne': True}}
    )
    pseudonym = 'deleted:' + hashlib.sha256(
        str(customer_id).encode('utf-8')
    ).hexdigest()[:24]
    held = collection.update_many(
        {**owner_query, 'legal_hold': True},
        {'$set': {
            'customer_id': pseudonym,
            'pseudonymized_at': datetime.now(timezone.utc),
        }},
    )
    remaining = collection.count_documents(owner_query)
    return {
        'deleted': int(deleted.deleted_count),
        'held_pseudonymized': int(held.modified_count),
        'remaining': int(remaining),
    }


def ai_interaction_inventory(*, limit=10000):
    """Return count-only encryption and lifecycle findings for a bounded sample."""
    collection = settings.MONGODB[AIInteraction.collection_name]
    counters = {
        'scanned': 0,
        'plaintext_sensitive_fields': 0,
        'missing_retention': 0,
        'invalid_customer_id': 0,
        'invalid_role': 0,
        'invalid_language': 0,
        'stale_search_index': 0,
    }
    for raw in collection.find({}, limit=max(1, min(int(limit), 100000))):
        counters['scanned'] += 1
        for field in AIInteraction.encrypted_fields:
            value = raw.get(field)
            if value not in (None, '') and not is_encrypted_value(value):
                counters['plaintext_sensitive_fields'] += 1
        if not raw.get('retention_expires_at') or not raw.get(
            'retention_policy_version'
        ):
            counters['missing_retention'] += 1
        owner = str(raw.get('customer_id') or '')
        if not (ObjectId.is_valid(owner) or owner.startswith('deleted:')):
            counters['invalid_customer_id'] += 1
        if raw.get('role', 'user') not in {'user', 'assistant'}:
            counters['invalid_role'] += 1
        if raw.get('language', 'en') not in {'en', 'tl'}:
            counters['invalid_language'] += 1
        if raw.get('search_key_id') != AIInteraction.search_key_id():
            counters['stale_search_index'] += 1
    return counters


def prepare_legacy_ai_backfill(raw):
    """Build encrypted, retained v2 fields without changing conversation meaning."""
    interaction = AIInteraction.from_dict(raw)
    if interaction.role not in {'user', 'assistant'}:
        raise ValueError('Invalid interaction role')
    if interaction.language not in {'en', 'tl'}:
        raise ValueError('Invalid interaction language')
    if not interaction.customer_id:
        raise ValueError('Missing customer_id')
    interaction.interaction_schema_version = 2
    interaction.retention_policy_version = (
        raw.get('retention_policy_version')
        or getattr(
            settings,
            'AI_ASSISTANT_RETENTION_POLICY_VERSION',
            '2026-08-14-v1',
        )
    )
    timestamp = interaction.timestamp or interaction.created_at
    if not interaction.retention_expires_at:
        interaction.retention_expires_at = timestamp + timedelta(
            days=int(getattr(settings, 'AI_ASSISTANT_RETENTION_DAYS', 365))
        )
    protected = interaction.to_dict()
    protected.pop('_id', None)
    # Explicitly encrypt all lifecycle-sensitive fields even if a legacy model
    # instance omitted one of the optional values.
    return encrypt_fields(protected, AIInteraction.encrypted_fields)
