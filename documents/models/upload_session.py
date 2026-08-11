"""Short-lived, owner-bound sessions for direct document uploads."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from django.conf import settings
from pymongo import ReturnDocument

from config.field_encryption import decrypt_fields, encrypt_fields

UPLOAD_SESSION_STATUSES = (
    "issued",
    "finalizing",
    "completed",
    "failed",
    "expired",
)


def _token_digest(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


class DocumentUploadSession:
    """Metadata and single-use claim state for a quarantined S3 upload."""

    collection_name = "document_upload_sessions"
    encrypted_fields = ("original_filename", "object_key", "description")

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.customer_id = kwargs.get("customer_id")
        self.document_type = kwargs.get("document_type")
        self.original_filename = kwargs.get("original_filename", "")
        self.description = kwargs.get("description", "")
        self.object_key = kwargs.get("object_key", "")
        self.expected_size = kwargs.get("expected_size", 0)
        self.expected_mime_type = kwargs.get("expected_mime_type", "")
        self.expected_sha256 = kwargs.get("expected_sha256", "")
        self.token_digest = kwargs.get("token_digest", "")
        self.status = kwargs.get("status", "issued")
        self.document_id = kwargs.get("document_id")
        self.failure_code = kwargs.get("failure_code", "")
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.expires_at = kwargs.get("expires_at")
        self.finalizing_at = kwargs.get("finalizing_at")
        self.completed_at = kwargs.get("completed_at")
        self.cleaned_at = kwargs.get("cleaned_at")
        self.purge_at = kwargs.get("purge_at")

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "customer_id": self.customer_id,
            "document_type": self.document_type,
            "original_filename": self.original_filename,
            "description": self.description,
            "object_key": self.object_key,
            "expected_size": self.expected_size,
            "expected_mime_type": self.expected_mime_type,
            "expected_sha256": self.expected_sha256,
            "token_digest": self.token_digest,
            "status": self.status,
            "document_id": self.document_id,
            "failure_code": self.failure_code,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "finalizing_at": self.finalizing_at,
            "completed_at": self.completed_at,
            "cleaned_at": self.cleaned_at,
            "purge_at": self.purge_at,
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
    def issue(
        cls,
        *,
        customer_id,
        document_type,
        original_filename,
        description,
        expected_size,
        expected_mime_type,
        expected_sha256,
        lifetime_seconds,
    ):
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        session = cls(
            customer_id=str(customer_id),
            document_type=document_type,
            original_filename=original_filename,
            description=description,
            expected_size=expected_size,
            expected_mime_type=expected_mime_type,
            expected_sha256=expected_sha256.lower(),
            token_digest=_token_digest(token),
            status="issued",
            created_at=now,
            expires_at=now + timedelta(seconds=lifetime_seconds),
        )
        collection = settings.MONGODB[cls.collection_name]
        result = collection.insert_one(session.to_dict())
        session._id = result.inserted_id
        return session, token

    @classmethod
    def find_by_id(cls, session_id):
        value = str(session_id or "").strip()
        if not ObjectId.is_valid(value):
            return None
        data = settings.MONGODB[cls.collection_name].find_one(
            {"_id": ObjectId(value)}
        )
        return cls.from_dict(data)

    def token_matches(self, token):
        return hmac.compare_digest(self.token_digest, _token_digest(token))

    @classmethod
    def claim_for_finalization(cls, *, session_id, customer_id, token):
        value = str(session_id or "").strip()
        if not ObjectId.is_valid(value):
            return None
        now = datetime.now(timezone.utc)
        lease_seconds = getattr(
            settings, "DOCUMENT_PRESIGNED_FINALIZE_LEASE_SECONDS", 300
        )
        data = settings.MONGODB[cls.collection_name].find_one_and_update(
            {
                "_id": ObjectId(value),
                "customer_id": str(customer_id),
                "token_digest": _token_digest(token),
                "status": "issued",
                "expires_at": {"$gt": now},
            },
            {
                "$set": {
                    "status": "finalizing",
                    "finalizing_at": now,
                    "expires_at": now + timedelta(seconds=lease_seconds),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return cls.from_dict(data)

    def set_object_key(self, object_key):
        self.object_key = object_key
        encrypted = encrypt_fields(
            {"object_key": object_key},
            ("object_key",),
        )["object_key"]
        settings.MONGODB[self.collection_name].update_one(
            {"_id": self._id, "status": "issued"},
            {"$set": {"object_key": encrypted}},
        )

    def mark_completed(self, document_id):
        now = datetime.now(timezone.utc)
        settings.MONGODB[self.collection_name].update_one(
            {"_id": self._id, "status": "finalizing"},
            {
                "$set": {
                    "status": "completed",
                    "document_id": str(document_id),
                    "completed_at": now,
                    "failure_code": "",
                    "purge_at": now + timedelta(days=1),
                }
            },
        )
        self.status = "completed"
        self.document_id = str(document_id)
        self.completed_at = now

    def mark_failed(self, failure_code):
        now = datetime.now(timezone.utc)
        settings.MONGODB[self.collection_name].update_one(
            {"_id": self._id, "status": {"$in": ["issued", "finalizing"]}},
            {
                "$set": {
                    "status": "failed",
                    "failure_code": str(failure_code)[:100],
                    "expires_at": now,
                }
            },
        )
        self.status = "failed"
        self.failure_code = str(failure_code)[:100]
        self.expires_at = now

    def release_finalization_for_retry(self, failure_code):
        """Return a claimed session to issued after a transient dependency failure."""
        now = datetime.now(timezone.utc)
        retry_seconds = max(
            60,
            int(
                getattr(
                    settings,
                    "DOCUMENT_PRESIGNED_FINALIZE_LEASE_SECONDS",
                    300,
                )
            ),
        )
        maximum_lifetime = (
            int(
                getattr(
                    settings,
                    "DOCUMENT_PRESIGNED_UPLOAD_EXPIRY_SECONDS",
                    900,
                )
            )
            + retry_seconds
        )
        created_at = self.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        retry_deadline = min(
            now + timedelta(seconds=retry_seconds),
            created_at + timedelta(seconds=maximum_lifetime),
        )
        result = settings.MONGODB[self.collection_name].update_one(
            {"_id": self._id, "status": "finalizing"},
            {
                "$set": {
                    "status": "issued",
                    "failure_code": str(failure_code)[:100],
                    "finalizing_at": None,
                    "expires_at": retry_deadline,
                }
            },
        )
        if result.modified_count:
            self.status = "issued"
            self.failure_code = str(failure_code)[:100]
            self.finalizing_at = None
            self.expires_at = retry_deadline
        return result.modified_count == 1

    @classmethod
    def find_cleanup_candidates(cls, *, limit=100, now=None):
        now = now or datetime.now(timezone.utc)
        cursor = (
            settings.MONGODB[cls.collection_name]
            .find(
                {
                    "status": {"$in": ["issued", "finalizing", "failed"]},
                    "expires_at": {"$lte": now},
                }
            )
            .sort("expires_at", 1)
            .limit(limit)
        )
        return [cls.from_dict(item) for item in cursor]

    def mark_expired_and_cleaned(self):
        now = datetime.now(timezone.utc)
        result = settings.MONGODB[self.collection_name].update_one(
            {
                "_id": self._id,
                "status": {"$in": ["issued", "finalizing", "failed"]},
            },
            {
                "$set": {
                    "status": "expired",
                    "cleaned_at": now,
                    "purge_at": now + timedelta(days=1),
                }
            },
        )
        return result.modified_count == 1

    @classmethod
    def create_indexes(cls):
        collection = settings.MONGODB[cls.collection_name]
        collection.create_index([("customer_id", 1), ("created_at", -1)])
        collection.create_index([("status", 1), ("expires_at", 1)])
        collection.create_index("purge_at", expireAfterSeconds=0)
