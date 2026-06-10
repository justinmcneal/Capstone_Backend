"""
Device Token Model - Stores FCM push notification tokens.
"""
from datetime import datetime, timezone
from django.conf import settings

def get_db():
    return settings.MONGODB

class DeviceToken:
    collection_name = 'device_tokens'

    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.user_id = str(kwargs.get('user_id', ''))
        self.token = kwargs.get('token', '')
        self.platform = kwargs.get('platform', 'unknown')  # android/ios/web
        self.created_at = kwargs.get('created_at', datetime.now(timezone.utc))
        self.last_used_at = kwargs.get('last_used_at', datetime.now(timezone.utc))
        self.is_active = kwargs.get('is_active', True)

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            'user_id': self.user_id,
            'token': self.token,
            'platform': self.platform,
            'created_at': self.created_at,
            'last_used_at': self.last_used_at,
            'is_active': self.is_active,
        }
        if self._id:
            data['_id'] = self._id
        return data

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
            # Check if token exists
            existing = collection.find_one({'token': self.token})
            if existing:
                self._id = existing['_id']
                collection.update_one({'_id': self._id}, {'$set': data})
            else:
                result = collection.insert_one(data)
                self._id = result.inserted_id
        return self

    @classmethod
    def get_tokens_for_user(cls, user_id):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find({'user_id': str(user_id), 'is_active': True})
        return [cls.from_dict(doc) for doc in cursor]

    @classmethod
    def deactivate_token(cls, token):
        db = get_db()
        collection = db[cls.collection_name]
        collection.update_one(
            {'token': token},
            {'$set': {'is_active': False}}
        )

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('user_id')
        collection.create_index('token', unique=True)
