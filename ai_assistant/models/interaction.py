"""
AIInteraction Model for storing chat history.
"""
from datetime import datetime
import re

from bson import ObjectId
from django.conf import settings


def get_db():
    """Helper function to get MongoDB database instance"""
    return settings.MONGODB


class AIInteraction:
    """
    Model for storing AI chat interactions.
    """
    collection_name = 'ai_interactions'
    
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
        
        # Timestamps
        self.timestamp = kwargs.get('timestamp', datetime.utcnow())
        self.created_at = kwargs.get('created_at', datetime.utcnow())
    
    @property
    def id(self):
        return str(self._id) if self._id else None
    
    def to_dict(self):
        data = {
            'customer_id': self.customer_id,
            'message': self.message,
            'response': self.response,
            'language': self.language,
            'conversation_id': self.conversation_id,
            'role': self.role,
            'model_used': self.model_used,
            'response_time_ms': self.response_time_ms,
            'tokens_used': self.tokens_used,
            'timestamp': self.timestamp,
            'created_at': self.created_at,
        }
        if self._id:
            data['_id'] = self._id
        return data

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
            try:
                candidates.insert(0, ObjectId(customer_id_str))
            except Exception:
                pass

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
        return cls(**data)
    
    def save(self):
        db = get_db()
        collection = db[self.collection_name]
        data = self.to_dict()
        
        if self._id:
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
        if search_query:
            escaped_query = re.escape(search_query)
            query['$or'] = [
                {'message': {'$regex': escaped_query, '$options': 'i'}},
                {'response': {'$regex': escaped_query, '$options': 'i'}},
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

        return cls.find(
            query,
            sort=[('timestamp', 1)]
        )
    
    @classmethod
    def delete_by_customer(cls, customer_id):
        """Delete all chat history for a customer"""
        db = get_db()
        collection = db[cls.collection_name]
        result = collection.delete_many(cls._customer_query(customer_id))
        return result.deleted_count
    
    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('customer_id')
        collection.create_index('conversation_id')
        collection.create_index('timestamp')
        collection.create_index([('customer_id', 1), ('conversation_id', 1), ('timestamp', 1)])
