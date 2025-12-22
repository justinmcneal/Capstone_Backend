from datetime import datetime
import bcrypt
from bson import ObjectId
from django.conf import settings


def get_db():
    """Helper function to get the MongoDB database instance"""
    return settings.MONGODB


class Customer:
    """Customer model using PyMongo"""
    collection_name = 'customer'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.first_name = kwargs.get('first_name')
        self.middle_name = kwargs.get('middle_name', '')
        self.last_name = kwargs.get('last_name')
        self.email = kwargs.get('email')
        self.password = kwargs.get('password')
        self.role = kwargs.get('role', 'customer')
        self.verified = kwargs.get('verified', False)
        self.created_at = kwargs.get('created_at', datetime.utcnow())
        self.updated_at = kwargs.get('updated_at', datetime.utcnow())
        
        # Email verification
        self.verification_token = kwargs.get('verification_token')
        self.verification_token_expires = kwargs.get('verification_token_expires')
        self.verification_resend_count = kwargs.get('verification_resend_count', 0)
        self.otp_attempt_count = kwargs.get('otp_attempt_count', 0)
        self.otp_last_attempt = kwargs.get('otp_last_attempt')
        
        # Login rate limiting
        self.last_login_attempt = kwargs.get('last_login_attempt')
        self.login_attempt_count = kwargs.get('login_attempt_count', 0)
        
        # Account lockout protection
        self.failed_login_attempts = kwargs.get('failed_login_attempts', 0)
        self.locked_until = kwargs.get('locked_until')
        
        # Password reset fields
        self.password_reset_otp = kwargs.get('password_reset_otp')
        self.password_reset_otp_expires = kwargs.get('password_reset_otp_expires')
        self.password_reset_attempt_count = kwargs.get('password_reset_attempt_count', 0)
        self.password_reset_last_attempt = kwargs.get('password_reset_last_attempt')
        
        # Two-Factor Authentication (2FA)
        self.two_factor_enabled = kwargs.get('two_factor_enabled', False)
        self.two_factor_secret = kwargs.get('two_factor_secret')
        self.backup_codes = kwargs.get('backup_codes', [])
    
    @property
    def id(self):
        """Get string representation of _id"""
        return str(self._id) if self._id else None
    
    def to_dict(self):
        """Convert instance to dictionary for MongoDB operations"""
        data = {
            'first_name': self.first_name,
            'middle_name': self.middle_name,
            'last_name': self.last_name,
            'email': self.email,
            'password': self.password,
            'role': self.role,
            'verified': self.verified,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'verification_token': self.verification_token,
            'verification_token_expires': self.verification_token_expires,
            'verification_resend_count': self.verification_resend_count,
            'otp_attempt_count': self.otp_attempt_count,
            'otp_last_attempt': self.otp_last_attempt,
            'last_login_attempt': self.last_login_attempt,
            'login_attempt_count': self.login_attempt_count,
            'failed_login_attempts': self.failed_login_attempts,
            'locked_until': self.locked_until,
            'password_reset_otp': self.password_reset_otp,
            'password_reset_otp_expires': self.password_reset_otp_expires,
            'password_reset_attempt_count': self.password_reset_attempt_count,
            'password_reset_last_attempt': self.password_reset_last_attempt,
            'two_factor_enabled': self.two_factor_enabled,
            'two_factor_secret': self.two_factor_secret,
            'backup_codes': self.backup_codes,
        }
        if self._id:
            data['_id'] = self._id
        return data
    
    @classmethod
    def from_dict(cls, data):
        """Create Customer instance from MongoDB document"""
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
        """Save customer to database"""
        db = get_db()
        collection = db[self.collection_name]
        
        self.updated_at = datetime.utcnow()
        data = self.to_dict()
        
        if self._id:
            # Update existing document
            collection.update_one(
                {'_id': self._id},
                {'$set': data}
            )
        else:
            # Insert new document
            result = collection.insert_one(data)
            self._id = result.inserted_id
        
        return self
    
    def delete(self):
        """Delete customer from database"""
        if self._id:
            db = get_db()
            collection = db[self.collection_name]
            collection.delete_one({'_id': self._id})
    
    @classmethod
    def find_one(cls, query):
        """Find one customer by query"""
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)
    
    @classmethod
    def find(cls, query, **kwargs):
        """Find multiple customers by query"""
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find(query, **kwargs)
        return [cls.from_dict(doc) for doc in docs]
    
    @classmethod
    def create_indexes(cls):
        """Create indexes for the collection"""
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('email', unique=True)


class BlacklistedToken:
    """BlacklistedToken model using PyMongo"""
    collection_name = 'blacklisted_tokens'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.token = kwargs.get('token')
        self.token_type = kwargs.get('token_type', 'refresh')
        self.blacklisted_at = kwargs.get('blacklisted_at', datetime.utcnow())
        self.expires_at = kwargs.get('expires_at')
    
    @property
    def id(self):
        return str(self._id) if self._id else None
    
    def to_dict(self):
        data = {
            'token': self.token,
            'token_type': self.token_type,
            'blacklisted_at': self.blacklisted_at,
            'expires_at': self.expires_at,
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
            collection.update_one(
                {'_id': self._id},
                {'$set': data}
            )
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        
        return self
    
    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)
    
    @classmethod
    def find(cls, query, **kwargs):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find(query, **kwargs)
        return [cls.from_dict(doc) for doc in docs]
    
    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('token', unique=True)
        collection.create_index('token_type')
        collection.create_index('expires_at', expireAfterSeconds=0)


class RefreshTokenEntry:
    """RefreshTokenEntry model using PyMongo"""
    collection_name = 'refresh_tokens'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.customer = kwargs.get('customer')
        self.token_hash = kwargs.get('token_hash')
        self.issued_at = kwargs.get('issued_at', datetime.utcnow())
        self.expires_at = kwargs.get('expires_at')
    
    @property
    def id(self):
        return str(self._id) if self._id else None
    
    def to_dict(self):
        data = {
            'customer': self.customer,
            'token_hash': self.token_hash,
            'issued_at': self.issued_at,
            'expires_at': self.expires_at,
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
            collection.update_one(
                {'_id': self._id},
                {'$set': data}
            )
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        
        return self
    
    def delete(self):
        if self._id:
            db = get_db()
            collection = db[self.collection_name]
            collection.delete_one({'_id': self._id})
    
    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)
    
    @classmethod
    def find(cls, query, **kwargs):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find(query, **kwargs)
        return [cls.from_dict(doc) for doc in docs]
    
    @classmethod
    def delete_many(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        return collection.delete_many(query)
    
    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('customer')
        collection.create_index('token_hash')
        collection.create_index('expires_at', expireAfterSeconds=0)


