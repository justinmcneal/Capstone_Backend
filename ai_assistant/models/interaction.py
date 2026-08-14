"""
AIInteraction Model for storing chat history.
"""
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from django.conf import settings
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from config.field_encryption import decrypt_fields, encrypt_fields


def get_db():
    """Helper function to get MongoDB database instance"""
    return settings.MONGODB


class AIInteraction:
    """
    Model for storing AI chat interactions.
    """
    collection_name = 'ai_interactions'
    encrypted_fields = ('message', 'response', 'legal_hold_reason')
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.customer_id = kwargs.get('customer_id')
        
        # Message content
        self.message = kwargs.get('message', '')  # User's message
        self.response = kwargs.get('response', '')  # AI response
        self.language = kwargs.get('language', 'en')  # en or tl
        
        # Conversation context
        self.conversation_id = kwargs.get('conversation_id')  # Group messages
        self.role = kwargs.get('role', 'user')  # user or assistant
        
        # Metadata
        self.model_used = kwargs.get('model_used', '')  # e.g., llama3.2
        self.response_time_ms = kwargs.get('response_time_ms')  # Processing time
        self.tokens_used = kwargs.get('tokens_used')
        self.request_id = kwargs.get('request_id')  # Correlation/tracing ID

        # Privacy lifecycle
        self.interaction_schema_version = kwargs.get('interaction_schema_version', 2)
        self.retention_policy_version = kwargs.get('retention_policy_version')
        self.retention_expires_at = kwargs.get('retention_expires_at')
        self.legal_hold = bool(kwargs.get('legal_hold', False))
        self.legal_hold_reason = kwargs.get('legal_hold_reason', '')
        self.legal_hold_set_at = kwargs.get('legal_hold_set_at')
        self.legal_hold_set_by = kwargs.get('legal_hold_set_by')
        self.legal_hold_released_at = kwargs.get('legal_hold_released_at')
        self.legal_hold_released_by = kwargs.get('legal_hold_released_by')
        self.pseudonymized_at = kwargs.get('pseudonymized_at')
        self.customer_hidden_at = kwargs.get('customer_hidden_at')
        
        # Timestamps
        self.timestamp = kwargs.get('timestamp', datetime.now(timezone.utc))
        self.created_at = kwargs.get('created_at', datetime.now(timezone.utc))
        if self.retention_expires_at is None:
            self.retention_policy_version = getattr(
                settings,
                'AI_ASSISTANT_RETENTION_POLICY_VERSION',
                '2026-08-14-v1',
            )
            self.retention_expires_at = self.timestamp + timedelta(
                days=int(getattr(settings, 'AI_ASSISTANT_RETENTION_DAYS', 365))
            )
    
    @property
    def id(self):
        return str(self._id) if self._id else None

    @classmethod
    def _search_keys(cls):
        configured = [
            str(getattr(settings, 'FIELD_ENCRYPTION_KEY', '') or '').strip(),
            *[
                str(key or '').strip()
                for key in getattr(settings, 'FIELD_ENCRYPTION_PREVIOUS_KEYS', ())
            ],
        ]
        keys = []
        for value in configured:
            encoded = value.encode('utf-8') if value else None
            if encoded and encoded not in keys:
                keys.append(encoded)
        return keys or [str(settings.SECRET_KEY).encode('utf-8')]

    @staticmethod
    def _search_words(value):
        return sorted(set(re.findall(r'\w+', str(value or '').lower(), flags=re.UNICODE)))

    @classmethod
    def search_tokens(cls, *values, key=None):
        active_key = key or cls._search_keys()[0]
        words = sorted({word for value in values for word in cls._search_words(value)})
        return [
            hmac.new(active_key, word.encode('utf-8'), hashlib.sha256).hexdigest()
            for word in words
        ]

    @classmethod
    def search_key_id(cls):
        return hashlib.sha256(cls._search_keys()[0]).hexdigest()[:12]
    
    def to_dict(self):
        data = {
            'customer_id': self.customer_id,
            'message': self.message,
            'response': self.response,
            'search_tokens': self.search_tokens(self.message, self.response),
            'search_key_id': self.search_key_id(),
            'language': self.language,
            'conversation_id': self.conversation_id,
            'role': self.role,
            'model_used': self.model_used,
            'response_time_ms': self.response_time_ms,
            'tokens_used': self.tokens_used,
            'request_id': self.request_id,
            'interaction_schema_version': self.interaction_schema_version,
            'retention_policy_version': self.retention_policy_version,
            'retention_expires_at': self.retention_expires_at,
            'legal_hold': self.legal_hold,
            'legal_hold_reason': self.legal_hold_reason,
            'legal_hold_set_at': self.legal_hold_set_at,
            'legal_hold_set_by': self.legal_hold_set_by,
            'legal_hold_released_at': self.legal_hold_released_at,
            'legal_hold_released_by': self.legal_hold_released_by,
            'pseudonymized_at': self.pseudonymized_at,
            'customer_hidden_at': self.customer_hidden_at,
            'timestamp': self.timestamp,
            'created_at': self.created_at,
        }
        if self._id:
            data['_id'] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def _customer_id_candidates(cls, customer_id):
        """Return customer_id candidates for both ObjectId and string storage."""
        if customer_id is None:
            return []

        candidates = []

        if isinstance(customer_id, ObjectId):
            candidates.append(customer_id)
            candidates.append(str(customer_id))
        else:
            customer_id_str = str(customer_id)
            candidates.append(customer_id_str)
            if ObjectId.is_valid(customer_id_str):
                candidates.insert(0, ObjectId(customer_id_str))

        deduped = []
        seen = set()
        for value in candidates:
            marker = (type(value).__name__, str(value))
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(value)
        return deduped

    @classmethod
    def _customer_query(cls, customer_id):
        """Build customer filter that supports legacy and current ID shapes."""
        candidates = cls._customer_id_candidates(customer_id)
        if not candidates:
            return {'customer_id': customer_id}
        if len(candidates) == 1:
            return {'customer_id': candidates[0]}
        return {'customer_id': {'$in': candidates}}
    
    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))
    
    def save(self):
        db = get_db()
        collection = db[self.collection_name]
        data = self.to_dict()
        
        if self._id:
            data.pop('_id', None)
            collection.update_one({'_id': self._id}, {'$set': data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        
        return self
    
    def delete(self):
        if self._id:
            db = get_db()
            collection = db[self.collection_name]
            collection.delete_one({'_id': self._id})
            return True
        return False
    
    @classmethod
    def find(cls, query, sort=None, limit=None):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return [cls.from_dict(doc) for doc in cursor]
    
    @classmethod
    def find_by_customer(cls, customer_id, limit=50):
        """Get chat history for a customer"""
        interactions, _ = cls.find_by_customer_paginated(
            customer_id=customer_id,
            page=1,
            limit=limit,
        )
        return interactions

    @classmethod
    def find_by_customer_paginated(
        cls,
        customer_id,
        page=1,
        limit=50,
        search_query=None,
    ):
        """Get paginated chat history for a customer with optional search."""
        db = get_db()
        collection = db[cls.collection_name]

        page = max(1, int(page))
        limit = max(1, int(limit))

        query = cls._customer_query(customer_id)
        query['customer_hidden_at'] = None
        if search_query:
            terms = cls._search_words(search_query)
            if terms:
                query['$and'] = [
                    {
                        'search_tokens': {
                            '$in': [
                                hmac.new(key, term.encode('utf-8'), hashlib.sha256).hexdigest()
                                for key in cls._search_keys()
                            ]
                        }
                    }
                    for term in terms
                ]

        total_count = collection.count_documents(query)
        skip = (page - 1) * limit

        cursor = (
            collection.find(query)
            .sort([('timestamp', -1)])
            .skip(skip)
            .limit(limit)
        )

        interactions = [cls.from_dict(doc) for doc in cursor]
        return interactions, total_count
    
    @classmethod
    def find_by_conversation(cls, conversation_id, customer_id=None):
        """Get all messages in a conversation, optionally scoped to a customer."""
        query = {'conversation_id': str(conversation_id)}
        if customer_id is not None:
            query.update(cls._customer_query(customer_id))
            query['customer_hidden_at'] = None

        return cls.find(
            query,
            sort=[('timestamp', 1)]
        )

    @classmethod
    def find_by_id(cls, interaction_id):
        if not ObjectId.is_valid(str(interaction_id)):
            return None
        return cls.from_dict(
            get_db()[cls.collection_name].find_one({'_id': ObjectId(str(interaction_id))})
        )

    def set_legal_hold(self, *, reason, set_by):
        reason = str(reason or '').strip()
        if not reason:
            raise ValueError('A legal-hold reason is required')
        encrypted_reason = encrypt_fields(
            {'legal_hold_reason': reason}, self.encrypted_fields
        )['legal_hold_reason']
        now = datetime.now(timezone.utc)
        updated = get_db()[self.collection_name].find_one_and_update(
            {'_id': self._id, 'legal_hold': {'$ne': True}},
            {'$set': {
                'legal_hold': True,
                'legal_hold_reason': encrypted_reason,
                'legal_hold_set_at': now,
                'legal_hold_set_by': str(set_by),
            }},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            return False
        refreshed = self.from_dict(updated)
        self.__dict__.update(refreshed.__dict__)
        return True

    def release_legal_hold(self, *, released_by):
        now = datetime.now(timezone.utc)
        updated = get_db()[self.collection_name].find_one_and_update(
            {'_id': self._id, 'legal_hold': True},
            {'$set': {
                'legal_hold': False,
                'legal_hold_reason': '',
                'legal_hold_set_at': None,
                'legal_hold_set_by': None,
                'legal_hold_released_at': now,
                'legal_hold_released_by': str(released_by),
            }},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            return False
        refreshed = self.from_dict(updated)
        self.__dict__.update(refreshed.__dict__)
        return True
    
    @classmethod
    def delete_by_customer(cls, customer_id):
        """Delete ordinary history and hide held evidence from customer history."""
        db = get_db()
        collection = db[cls.collection_name]
        owner_query = cls._customer_query(customer_id)
        deleted = collection.delete_many(
            {**owner_query, 'legal_hold': {'$ne': True}}
        )
        hidden = collection.update_many(
            {**owner_query, 'legal_hold': True, 'customer_hidden_at': None},
            {'$set': {'customer_hidden_at': datetime.now(timezone.utc)}},
        )
        return int(deleted.deleted_count) + int(hidden.modified_count)
    
    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('customer_id')
        collection.create_index('conversation_id')
        collection.create_index('timestamp')
        collection.create_index(
            [('customer_id', ASCENDING), ('timestamp', DESCENDING)],
            name='ai_history_by_customer',
        )
        collection.create_index(
            [('customer_id', ASCENDING), ('conversation_id', ASCENDING), ('timestamp', ASCENDING)],
            name='ai_conversation_by_customer',
        )
        collection.create_index(
            [('legal_hold', ASCENDING), ('retention_expires_at', ASCENDING)],
            name='ai_retention_cleanup',
        )
        collection.create_index(
            [('customer_id', ASCENDING), ('search_tokens', ASCENDING)],
            name='ai_history_search',
        )
