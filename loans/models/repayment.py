"""
RepaymentSchedule Model - Loan repayment installments.
"""
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from bson import ObjectId
from django.conf import settings


def get_db():
    return settings.MONGODB


INSTALLMENT_STATUSES = ['pending', 'paid', 'overdue', 'partial']


class RepaymentSchedule:
    """
    Repayment schedule for disbursed loans.
    """
    collection_name = 'repayment_schedules'
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.loan_id = kwargs.get('loan_id')
        self.customer_id = kwargs.get('customer_id')
        
        # Schedule details
        self.principal = kwargs.get('principal', 0)
        self.interest_rate = kwargs.get('interest_rate', 0)  # Monthly rate
        self.term_months = kwargs.get('term_months', 12)
        self.monthly_payment = kwargs.get('monthly_payment', 0)
        self.total_amount = kwargs.get('total_amount', 0)
        self.total_interest = kwargs.get('total_interest', 0)
        
        # Installments list
        self.installments = kwargs.get('installments', [])
        
        # Timestamps
        self.start_date = kwargs.get('start_date', datetime.utcnow())
        self.created_at = kwargs.get('created_at', datetime.utcnow())
    
    @property
    def id(self):
        return str(self._id) if self._id else None
    
    def to_dict(self):
        data = {
            'loan_id': self.loan_id,
            'customer_id': self.customer_id,
            'principal': self.principal,
            'interest_rate': self.interest_rate,
            'term_months': self.term_months,
            'monthly_payment': self.monthly_payment,
            'total_amount': self.total_amount,
            'total_interest': self.total_interest,
            'installments': self.installments,
            'start_date': self.start_date,
            'created_at': self.created_at,
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
    def generate_for_loan(cls, loan_application, product):
        """
        Generate repayment schedule for a disbursed loan.
        
        Args:
            loan_application: LoanApplication instance
            product: LoanProduct instance
        
        Returns:
            RepaymentSchedule instance
        """
        principal = loan_application.disbursed_amount or loan_application.approved_amount
        interest_rate = product.interest_rate  # Monthly rate
        term_months = loan_application.term_months
        
        # Calculate monthly interest
        monthly_interest = principal * interest_rate
        total_interest = monthly_interest * term_months
        
        # Monthly principal portion
        monthly_principal = principal / term_months
        
        # Total monthly payment
        monthly_payment = monthly_principal + monthly_interest
        total_amount = principal + total_interest
        
        # Generate installments
        installments = []
        start_date = loan_application.disbursed_at or datetime.utcnow()
        
        for i in range(1, term_months + 1):
            due_date = start_date + relativedelta(months=i)
            installments.append({
                'number': i,
                'due_date': due_date,
                'principal': round(monthly_principal, 2),
                'interest': round(monthly_interest, 2),
                'total_amount': round(monthly_payment, 2),
                'status': 'pending',
                'paid_amount': 0,
                'paid_at': None
            })
        
        schedule = cls(
            loan_id=loan_application.id,
            customer_id=loan_application.customer_id,
            principal=principal,
            interest_rate=interest_rate,
            term_months=term_months,
            monthly_payment=round(monthly_payment, 2),
            total_amount=round(total_amount, 2),
            total_interest=round(total_interest, 2),
            installments=installments,
            start_date=start_date
        )
        return schedule.save()
    
    def get_next_payment(self):
        """Get next pending installment"""
        for inst in self.installments:
            if inst['status'] == 'pending':
                return inst
        return None
    
    def get_paid_count(self):
        """Count paid installments"""
        return sum(1 for inst in self.installments if inst['status'] == 'paid')
    
    def get_remaining_balance(self):
        """Calculate remaining balance"""
        paid = sum(inst.get('paid_amount', 0) for inst in self.installments)
        return self.total_amount - paid
    
    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)
    
    @classmethod
    def find_by_loan(cls, loan_id):
        return cls.find_one({'loan_id': str(loan_id)})
    
    @classmethod
    def find_by_customer(cls, customer_id):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find({'customer_id': str(customer_id)})
        return [cls.from_dict(doc) for doc in docs]
    
    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index('loan_id', unique=True)
        collection.create_index('customer_id')
    
    def record_payment(self, installment_number, amount):
        """
        Record a payment against an installment.
        
        Returns:
            Updated installment or None if not found
        """
        for i, inst in enumerate(self.installments):
            if inst['number'] == installment_number:
                inst['paid_amount'] = inst.get('paid_amount', 0) + amount
                
                # Update status based on payment
                if inst['paid_amount'] >= inst['total_amount']:
                    inst['status'] = 'paid'
                    inst['paid_at'] = datetime.utcnow()
                elif inst['paid_amount'] > 0:
                    inst['status'] = 'partial'
                
                self.installments[i] = inst
                self.save()
                return inst
        return None

