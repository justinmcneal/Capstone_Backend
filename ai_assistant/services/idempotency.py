"""Lease-backed idempotency for costly AI chat requests."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from django.conf import settings
from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from ai_assistant.models import AIInteraction

COLLECTION = 'ai_chat_requests'


def _collection():
    return settings.MONGODB[COLLECTION]


def _aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_indexes():
    collection = _collection()
    collection.create_index(
        [('customer_id', ASCENDING), ('request_id', ASCENDING)],
        name='ai_chat_request_idempotency',
        unique=True,
    )
    collection.create_index(
        [('status', ASCENDING), ('lease_expires_at', ASCENDING)],
        name='ai_chat_request_recovery',
    )
    collection.create_index(
        'retention_expires_at',
        name='ai_chat_request_expiry',
        expireAfterSeconds=0,
    )


def create_validator():
    settings.MONGODB.command(
        'collMod',
        COLLECTION,
        validator={
            '$jsonSchema': {
                'bsonType': 'object',
                'required': [
                    'customer_id', 'request_id', 'status', 'attempts',
                    'request_fingerprint', 'created_at', 'updated_at',
                    'lease_expires_at', 'retention_expires_at',
                ],
                'properties': {
                    'customer_id': {'bsonType': 'string'},
                    'request_id': {
                        'bsonType': 'string',
                        'pattern': '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
                    },
                    'status': {'enum': ['processing', 'complete', 'failed']},
                    'request_fingerprint': {'bsonType': 'string'},
                    'attempts': {'bsonType': ['int', 'long']},
                    'created_at': {'bsonType': 'date'},
                    'updated_at': {'bsonType': 'date'},
                    'lease_expires_at': {'bsonType': 'date'},
                    'retention_expires_at': {'bsonType': 'date'},
                },
            }
        },
        validationLevel='strict',
        validationAction='error',
    )


def request_fingerprint(
    message,
    conversation_id,
    language,
    *,
    history=None,
    scope_key=None,
):
    parts = [str(message), str(conversation_id), str(language)]
    if history is not None:
        parts.append(json.dumps(history, sort_keys=True, separators=(',', ':')))
    if scope_key is not None:
        parts.append(str(scope_key))
    payload = '\x1f'.join(parts)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def claim(customer_id, request_id, *, fingerprint='', lease_seconds=None):
    """Return owned, replay, or in_progress without invoking the provider."""
    customer_id = str(customer_id)
    request_id = str(request_id)
    key = {'customer_id': customer_id, 'request_id': request_id}
    current = _collection().find_one(
        key,
        {
            'request_fingerprint': 1,
            'status': 1,
            'lease_expires_at': 1,
        },
    )
    if (
        current
        and fingerprint
        and current.get('request_fingerprint')
        and current['request_fingerprint'] != fingerprint
    ):
        return {'state': 'conflict'}
    existing_exchange = AIInteraction.find_by_request_id(customer_id, request_id)
    if len(existing_exchange) == 2:
        mark_complete(customer_id, request_id)
        return {'state': 'replay', 'interactions': existing_exchange}

    now = datetime.now(timezone.utc)
    lease_seconds = lease_seconds or settings.AI_ASSISTANT_IDEMPOTENCY_LEASE_SECONDS
    lease_expires_at = now + timedelta(seconds=max(60, min(int(lease_seconds), 3600)))
    retention_expires_at = now + timedelta(
        days=int(getattr(settings, 'AI_ASSISTANT_RETENTION_DAYS', 365))
    )
    try:
        before = _collection().find_one_and_update(
            {
                **key,
                '$or': [
                    {'status': 'failed'},
                    {'status': 'processing', 'lease_expires_at': {'$lte': now}},
                ],
            },
            {
                '$set': {
                    'status': 'processing',
                    'updated_at': now,
                    'lease_expires_at': lease_expires_at,
                    'request_fingerprint': fingerprint,
                },
                '$setOnInsert': {
                    'created_at': now,
                    'retention_expires_at': retention_expires_at,
                },
                '$inc': {'attempts': 1},
            },
            upsert=True,
            return_document=ReturnDocument.BEFORE,
        )
    except DuplicateKeyError:
        before = _collection().find_one(key)

    if before is None:
        return {'state': 'owned'}
    if before.get('status') == 'complete':
        interactions = AIInteraction.find_by_request_id(customer_id, request_id)
        if len(interactions) == 2:
            return {'state': 'replay', 'interactions': interactions}
        return {'state': 'complete'}
    if before.get('status') == 'failed' or _aware(before.get('lease_expires_at', now)) <= now:
        return {'state': 'owned'}
    return {'state': 'in_progress'}


def mark_complete(customer_id, request_id):
    now = datetime.now(timezone.utc)
    _collection().update_one(
        {'customer_id': str(customer_id), 'request_id': str(request_id)},
        {
            '$set': {'status': 'complete', 'updated_at': now, 'lease_expires_at': now},
            '$setOnInsert': {
                'created_at': now,
                'attempts': 1,
                'request_fingerprint': '',
                'retention_expires_at': now + timedelta(
                    days=int(getattr(settings, 'AI_ASSISTANT_RETENTION_DAYS', 365))
                ),
            },
        },
        upsert=True,
    )


def mark_failed(customer_id, request_id):
    now = datetime.now(timezone.utc)
    _collection().update_one(
        {'customer_id': str(customer_id), 'request_id': str(request_id), 'status': 'processing'},
        {'$set': {'status': 'failed', 'updated_at': now, 'lease_expires_at': now}},
    )
