"""Profile-data cleanup used by the customer account lifecycle."""

from bson import ObjectId

from analytics.models import AuditLog
from profiles.models import (
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
    RiskReviewRequest,
)

PROFILE_COLLECTIONS = (
    CustomerProfile.collection_name,
    BusinessProfile.collection_name,
    AlternativeData.collection_name,
    RiskReviewRequest.collection_name,
)
PROFILE_AUDIT_FAILURE_COLLECTION = "audit_write_failures"
PROFILE_AUDIT_FAILURE_COUNT_KEY = "profile_audit_write_failures"


def _customer_id_variants(customer_id):
    value = str(customer_id or "").strip()
    if not value:
        return []
    variants = [value]
    if ObjectId.is_valid(value):
        variants.insert(0, ObjectId(value))
    return variants


def _customer_profile_query(customer_id):
    variants = _customer_id_variants(customer_id)
    if not variants:
        raise ValueError("customer_id is required")
    return {"customer_id": {"$in": variants}}


def _customer_audit_failure_query(customer_id):
    """Match unresolved profile audit payloads that identify the customer."""

    variants = _customer_id_variants(customer_id)
    if not variants:
        raise ValueError("customer_id is required")
    return {
        "domain": "profiles",
        "resolved_at": None,
        "$or": [
            {"subject_index": AuditLog.blind_index(str(customer_id))},
            {"payload.user_id": {"$in": variants}},
            {"payload.resource_id": {"$in": variants}},
            {"payload.details.customer_id": {"$in": variants}},
        ],
    }


def count_customer_profile_data(db, customer_id):
    """Count profile documents subject to the deletion policy."""

    query = _customer_profile_query(customer_id)
    counts = {
        collection_name: db[collection_name].count_documents(query)
        for collection_name in PROFILE_COLLECTIONS
    }
    counts[PROFILE_AUDIT_FAILURE_COUNT_KEY] = db[
        PROFILE_AUDIT_FAILURE_COLLECTION
    ].count_documents(_customer_audit_failure_query(customer_id))
    return counts


def delete_customer_profile_data(db, customer_id):
    """Irreversibly delete all profile-domain records owned by a customer.

    The operation is idempotent and includes both ObjectId and string customer-ID
    representations so legacy records follow the same deletion policy.
    """

    query = _customer_profile_query(customer_id)
    deleted = {}
    for collection_name in PROFILE_COLLECTIONS:
        result = db[collection_name].delete_many(query)
        deleted[collection_name] = result.deleted_count
    audit_result = db[PROFILE_AUDIT_FAILURE_COLLECTION].delete_many(
        _customer_audit_failure_query(customer_id)
    )
    deleted[PROFILE_AUDIT_FAILURE_COUNT_KEY] = audit_result.deleted_count
    return deleted
