"""Durable queue for document objects that could not be deleted inline."""

import hashlib
from datetime import datetime, timedelta, timezone

from django.conf import settings

from config.field_encryption import decrypt_fields, encrypt_fields


class DocumentStorageCleanup:
    """A retryable, idempotent request to remove one storage object."""

    collection_name = "document_storage_cleanup"
    encrypted_fields = ("file_path",)

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.file_path = kwargs.get("file_path", "")
        self.pending_key = kwargs.get("pending_key")
        self.reason = kwargs.get("reason", "orphaned_upload")
        self.document_id = kwargs.get("document_id")
        self.status = kwargs.get("status", "pending")
        self.attempts = int(kwargs.get("attempts", 0) or 0)
        self.last_error = kwargs.get("last_error", "")
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))
        self.purge_at = kwargs.get("purge_at")

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "file_path": self.file_path,
            "pending_key": self.pending_key,
            "reason": self.reason,
            "document_id": self.document_id,
            "status": self.status,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "purge_at": self.purge_at,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        return cls(**decrypt_fields(data, cls.encrypted_fields)) if data else None

    @classmethod
    def enqueue(cls, file_path, *, reason, document_id=None):
        """Insert at most one pending cleanup request for an object path."""
        now = datetime.now(timezone.utc)
        pending_key = hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()
        encrypted = encrypt_fields({"file_path": file_path}, cls.encrypted_fields)
        collection = settings.MONGODB[cls.collection_name]
        collection.update_one(
            {"pending_key": pending_key, "status": "pending"},
            {
                "$setOnInsert": {
                    "file_path": encrypted["file_path"],
                    "pending_key": pending_key,
                    "reason": str(reason)[:100],
                    "document_id": str(document_id) if document_id else None,
                    "status": "pending",
                    "attempts": 0,
                    "last_error": "",
                    "created_at": now,
                    "updated_at": now,
                    "purge_at": None,
                }
            },
            upsert=True,
        )

    @classmethod
    def find_pending(cls, limit=100):
        cursor = (
            settings.MONGODB[cls.collection_name]
            .find({"status": "pending"})
            .sort("updated_at", 1)
            .limit(max(1, min(int(limit), 1000)))
        )
        return [cls.from_dict(item) for item in cursor]

    def mark_completed(self):
        now = datetime.now(timezone.utc)
        result = settings.MONGODB[self.collection_name].update_one(
            {"_id": self._id, "status": "pending"},
            {
                "$set": {
                    "status": "completed",
                    "last_error": "",
                    "updated_at": now,
                    "purge_at": now + timedelta(days=1),
                },
                "$unset": {"pending_key": ""},
                "$inc": {"attempts": 1},
            },
        )
        return result.modified_count == 1

    def mark_failed(self, error_code):
        result = settings.MONGODB[self.collection_name].update_one(
            {"_id": self._id, "status": "pending"},
            {
                "$set": {
                    "last_error": str(error_code)[:100],
                    "updated_at": datetime.now(timezone.utc),
                },
                "$inc": {"attempts": 1},
            },
        )
        return result.modified_count == 1

    @classmethod
    def create_indexes(cls):
        collection = settings.MONGODB[cls.collection_name]
        collection.create_index([("status", 1), ("updated_at", 1)])
        collection.create_index("pending_key", unique=True, sparse=True)
        collection.create_index("purge_at", expireAfterSeconds=0)
