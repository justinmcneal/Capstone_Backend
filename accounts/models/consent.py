from datetime import datetime
from bson import ObjectId
from django.conf import settings


def get_db():
    """Helper function to get the MongoDB database instance"""
    return settings.MONGODB


class Consent:
    """
    Consent model for tracking user consent for data collection and AI features.
    
    Users must provide explicit consent before:
    - Their data is collected and processed (data_consent)
    - They interact with AI-powered features (ai_consent)
    """
    collection_name = 'consents'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.user_id = kwargs.get('user_id')  # Reference to Customer/LoanOfficer ObjectId
        self.user_type = kwargs.get('user_type', 'customer')  # 'customer' or 'loan_officer'
        self.data_consent = kwargs.get('data_consent', False)  # Consent to data collection
        self.ai_consent = kwargs.get('ai_consent', False)  # Consent to AI interactions
        self.consent_date = kwargs.get('consent_date')  # When consent was first given
        self.updated_at = kwargs.get('updated_at', datetime.utcnow())
        self.ip_address = kwargs.get('ip_address', '')  # IP at time of consent for audit
        self.consent_version = kwargs.get('consent_version', '1.0')  # Version of terms accepted
    
    @property
    def id(self):
        """Get string representation of _id"""
        return str(self._id) if self._id else None
    
    @property
    def can_access_ai(self):
        """Check if user can access AI features"""
        return self.ai_consent is True
    
    @property
    def can_access_data_features(self):
        """Check if user can use data-dependent features"""
        return self.data_consent is True
    
    def to_dict(self):
        """Convert instance to dictionary for MongoDB operations"""
        data = {
            'user_id': self.user_id,
            'user_type': self.user_type,
            'data_consent': self.data_consent,
            'ai_consent': self.ai_consent,
            'consent_date': self.consent_date,
            'updated_at': self.updated_at,
            'ip_address': self.ip_address,
            'consent_version': self.consent_version,
        }
        if self._id:
            data['_id'] = self._id
        return data
    
    @classmethod
    def from_dict(cls, data):
        """Create Consent instance from MongoDB document"""
        if not data:
            return None
        return cls(**data)
    
    def save(self):
        """Save consent to database"""
        db = get_db()
        collection = db[self.collection_name]
        
        self.updated_at = datetime.utcnow()
        
        # Set consent_date on first save if any consent is given
        if not self.consent_date and (self.data_consent or self.ai_consent):
            self.consent_date = datetime.utcnow()
        
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
        """Delete consent from database"""
        if self._id:
            db = get_db()
            collection = db[self.collection_name]
            collection.delete_one({'_id': self._id})
    
    @classmethod
    def find_one(cls, query):
        """Find one consent record by query"""
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)
    
    @classmethod
    def find(cls, query, **kwargs):
        """Find multiple consent records by query"""
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find(query, **kwargs)
        return [cls.from_dict(doc) for doc in docs]
    
    @classmethod
    def find_by_user(cls, user_id, user_type='customer'):
        """Find consent record for a specific user"""
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
        return cls.find_one({
            'user_id': user_id,
            'user_type': user_type
        })
    
    @classmethod
    def create_indexes(cls):
        """Create indexes for the collection"""
        db = get_db()
        collection = db[cls.collection_name]
        # Unique index on user_id + user_type combination
        collection.create_index(
            [('user_id', 1), ('user_type', 1)],
            unique=True
        )
