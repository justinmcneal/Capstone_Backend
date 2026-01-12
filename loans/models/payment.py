"""
LoanPayment Model - Records customer payments.
"""
from datetime import datetime
from bson import ObjectId
from django.conf import settings


def get_db():
    return settings.MONGODB


PAYMENT_METHODS = ['cash', 'bank_transfer', 'gcash', 'maya', 'other']


class LoanPayment:
    """
    Records individual loan payments.
    """
    collection_name = 'loan_payments'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.loan_id = kwargs.get('loan_id')
        self.schedule_id = kwargs.get('schedule_id')
        self.customer_id = kwargs.get('customer_id')
        self.installment_number = kwargs.get('installment_number')
        
        # Payment details
        self.amount = kwargs.get('amount', 0)
        self.payment_method = kwargs.get('payment_method', 'cash')
        self.reference = kwargs.get('reference', '')
        self.notes = kwargs.get('notes', '')
        
        # Recording info
        self.recorded_by = kwargs.get('recorded_by')  # Officer ID
        self.recorded_at = kwargs.get('recorded_at', datetime.utcnow())
    
    @property
    def id(self):
        return str(self._id) if self._id else None
    
    def to_dict(self):
        data = {
            'loan_id': self.loan_id,
            'schedule_id': self.schedule_id,
            'customer_id': self.customer_id,
            'installment_number': self.installment_number,
            'amount': self.amount,
            'payment_method': self.payment_method,
            'reference': self.reference,
            'notes': self.notes,
            'recorded_by': self.recorded_by,
            'recorded_at': self.recorded_at,
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
    
    @classmethod
    def find_by_loan(cls, loan_id):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find({'loan_id': str(loan_id)}).sort('recorded_at', -1)
        return [cls.from_dict(doc) for doc in docs]
    
    @classmethod
    def find_by_customer(cls, customer_id):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find({'customer_id': str(customer_id)}).sort('recorded_at', -1)
        return [cls.from_dict(doc) for doc in docs]
    
    @classmethod
    def get_total_paid(cls, loan_id):
        """Get total amount paid for a loan"""
        payments = cls.find_by_loan(loan_id)
        return sum(p.amount for p in payments)
    
    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('loan_id')
        collection.create_index('schedule_id')
        collection.create_index('customer_id')
        collection.create_index('recorded_at')
