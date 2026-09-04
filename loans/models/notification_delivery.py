"""Durable, encrypted delivery records for loan customer notifications."""

import hashlib
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from django.conf import settings
from pymongo import ReturnDocument

from config.field_encryption import decrypt_fields, encrypt_fields


class LoanNotificationDelivery:
    collection_name = "loan_notification_deliveries"
    encrypted_fields = ("recipient_email", "recipient_name", "payload")
    event_types = {
        "submitted",
        "approved",
        "rejected",
        "missing_documents",
        "disbursed",
        "payment_received",
    }

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.loan_id = str(kwargs.get("loan_id", ""))
        self.event_type = kwargs.get("event_type", "")
        self.event_key = kwargs.get("event_key", "")
        self.recipient_key = kwargs.get("recipient_key", "")
        self.recipient_email = kwargs.get("recipient_email", "")
        self.recipient_name = kwargs.get("recipient_name", "Customer")
        self.recipient_user_id = str(kwargs.get("recipient_user_id", ""))
        self.recipient_user_type = kwargs.get("recipient_user_type", "customer")
        self.payload = kwargs.get("payload", {})
        self.status = kwargs.get("status", "pending")
        self.attempt_count = int(kwargs.get("attempt_count", 0) or 0)
        self.next_attempt_at = kwargs.get("next_attempt_at")
        self.lease_started_at = kwargs.get("lease_started_at")
        self.last_error_code = kwargs.get("last_error_code", "")
        self.delivered_at = kwargs.get("delivered_at")
        self.pseudonymized_at = kwargs.get("pseudonymized_at")
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "loan_id": self.loan_id,
            "event_type": self.event_type,
            "event_key": self.event_key,
            "recipient_key": self.recipient_key,
            "recipient_email": self.recipient_email,
            "recipient_name": self.recipient_name,
            "recipient_user_id": self.recipient_user_id,
            "recipient_user_type": self.recipient_user_type,
            "payload": self.payload,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "next_attempt_at": self.next_attempt_at,
            "lease_started_at": self.lease_started_at,
            "last_error_code": self.last_error_code,
            "delivered_at": self.delivered_at,
            "pseudonymized_at": self.pseudonymized_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        return cls(**decrypt_fields(data, cls.encrypted_fields)) if data else None

    @staticmethod
    def recipient_fingerprint(user_type, user_id, email):
        value = f"{user_type}:{user_id}:{str(email).strip().lower()}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @classmethod
    def ensure(cls, *, loan_id, event_type, event_key, recipient, payload):
        if event_type not in cls.event_types:
            raise ValueError("Unsupported loan notification event")
        if not str(event_key or "").strip():
            raise ValueError("event_key is required")
        now = datetime.now(timezone.utc)
        recipient_key = cls.recipient_fingerprint(
            recipient.get("user_type", "customer"),
            recipient.get("id", ""),
            recipient.get("email", ""),
        )
        query = {
            "event_key": str(event_key),
            "event_type": event_type,
            "recipient_key": recipient_key,
        }
        raw = cls(
            loan_id=loan_id,
            event_type=event_type,
            event_key=str(event_key),
            recipient_key=recipient_key,
            recipient_email=recipient.get("email", ""),
            recipient_name=recipient.get("name", "Customer"),
            recipient_user_id=recipient.get("id", ""),
            recipient_user_type=recipient.get("user_type", "customer"),
            payload=dict(payload or {}),
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        ).to_dict()
        record = settings.MONGODB[cls.collection_name].find_one_and_update(
            query,
            {"$setOnInsert": raw},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return cls.from_dict(record)

    @classmethod
    def claim(cls, delivery_id, *, lease_seconds=300):
        try:
            object_id = (
                delivery_id
                if isinstance(delivery_id, ObjectId)
                else ObjectId(str(delivery_id))
            )
        except Exception:
            return None
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=max(30, int(lease_seconds)))
        raw = settings.MONGODB[cls.collection_name].find_one_and_update(
            {
                "_id": object_id,
                "$or": [
                    {
                        "status": {"$in": ["pending", "retry_wait"]},
                        "next_attempt_at": {"$lte": now},
                    },
                    {"status": "sending", "lease_started_at": {"$lte": stale_before}},
                ],
            },
            {
                "$set": {
                    "status": "sending",
                    "lease_started_at": now,
                    "next_attempt_at": None,
                    "updated_at": now,
                },
                "$inc": {"attempt_count": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        return cls.from_dict(raw)

    def mark_delivered(self):
        now = datetime.now(timezone.utc)
        return (
            settings.MONGODB[self.collection_name]
            .update_one(
                {"_id": self._id, "status": "sending"},
                {
                    "$set": {
                        "status": "delivered",
                        "delivered_at": now,
                        "lease_started_at": None,
                        "last_error_code": "",
                        "updated_at": now,
                    }
                },
            )
            .modified_count
            == 1
        )

    def defer(self, error_code, *, max_attempts, backoff_seconds):
        now = datetime.now(timezone.utc)
        exhausted = self.attempt_count >= max(1, int(max_attempts))
        next_attempt = (
            None
            if exhausted
            else now
            + timedelta(
                seconds=max(1, int(backoff_seconds))
                * (2 ** max(0, self.attempt_count - 1))
            )
        )
        return (
            settings.MONGODB[self.collection_name]
            .update_one(
                {"_id": self._id, "status": "sending"},
                {
                    "$set": {
                        "status": "failed" if exhausted else "retry_wait",
                        "next_attempt_at": next_attempt,
                        "lease_started_at": None,
                        "last_error_code": str(error_code)[:64],
                        "updated_at": now,
                    }
                },
            )
            .modified_count
            == 1
        )

    @classmethod
    def due_ids(cls, limit=100):
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(
            seconds=max(
                30, int(getattr(settings, "LOAN_NOTIFICATION_LEASE_SECONDS", 300))
            )
        )
        cursor = (
            settings.MONGODB[cls.collection_name]
            .find(
                {
                    "$or": [
                        {
                            "status": {"$in": ["pending", "retry_wait"]},
                            "next_attempt_at": {"$lte": now},
                        },
                        {
                            "status": "sending",
                            "lease_started_at": {"$lte": stale_before},
                        },
                    ]
                },
                {"_id": 1},
            )
            .sort([("next_attempt_at", 1), ("_id", 1)])
            .limit(max(1, min(int(limit), 1000)))
        )
        return [str(row["_id"]) for row in cursor]

    @classmethod
    def create_indexes(cls):
        collection = settings.MONGODB[cls.collection_name]
        collection.create_index(
            [("event_key", 1), ("event_type", 1), ("recipient_key", 1)],
            unique=True,
            name="unique_loan_notification_delivery",
        )
        collection.create_index(
            [("status", 1), ("next_attempt_at", 1)], name="loan_notification_due"
        )
        collection.create_index(
            [("status", 1), ("lease_started_at", 1)],
            name="loan_notification_stale_lease",
        )
        collection.create_index(
            [("loan_id", 1), ("created_at", -1)], name="loan_notification_history"
        )
