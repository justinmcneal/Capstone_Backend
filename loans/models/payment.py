"""
LoanPayment Model - Records customer payments.
"""

from django.conf import settings

from config.field_encryption import decrypt_fields, encrypt_fields

from loans.utils.time import utcnow


def get_db():
    return settings.MONGODB


PAYMENT_METHODS = ["cash", "gcash", "bank_transfer", "check", "wallet"]


class LoanPayment:
    """
    Records individual loan payments.
    """

    collection_name = "loan_payments"
    encrypted_fields = ("notes", "reference")

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.loan_id = kwargs.get("loan_id")
        self.schedule_id = kwargs.get("schedule_id")
        self.customer_id = kwargs.get("customer_id")
        self.installment_number = kwargs.get("installment_number")

        # Payment details
        self.amount = kwargs.get("amount", 0)
        self.payment_method = kwargs.get("payment_method", "cash")
        self.reference = kwargs.get("reference", "")
        self.notes = kwargs.get("notes", "")

        # Recording info
        self.recorded_by = kwargs.get("recorded_by")  # Officer ID
        self.recorded_at = kwargs.get("recorded_at", utcnow())

        # Blockchain sync tracking
        self.blockchain_tx_hash = kwargs.get("blockchain_tx_hash", "")
        self.blockchain_sync_status = kwargs.get("blockchain_sync_status", "pending")
        self.blockchain_sync_error = kwargs.get("blockchain_sync_error", "")
        self.blockchain_synced_at = kwargs.get("blockchain_synced_at")

        # ETH wallet payment metadata
        self.eth_tx_hash = kwargs.get("eth_tx_hash", "")
        self.eth_amount = kwargs.get("eth_amount", "")
        self.eth_rate = kwargs.get("eth_rate")
        self.eth_rate_source = kwargs.get("eth_rate_source", "")
        self.eth_sender = kwargs.get("eth_sender", "")
        self.eth_block_number = kwargs.get("eth_block_number")

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "loan_id": self.loan_id,
            "schedule_id": self.schedule_id,
            "customer_id": self.customer_id,
            "installment_number": self.installment_number,
            "amount": self.amount,
            "payment_method": self.payment_method,
            "reference": self.reference,
            "notes": self.notes,
            "recorded_by": self.recorded_by,
            "recorded_at": self.recorded_at,
            "blockchain_tx_hash": self.blockchain_tx_hash,
            "blockchain_sync_status": self.blockchain_sync_status,
            "blockchain_sync_error": self.blockchain_sync_error,
            "blockchain_synced_at": self.blockchain_synced_at,
            "eth_tx_hash": self.eth_tx_hash,
            "eth_amount": self.eth_amount,
            "eth_rate": self.eth_rate,
            "eth_rate_source": self.eth_rate_source,
            "eth_sender": self.eth_sender,
            "eth_block_number": self.eth_block_number,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))

    def save(self):
        db = get_db()
        collection = db[self.collection_name]
        data = self.to_dict()

        if self._id:
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        return self

    @classmethod
    def find_by_loan(cls, loan_id):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find({"loan_id": str(loan_id)}).sort("recorded_at", -1)
        return [cls.from_dict(doc) for doc in docs]

    @classmethod
    def find_by_customer(cls, customer_id):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find({"customer_id": str(customer_id)}).sort(
            "recorded_at", -1
        )
        return [cls.from_dict(doc) for doc in docs]

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
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc) if doc else None

    @classmethod
    def count(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        return collection.count_documents(query)

    @classmethod
    def get_total_paid(cls, loan_id):
        """Get total amount paid for a loan"""
        payments = cls.find_by_loan(loan_id)
        return sum(p.amount for p in payments)

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("loan_id")
        collection.create_index("schedule_id")
        collection.create_index("customer_id")
        collection.create_index("recorded_at")

    @classmethod
    def set_sync_result(cls, payment_id, tx_hash):
        db = get_db()
        collection = db[cls.collection_name]
        collection.update_one(
            {"_id": payment_id},
            {
                "$set": {
                    "blockchain_tx_hash": tx_hash,
                    "blockchain_sync_status": "synced",
                    "blockchain_synced_at": utcnow(),
                }
            },
        )

    @classmethod
    def set_sync_failed(cls, payment_id, error):
        db = get_db()
        collection = db[cls.collection_name]
        collection.update_one(
            {"_id": payment_id},
            {
                "$set": {
                    "blockchain_sync_status": "failed",
                    "blockchain_sync_error": str(error)[:500],
                }
            },
        )
