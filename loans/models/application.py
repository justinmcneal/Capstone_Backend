"""
LoanApplication Model - Customer loan applications.
"""
from datetime import datetime
from bson import ObjectId
from django.conf import settings


def get_db():
    return settings.MONGODB


# Application status flow
APPLICATION_STATUSES = [
    'draft',          # Started but not submitted
    'submitted',      # Submitted, waiting for review
    'under_review',   # Assigned to loan officer
    'approved',       # Approved by loan officer
    'rejected',       # Rejected by loan officer
    'disbursed',      # Loan amount transferred
    'cancelled',      # Cancelled by customer
]


class LoanApplication:
    """
    Customer loan application.
    """
    collection_name = 'loan_applications'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.customer_id = kwargs.get('customer_id')
        self.product_id = kwargs.get('product_id')
        
        # Loan details
        self.requested_amount = kwargs.get('requested_amount', 0)
        self.recommended_amount = kwargs.get('recommended_amount')  # AI recommendation
        self.approved_amount = kwargs.get('approved_amount')  # Final approved
        self.term_months = kwargs.get('term_months', 12)
        self.purpose = kwargs.get('purpose', '')
        
        # AI Scoring
        self.eligibility_score = kwargs.get('eligibility_score')  # 0-100
        self.ai_recommendation = kwargs.get('ai_recommendation', {})  # AI analysis
        self.risk_category = kwargs.get('risk_category')  # low/medium/high
        
        # Status
        self.status = kwargs.get('status', 'draft')
        
        # Loan officer review
        self.assigned_officer = kwargs.get('assigned_officer')  # Loan officer ID
        self.officer_notes = kwargs.get('officer_notes', '')
        self.rejection_reason = kwargs.get('rejection_reason', '')
        self.decision_date = kwargs.get('decision_date')
        
        # Disbursement tracking
        self.disbursed_amount = kwargs.get('disbursed_amount')
        self.disbursed_at = kwargs.get('disbursed_at')
        self.disbursement_method = kwargs.get('disbursement_method')  # bank_transfer, cash, etc.
        self.disbursement_reference = kwargs.get('disbursement_reference', '')
        self.disbursed_by = kwargs.get('disbursed_by')  # Officer/Admin who processed
        
        # Timestamps
        self.submitted_at = kwargs.get('submitted_at')
        self.created_at = kwargs.get('created_at', datetime.utcnow())
        self.updated_at = kwargs.get('updated_at', datetime.utcnow())
    
    @property
    def id(self):
        return str(self._id) if self._id else None
    
    def to_dict(self):
        data = {
            'customer_id': self.customer_id,
            'product_id': self.product_id,
            'requested_amount': self.requested_amount,
            'recommended_amount': self.recommended_amount,
            'approved_amount': self.approved_amount,
            'term_months': self.term_months,
            'purpose': self.purpose,
            'eligibility_score': self.eligibility_score,
            'ai_recommendation': self.ai_recommendation,
            'risk_category': self.risk_category,
            'status': self.status,
            'assigned_officer': self.assigned_officer,
            'officer_notes': self.officer_notes,
            'rejection_reason': self.rejection_reason,
            'decision_date': self.decision_date,
            'disbursed_amount': self.disbursed_amount,
            'disbursed_at': self.disbursed_at,
            'disbursement_method': self.disbursement_method,
            'disbursement_reference': self.disbursement_reference,
            'disbursed_by': self.disbursed_by,
            'submitted_at': self.submitted_at,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
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
        self.updated_at = datetime.utcnow()
        data = self.to_dict()
        
        if self._id:
            collection.update_one({'_id': self._id}, {'$set': data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        return self
    
    def submit(self):
        """Submit the application for review"""
        self.status = 'submitted'
        self.submitted_at = datetime.utcnow()
        return self.save()
    
    def assign_officer(self, officer_id):
        """Assign to a loan officer"""
        self.assigned_officer = officer_id
        self.status = 'under_review'
        return self.save()
    
    def approve(self, officer_id, approved_amount, notes=''):
        """Approve the application"""
        self.status = 'approved'
        self.approved_amount = approved_amount
        self.assigned_officer = officer_id
        self.officer_notes = notes
        self.decision_date = datetime.utcnow()
        return self.save()
    
    def reject(self, officer_id, reason, notes=''):
        """Reject the application"""
        self.status = 'rejected'
        self.assigned_officer = officer_id
        self.rejection_reason = reason
        self.officer_notes = notes
        self.decision_date = datetime.utcnow()
        return self.save()
    
    def disburse(self, amount, method, reference, processed_by):
        """Mark loan as disbursed"""
        if self.status != 'approved':
            raise ValueError("Only approved loans can be disbursed")
        
        self.status = 'disbursed'
        self.disbursed_amount = amount
        self.disbursed_at = datetime.utcnow()
        self.disbursement_method = method
        self.disbursement_reference = reference
        self.disbursed_by = processed_by
        return self.save()
    
    def can_resubmit(self):
        """Check if application can be resubmitted"""
        return self.status == 'rejected'
    
    def resubmit(self):
        """Resubmit a rejected application"""
        if not self.can_resubmit():
            raise ValueError("Only rejected applications can be resubmitted")
        
        # Reset to draft status
        self.status = 'draft'
        self.rejection_reason = None
        self.officer_notes = None
        self.decision_date = None
        self.assigned_officer = None
        self.updated_at = datetime.utcnow()
        return self.save()
    
    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)
    
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
    def find_by_id(cls, app_id):
        try:
            return cls.find_one({'_id': ObjectId(app_id)})
        except:
            return None
    
    @classmethod
    def find_by_customer(cls, customer_id):
        return cls.find(
            {'customer_id': str(customer_id)},
            sort=[('created_at', -1)]
        )
    
    @classmethod
    def find_pending(cls):
        """Get applications pending review"""
        return cls.find(
            {'status': {'$in': ['submitted', 'under_review']}},
            sort=[('submitted_at', 1)]
        )
    
    @classmethod
    def find_by_officer(cls, officer_id):
        """Get applications assigned to officer"""
        return cls.find(
            {'assigned_officer': str(officer_id)},
            sort=[('updated_at', -1)]
        )
    
    @classmethod
    def count_by_status(cls, status):
        db = get_db()
        collection = db[cls.collection_name]
        return collection.count_documents({'status': status})
    
    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('customer_id')
        collection.create_index('product_id')
        collection.create_index('status')
        collection.create_index('assigned_officer')
        collection.create_index('submitted_at')
