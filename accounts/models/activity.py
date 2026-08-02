import hashlib
import uuid
from datetime import datetime, timezone

from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken


def get_db():
    return settings.MONGODB


class ActiveSession:
    """ActiveSession model using PyMongo for Session & Device Management"""

    collection_name = "active_sessions"

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.user_id = kwargs.get("user_id")
        self.role = kwargs.get("role", "customer")
        self.session_id = kwargs.get("session_id")
        if not self.session_id and not kwargs.get("_id"):
            self.session_id = str(uuid.uuid4())
        self.refresh_token_hash = kwargs.get("refresh_token_hash")
        legacy_token = kwargs.get("session_token")
        if legacy_token and not self.refresh_token_hash:
            self.refresh_token_hash = hashlib.sha256(
                legacy_token.encode("utf-8")
            ).hexdigest()
        self.device_info = kwargs.get("device_info", "")
        self.ip_address = kwargs.get("ip_address", "")
        self.last_active = kwargs.get("last_active", datetime.now(timezone.utc))
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.is_active = kwargs.get("is_active", True)

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "user_id": self.user_id,
            "role": self.role,
            "session_id": self.session_id,
            "device_info": self.device_info,
            "ip_address": self.ip_address,
            "last_active": self.last_active,
            "created_at": self.created_at,
            "is_active": self.is_active,
        }
        if self._id:
            data["id"] = str(self._id)
            data["_id"] = str(self._id)
        return data

    def to_storage_dict(self):
        """Return persistence fields; credential hashes never enter API output."""
        data = self.to_dict()
        data["refresh_token_hash"] = self.refresh_token_hash
        return data

    @classmethod
    def from_refresh_token(cls, *, user_id, role, refresh_token, **kwargs):
        """Build a session record from JWT identity without retaining the JWT."""
        parsed = RefreshToken(refresh_token)
        session_id = parsed.get("session_id")
        if not session_id:
            raise ValueError("Refresh token has no session identity")
        return cls(
            user_id=str(user_id),
            role=role,
            session_id=session_id,
            refresh_token_hash=hashlib.sha256(
                refresh_token.encode("utf-8")
            ).hexdigest(),
            **kwargs,
        )

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**data)

    def save(self):
        db = get_db()
        collection = db[self.collection_name]
        data = self.to_storage_dict()

        if self._id:
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        return self

    def delete(self):
        if self._id:
            db = get_db()
            collection = db[self.collection_name]
            collection.delete_one({"_id": self._id})

    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find(cls, query, sort=None, **kwargs):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query, **kwargs)
        if sort:
            cursor = cursor.sort(sort)
        return [cls.from_dict(doc) for doc in cursor]

    @classmethod
    def update_many(cls, query, update):
        db = get_db()
        collection = db[cls.collection_name]
        return collection.update_many(query, update)

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("user_id")
        collection.create_index("session_id", unique=True, sparse=True)
        collection.create_index("refresh_token_hash", sparse=True)
        collection.create_index("is_active")
        # Automatically remove session records after 30 days of inactivity.
        collection.create_index("last_active", expireAfterSeconds=2592000)


class LoginActivity:
    """LoginActivity model using PyMongo for logging auth attempts"""

    collection_name = "login_activity"

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.user_id = kwargs.get("user_id")
        self.email = kwargs.get("email")
        self.role = kwargs.get("role", "customer")
        self.status = kwargs.get("status")  # "SUCCESS" or "FAILED"
        self.ip_address = kwargs.get("ip_address", "")
        self.device_info = kwargs.get("device_info", "")
        self.timestamp = kwargs.get("timestamp", datetime.now(timezone.utc))
        self.failure_reason = kwargs.get("failure_reason", "")

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "user_id": self.user_id,
            "email": self.email,
            "role": self.role,
            "status": self.status,
            "ip_address": self.ip_address,
            "device_info": self.device_info,
            "timestamp": self.timestamp,
            "failure_reason": self.failure_reason,
        }
        if self._id:
            data["id"] = str(self._id)
            data["_id"] = str(self._id)
        return data

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**data)

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
    def find(cls, query, limit=50, sort=None, **kwargs):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query, **kwargs).limit(limit)
        if sort:
            cursor = cursor.sort(sort)
        else:
            # Default sort by timestamp descending
            cursor = cursor.sort("timestamp", -1)
        return [cls.from_dict(doc) for doc in cursor]

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("user_id")
        collection.create_index("email")
        collection.create_index("ip_address")
        collection.create_index("timestamp")
        # Automatically purge login activity records after 90 days.
        collection.create_index("timestamp", expireAfterSeconds=7776000)
