"""Stage 1 AI conversation encryption, retention, and account lifecycle tests."""

from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from django.core.management import call_command

from accounts.management.commands.encrypt_sensitive_fields import FIELD_MAP
from accounts.models import Customer
from accounts.services.account_lifecycle_service import AccountLifecycleService
from ai_assistant.models import AIInteraction
from ai_assistant.services.lifecycle import (
    ai_interaction_inventory,
    delete_customer_ai_data,
    enforce_ai_retention,
    export_customer_ai_history,
)
from config.field_encryption import is_encrypted_value


@pytest.fixture
def ai_encryption(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = ()
    settings.FIELD_ENCRYPTION_STRICT_DECRYPTION = True
    settings.AI_ASSISTANT_RETENTION_DAYS = 365
    settings.AI_ASSISTANT_RETENTION_POLICY_VERSION = 'test-ai-v1'
    return settings


def _interaction(customer_id=None, **overrides):
    values = {
        'customer_id': str(customer_id or ObjectId()),
        'message': 'What is my remaining balance?',
        'response': '',
        'language': 'en',
        'conversation_id': str(ObjectId()),
        'role': 'user',
    }
    values.update(overrides)
    return AIInteraction(**values).save()


def _deletion_customer():
    customer = Customer(
        first_name='AI',
        last_name='Delete',
        email=f'ai-delete-{ObjectId()}@example.test',
        verified=True,
        active=False,
        account_state='pending_deletion',
        deletion_scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    customer.set_password('TestPass123!')
    return customer.save()


def test_new_interactions_encrypt_content_and_receive_versioned_retention(ai_encryption):
    interaction = _interaction()
    raw = ai_encryption.MONGODB[AIInteraction.collection_name].find_one(
        {'_id': interaction._id}
    )

    assert is_encrypted_value(raw['message'])
    assert raw['message'] != interaction.message
    assert raw['interaction_schema_version'] == 2
    assert raw['retention_policy_version'] == 'test-ai-v1'
    assert raw['retention_expires_at'] > raw['timestamp']
    assert raw['search_tokens']
    assert raw['search_key_id'] == AIInteraction.search_key_id()
    assert AIInteraction.find_by_id(interaction.id).message == interaction.message


def test_encrypted_history_search_uses_blind_tokens(ai_encryption):
    customer_id = str(ObjectId())
    expected = _interaction(customer_id=customer_id, message='Outstanding loan balance')
    _interaction(customer_id=customer_id, message='Uploaded document status')

    results, total = AIInteraction.find_by_customer_paginated(
        customer_id, search_query='loan balance'
    )

    assert total == 1
    assert [item.id for item in results] == [expected.id]


def test_legal_hold_blocks_retention_until_release(ai_encryption):
    due = _interaction(
        retention_expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )
    assert due.set_legal_hold(reason='Active complaint', set_by='admin-1') is True
    assert enforce_ai_retention() == {'deleted': 0}

    held = AIInteraction.find_by_id(due.id)
    assert held.legal_hold_reason == 'Active complaint'
    assert held.release_legal_hold(released_by='admin-2') is True
    assert enforce_ai_retention() == {'deleted': 1}
    assert AIInteraction.find_by_id(due.id) is None


def test_account_export_decrypts_allowlisted_ai_history(ai_encryption):
    customer = _deletion_customer()
    interaction = _interaction(customer_id=customer.id)

    direct = export_customer_ai_history(ai_encryption.MONGODB, customer.id)
    payload = AccountLifecycleService.export_customer_data(customer)

    assert direct['items'][0]['content'] == interaction.message
    assert payload['ai_history']['items'][0]['content'] == interaction.message
    assert 'search_tokens' not in payload['ai_history']['items'][0]
    assert 'customer_id' not in payload['ai_history']['items'][0]


def test_account_cleanup_deletes_normal_and_pseudonymizes_held(ai_encryption):
    customer_id = str(ObjectId())
    ordinary = _interaction(customer_id=customer_id)
    legacy_object_id = AIInteraction(
        customer_id=ObjectId(customer_id),
        message='Legacy ObjectId-owned history',
        response='',
        language='en',
        conversation_id=str(ObjectId()),
        role='user',
    ).save()
    held = _interaction(customer_id=customer_id, message='Held evidence')
    assert held.set_legal_hold(reason='Investigation', set_by='admin-1') is True

    counts = delete_customer_ai_data(ai_encryption.MONGODB, customer_id)

    assert counts == {'deleted': 2, 'held_pseudonymized': 1, 'remaining': 0}
    assert AIInteraction.find_by_id(ordinary.id) is None
    assert AIInteraction.find_by_id(legacy_object_id.id) is None
    raw_held = ai_encryption.MONGODB[AIInteraction.collection_name].find_one(
        {'_id': held._id}
    )
    assert raw_held['customer_id'].startswith('deleted:')
    assert raw_held['pseudonymized_at'] is not None
    assert is_encrypted_value(raw_held['message'])


def test_customer_clear_history_hides_but_does_not_delete_held_record(ai_encryption):
    customer_id = str(ObjectId())
    ordinary = _interaction(customer_id=customer_id)
    held = _interaction(customer_id=customer_id, message='Held complaint evidence')
    assert held.set_legal_hold(reason='Active complaint', set_by='admin-1') is True

    assert AIInteraction.delete_by_customer(customer_id) == 2
    assert AIInteraction.find_by_id(ordinary.id) is None
    retained = AIInteraction.find_by_id(held.id)
    assert retained is not None
    assert retained.customer_hidden_at is not None
    assert AIInteraction.find_by_customer(customer_id) == []


def test_final_deletion_tracks_retryable_ai_cleanup(monkeypatch, ai_encryption):
    customer = _deletion_customer()
    _interaction(customer_id=customer.id)

    from ai_assistant.services import lifecycle

    real_cleanup = lifecycle.delete_customer_ai_data

    def interrupted(*args, **kwargs):
        raise RuntimeError('temporary AI cleanup failure')

    monkeypatch.setattr(lifecycle, 'delete_customer_ai_data', interrupted)
    with pytest.raises(RuntimeError, match='temporary AI cleanup failure'):
        AccountLifecycleService.finalize_deletion(customer)

    pending = Customer.find_one({'_id': customer._id})
    assert pending.account_state == 'deleted'
    assert pending.ai_cleanup_status == 'pending'
    assert pending.ai_cleanup_attempts == 1
    assert pending.ai_cleanup_last_error == 'RuntimeError'

    monkeypatch.setattr(lifecycle, 'delete_customer_ai_data', real_cleanup)
    completed = AccountLifecycleService.finalize_deletion(pending)
    assert completed.ai_cleanup_status == 'complete'
    assert completed.ai_cleanup_attempts == 2
    assert completed.ai_cleanup_counts['deleted'] == 1


def test_inventory_and_dry_run_first_backfill(ai_encryption):
    collection = ai_encryption.MONGODB[AIInteraction.collection_name]
    legacy_id = collection.insert_one({
        'customer_id': str(ObjectId()),
        'message': 'legacy private message',
        'response': '',
        'language': 'en',
        'conversation_id': str(ObjectId()),
        'role': 'user',
        'timestamp': datetime.now(timezone.utc),
        'created_at': datetime.now(timezone.utc),
    }).inserted_id

    before = ai_interaction_inventory()
    assert before['plaintext_sensitive_fields'] == 1
    assert before['missing_retention'] == 1
    assert before['stale_search_index'] == 1

    dry_output = StringIO()
    call_command('backfill_ai_interactions', stdout=dry_output)
    assert '[DRY-RUN]' in dry_output.getvalue()
    assert collection.find_one({'_id': legacy_id})['message'] == 'legacy private message'

    call_command('backfill_ai_interactions', '--apply', stdout=StringIO())
    protected = collection.find_one({'_id': legacy_id})
    assert is_encrypted_value(protected['message'])
    assert protected['retention_policy_version'] == 'test-ai-v1'
    assert protected['search_tokens']
    inventory = ai_interaction_inventory()
    assert inventory['plaintext_sensitive_fields'] == 0
    assert inventory['stale_search_index'] == 0


def test_legal_hold_command_is_dry_run_by_default(ai_encryption):
    interaction = _interaction()
    output = StringIO()
    call_command(
        'manage_ai_legal_hold',
        interaction.id,
        'set',
        '--reason',
        'Active case',
        '--operator',
        'admin-1',
        stdout=output,
    )
    assert '[DRY RUN]' in output.getvalue()
    assert AIInteraction.find_by_id(interaction.id).legal_hold is False


def test_global_encryption_backfill_includes_ai_interactions():
    assert FIELD_MAP[AIInteraction.collection_name] == AIInteraction.encrypted_fields
