from datetime import datetime
import bcrypt
from bson import ObjectId
from django.conf import settings


def get_db():
    """Helper function to get the MongoDB database instance"""
    return settings.MONGODB


class LoanOfficer:
    """
    Loan Officer model for bank/microfinance institution staff.
    
    Loan officers are created by admins only (no self-registration).
    They can:
    - Review customer loan applications
    - Approve/reject loans
    - View customer profiles (with consent)
    - Access loan analytics
    """
    collection_name = 'loan_officers'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.employee_id = kwargs.get('employee_id')  # Institution employee ID
        self.first_name = kwargs.get('first_name')
        self.last_name = kwargs.get('last_name')
        self.email = kwargs.get('email')
        self.password = kwargs.get('password')
        self.phone = kwargs.get('phone', '')
        self.department = kwargs.get('department', '')  # e.g., "Loan Processing", "Risk Assessment"
        self.role = 'loan_officer'  # Fixed role
        self.verified = kwargs.get('verified', True)  # Admin-created, so verified by default
        self.active = kwargs.get('active', True)  # Can be deactivated by admin
        self.created_at = kwargs.get('created_at', datetime.utcnow())
        self.updated_at = kwargs.get('updated_at', datetime.utcnow())
        self.created_by = kwargs.get('created_by')  # Admin ObjectId who created this officer
        
        # Password reset on first login
        self.must_change_password = kwargs.get('must_change_password', True)
        
        # Login rate limiting
        self.last_login_attempt = kwargs.get('last_login_attempt')
        self.login_attempt_count = kwargs.get('login_attempt_count', 0)
        
        # Account lockout protection
        self.failed_login_attempts = kwargs.get('failed_login_attempts', 0)
        self.locked_until = kwargs.get('locked_until')
        
        # Two-Factor Authentication (2FA)
        self.two_factor_enabled = kwargs.get('two_factor_enabled', False)
        self.two_factor_secret = kwargs.get('two_factor_secret')
        self.backup_codes = kwargs.get('backup_codes', [])
        
        # Password Reset OTP
        self.password_reset_otp = kwargs.get('password_reset_otp')
        self.password_reset_otp_expires = kwargs.get('password_reset_otp_expires')
        self.password_reset_attempt_count = kwargs.get('password_reset_attempt_count', 0)
        self.password_reset_last_attempt = kwargs.get('password_reset_last_attempt')
    
    @property
    def id(self):
        """Get string representation of _id"""
        return str(self._id) if self._id else None
    
    @property
    def full_name(self):
        """Get full name"""
        return f"{self.first_name} {self.last_name}".strip()
    
    def to_dict(self):
        """Convert instance to dictionary for MongoDB operations"""
        data = {
            'employee_id': self.employee_id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'password': self.password,
            'phone': self.phone,
            'department': self.department,
            'role': self.role,
            'verified': self.verified,
            'active': self.active,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'created_by': self.created_by,
            'must_change_password': self.must_change_password,
            'last_login_attempt': self.last_login_attempt,
            'login_attempt_count': self.login_attempt_count,
            'failed_login_attempts': self.failed_login_attempts,
            'locked_until': self.locked_until,
            'two_factor_enabled': self.two_factor_enabled,
            'two_factor_secret': self.two_factor_secret,
            'backup_codes': self.backup_codes,
            'password_reset_otp': self.password_reset_otp,
            'password_reset_otp_expires': self.password_reset_otp_expires,
            'password_reset_attempt_count': self.password_reset_attempt_count,
            'password_reset_last_attempt': self.password_reset_last_attempt,
        }
        if self._id:
            data['_id'] = self._id
        return data
    
    @classmethod
    def from_dict(cls, data):
        """Create LoanOfficer instance from MongoDB document"""
        if not data:
            return None
        return cls(**data)
    
    def set_password(self, raw_password):
        """Hash and set password"""
        self.password = bcrypt.hashpw(raw_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, raw_password):
        """Verify password"""
        return bcrypt.checkpw(raw_password.encode('utf-8'), self.password.encode('utf-8'))
    
    def save(self):
        """Save loan officer to database"""
        db = get_db()
        collection = db[self.collection_name]
        
        self.updated_at = datetime.utcnow()
        data = self.to_dict()
        
        if self._id:
            collection.update_one(
                {'_id': self._id},
                {'$set': data}
            )
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        
        return self
    
    def delete(self):
        """Delete loan officer from database"""
        if self._id:
            db = get_db()
            collection = db[self.collection_name]
            collection.delete_one({'_id': self._id})
    
    @classmethod
    def find_one(cls, query):
        """Find one loan officer by query"""
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)
    
    @classmethod
    def find(cls, query, **kwargs):
        """Find multiple loan officers by query"""
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find(query, **kwargs)
        return [cls.from_dict(doc) for doc in docs]
    
    @classmethod
    def count(cls, query=None):
        """Count loan officers matching query"""
        db = get_db()
        collection = db[cls.collection_name]
        return collection.count_documents(query or {})
    
    @classmethod
    def create_indexes(cls):
        """Create indexes for the collection"""
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('email', unique=True)
        collection.create_index('employee_id', unique=True)
        collection.create_index('department')
        collection.create_index('active')
    
    def get_pending_count(self):
        """Get count of pending applications assigned to this officer"""
        db = get_db()
        return db['loan_applications'].count_documents({
            'assigned_officer': self.id,
            'status': {'$in': ['submitted', 'under_review']}
        })
    
    @classmethod
    def find_active(cls):
        """Find all active loan officers"""
        return cls.find({'active': True})
    
    @classmethod
    def find_with_least_workload(cls):
        """Find active officer with least pending applications"""
        officers = cls.find_active()
        if not officers:
            return None
        
        # Find officer with minimum pending count
        min_officer = None
        min_count = float('inf')
        
        for officer in officers:
            count = officer.get_pending_count()
            if count < min_count:
                min_count = count
                min_officer = officer
        
        return min_officer

