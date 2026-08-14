"""Stage 3 persistence, idempotency, cursor, validator, and index coverage."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId

from ai_assistant.models import AIInteraction
from ai_assistant.services import idempotency
from ai_assistant.services.lifecycle import prepare_legacy_ai_backfill
from ai_assistant.services.request_limits import resolve_request_id


def _exchange(customer_id, request_id, conversation_id=None):
    conversation_id = conversation_id or str(uuid.uuid4())
    return (
        AIInteraction(
            customer_id=str(customer_id),
            conversation_id=conversation_id,
            request_id=request_id,
            role='user',
            message='question',
            response='',
        ),
        AIInteraction(
            customer_id=str(customer_id),
            conversation_id=conversation_id,
            request_id=request_id,
            role='assistant',
            message='',
            response='answer',
            model_used='test-model',
        ),
    )


def test_save_exchange_is_idempotent_and_never_creates_more_than_two_rows(settings):
    request_id = str(uuid.uuid4())
    customer_id = str(ObjectId())
    user, assistant = _exchange(customer_id, request_id)

    AIInteraction.save_exchange(user, assistant)
    AIInteraction.save_exchange(user, assistant)

    rows = AIInteraction.find_by_request_id(customer_id, request_id)
    assert [row.role for row in rows] == ['user', 'assistant']
    assert settings.MONGODB['ai_interactions'].count_documents({}) == 2


def test_retry_repairs_interrupted_development_pair_without_duplicate(settings, monkeypatch):
    request_id = str(uuid.uuid4())
    customer_id = str(ObjectId())
    user, assistant = _exchange(customer_id, request_id)
    collection = settings.MONGODB['ai_interactions']
    original_update = collection.update_one
    calls = {'count': 0}

    def fail_second(*args, **kwargs):
        calls['count'] += 1
        if calls['count'] == 2:
            raise RuntimeError('injected second-write failure')
        return original_update(*args, **kwargs)

    monkeypatch.setattr(collection, 'update_one', fail_second)
    with pytest.raises(RuntimeError, match='injected'):
        AIInteraction._save_exchange_without_transactions(collection, user, assistant)
    assert collection.count_documents({}) == 1

    monkeypatch.setattr(collection, 'update_one', original_update)
    AIInteraction.save_exchange(user, assistant)
    assert collection.count_documents({}) == 2


def test_idempotency_claim_replays_complete_exchange_without_new_work():
    idempotency.create_indexes()
    request_id = str(uuid.uuid4())
    customer_id = str(ObjectId())
    first = idempotency.claim(customer_id, request_id)
    assert first['state'] == 'owned'

    user, assistant = _exchange(customer_id, request_id)
    AIInteraction.save_exchange(user, assistant)
    idempotency.mark_complete(customer_id, request_id)

    replay = idempotency.claim(customer_id, request_id)
    assert replay['state'] == 'replay'
    assert replay['interactions'][-1].response == 'answer'


def test_active_idempotency_lease_returns_in_progress():
    idempotency.create_indexes()
    request_id = str(uuid.uuid4())
    customer_id = str(ObjectId())
    assert idempotency.claim(customer_id, request_id)['state'] == 'owned'
    assert idempotency.claim(customer_id, request_id)['state'] == 'in_progress'


def test_expired_or_failed_idempotency_lease_can_be_reclaimed(settings):
    idempotency.create_indexes()
    request_id = str(uuid.uuid4())
    customer_id = str(ObjectId())
    assert idempotency.claim(customer_id, request_id)['state'] == 'owned'
    settings.MONGODB[idempotency.COLLECTION].update_one(
        {'customer_id': customer_id, 'request_id': request_id},
        {'$set': {'lease_expires_at': datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )
    assert idempotency.claim(customer_id, request_id)['state'] == 'owned'


def test_idempotency_header_must_be_uuid():
    value, error = resolve_request_id(
        SimpleNamespace(headers={'Idempotency-Key': 'not-a-uuid'}, META={})
    )
    assert value is None
    assert error.status_code == 400
    assert error.data['code'] == 'AI_IDEMPOTENCY_KEY_INVALID'


def test_cursor_history_has_no_overlap_and_rejects_tampering():
    customer_id = str(ObjectId())
    conversation_id = str(uuid.uuid4())
    for offset in range(5):
        AIInteraction(
            customer_id=customer_id,
            conversation_id=conversation_id,
            role='user',
            message=str(offset),
            timestamp=datetime.now(timezone.utc) + timedelta(seconds=offset),
        ).save()

    first, cursor = AIInteraction.find_by_customer_cursor(customer_id, limit=2)
    second, next_cursor = AIInteraction.find_by_customer_cursor(
        customer_id, limit=2, cursor=cursor
    )
    assert cursor and next_cursor
    assert {row.id for row in first}.isdisjoint({row.id for row in second})
    with pytest.raises(ValueError, match='Invalid history cursor'):
        AIInteraction.find_by_customer_cursor(customer_id, cursor=cursor + 'tampered')


def test_conversation_lookup_is_database_bounded():
    customer_id = str(ObjectId())
    conversation_id = str(uuid.uuid4())
    for offset in range(15):
        AIInteraction(
            customer_id=customer_id,
            conversation_id=conversation_id,
            role='user',
            message=str(offset),
            timestamp=datetime.now(timezone.utc) + timedelta(seconds=offset),
        ).save()
    rows = AIInteraction.find_by_conversation(conversation_id, customer_id, limit=10)
    assert len(rows) == 10
    assert rows[0].timestamp < rows[-1].timestamp


def test_validator_defines_required_encrypted_lifecycle_shape(monkeypatch, settings):
    settings.FIELD_ENCRYPTION_KEY = 'configured-for-validator-shape-test'
    database = MagicMock()
    monkeypatch.setattr('ai_assistant.models.interaction.get_db', lambda: database)
    AIInteraction.create_validator()
    validator = database.command.call_args.kwargs['validator']['$jsonSchema']
    assert {'customer_id', 'conversation_id', 'role', 'message', 'response'} <= set(
        validator['required']
    )
    assert validator['properties']['role']['enum'] == ['user', 'assistant']
    assert validator['properties']['message']['oneOf'][1]['pattern'].startswith('^enc::v2::')


def test_indexes_include_history_and_exchange_idempotency(settings):
    AIInteraction.create_indexes()
    indexes = settings.MONGODB['ai_interactions'].index_information()
    assert indexes['ai_history_by_customer']['key'] == [
        ('customer_id', 1), ('timestamp', -1), ('_id', -1)
    ]
    assert indexes['ai_exchange_idempotency']['unique'] is True


def test_legacy_backfill_canonicalizes_object_id_owner(settings):
    settings.FIELD_ENCRYPTION_KEY = ''
    owner = ObjectId()
    protected = prepare_legacy_ai_backfill({
        '_id': ObjectId(),
        'customer_id': owner,
        'conversation_id': str(uuid.uuid4()),
        'role': 'user',
        'language': 'en',
        'message': 'legacy',
        'response': '',
        'timestamp': datetime.now(timezone.utc),
        'created_at': datetime.now(timezone.utc),
    })
    assert protected['customer_id'] == str(owner)
