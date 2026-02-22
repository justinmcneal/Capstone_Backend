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
    # Authentication
    'user_login',
    'user_login_failed',
    'user_logout',
    'user_registered',
    # Profile
    'profile_updated',
    # Documents
    'document_uploaded',
    'document_verified',
    'document_rejected',
    # Loans
    'loan_submitted',
    'loan_approved',
    'loan_rejected',
    'loan_disbursed',
    # Payments
    'payment_recorded',
    # Admin
    'admin_action',
]

# High-level action group mapping for analytics filtering.
ACTION_GROUPS = {
    'login': ['user_login', 'user_login_failed', 'user_logout'],
    'create': [
        'user_registered',
        'loan_submitted',
        'document_uploaded',
        'payment_recorded',
    ],
    'update': [
        'profile_updated',
        'document_verified',
        'document_rejected',
        'loan_approved',
        'loan_rejected',
        'loan_disbursed',
        'admin_action',
    ],
}


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
    def find_with_filters(
        cls,
        action=None,
        action_group=None,
        user_id=None,
        user_type=None,
        date_from=None,
        date_to=None,
        limit=100,
    ):
        """
        Find audit logs with optional filters.
        """
        query = {}
        
        # Action filter
        if action:
            query['action'] = action

        # Action-group filter (Login/Create/Update/Delete)
        if action_group:
            group = str(action_group).strip().lower()
            if group in ACTION_GROUPS:
                query['action'] = {'$in': ACTION_GROUPS[group]}
            elif group == 'delete':
                # Most delete/deactivate events are captured as admin_action + descriptive text.
                query['$and'] = [
                    {'action': 'admin_action'},
                    {'description': {'$regex': '(delete|deleted|deactivate|deactivated|remove|removed)', '$options': 'i'}},
                ]

        # User filter
        if user_id:
            query['user_id'] = str(user_id).strip()

        # Role filter
        if user_type:
            query['user_type'] = str(user_type).strip()
        
        # Date range filter
        if date_from or date_to:
            from datetime import datetime, timedelta
            query['timestamp'] = {}
            
            if date_from:
                try:
                    # Parse YYYY-MM-DD format to start of day
                    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
                    query['timestamp']['$gte'] = date_from_obj
                except ValueError:
                    # If parsing fails, ignore the filter
                    pass
                    
            if date_to:
                try:
                    # Parse YYYY-MM-DD format to end of day
                    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
                    # Add 23:59:59 to include the entire day
                    date_to_obj = date_to_obj.replace(hour=23, minute=59, second=59, microsecond=999999)
                    query['timestamp']['$lte'] = date_to_obj
                except ValueError:
                    # If parsing fails, ignore the filter
                    pass
        
        return cls.find(
            query,
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

    @classmethod
    def log_action(cls, action, user_id=None, user_type='customer', user_email='',
                   description='', resource_type=None, resource_id=None, 
                   details=None, ip_address=''):
        """
        Convenience method to create and save an audit log entry.
        
        Usage:
            AuditLog.log_action(
                action='user_login',
                user_id=user.id,
                user_type='customer',
                user_email=user.email,
                description='User logged in successfully',
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
        """
        log = cls(
            user_id=str(user_id) if user_id else None,
            user_type=user_type,
            user_email=user_email,
            action=action,
            description=description,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            details=details or {},
            ip_address=ip_address,
        )
        return log.save()
