"""
Document Model for MSME Pathways

Stores document metadata and references to uploaded files.
"""
from datetime import datetime
from bson import ObjectId
from django.conf import settings


def get_db():
    """Helper function to get MongoDB database instance"""
    return settings.MONGODB


# Document Types - All optional except valid_id for loan applications
DOCUMENT_TYPES = [
    'valid_id',         # Government-issued ID (required for loan)
    'selfie_with_id',   # Selfie holding ID (identity verification)
    'proof_of_address', # Utility bill, barangay cert
    'business_permit',  # DTI/SEC/Mayor's permit
    'business_photo',   # Photo of business premises
    'income_proof',     # Bank statement, sales records (OPTIONAL - informal economy)
    'other'             # Other supporting documents
]

# Document statuses
DOCUMENT_STATUSES = [
    'pending',      # Uploaded, awaiting review
    'needs_review', # Flagged by AI for quality issues
    'approved',     # Verified by loan officer
    'rejected',     # Rejected by loan officer
    'expired'       # Document has expired
]

# Allowed file types
ALLOWED_MIME_TYPES = [
    'image/jpeg',
    'image/png',
    'image/jpg',
    'application/pdf'
]

# Max file size (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


class Document:
    """
    Document model for storing uploaded files metadata.
    """
    collection_name = 'documents'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.customer_id = kwargs.get('customer_id')
        
        # Document info
        self.document_type = kwargs.get('document_type')  # From DOCUMENT_TYPES
        self.original_filename = kwargs.get('original_filename', '')
        self.file_path = kwargs.get('file_path', '')  # Storage path
        self.file_size = kwargs.get('file_size', 0)  # Bytes
        self.mime_type = kwargs.get('mime_type', '')
        
        # Status and verification
        self.status = kwargs.get('status', 'pending')
        self.verified = kwargs.get('verified', False)
        self.verified_by = kwargs.get('verified_by')  # Loan officer ID
        self.verified_at = kwargs.get('verified_at')
        self.rejection_reason = kwargs.get('rejection_reason', '')
        
        # AI Analysis (for future CNN integration)
        self.confidence_score = kwargs.get('confidence_score')  # 0.0 - 1.0
        self.ai_analysis = kwargs.get('ai_analysis', {})  # CNN results
        self.ai_analyzed_at = kwargs.get('ai_analyzed_at')
        
        # Notes
        self.notes = kwargs.get('notes', '')  # Officer notes
        self.description = kwargs.get('description', '')  # User description
        
        # Re-upload request
        self.reupload_requested = kwargs.get('reupload_requested', False)
        self.reupload_reason = kwargs.get('reupload_reason', '')
        self.reupload_requested_by = kwargs.get('reupload_requested_by')
        self.reupload_requested_at = kwargs.get('reupload_requested_at')
        
        # Timestamps
        self.uploaded_at = kwargs.get('uploaded_at', datetime.utcnow())
        self.updated_at = kwargs.get('updated_at', datetime.utcnow())
    
    @property
    def id(self):
        return str(self._id) if self._id else None
    
    @property
    def file_size_display(self):
        """Human-readable file size"""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def to_dict(self):
        data = {
            'customer_id': self.customer_id,
            'document_type': self.document_type,
            'original_filename': self.original_filename,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'status': self.status,
            'verified': self.verified,
            'verified_by': self.verified_by,
            'verified_at': self.verified_at,
            'rejection_reason': self.rejection_reason,
            'confidence_score': self.confidence_score,
            'ai_analysis': self.ai_analysis,
            'ai_analyzed_at': self.ai_analyzed_at,
            'notes': self.notes,
            'description': self.description,
            'reupload_requested': self.reupload_requested,
            'reupload_reason': self.reupload_reason,
            'reupload_requested_by': self.reupload_requested_by,
            'reupload_requested_at': self.reupload_requested_at,
            'uploaded_at': self.uploaded_at,
            'updated_at': self.updated_at,
        }
        if self._id:
            data['_id'] = self._id
        return data
    
    def request_reupload(self, officer_id, reason):
        """Officer requests customer to re-upload this document"""
        self.reupload_requested = True
        self.reupload_reason = reason
        self.reupload_requested_by = officer_id
        self.reupload_requested_at = datetime.utcnow()
        self.status = 'needs_review'
        return self.save()
    
    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**data)
    
    def save(self):
        db = get_db()
        collection = db[self.collection_name]
        
        self.updated_at = datetime.utcnow()
        data = self.to_dict()
        
        if self._id:
            collection.update_one({'_id': self._id}, {'$set': data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        
        return self
    
    def delete(self):
        """Delete document record from database"""
        if self._id:
            db = get_db()
            collection = db[self.collection_name]
            collection.delete_one({'_id': self._id})
            return True
        return False
    
    @classmethod
    def _customer_id_candidates(cls, customer_id):
        """Return customer_id candidates covering both ObjectId and string storage."""
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
        """Build a Mongo query that matches both legacy and current ID shapes."""
        candidates = cls._customer_id_candidates(customer_id)
        if not candidates:
            return {'customer_id': customer_id}
        if len(candidates) == 1:
            return {'customer_id': candidates[0]}
        return {'customer_id': {'$in': candidates}}

    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)
    
    @classmethod
    def find(cls, query, sort=None):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        return [cls.from_dict(doc) for doc in cursor]
    
    @classmethod
    def find_by_customer(cls, customer_id, document_type=None):
        """Find all documents for a customer, optionally filtered by type"""
        query = cls._customer_query(customer_id)
        if document_type:
            query['document_type'] = document_type
        return cls.find(query, sort=[('uploaded_at', -1)])
    
    @classmethod
    def count_by_customer(cls, customer_id, document_type=None):
        """Count documents for a customer"""
        db = get_db()
        collection = db[cls.collection_name]
        query = cls._customer_query(customer_id)
        if document_type:
            query['document_type'] = document_type
        return collection.count_documents(query)
    
    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('customer_id')
        collection.create_index('document_type')
        collection.create_index([('customer_id', 1), ('document_type', 1)])
        collection.create_index('status')
        collection.create_index('uploaded_at')
