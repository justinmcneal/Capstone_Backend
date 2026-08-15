"""
LoanPayment Model - Records customer payments.
"""

import hashlib
import hmac

from django.conf import settings

from config.field_encryption import decrypt_fields, encrypt_fields
from loans.utils.money import from_centavos, to_centavos
from loans.utils.time import utcnow


def get_db():
    return settings.MONGODB


ACTIVE_PAYMENT_METHODS = ("cash", "check", "wallet")
PLANNED_PROVIDER_PAYMENT_METHODS = ("gcash", "bank_transfer")
# Includes reserved values so historical/future records and contract enum
# mappings remain readable. API availability comes from settlement_policy.py.
PAYMENT_METHODS = [*ACTIVE_PAYMENT_METHODS, *PLANNED_PROVIDER_PAYMENT_METHODS]
PAYMENT_STATUSES = [
    "pending_verification",
    "posting",
    "posted",
    "failed",
    "reversed",
]


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
        self.amount_centavos = kwargs.get(
            "amount_centavos", to_centavos(kwargs.get("amount", 0), "amount")
        )
        self.amount = from_centavos(self.amount_centavos)
        self.payment_method = kwargs.get("payment_method", "cash")
        self.reference = kwargs.get("reference", "")
        self.reference_fingerprint = kwargs.get("reference_fingerprint", "")
        self.reference_search_index = kwargs.get("reference_search_index", "")
        self.notes = kwargs.get("notes", "")
        # Existing records predate explicit status and are treated as posted.
        self.payment_status = kwargs.get("payment_status", "posted")
        self.idempotency_key = kwargs.get("idempotency_key", "")
        self.verification_source = kwargs.get("verification_source", "")
        self.verified_at = kwargs.get("verified_at")
        self.failure_reason = kwargs.get("failure_reason", "")
        self.allocations = kwargs.get("allocations", [])
        self.timing_status = kwargs.get("timing_status", "")
        self.scope_officer_id = kwargs.get("scope_officer_id", "")
        self._loan_disbursed_explicit = "loan_disbursed" in kwargs
        self.loan_disbursed = bool(kwargs.get("loan_disbursed", False))

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
            "amount_centavos": self.amount_centavos,
            "payment_method": self.payment_method,
            "reference": self.reference,
            "reference_fingerprint": self.reference_fingerprint,
            "reference_search_index": self.reference_search_index
            or self.blind_index_reference(self.reference),
            "notes": self.notes,
            "payment_status": self.payment_status,
            "idempotency_key": self.idempotency_key,
            "verification_source": self.verification_source,
            "verified_at": self.verified_at,
            "failure_reason": self.failure_reason,
            "allocations": self.allocations,
            "timing_status": self.timing_status,
            "scope_officer_id": self.scope_officer_id,
            "loan_disbursed": self.loan_disbursed,
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
        if not self.scope_officer_id or not self.timing_status or not self._loan_disbursed_explicit:
            from loans.models.application import LoanApplication
            from loans.models.repayment import RepaymentSchedule

            application = LoanApplication.find_by_id(self.loan_id)
            schedule = RepaymentSchedule.find_by_loan(self.loan_id)
            if not self.scope_officer_id and application:
                self.scope_officer_id = str(
                    getattr(application, "assigned_officer", "") or ""
                )
            if not self._loan_disbursed_explicit:
                self.loan_disbursed = bool(
                    application
                    and getattr(application, "status", "")
                    in {"disbursed", "completed", "written_off"}
                )
            if not self.timing_status:
                if self.installment_number == 0:
                    self.timing_status = "payoff"
                else:
                    installment = (
                        schedule.get_installment(self.installment_number)
                        if schedule
                        else None
                    )
                    due_date = installment.get("due_date") if installment else None
                    self.timing_status = (
                        "on_time"
                        if due_date and self.recorded_at.date() <= due_date.date()
                        else "late"
                        if due_date
                        else "unknown"
                    )
        data = self.to_dict()

        if self._id:
            # MongoDB's _id field is immutable and cannot be included in $set.
            data.pop("_id", None)
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        return self

    @staticmethod
    def fingerprint_reference(payment_method, reference):
        """Return a non-reversible, normalized external-reference fingerprint."""
        normalized = f"{payment_method}:{str(reference).strip().lower()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def _search_keys(cls):
        configured = [
            str(getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "").strip(),
            *[
                str(value or "").strip()
                for value in getattr(settings, "FIELD_ENCRYPTION_PREVIOUS_KEYS", ())
            ],
        ]
        keys = []
        for value in configured:
            encoded = value.encode("utf-8") if value else None
            if encoded and encoded not in keys:
                keys.append(encoded)
        return keys or [str(settings.SECRET_KEY).encode("utf-8")]

    @staticmethod
    def _normalized_reference(reference):
        return " ".join(str(reference or "").strip().lower().split())

    @classmethod
    def blind_index_reference(cls, reference, key=None):
        normalized = cls._normalized_reference(reference)
        if not normalized:
            return ""
        active_key = key or cls._search_keys()[0]
        return hmac.new(active_key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()

    @classmethod
    def reference_search_candidates(cls, reference):
        return [
            cls.blind_index_reference(reference, key=key) for key in cls._search_keys()
        ]

    def mark_posted(self, verification_source):
        self.payment_status = "posted"
        self.verification_source = verification_source
        self.verified_at = utcnow()
        self.failure_reason = ""
        return self.save()

    def mark_failed(self, reason):
        self.payment_status = "failed"
        self.failure_reason = str(reason)[:500]
        return self.save()

    @classmethod
    def find_by_loan(cls, loan_id):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find({"loan_id": str(loan_id)}).sort("recorded_at", -1)
        return [cls.from_dict(doc) for doc in docs]

    @classmethod
    def find_by_customer(cls, customer_id, limit=None, projection=None):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find(
            {"customer_id": str(customer_id)}, projection
        ).sort("recorded_at", -1)
        if limit:
            docs = docs.limit(max(1, int(limit)))
        return [cls.from_dict(doc) for doc in docs]

    @classmethod
    def find(cls, query, sort=None, limit=None, skip=None):
        return list(cls.iter_find(query, sort=sort, limit=limit, skip=skip))

    @classmethod
    def iter_find(cls, query, sort=None, limit=None, skip=None):
        """Iterate payments lazily for derived filters and large scans."""
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        for document in cursor:
            payment = cls.from_dict(document)
            if payment:
                yield payment

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
    def summarize(cls, query):
        """Return count and amount across the complete matching result set."""
        db = get_db()
        collection = db[cls.collection_name]
        count = collection.count_documents(query)
        rows = list(
            collection.aggregate(
                [
                    {"$match": query},
                    {
                        "$group": {
                            "_id": None,
                            "total_centavos": {"$sum": "$amount_centavos"},
                        }
                    },
                ]
            )
        )
        if not count:
            return {"count": 0, "total_amount": 0}
        total_centavos = int(rows[0].get("total_centavos", 0)) if rows else 0
        legacy_query = {"$and": [query, {"amount_centavos": {"$exists": False}}]}
        for legacy in collection.find(legacy_query, {"amount": 1}):
            total_centavos += to_centavos(legacy.get("amount", 0), "amount")
        return {
            "count": count,
            "total_amount": from_centavos(total_centavos),
        }

    @classmethod
    def get_total_paid(cls, loan_id):
        """Get total amount paid for a loan"""
        payments = cls.find_by_loan(loan_id)
        total_centavos = sum(
            p.amount_centavos for p in payments if p.payment_status == "posted"
        )
        return from_centavos(total_centavos)

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("loan_id")
        collection.create_index("schedule_id")
        collection.create_index("customer_id")
        collection.create_index("recorded_at")
        collection.create_index("payment_status")
        collection.create_index(
            [("reference_search_index", 1), ("recorded_at", -1), ("_id", -1)],
            name="payment_reference_search",
        )
        collection.create_index(
            [("scope_officer_id", 1), ("recorded_at", -1), ("_id", -1)],
            name="payment_officer_scope_sort",
        )
        collection.create_index(
            [("loan_disbursed", 1), ("timing_status", 1), ("recorded_at", -1)],
            name="payment_lifecycle_timing_sort",
        )
        collection.create_index(
            [("loan_id", 1), ("payment_status", 1), ("recorded_at", -1)],
            name="payment_loan_status_sort",
        )
        collection.create_index(
            "idempotency_key",
            unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string", "$gt": ""}},
        )
        collection.create_index(
            "reference_fingerprint",
            unique=True,
            partialFilterExpression={
                "reference_fingerprint": {"$type": "string", "$gt": ""}
            },
        )
        collection.create_index(
            "eth_tx_hash",
            unique=True,
            partialFilterExpression={"eth_tx_hash": {"$type": "string", "$gt": ""}},
        )

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
