"""
MongoDB model for tracking blockchain transactions.

Provides an immutable log of every on-chain transaction attempted by the backend,
including pending, confirmed, and failed states.
"""

from datetime import datetime

from django.conf import settings


def _get_collection():
    """Get the blockchain_transactions MongoDB collection."""
    db = getattr(settings, 'MONGODB', None)
    if db is None:
        return None
    return db['blockchain_transactions']


class BlockchainTransaction:
    """
    Records every blockchain transaction sent by the backend service.
    """
    collection_name = 'blockchain_transactions'

    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_FAILED = 'failed'

    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.tx_hash = kwargs.get('tx_hash', '')
        self.contract_name = kwargs.get('contract_name', '')
        self.method = kwargs.get('method', '')
        self.loan_id = kwargs.get('loan_id', '')
        self.action = kwargs.get('action', '')  # submit, approve, disburse, schedule, payment
        self.status = kwargs.get('status', self.STATUS_PENDING)
        self.gas_used = kwargs.get('gas_used', 0)
        self.block_number = kwargs.get('block_number', 0)
        self.error = kwargs.get('error', '')
        self.details = kwargs.get('details', {})
        self.created_at = kwargs.get('created_at', datetime.utcnow())
        self.completed_at = kwargs.get('completed_at')

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            'tx_hash': self.tx_hash,
            'contract_name': self.contract_name,
            'method': self.method,
            'loan_id': self.loan_id,
            'action': self.action,
            'status': self.status,
            'gas_used': self.gas_used,
            'block_number': self.block_number,
            'error': self.error,
            'details': self.details,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
        }
        if self._id:
            data['_id'] = self._id
        return data

    def save(self):
        collection = _get_collection()
        if collection is None:
            return self
        data = self.to_dict()
        if self._id:
            collection.update_one({'_id': self._id}, {'$set': data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        return self

    @classmethod
    def create_pending(cls, loan_id, action, contract_name, method, details=None):
        """Create a pending transaction record before sending to chain."""
        tx = cls(
            loan_id=loan_id,
            action=action,
            contract_name=contract_name,
            method=method,
            status=cls.STATUS_PENDING,
            details=details or {},
        )
        return tx.save()

    def mark_confirmed(self, tx_hash, gas_used, block_number):
        """Update record after successful on-chain confirmation."""
        self.tx_hash = tx_hash
        self.gas_used = gas_used
        self.block_number = block_number
        self.status = self.STATUS_CONFIRMED
        self.completed_at = datetime.utcnow()
        return self.save()

    def mark_failed(self, error_message):
        """Update record after a permanent failure."""
        self.error = str(error_message)[:2000]
        self.status = self.STATUS_FAILED
        self.completed_at = datetime.utcnow()
        return self.save()

    @classmethod
    def find_by_loan(cls, loan_id):
        """Find all blockchain transactions for a loan."""
        collection = _get_collection()
        if collection is None:
            return []
        cursor = collection.find({'loan_id': loan_id}).sort('created_at', 1)
        return [cls(**doc) for doc in cursor]

    @classmethod
    def find_by_loan_and_action(cls, loan_id, action):
        """Find a specific transaction by loan + action."""
        collection = _get_collection()
        if collection is None:
            return None
        doc = collection.find_one(
            {'loan_id': loan_id, 'action': action, 'status': cls.STATUS_CONFIRMED}
        )
        return cls(**doc) if doc else None
