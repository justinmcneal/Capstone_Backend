"""MongoDB validators and legacy inventory helpers for Notifications."""

import hashlib
from datetime import datetime, timedelta, timezone

from django.conf import settings
from pymongo.errors import CollectionInvalid

from config.field_encryption import is_encrypted_value
from notifications.models.delivery import NotificationDelivery
from notifications.models.device_token import DeviceToken
from notifications.models.notification import DELIVERY_STATUSES, Notification

OWNER_TYPES = ["customer", "loan_officer", "admin"]

NOTIFICATION_VALIDATORS = {
    Notification.collection_name: {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "user_id",
                "user_type",
                "notification_type",
                "channel",
                "status",
                "delivery_status",
                "is_read",
                "created_at",
                "retention_expires_at",
                "legal_hold",
            ],
            "properties": {
                "user_id": {"bsonType": "string", "minLength": 1},
                "user_type": {"enum": OWNER_TYPES},
                "notification_type": {"bsonType": "string", "minLength": 1},
                "channel": {"enum": ["email", "in_app"]},
                "status": {"enum": sorted(DELIVERY_STATUSES)},
                "delivery_status": {"enum": sorted(DELIVERY_STATUSES)},
                "is_read": {"bsonType": "bool"},
                "created_at": {"bsonType": "date"},
                "sent_at": {"bsonType": ["date", "null"]},
                "read_at": {"bsonType": ["date", "null"]},
                "retention_expires_at": {"bsonType": "date"},
                "legal_hold": {"bsonType": "bool"},
                "metadata": {"bsonType": ["object", "string"]},
                "idempotency_key_hash": {
                    "bsonType": ["string", "null"],
                    "pattern": "^[a-f0-9]{64}$",
                },
            },
        }
    },
    DeviceToken.collection_name: {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "user_id",
                "user_type",
                "session_id",
                "token",
                "token_hash",
                "platform",
                "is_active",
                "created_at",
                "updated_at",
                "expires_at",
            ],
            "properties": {
                "user_id": {"bsonType": "string", "minLength": 1},
                "user_type": {"enum": OWNER_TYPES},
                "session_id": {"bsonType": "string", "minLength": 1},
                "token": {"bsonType": "string", "minLength": 1},
                "token_hash": {
                    "bsonType": "string",
                    "pattern": "^[a-f0-9]{64}$",
                },
                "platform": {"enum": sorted(DeviceToken.supported_platforms)},
                "is_active": {"bsonType": "bool"},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
                "expires_at": {"bsonType": "date"},
            },
        }
    },
    NotificationDelivery.collection_name: {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "event_key",
                "event_type",
                "recipient_key",
                "recipient_user_id",
                "recipient_user_type",
                "channels",
                "payload",
                "status",
                "attempt_count",
                "created_at",
                "updated_at",
            ],
            "properties": {
                "event_key": {
                    "bsonType": "string",
                    "pattern": "^[a-f0-9]{64}$",
                },
                "event_type": {"bsonType": "string", "minLength": 1},
                "recipient_key": {
                    "bsonType": "string",
                    "pattern": "^[a-f0-9]{64}$",
                },
                "recipient_user_id": {"bsonType": "string", "minLength": 1},
                "recipient_user_type": {"enum": OWNER_TYPES},
                "channels": {
                    "bsonType": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"enum": sorted(NotificationDelivery.supported_channels)},
                },
                "payload": {"bsonType": ["object", "string"]},
                "status": {
                    "enum": [
                        "pending",
                        "sending",
                        "retry_wait",
                        "delivered",
                        "failed",
                        "suppressed",
                    ]
                },
                "attempt_count": {"bsonType": "int", "minimum": 0},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
            },
        }
    },
}


