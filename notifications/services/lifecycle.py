"""Privacy export, account cleanup, and bounded retention for Notifications."""

import hashlib
from datetime import datetime, timedelta, timezone

from django.conf import settings

from notifications.models.delivery import NotificationDelivery
from notifications.models.device_token import DeviceToken
from notifications.models.notification import Notification, serialize_utc_datetime


def _owner_query(customer_id):
    value = str(customer_id or "").strip()
    if not value:
        raise ValueError("customer_id is required")
    return {"user_id": value, "user_type": "customer"}


def _export_item(notification):
    return {
        "id": notification.id,
        "notification_type": notification.notification_type,
        "subject": notification.subject,
        "message": notification.message,
        "related_type": notification.related_type,
        "related_id": notification.related_id,
        "metadata": notification.metadata,
        "channel": notification.channel,
        "delivery_status": notification.delivery_status,
        "is_read": notification.is_read,
        "created_at": serialize_utc_datetime(notification.created_at),
        "sent_at": serialize_utc_datetime(notification.sent_at),
        "read_at": serialize_utc_datetime(notification.read_at),
    }


def export_customer_notifications(db, customer_id, *, limit=None):
    """Return a bounded customer-readable export with explicit truncation."""
    query = _owner_query(customer_id)
    approved_limit = max(
        1,
        min(
            int(limit or settings.NOTIFICATIONS_ACCOUNT_EXPORT_MAX_ROWS),
            int(settings.NOTIFICATIONS_ACCOUNT_EXPORT_MAX_ROWS),
        ),
    )
    collection = db[Notification.collection_name]
    total = collection.count_documents(query)
    cursor = (
        collection.find(query)
        .sort([("created_at", -1), ("_id", -1)])
        .limit(approved_limit)
    )
    items = [_export_item(Notification.from_dict(row)) for row in cursor]
    return {
        "items": items,
        "total": total,
        "returned": len(items),
        "limit": approved_limit,
        "truncated": total > len(items),
    }


def count_customer_notification_data(db, customer_id):
    query = _owner_query(customer_id)
    return {
        Notification.collection_name: db[Notification.collection_name].count_documents(
            query
        ),
        NotificationDelivery.collection_name: db[
            NotificationDelivery.collection_name
        ].count_documents(
            {
                "recipient_user_id": query["user_id"],
                "recipient_user_type": "customer",
            }
        ),
        DeviceToken.collection_name: db[DeviceToken.collection_name].count_documents(
            query
        ),
    }


def delete_customer_notification_data(db, customer_id):
    """Idempotently erase customer inbox, shared delivery, and push credentials."""
    query = _owner_query(customer_id)
    notification_collection = db[Notification.collection_name]
    pseudonym = (
        "deleted:" + hashlib.sha256(query["user_id"].encode("utf-8")).hexdigest()
    )
    held_ids = []
    for row in notification_collection.find({**query, "legal_hold": True}):
        record = Notification.from_dict(row)
        record.user_id = pseudonym
        record.recipient_email = ""
        record.recipient_name = ""
        held_ids.append(record._id)
        notification_collection.replace_one({"_id": record._id}, record.to_dict())
    deleted = {
        Notification.collection_name: notification_collection.delete_many(
            query
        ).deleted_count,
        "notifications_pseudonymized": len(held_ids),
        NotificationDelivery.collection_name: db[NotificationDelivery.collection_name]
        .delete_many(
            {
                "recipient_user_id": query["user_id"],
                "recipient_user_type": "customer",
            }
        )
        .deleted_count,
        DeviceToken.collection_name: db[DeviceToken.collection_name]
        .delete_many(query)
        .deleted_count,
    }
    remaining = count_customer_notification_data(db, customer_id)
    deleted["remaining"] = sum(remaining.values())
    deleted["pseudonym"] = pseudonym
    return deleted


def _bounded_ids(collection, query, limit):
    return [
        row["_id"]
        for row in collection.find(query, {"_id": 1}).sort("_id", 1).limit(limit)
    ]


def enforce_notification_retention(*, limit=1000, now=None):
    """Delete only due, non-held, terminal records within a bounded batch."""
    now = now or datetime.now(timezone.utc)
    approved_limit = max(1, min(int(limit), 10_000))
    db = settings.MONGODB

    notification_collection = db[Notification.collection_name]
    notification_ids = _bounded_ids(
        notification_collection,
        {
            "legal_hold": {"$ne": True},
            "retention_expires_at": {"$lte": now},
        },
        approved_limit,
    )
    notification_deleted = (
        notification_collection.delete_many(
            {"_id": {"$in": notification_ids}}
        ).deleted_count
        if notification_ids
        else 0
    )

    delivery_collection = db[NotificationDelivery.collection_name]
    delivery_cutoff = now - timedelta(
        days=int(settings.NOTIFICATIONS_DELIVERY_RETENTION_DAYS)
    )
    delivery_ids = _bounded_ids(
        delivery_collection,
        {
            "status": {"$in": list(NotificationDelivery.terminal_statuses)},
            "updated_at": {"$lte": delivery_cutoff},
        },
        approved_limit,
    )
    delivery_deleted = (
        delivery_collection.delete_many({"_id": {"$in": delivery_ids}}).deleted_count
        if delivery_ids
        else 0
    )

    token_collection = db[DeviceToken.collection_name]
    token_cutoff = now - timedelta(
        days=int(settings.NOTIFICATIONS_INACTIVE_TOKEN_RETENTION_DAYS)
    )
    token_ids = _bounded_ids(
        token_collection,
        {
            "$or": [
                {"expires_at": {"$lte": now}},
                {"is_active": False, "updated_at": {"$lte": token_cutoff}},
            ]
        },
        approved_limit,
    )
    token_deleted = (
        token_collection.delete_many({"_id": {"$in": token_ids}}).deleted_count
        if token_ids
        else 0
    )
    return {
        "notifications_deleted": notification_deleted,
        "deliveries_deleted": delivery_deleted,
        "device_tokens_deleted": token_deleted,
    }
