"""Opt-in Stage 3 proof against an explicitly isolated real MongoDB database."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from pymongo import MongoClient
from pymongo.errors import WriteError

from ai_assistant.models import AIInteraction
from ai_assistant.services import idempotency

pytestmark = pytest.mark.deployment_integration


@pytest.fixture
def ai_real_mongo(settings, monkeypatch):
    uri = os.getenv('AI_ASSISTANT_REAL_MONGO_URI')
    database_name = os.getenv('AI_ASSISTANT_REAL_MONGO_DB')
    if not uri or not database_name:
        pytest.skip('AI_ASSISTANT_REAL_MONGO_URI/DB are not configured')
    if not database_name.lower().endswith(('_test', '_testing', '_isolated')):
        pytest.fail('AI_ASSISTANT_REAL_MONGO_DB must identify an isolated test database')

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    database = client[database_name]
    suffix = uuid.uuid4().hex
    interaction_collection = f'ai_interactions_stage3_{suffix}'
    request_collection = f'ai_chat_requests_stage3_{suffix}'
    database.create_collection(interaction_collection)
    database.create_collection(request_collection)
    monkeypatch.setattr(AIInteraction, 'collection_name', interaction_collection)
    monkeypatch.setattr(idempotency, 'COLLECTION', request_collection)
    settings.MONGODB = database
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    try:
        yield database
    finally:
        database.drop_collection(interaction_collection)
        database.drop_collection(request_collection)
        client.close()


def test_real_mongo_validator_indexes_query_plan_and_atomic_exchange(ai_real_mongo):
    AIInteraction.create_indexes()
    AIInteraction.create_validator()
    idempotency.create_indexes()
    idempotency.create_validator()

    customer_id = '65b7e7f7e4f1a2b3c4d5e6f7'
    request_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    user = AIInteraction(
        customer_id=customer_id,
        request_id=request_id,
        conversation_id=conversation_id,
        role='user',
        message='synthetic question',
    )
    assistant = AIInteraction(
        customer_id=customer_id,
        request_id=request_id,
        conversation_id=conversation_id,
        role='assistant',
        response='synthetic answer',
    )
    rows = AIInteraction.save_exchange(user, assistant)
    assert [row.role for row in rows] == ['user', 'assistant']

    collection = ai_real_mongo[AIInteraction.collection_name]
    raw = collection.find_one({'request_id': request_id, 'role': 'user'})
    assert raw['message'].startswith('enc::v2::')
    indexes = collection.index_information()
    assert indexes['ai_exchange_idempotency']['unique'] is True

    explanation = collection.find(
        {'customer_id': customer_id}
    ).sort([('timestamp', -1), ('_id', -1)]).explain()
    assert 'ai_history_by_customer' in str(explanation)


def test_real_mongo_validator_rejects_plaintext(ai_real_mongo):
    AIInteraction.create_validator()
    now = datetime.now(timezone.utc)
    with pytest.raises(WriteError):
        ai_real_mongo[AIInteraction.collection_name].insert_one({
            'customer_id': '65b7e7f7e4f1a2b3c4d5e6f7',
            'conversation_id': str(uuid.uuid4()),
            'role': 'user',
            'language': 'en',
            'message': 'plaintext is forbidden',
            'response': '',
            'timestamp': now,
            'created_at': now,
            'interaction_schema_version': 2,
            'retention_policy_version': 'test-v1',
            'retention_expires_at': now + timedelta(days=1),
            'legal_hold': False,
        })
