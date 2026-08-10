"""Durable delivery records for document reviewer notifications."""

import hashlib
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from django.conf import settings
from pymongo import ReturnDocument

from config.field_encryption import decrypt_fields, encrypt_fields


class DocumentNotificationDelivery:
    collection_name = "document_notification_deliveries"
    encrypted_fields = (
        "recipient_email",
        "recipient_name",
        "customer_name",
        "issues",
        "notes",
    )

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.document_id = str(kwargs.get("document_id", ""))
        self.delivery_type = kwargs.get("delivery_type", "pending_review")
        self.recipient_key = kwargs.get("recipient_key", "")
        self.recipient_email = kwargs.get("recipient_email", "")
        self.recipient_name = kwargs.get("recipient_name", "")
        self.recipient_user_id = str(kwargs.get("recipient_user_id", ""))
        self.recipient_user_type = kwargs.get("recipient_user_type", "loan_officer")
        self.customer_name = kwargs.get("customer_name", "Customer")
        self.document_type = kwargs.get("document_type", "")
        self.issues = kwargs.get("issues", [])
        self.notes = kwargs.get("notes", "")
        self.status = kwargs.get("status", "pending")
        self.attempt_count = int(kwargs.get("attempt_count", 0) or 0)
        self.next_attempt_at = kwargs.get("next_attempt_at")
        self.lease_started_at = kwargs.get("lease_started_at")
        self.last_error_code = kwargs.get("last_error_code", "")
        self.delivered_at = kwargs.get("delivered_at")
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))

    @property
    def id(self):
        return str(self._id) if self._id else None

    @staticmethod
    def build_recipient_key(user_type, user_id, email):
        identity = f"{user_type}:{user_id}:{str(email).strip().lower()}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def to_dict(self):
        data = {
            "document_id": self.document_id,
            "delivery_type": self.delivery_type,
            "recipient_key": self.recipient_key,
            "recipient_email": self.recipient_email,
            "recipient_name": self.recipient_name,
            "recipient_user_id": self.recipient_user_id,
            "recipient_user_type": self.recipient_user_type,
            "customer_name": self.customer_name,
            "document_type": self.document_type,
            "issues": self.issues,
            "notes": self.notes,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "next_attempt_at": self.next_attempt_at,
            "lease_started_at": self.lease_started_at,
            "last_error_code": self.last_error_code,
            "delivered_at": self.delivered_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))

    @classmethod
    def ensure(cls, *, document, recipient, customer_name):
        now = datetime.now(timezone.utc)
        recipient_key = cls.build_recipient_key(
            recipient["user_type"], recipient["user_id"], recipient["email"]
        )
        query = {
            "document_id": str(document.id),
            "delivery_type": "pending_review",
            "recipient_key": recipient_key,
        }
        encrypted = cls(
            document_id=document.id,
            recipient_key=recipient_key,
            recipient_email=recipient["email"],
            recipient_name=recipient["name"],
            recipient_user_id=recipient["user_id"],
            recipient_user_type=recipient["user_type"],
            customer_name=customer_name,
            document_type=document.document_type,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        ).to_dict()
        record = settings.MONGODB[cls.collection_name].find_one_and_update(
            query,
            {"$setOnInsert": encrypted},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return cls.from_dict(record)

    @classmethod
    def ensure_customer_outcome(
        cls, *, document, customer, delivery_type, issues=None, notes=""
    ):
        """Persist one idempotent approved/flagged customer delivery."""
        if delivery_type not in {"approved", "rejected", "reupload_requested"}:
            raise ValueError("Unsupported customer document delivery type")
        now = datetime.now(timezone.utc)
        email = str(customer.email or "").strip()
        recipient_key = cls.build_recipient_key("customer", customer.id, email)
        query = {
            "document_id": str(document.id),
            "delivery_type": delivery_type,
            "recipient_key": recipient_key,
        }
        record = cls(
            document_id=document.id,
            delivery_type=delivery_type,
            recipient_key=recipient_key,
            recipient_email=email,
            recipient_name=(
                f"{getattr(customer, 'first_name', '')} "
                f"{getattr(customer, 'last_name', '')}"
            ).strip()
            or email
            or "Customer",
            recipient_user_id=customer.id,
            recipient_user_type="customer",
            customer_name="Customer",
            document_type=document.document_type,
            issues=list(issues or []),
            notes=notes or "",
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        ).to_dict()
        raw = settings.MONGODB[cls.collection_name].find_one_and_update(
            query,
            {"$setOnInsert": record},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return cls.from_dict(raw)

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
        record = settings.MONGODB[cls.collection_name].find_one_and_update(
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
        return cls.from_dict(record)

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

    def defer(self, error_code, *, max_attempts=5, backoff_seconds=60):
        now = datetime.now(timezone.utc)
        exhausted = self.attempt_count >= max(1, int(max_attempts))
        next_attempt = None
        if not exhausted:
            next_attempt = now + timedelta(
                seconds=max(1, int(backoff_seconds))
                * (2 ** max(0, self.attempt_count - 1))
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
        lease_seconds = max(
            30, int(getattr(settings, "DOCUMENT_NOTIFICATION_LEASE_SECONDS", 300))
        )
        stale_before = now - timedelta(seconds=lease_seconds)
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
            .sort("next_attempt_at", 1)
            .limit(max(1, min(int(limit), 1000)))
        )
        return [str(item["_id"]) for item in cursor]

    @classmethod
    def create_indexes(cls):
        collection = settings.MONGODB[cls.collection_name]
        collection.create_index(
            [("document_id", 1), ("delivery_type", 1), ("recipient_key", 1)],
            unique=True,
            name="unique_document_reviewer_delivery",
        )
        collection.create_index(
            [("status", 1), ("next_attempt_at", 1)],
            name="document_notification_reconciliation",
        )
        collection.create_index(
            [("status", 1), ("lease_started_at", 1)],
            name="document_notification_stale_lease",
        )
