"""Owner-scoped notification inbox queries and atomic read mutations."""

from datetime import datetime, timezone

from bson import ObjectId

from notifications.models.notification import Notification


def notification_is_read(document):
    """Read current state while accepting the legacy ``status='read'`` shape."""
    value = document.get("is_read")
    if type(value) is bool:
        return value
    return document.get("status") == "read"


def unread_state_query():
    """Match unread current rows plus legacy rows without ``is_read``."""
    return {
        "$or": [
            {"is_read": False},
            {
                "is_read": {"$exists": False},
                "status": {"$ne": "read"},
            },
        ]
    }


def with_unread_state(owner_query):
    return {"$and": [dict(owner_query), unread_state_query()]}


def mark_notification_read(db, notification_id, owner_query):
    """Atomically mark one owned row read and make an identical replay succeed."""
    object_id = ObjectId(str(notification_id))
    collection = db[Notification.collection_name]
    now = datetime.now(timezone.utc)
    unread_owner_query = {
        "$and": [
            {"_id": object_id},
            dict(owner_query),
            unread_state_query(),
        ]
    }
    result = collection.update_one(
        unread_owner_query,
        {"$set": {"is_read": True, "read_at": now}},
    )
    if result.modified_count:
        document = collection.find_one({"_id": object_id, **owner_query})
        return {"found": True, "replayed": False, "document": document}

    document = collection.find_one({"_id": object_id, **owner_query})
    if document is None:
        return {"found": False, "replayed": False, "document": None}
    if notification_is_read(document):
        return {"found": True, "replayed": True, "document": document}

    # A concurrent owner/read-state rewrite prevented this update. Treat it as
    # a stable conflict rather than reporting a false success.
    return {"found": True, "replayed": False, "document": document, "conflict": True}


def bounded_owner_ids(collection, owner_query, *, limit):
    """Return a stable owner snapshot or ``None`` when the approved bound is exceeded."""
    rows = list(
        collection.find(dict(owner_query), {"_id": 1})
        .sort("_id", 1)
        .limit(int(limit) + 1)
    )
    if len(rows) > int(limit):
        return None
    return [row["_id"] for row in rows]
