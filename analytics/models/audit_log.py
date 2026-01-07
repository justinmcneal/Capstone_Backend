"""
AuditLog Model - Track all important actions in the system.
"""
from datetime import datetime
from bson import ObjectId
from django.conf import settings


def get_db():
    return settings.MONGODB


# Actions to track
AUDIT_ACTIONS = [
    'user_login',
    'user_logout',
    'user_registered',
    'profile_updated',
    'document_uploaded',
    'document_verified',
    'loan_submitted',
    'loan_approved',
    'loan_rejected',
    'admin_action',
]


class AuditLog:
    """
    Audit log for tracking system actions.
    """
    collection_name = 'audit_logs'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        
        # Who performed the action
        self.user_id = kwargs.get('user_id')
        self.user_type = kwargs.get('user_type', 'customer')  # customer/loan_officer/admin
        self.user_email = kwargs.get('user_email', '')
        
        # What action was performed
        self.action = kwargs.get('action')  # From AUDIT_ACTIONS
        self.description = kwargs.get('description', '')
        
        # Related resource
        self.resource_type = kwargs.get('resource_type')  # loan, document, user
        self.resource_id = kwargs.get('resource_id')
        
        # Additional details
        self.details = kwargs.get('details', {})
        self.ip_address = kwargs.get('ip_address', '')
        
        # Timestamp
        self.timestamp = kwargs.get('timestamp', datetime.utcnow())
    
    @property
    def id(self):
        return str(self._id) if self._id else None
    
    def to_dict(self):
        data = {
            'user_id': self.user_id,
            'user_type': self.user_type,
            'user_email': self.user_email,
            'action': self.action,
            'description': self.description,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'details': self.details,
            'ip_address': self.ip_address,
            'timestamp': self.timestamp,
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
        result = collection.insert_one(data)
        self._id = result.inserted_id
        return self
    
    @classmethod
    def find(cls, query, sort=None, limit=100):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        cursor = cursor.limit(limit)
        return [cls.from_dict(doc) for doc in cursor]
    
    @classmethod
    def find_by_user(cls, user_id, limit=50):
        return cls.find(
            {'user_id': str(user_id)},
            sort=[('timestamp', -1)],
            limit=limit
        )
    
    @classmethod
    def find_recent(cls, limit=100):
        return cls.find(
            {},
            sort=[('timestamp', -1)],
            limit=limit
        )
    
    @classmethod
    def find_by_action(cls, action, limit=100):
        return cls.find(
            {'action': action},
            sort=[('timestamp', -1)],
            limit=limit
        )
    
    @classmethod
    def count_by_action(cls, action, start_date=None, end_date=None):
        db = get_db()
        collection = db[cls.collection_name]
        query = {'action': action}
        if start_date or end_date:
            query['timestamp'] = {}
            if start_date:
                query['timestamp']['$gte'] = start_date
            if end_date:
                query['timestamp']['$lte'] = end_date
        return collection.count_documents(query)
    
    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('user_id')
        collection.create_index('action')
        collection.create_index('timestamp')
        collection.create_index('resource_type')
