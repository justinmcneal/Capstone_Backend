from datetime import datetime
from django.conf import settings


def get_db():
    """Helper function to get the MongoDB database instance"""
    return settings.MONGODB


class BlacklistedToken:
    """BlacklistedToken model using PyMongo"""

    collection_name = "blacklisted_tokens"

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.token = kwargs.get("token")
        self.token_type = kwargs.get("token_type", "refresh")
        self.blacklisted_at = kwargs.get("blacklisted_at", datetime.utcnow())
        self.expires_at = kwargs.get("expires_at")

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "token": self.token,
            "token_type": self.token_type,
            "blacklisted_at": self.blacklisted_at,
            "expires_at": self.expires_at,
        }
        if self._id:
            data["_id"] = self._id
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
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find(cls, query, **kwargs):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find(query, **kwargs)
        return [cls.from_dict(doc) for doc in docs]

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("token", unique=True)
        collection.create_index("token_type")
        collection.create_index("expires_at", expireAfterSeconds=0)


class RefreshTokenEntry:
    """RefreshTokenEntry model using PyMongo"""

    collection_name = "refresh_tokens"

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.customer = kwargs.get("customer")
        self.role = kwargs.get("role", "customer")
        self.token_hash = kwargs.get("token_hash")
        self.issued_at = kwargs.get("issued_at", datetime.utcnow())
        self.expires_at = kwargs.get("expires_at")
        self.is_active = kwargs.get("is_active", True)
        self.revoked_at = kwargs.get("revoked_at")

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "customer": self.customer,
            "role": self.role,
            "token_hash": self.token_hash,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "is_active": self.is_active,
            "revoked_at": self.revoked_at,
        }
        if self._id:
            data["_id"] = self._id
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
    def find(cls, query, **kwargs):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find(query, **kwargs)
        return [cls.from_dict(doc) for doc in docs]

    @classmethod
    def delete_many(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        return collection.delete_many(query)

    @classmethod
    def update_many(cls, query, update):
        db = get_db()
        collection = db[cls.collection_name]
        return collection.update_many(query, update)

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("customer")
        collection.create_index("role")
        collection.create_index("token_hash")
        collection.create_index("is_active")
        collection.create_index("expires_at", expireAfterSeconds=0)