def install_notification_validators(db=None):
    database = db or settings.MONGODB
    existing = set(database.list_collection_names())
    for collection_name, validator in NOTIFICATION_VALIDATORS.items():
        if collection_name not in existing:
            try:
                database.create_collection(
                    collection_name,
                    validator=validator,
                    validationLevel="strict",
                    validationAction="error",
                )
            except CollectionInvalid:
                pass
        else:
            database.command(
                "collMod",
                collection_name,
                validator=validator,
                validationLevel="strict",
                validationAction="error",
            )


def _duplicate_count(collection, field):
    rows = collection.aggregate(
        [
            {"$match": {field: {"$type": "string", "$ne": ""}}},
            {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
            {"$count": "groups"},
        ]
    )
    first = next(iter(rows), None)
    return int(first["groups"]) if first else 0


def inventory_notification_data(db=None):
    database = db or settings.MONGODB
    notifications = database[Notification.collection_name]
    tokens = database[DeviceToken.collection_name]
    deliveries = database[NotificationDelivery.collection_name]
    sensitive_fields = Notification.encrypted_fields
    plaintext = 0
    invalid_notification_timestamps = 0
    for row in notifications.find({}, {field: 1 for field in sensitive_fields}):
        plaintext += sum(
            1
            for field in sensitive_fields
            if row.get(field) not in (None, "")
            and not is_encrypted_value(row.get(field))
        )
    for row in notifications.find({}, {"created_at": 1, "retention_expires_at": 1}):
        if not isinstance(row.get("created_at"), datetime) or (
            "retention_expires_at" in row
            and not isinstance(row.get("retention_expires_at"), datetime)
        ):
            invalid_notification_timestamps += 1
    return {
        "notifications": notifications.count_documents({}),
        "legacy_read_status": notifications.count_documents({"status": "read"}),
        "missing_user_type": notifications.count_documents(
            {"user_type": {"$exists": False}}
        ),
        "invalid_user_type": notifications.count_documents(
            {"user_type": {"$nin": OWNER_TYPES}}
        ),
        "missing_read_state": notifications.count_documents(
            {"is_read": {"$exists": False}}
        ),
        "missing_retention": notifications.count_documents(
            {"retention_expires_at": {"$exists": False}}
        ),
        "missing_idempotency_hash": notifications.count_documents(
            {
                "idempotency_key": {"$nin": [None, ""]},
                "idempotency_key_hash": {"$exists": False},
            }
        ),
        "plaintext_sensitive_fields": plaintext,
        "invalid_notification_timestamps": invalid_notification_timestamps,
        "duplicate_idempotency_hash_groups": _duplicate_count(
            notifications, "idempotency_key_hash"
        ),
        "device_tokens": tokens.count_documents({}),
        "plaintext_device_tokens": sum(
            1
            for row in tokens.find({}, {"token": 1})
            if row.get("token") and not is_encrypted_value(row["token"])
        ),
        "missing_token_hash": tokens.count_documents(
            {"$or": [{"token_hash": ""}, {"token_hash": {"$exists": False}}]}
        ),
        "missing_token_session": tokens.count_documents(
            {"$or": [{"session_id": ""}, {"session_id": {"$exists": False}}]}
        ),
        "invalid_token_owner_type": tokens.count_documents(
            {"user_type": {"$nin": OWNER_TYPES}}
        ),
        "invalid_token_platform": tokens.count_documents(
            {"platform": {"$nin": sorted(DeviceToken.supported_platforms)}}
        ),
        "missing_token_expiry": tokens.count_documents(
            {"expires_at": {"$exists": False}}
        ),
        "duplicate_token_hash_groups": _duplicate_count(tokens, "token_hash"),
        "deliveries": deliveries.count_documents({}),
        "plaintext_delivery_event_keys": deliveries.count_documents(
            {"event_key": {"$not": {"$regex": "^[a-f0-9]{64}$"}}}
        ),
    }


def backfill_notification_data(db=None, *, apply=False):
    """Conditionally repair deterministic legacy shape; encryption is separate."""
    database = db or settings.MONGODB
    collection = database[Notification.collection_name]
    now = datetime.now(timezone.utc)
    counts = {"scanned": 0, "changed": 0, "conflicts": 0}
    for row in collection.find({}):
        counts["scanned"] += 1
        updates = {}
        user_type = row.get("user_type")
        if user_type in (None, ""):
            updates["user_type"] = "customer"
        elif user_type == "super_admin":
            updates["user_type"] = "admin"
        legacy_read = row.get("status") == "read"
        if "is_read" not in row:
            updates["is_read"] = legacy_read
        if legacy_read:
            updates["status"] = "unknown"
            updates["delivery_status"] = "unknown"
            updates["read_at"] = row.get("read_at") or row.get("created_at") or now
        elif "delivery_status" not in row:
            status = row.get("status", "pending")
            updates["delivery_status"] = (
                status if status in DELIVERY_STATUSES else "unknown"
            )
        if "legal_hold" not in row:
            updates["legal_hold"] = False
        if "retention_expires_at" not in row:
            created_at = row.get("created_at") or now
            updates["retention_expires_at"] = created_at + timedelta(
                days=int(settings.NOTIFICATIONS_RETENTION_DAYS)
            )
        raw_key = Notification.from_dict(row).idempotency_key
        if raw_key and "idempotency_key_hash" not in row:
            updates["idempotency_key_hash"] = Notification.fingerprint(raw_key)
        if not updates:
            continue
        counts["changed"] += 1
        if apply:
            result = collection.update_one(
                {"_id": row["_id"], "updated_at": row.get("updated_at")},
                {"$set": updates},
            )
            if result.modified_count != 1:
                counts["conflicts"] += 1

    for row in database[NotificationDelivery.collection_name].find(
        {"event_key": {"$not": {"$regex": "^[a-f0-9]{64}$"}}},
        {"event_key": 1},
    ):
        counts["scanned"] += 1
        counts["changed"] += 1
        if apply:
            raw_key = str(row.get("event_key", ""))
            result = database[NotificationDelivery.collection_name].update_one(
                {"_id": row["_id"], "event_key": raw_key},
                {
                    "$set": {
                        "event_key": hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
                    }
                },
            )
            if result.modified_count != 1:
                counts["conflicts"] += 1

    token_collection = database[DeviceToken.collection_name]
    for row in token_collection.find({}):
        record = DeviceToken.from_dict(row)
        updates = {}
        if not row.get("token_hash") and record.token:
            updates["token_hash"] = DeviceToken.fingerprint(record.token)
        if row.get("user_type") in (None, ""):
            updates["user_type"] = "customer"
        elif row.get("user_type") == "super_admin":
            updates["user_type"] = "admin"
        if not row.get("session_id"):
            updates.update(
                {
                    "session_id": f"legacy-unbound:{row['_id']}",
                    "is_active": False,
                    "deactivation_reason": "legacy_unbound_session",
                    "deactivated_at": now,
                }
            )
        created_at = row.get("created_at") or now
        if "created_at" not in row:
            updates["created_at"] = created_at
        if "updated_at" not in row:
            updates["updated_at"] = created_at
        if "expires_at" not in row:
            updates["expires_at"] = created_at + timedelta(
                days=int(settings.NOTIFICATIONS_DEVICE_TOKEN_TTL_DAYS)
            )
        if "is_active" not in row and row.get("session_id"):
            updates["is_active"] = True
        normalized_platform = str(row.get("platform", "")).strip().lower()
        if normalized_platform in DeviceToken.supported_platforms and (
            normalized_platform != row.get("platform")
        ):
            updates["platform"] = normalized_platform
        if not updates:
            continue
        counts["scanned"] += 1
        counts["changed"] += 1
        if apply:
            result = token_collection.update_one(
                {"_id": row["_id"], "updated_at": row.get("updated_at")},
                {"$set": updates},
            )
            if result.modified_count != 1:
                counts["conflicts"] += 1
    return counts
