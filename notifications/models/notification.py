"""
Notification Model - Store notification history.
"""
from datetime import datetime, timezone

from django.conf import settings


def get_db():
    return settings.MONGODB


def serialize_utc_datetime(value):
    """Return a datetime as an explicit UTC ISO 8601 string.

    PyMongo stores dates as UTC but, unless configured otherwise, returns them
    as naive ``datetime`` instances.  A timezone-less ISO string is interpreted
    in the browser's local timezone, so API consumers would see an eight-hour
    offset in the Philippines.  Treat naive values from MongoDB as UTC and
    always include the UTC designator in the API contract.
    """
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)

    return value.isoformat().replace('+00:00', 'Z')


# Notification types
NOTIFICATION_TYPES = [
    'loan_submitted',
    'loan_approved',
    'loan_rejected',
    'loan_disbursed',
    'payment_received',
    'document_flagged',
    'document_pending_review',
    'missing_documents_requested',
    'document_verified',
    'new_application',  # For loan officers
    'application_assigned',
    'application_reassigned',
    'application_unassigned',
    'welcome',
    'password_reset',
    'two_factor_setup_started',
    'two_factor_enabled',
    'two_factor_disabled',
    'two_factor_backup_codes_regenerated',
    'two_factor_backup_code_used',
    'password_changed',
    'password_reset_completed',
    'sessions_terminated',
    'email_change_requested',
    'email_changed',
    'account_suspended',
    'account_deactivated',
    'account_deletion_requested',
    'account_deletion_cancelled',
    'account_deleted',
    'two_factor_recovery_requested',
    'two_factor_recovery_approved',
    'two_factor_recovery_rejected',
    'admin_customer_unlock',
    'new_device_login',
    'admin_permissions_changed',
]


class Notification:
    """
    Notification model for tracking sent notifications.
    """
    collection_name = 'notifications'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        
        # Recipient info
        self.user_id = kwargs.get('user_id')
        self.user_type = kwargs.get('user_type', 'customer')  # customer/loan_officer/admin
        self.recipient_email = kwargs.get('recipient_email', '')
        self.recipient_name = kwargs.get('recipient_name', '')
        
        # Notification content
        self.notification_type = kwargs.get('notification_type')
        self.subject = kwargs.get('subject', '')
        self.message = kwargs.get('message', '')
        
        # Related entity
        self.related_type = kwargs.get('related_type')  # loan/document
        self.related_id = kwargs.get('related_id')
        self.metadata = kwargs.get('metadata', {})
        
        # Status
        self.channel = kwargs.get('channel', 'email')
        self.status = kwargs.get('status', 'pending')  # pending/sent/failed
        self.error_message = kwargs.get('error_message', '')
        
        # Timestamps
        self.created_at = kwargs.get('created_at', datetime.now(timezone.utc))
        self.sent_at = kwargs.get('sent_at')
    
    @property
    def id(self):
        return str(self._id) if self._id else None
    
    def to_dict(self):
        data = {
            'user_id': self.user_id,
            'user_type': self.user_type,
            'recipient_email': self.recipient_email,
            'recipient_name': self.recipient_name,
            'notification_type': self.notification_type,
            'subject': self.subject,
            'message': self.message,
            'related_type': self.related_type,
            'related_id': self.related_id,
            'metadata': self.metadata,
            'channel': self.channel,
            'status': self.status,
            'error_message': self.error_message,
            'created_at': self.created_at,
            'sent_at': self.sent_at,
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
            result = collection.insert_one(data)
            self._id = result.inserted_id
        return self
    
    def mark_sent(self):
        self.status = 'sent'
        self.sent_at = datetime.now(timezone.utc)
        return self.save()
    
    def mark_failed(self, error):
        self.status = 'failed'
        self.error_message = str(error)
        return self.save()
    
    @classmethod
    def find_by_user(cls, user_id, limit=50):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find({'user_id': str(user_id)}).sort('created_at', -1).limit(limit)
        return [cls.from_dict(doc) for doc in cursor]
    
    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('user_id')
        collection.create_index('notification_type')
        collection.create_index('created_at')
        collection.create_index('status')
