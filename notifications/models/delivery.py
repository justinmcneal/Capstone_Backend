"""Durable shared outbox for notification producers without a domain outbox."""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import ClassVar

from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings
from pymongo import ReturnDocument

from config.field_encryption import decrypt_fields, encrypt_fields
from notifications.ownership import normalize_notification_user_type


class NotificationDelivery:
    collection_name = "notification_deliveries"
    encrypted_fields = (
        "recipient_email",
        "recipient_name",
        "payload",
    )
    supported_channels: ClassVar[set[str]] = {"in_app", "email", "push"}
    terminal_statuses: ClassVar[set[str]] = {"delivered", "failed", "suppressed"}

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.event_key = str(kwargs.get("event_key", ""))
        self.event_type = str(kwargs.get("event_type", ""))
        self.recipient_key = str(kwargs.get("recipient_key", ""))
        self.recipient_user_id = str(kwargs.get("recipient_user_id", ""))
        self.recipient_user_type = normalize_notification_user_type(
            kwargs.get("recipient_user_type", "customer")
        )
        self.recipient_email = kwargs.get("recipient_email", "")
        self.recipient_name = kwargs.get("recipient_name", "")
        self.channels = list(kwargs.get("channels", []))
        self.payload = dict(kwargs.get("payload", {}) or {})
        self.status = kwargs.get("status", "pending")
        self.attempt_count = int(kwargs.get("attempt_count", 0) or 0)
        self.next_attempt_at = kwargs.get("next_attempt_at")
        self.lease_started_at = kwargs.get("lease_started_at")
        self.last_error_code = kwargs.get("last_error_code", "")
        self.notification_id = kwargs.get("notification_id")
        self.email_status = kwargs.get("email_status", "not_requested")
        self.push_status = kwargs.get("push_status", "not_requested")
        self.push_target_hashes = list(kwargs.get("push_target_hashes", []))
        self.push_delivered_hashes = list(kwargs.get("push_delivered_hashes", []))
        self.push_permanent_hashes = list(kwargs.get("push_permanent_hashes", []))
        self.policy_version = kwargs.get("policy_version", "")
        self.preference_key = kwargs.get("preference_key")
        self.preference_allowed = kwargs.get("preference_allowed")
        self.policy_decided_at = kwargs.get("policy_decided_at")
        self.delivered_at = kwargs.get("delivered_at")
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", self.created_at)

    @property
    def id(self):
        return str(self._id) if self._id else None

    @staticmethod
    def recipient_fingerprint(user_type, user_id):
        value = f"{normalize_notification_user_type(user_type)}:{user_id!s}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def to_dict(self):
        data = {
            "event_key": self.event_key,
            "event_type": self.event_type,
            "recipient_key": self.recipient_key,
            "recipient_user_id": self.recipient_user_id,
            "recipient_user_type": self.recipient_user_type,
            "recipient_email": self.recipient_email,
            "recipient_name": self.recipient_name,
            "channels": self.channels,
            "payload": self.payload,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "next_attempt_at": self.next_attempt_at,
            "lease_started_at": self.lease_started_at,
            "last_error_code": self.last_error_code,
            "notification_id": self.notification_id,
            "email_status": self.email_status,
            "push_status": self.push_status,
            "push_target_hashes": self.push_target_hashes,
            "push_delivered_hashes": self.push_delivered_hashes,
            "push_permanent_hashes": self.push_permanent_hashes,
            "policy_version": self.policy_version,
            "preference_key": self.preference_key,
            "preference_allowed": self.preference_allowed,
            "policy_decided_at": self.policy_decided_at,
            "delivered_at": self.delivered_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        return cls(**decrypt_fields(data, cls.encrypted_fields)) if data else None

    @classmethod
    def ensure(
        cls,
        *,
        event_key,
        event_type,
        recipient,
        channels,
        payload,
    ):
        normalized_key = str(event_key or "").strip()
        normalized_event = str(event_type or "").strip()
        user_id = str(recipient.get("id", "")).strip()
        user_type = normalize_notification_user_type(recipient.get("user_type"))
        normalized_channels = list(dict.fromkeys(str(item) for item in channels))
        if not normalized_key or not normalized_event or not user_id or not user_type:
            raise ValueError("event and role-qualified recipient are required")
        if not normalized_channels or any(
            channel not in cls.supported_channels for channel in normalized_channels
        ):
            raise ValueError("at least one supported notification channel is required")

        now = datetime.now(timezone.utc)
        recipient_key = cls.recipient_fingerprint(user_type, user_id)
        query = {"event_key": normalized_key, "recipient_key": recipient_key}
        record = cls(
            event_key=normalized_key,
            event_type=normalized_event,
            recipient_key=recipient_key,
            recipient_user_id=user_id,
            recipient_user_type=user_type,
            recipient_email=recipient.get("email", ""),
            recipient_name=recipient.get("name", ""),
            channels=normalized_channels,
            payload=dict(payload or {}),
            email_status=(
                "pending" if "email" in normalized_channels else "not_requested"
            ),
            push_status=(
                "pending" if "push" in normalized_channels else "not_requested"
            ),
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
    def claim(cls, delivery_id, *, lease_seconds):
        try:
            object_id = (
                delivery_id
                if isinstance(delivery_id, ObjectId)
                else ObjectId(str(delivery_id))
            )
        except (InvalidId, TypeError):
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

    def checkpoint(self, **values):
        values["updated_at"] = datetime.now(timezone.utc)
        result = settings.MONGODB[self.collection_name].update_one(
            {"_id": self._id, "status": "sending"}, {"$set": values}
        )
        if result.modified_count:
            for key, value in values.items():
                setattr(self, key, value)
        return result.modified_count == 1

    def mark_delivered(self):
        now = datetime.now(timezone.utc)
        return self.checkpoint(
            status="delivered",
            delivered_at=now,
            lease_started_at=None,
            last_error_code="",
        )

    def mark_suppressed(self):
        now = datetime.now(timezone.utc)
        return self.checkpoint(
            status="suppressed",
            delivered_at=now,
            lease_started_at=None,
            last_error_code="",
        )

    def defer(self, error_code, *, max_attempts, backoff_seconds):
        exhausted = self.attempt_count >= max(1, int(max_attempts))
        now = datetime.now(timezone.utc)
        next_attempt = None
        if not exhausted:
            next_attempt = now + timedelta(
                seconds=max(1, int(backoff_seconds))
                * (2 ** max(0, self.attempt_count - 1))
            )
        return self.checkpoint(
            status="failed" if exhausted else "retry_wait",
            next_attempt_at=next_attempt,
            lease_started_at=None,
            last_error_code=str(error_code)[:64],
        )

    @classmethod
    def due_ids(cls, limit=100):
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(
            seconds=max(30, int(settings.NOTIFICATIONS_DELIVERY_LEASE_SECONDS))
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
        return [str(item["_id"]) for item in cursor]

    @classmethod
    def create_indexes(cls):
        collection = settings.MONGODB[cls.collection_name]
        collection.create_index(
            [("event_key", 1), ("recipient_key", 1)],
            unique=True,
            name="unique_notification_delivery",
        )
        collection.create_index(
            [("status", 1), ("next_attempt_at", 1)],
            name="notification_delivery_due",
        )
        collection.create_index(
            [("status", 1), ("lease_started_at", 1)],
            name="notification_delivery_stale_lease",
        )
        collection.create_index(
            [("recipient_user_id", 1), ("recipient_user_type", 1), ("created_at", -1)],
            name="notification_delivery_owner_history",
        )
