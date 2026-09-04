"""MongoDB-backed leases and checkpoints for bounded Loans jobs."""

import uuid
from datetime import timedelta

from django.conf import settings
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from loans.utils.time import utcnow

STATE_COLLECTION = "loan_operational_state"


def _limits():
    return (
        max(1, int(getattr(settings, "LOAN_JOB_BATCH_SIZE", 200))),
        max(1, int(getattr(settings, "LOAN_JOB_MAX_BATCHES", 10))),
        max(30, int(getattr(settings, "LOAN_JOB_LEASE_SECONDS", 900))),
    )


def acquire_job_lease(job_name, owner=None):
    """Claim one job lease without allowing overlapping workers."""
    owner = owner or f"job:{uuid.uuid4().hex}"
    now = utcnow()
    _batch_size, _max_batches, lease_seconds = _limits()
    collection = settings.MONGODB[STATE_COLLECTION]
    try:
        state = collection.find_one_and_update(
            {
                "_id": job_name,
                "$or": [
                    {"lease_expires_at": {"$lte": now}},
                    {"lease_expires_at": {"$exists": False}},
                    {"lease_owner": owner},
                ],
            },
            {
                "$set": {
                    "lease_owner": owner,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "updated_at": now,
                },
                "$setOnInsert": {"checkpoint": None, "created_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return None
    return owner if state and state.get("lease_owner") == owner else None


def release_job_lease(job_name, owner):
    settings.MONGODB[STATE_COLLECTION].update_one(
        {"_id": job_name, "lease_owner": owner},
        {
            "$unset": {"lease_owner": "", "lease_expires_at": ""},
            "$set": {"updated_at": utcnow()},
        },
    )


def run_bounded_scan(job_name, collection_name, query, handler, projection=None):
    """Process an indexed `_id` scan under one lease and durable checkpoint."""
    owner = acquire_job_lease(job_name)
    if not owner:
        return {"processed": 0, "complete": False, "lease_acquired": False}

    db = settings.MONGODB
    state_collection = db[STATE_COLLECTION]
    collection = db[collection_name]
    batch_size, max_batches, _lease_seconds = _limits()
    processed = 0
    complete = False
    try:
        state = state_collection.find_one({"_id": job_name}) or {}
        checkpoint = state.get("checkpoint")
        for _batch_number in range(max_batches):
            bounded_query = dict(query or {})
            if checkpoint is not None:
                bounded_query = {
                    "$and": [bounded_query, {"_id": {"$gt": checkpoint}}]
                }
            documents = list(
                collection.find(bounded_query, projection)
                .sort("_id", 1)
                .limit(batch_size)
            )
            if not documents:
                complete = True
                state_collection.update_one(
                    {"_id": job_name, "lease_owner": owner},
                    {"$set": {"checkpoint": None, "completed_at": utcnow()}},
                )
                break
            for document in documents:
                handler(document)
                checkpoint = document["_id"]
                processed += 1
                state_collection.update_one(
                    {"_id": job_name, "lease_owner": owner},
                    {"$set": {"checkpoint": checkpoint, "updated_at": utcnow()}},
                )
            if len(documents) < batch_size:
                complete = True
                state_collection.update_one(
                    {"_id": job_name, "lease_owner": owner},
                    {"$set": {"checkpoint": None, "completed_at": utcnow()}},
                )
                break
        return {
            "processed": processed,
            "complete": complete,
            "lease_acquired": True,
        }
    finally:
        release_job_lease(job_name, owner)
