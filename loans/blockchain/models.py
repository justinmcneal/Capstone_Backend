"""
MongoDB model for tracking blockchain transactions.

Provides an immutable log of every on-chain transaction attempted by the backend,
including pending, confirmed, and failed states.
"""

import hashlib
import json

from django.conf import settings
from pymongo.errors import DuplicateKeyError

from loans.utils.time import utcnow


def _get_collection():
    """Get the blockchain_transactions MongoDB collection."""
    db = getattr(settings, "MONGODB", None)
    if db is None:
        return None
    return db["blockchain_transactions"]


class BlockchainTransaction:
    """
    Records every blockchain transaction sent by the backend service.
    """

    collection_name = "blockchain_transactions"

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_FAILED = "failed"

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.tx_hash = kwargs.get("tx_hash", "")
        self.contract_name = kwargs.get("contract_name", "")
        self.method = kwargs.get("method", "")
        self.loan_id = kwargs.get("loan_id", "")
        self.action = kwargs.get(
            "action", ""
        )  # submit, approve, disburse, schedule, payment
        self.status = kwargs.get("status", self.STATUS_PENDING)
        self.gas_used = kwargs.get("gas_used", 0)
        self.gas_price = kwargs.get("gas_price", 0)  # Gas price in Wei
        self.block_number = kwargs.get("block_number", 0)
        self.error = kwargs.get("error", "")
        self.details = kwargs.get("details", {})
        self.idempotency_key = kwargs.get("idempotency_key", "")
        self.created_at = kwargs.get("created_at", utcnow())
        self.completed_at = kwargs.get("completed_at")

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "tx_hash": self.tx_hash,
            "contract_name": self.contract_name,
            "method": self.method,
            "loan_id": self.loan_id,
            "action": self.action,
            "status": self.status,
            "gas_used": self.gas_used,
            "gas_price": self.gas_price,
            "block_number": self.block_number,
            "error": self.error,
            "details": self.details,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }
        if self._id:
            data["_id"] = str(self._id)
        return data

    def save(self):
        collection = _get_collection()
        if collection is None:
            return self
        data = self.to_dict()
        data.pop("_id", None)
        if self._id:
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        return self

    @classmethod
    def create_pending(cls, loan_id, action, contract_name, method, details=None):
        """Create a pending transaction record before sending to chain."""
        details = details or {}
        payload = json.dumps(
            {
                "loan_id": str(loan_id),
                "action": action,
                "contract_name": contract_name,
                "method": method,
                "details": details,
            },
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        idempotency_key = hashlib.sha256(payload.encode()).hexdigest()
        collection = _get_collection()
        if collection is not None:
            existing = collection.find_one({"idempotency_key": idempotency_key})
            if existing:
                return cls(**existing)
        tx = cls(
            loan_id=loan_id,
            action=action,
            contract_name=contract_name,
            method=method,
            status=cls.STATUS_PENDING,
            details=details,
            idempotency_key=idempotency_key,
        )
        try:
            return tx.save()
        except DuplicateKeyError:
            existing = collection.find_one({"idempotency_key": idempotency_key})
            if existing:
                return cls(**existing)
            raise

    @classmethod
    def create_indexes(cls):
        collection = _get_collection()
        if collection is None:
            return
        collection.create_index("loan_id")
        collection.create_index("status")
        collection.create_index("created_at")
        collection.create_index(
            "idempotency_key",
            unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string", "$gt": ""}},
        )

    def mark_confirmed(self, tx_hash, gas_used, block_number, gas_price=0):
        """Update record after successful on-chain confirmation."""
        self.tx_hash = tx_hash
        self.gas_used = gas_used
        self.gas_price = gas_price
        self.block_number = block_number
        self.status = self.STATUS_CONFIRMED
        self.completed_at = utcnow()
        return self.save()

    def mark_failed(self, error_message):
        """Update record after a permanent failure."""
        self.error = str(error_message)[:2000]
        self.status = self.STATUS_FAILED
        self.completed_at = utcnow()
        return self.save()

    def step_result(self, step_name):
        """Return a previously confirmed saga step result, if any."""
        return (self.details or {}).get("steps", {}).get(step_name)

    def mark_step_confirmed(self, step_name, result):
        """Persist a completed on-chain step before the next step starts."""
        collection = _get_collection()
        step = {
            "status": "confirmed",
            "result": result,
            "completed_at": utcnow(),
        }
        if collection is not None and self._id:
            collection.update_one(
                {"_id": self._id},
                {
                    "$set": {
                        f"details.steps.{step_name}": step,
                        "status": self.STATUS_PENDING,
                        "error": "",
                        "completed_at": None,
                    }
                },
            )
        self.details = dict(self.details or {})
        self.details.setdefault("steps", {})[step_name] = step
        self.status = self.STATUS_PENDING
        self.error = ""
        return result

    def confirmed_step_result(self, step_name):
        step = self.step_result(step_name)
        if step and step.get("status") == "confirmed":
            return step.get("result")
        return None

    def reopen_for_reconciliation(self):
        self.status = self.STATUS_PENDING
        self.error = ""
        self.completed_at = None
        return self.save()

    @classmethod
    def find_by_loan(cls, loan_id):
        """Find all blockchain transactions for a loan."""
        collection = _get_collection()
        if collection is None:
            return []
        cursor = collection.find({"loan_id": loan_id}).sort("created_at", 1)
        return [cls(**doc) for doc in cursor]

    @classmethod
    def find_by_loan_and_action(cls, loan_id, action):
        """Find a specific transaction by loan + action."""
        collection = _get_collection()
        if collection is None:
            return None
        doc = collection.find_one(
            {"loan_id": loan_id, "action": action, "status": cls.STATUS_CONFIRMED}
        )
        return cls(**doc) if doc else None

    @classmethod
    def find_confirmed(cls, loan_id, action, **details):
        """Find a confirmed transaction by loan + action + nested details."""
        collection = _get_collection()
        if collection is None:
            return None
        query = {
            "loan_id": loan_id,
            "action": action,
            "status": cls.STATUS_CONFIRMED,
        }
        for key, value in details.items():
            query[f"details.{key}"] = value
        doc = collection.find_one(query)
        return cls(**doc) if doc else None
