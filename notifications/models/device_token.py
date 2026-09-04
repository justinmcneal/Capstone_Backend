"""Role- and session-qualified FCM device-token persistence."""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import ClassVar

from django.conf import settings
from pymongo.errors import DuplicateKeyError

from config.field_encryption import decrypt_fields, encrypt_fields, is_encrypted_value
from notifications.ownership import normalize_notification_user_type


class DeviceTokenOwnershipConflict(ValueError):
    """An active token is already owned by another account."""


class DeviceTokenLimitExceeded(ValueError):
    """An account already has the approved number of active tokens."""


def get_db():
    return settings.MONGODB


class DeviceToken:
    collection_name = "device_tokens"
    encrypted_fields = ("token",)
    supported_platforms: ClassVar[set[str]] = {"android", "ios", "web"}

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.user_id = str(kwargs.get("user_id", ""))
        self.user_type = normalize_notification_user_type(
            kwargs.get("user_type", "customer")
        )
        self.session_id = str(kwargs.get("session_id", ""))
        self.token = kwargs.get("token", "")
        self.token_hash = kwargs.get("token_hash") or self.fingerprint(self.token)
        self.platform = kwargs.get("platform", "")
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", self.created_at)
        self.last_used_at = kwargs.get("last_used_at")
        self.expires_at = kwargs.get("expires_at")
        self.is_active = bool(kwargs.get("is_active", True))
        self.deactivated_at = kwargs.get("deactivated_at")
        self.deactivation_reason = kwargs.get("deactivation_reason", "")

    @property
    def id(self):
        return str(self._id) if self._id else None

    @staticmethod
    def fingerprint(token):
        value = str(token or "").strip()
        return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""

    @classmethod
    def validate_token(cls, token):
        value = str(token or "").strip()
        if not 20 <= len(value) <= 4096:
            raise ValueError("token must contain between 20 and 4096 characters")
        if not value.isascii() or any(
            character.isspace() or ord(character) < 32 for character in value
        ):
            raise ValueError("token must contain printable ASCII without whitespace")
        if is_encrypted_value(value):
            raise ValueError("token uses a reserved storage prefix")
        return value

    @classmethod
    def validate_platform(cls, platform):
        value = str(platform or "").strip().lower()
        if value not in cls.supported_platforms:
            raise ValueError("platform must be android, ios, or web")
        return value

    def to_dict(self):
        data = {
            "user_id": self.user_id,
            "user_type": self.user_type,
            "session_id": self.session_id,
            "token": self.token,
            "token_hash": self.token_hash,
            "platform": self.platform,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
            "is_active": self.is_active,
            "deactivated_at": self.deactivated_at,
            "deactivation_reason": self.deactivation_reason,
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
    def register(cls, *, user_id, user_type, session_id, token, platform):
        normalized_id = str(user_id or "").strip()
        normalized_type = normalize_notification_user_type(user_type)
        normalized_session = str(session_id or "").strip()
        normalized_token = cls.validate_token(token)
        normalized_platform = cls.validate_platform(platform)
        if not normalized_id or not normalized_type or not normalized_session:
            raise ValueError("an authenticated owner and session are required")

        collection = get_db()[cls.collection_name]
        now = datetime.now(timezone.utc)
        token_hash = cls.fingerprint(normalized_token)
        existing = collection.find_one(
            {"$or": [{"token_hash": token_hash}, {"token": normalized_token}]}
        )
        if existing:
            existing_owner = (
                str(existing.get("user_id", "")),
                normalize_notification_user_type(existing.get("user_type", "customer")),
            )
            requested_owner = (normalized_id, normalized_type)
            if existing.get("is_active", True) and existing_owner != requested_owner:
                raise DeviceTokenOwnershipConflict(
                    "device token is already registered to another account"
                )
        else:
            active_count = collection.count_documents(
                {
                    "user_id": normalized_id,
                    "user_type": normalized_type,
                    "is_active": True,
                    "$or": [
                        {"expires_at": {"$gt": now}},
                        {"expires_at": None},
                        {"expires_at": {"$exists": False}},
                    ],
                }
            )
            if active_count >= int(settings.NOTIFICATIONS_MAX_ACTIVE_DEVICE_TOKENS):
                raise DeviceTokenLimitExceeded(
                    "active device-token limit has been reached"
                )

        expires_at = now + timedelta(days=settings.NOTIFICATIONS_DEVICE_TOKEN_TTL_DAYS)
        record = cls(
            _id=existing.get("_id") if existing else None,
            user_id=normalized_id,
            user_type=normalized_type,
            session_id=normalized_session,
            token=normalized_token,
            token_hash=token_hash,
            platform=normalized_platform,
            created_at=existing.get("created_at", now) if existing else now,
            updated_at=now,
            last_used_at=existing.get("last_used_at") if existing else None,
            expires_at=expires_at,
            is_active=True,
            deactivated_at=None,
            deactivation_reason="",
        )
        stored = record.to_dict()
        try:
            if record._id:
                collection.update_one({"_id": record._id}, {"$set": stored})
            else:
                result = collection.insert_one(stored)
                record._id = result.inserted_id
        except DuplicateKeyError as exc:
            raise DeviceTokenOwnershipConflict(
                "device token registration changed concurrently"
            ) from exc
        return record

    @classmethod
    def get_tokens_for_user(cls, user_id, user_type):
        now = datetime.now(timezone.utc)
        cursor = get_db()[cls.collection_name].find(
            {
                "user_id": str(user_id),
                "user_type": normalize_notification_user_type(user_type),
                "is_active": True,
                "$or": [
                    {"expires_at": {"$gt": now}},
                    {"expires_at": None},
                    {"expires_at": {"$exists": False}},
                ],
            }
        )
        return [cls.from_dict(doc) for doc in cursor]

    @classmethod
    def deactivate_token_for_owner(cls, *, token, user_id, user_type):
        token_hash = cls.fingerprint(cls.validate_token(token))
        now = datetime.now(timezone.utc)
        result = get_db()[cls.collection_name].update_one(
            {
                "token_hash": token_hash,
                "user_id": str(user_id),
                "user_type": normalize_notification_user_type(user_type),
                "is_active": True,
            },
            {
                "$set": {
                    "is_active": False,
                    "deactivated_at": now,
                    "deactivation_reason": "client_unregister",
                    "updated_at": now,
                }
            },
        )
        return result.modified_count == 1

    @classmethod
    def deactivate_hashes(cls, token_hashes, reason):
        hashes = [value for value in token_hashes if value]
        if not hashes:
            return 0
        now = datetime.now(timezone.utc)
        result = get_db()[cls.collection_name].update_many(
            {"token_hash": {"$in": hashes}, "is_active": True},
            {
                "$set": {
                    "is_active": False,
                    "deactivated_at": now,
                    "deactivation_reason": str(reason),
                    "updated_at": now,
                }
            },
        )
        return result.modified_count

    @classmethod
    def deactivate_for_session(cls, user_id, user_type, session_id):
        return cls._deactivate_owner_query(
            {
                "user_id": str(user_id),
                "user_type": normalize_notification_user_type(user_type),
                "session_id": str(session_id),
            },
            "session_revoked",
        )

    @classmethod
    def deactivate_for_owner(cls, user_id, user_type, except_session_id=None):
        query = {
            "user_id": str(user_id),
            "user_type": normalize_notification_user_type(user_type),
        }
        if except_session_id:
            query["session_id"] = {"$ne": str(except_session_id)}
        return cls._deactivate_owner_query(query, "sessions_revoked")

    @classmethod
    def _deactivate_owner_query(cls, query, reason):
        now = datetime.now(timezone.utc)
        result = get_db()[cls.collection_name].update_many(
            {**query, "is_active": True},
            {
                "$set": {
                    "is_active": False,
                    "deactivated_at": now,
                    "deactivation_reason": reason,
                    "updated_at": now,
                }
            },
        )
        return result.modified_count

    @classmethod
    def touch_hashes(cls, token_hashes):
        hashes = [value for value in token_hashes if value]
        if hashes:
            get_db()[cls.collection_name].update_many(
                {"token_hash": {"$in": hashes}, "is_active": True},
                {"$set": {"last_used_at": datetime.now(timezone.utc)}},
            )

    @classmethod
    def create_indexes(cls):
        collection = get_db()[cls.collection_name]
        collection.create_index("token_hash", unique=True, sparse=True)
        collection.create_index(
            [("user_id", 1), ("user_type", 1), ("is_active", 1), ("expires_at", 1)]
        )
        collection.create_index(
            [("user_id", 1), ("user_type", 1), ("session_id", 1), ("is_active", 1)]
        )
        collection.create_index(
            [("expires_at", 1), ("_id", 1)], name="device_token_expiry_cleanup"
        )
        collection.create_index(
            [("is_active", 1), ("updated_at", 1), ("_id", 1)],
            name="device_token_inactive_cleanup",
        )
