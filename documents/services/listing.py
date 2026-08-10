"""Bounded query and display-name helpers for document listings."""

from bson import ObjectId
from django.conf import settings

from accounts.models import Customer
from documents.models import DOCUMENT_TYPES
from documents.services.notification import get_display_name


def append_query_condition(query, condition):
    """Append an AND clause without overwriting a caller's existing clauses."""
    conditions = list(query.pop("$and", []))
    conditions.append(condition)
    query["$and"] = conditions
    return query


def indexed_search_condition(search):
    """Build an indexed exact-match search or return ``None`` when unsupported."""
    value = str(search or "").strip()
    normalized_type = value.lower().replace(" ", "_")
    alternatives = []

    if normalized_type in DOCUMENT_TYPES:
        alternatives.append({"document_type": normalized_type})

    if ObjectId.is_valid(value):
        object_id = ObjectId(value)
        alternatives.extend(
            [
                {"_id": object_id},
                {"customer_id": {"$in": [object_id, str(object_id)]}},
            ]
        )

    if not alternatives:
        return None
    return alternatives[0] if len(alternatives) == 1 else {"$or": alternatives}


def bulk_customer_display_names(customer_ids):
    """Resolve one page of customer names with one bounded MongoDB query."""
    canonical_ids = {
        str(customer_id).strip()
        for customer_id in customer_ids
        if str(customer_id or "").strip()
    }
    if not canonical_ids:
        return {}

    variants = list(canonical_ids)
    variants.extend(
        ObjectId(value) for value in canonical_ids if ObjectId.is_valid(value)
    )
    cursor = settings.MONGODB[Customer.collection_name].find(
        {
            "$or": [
                {"_id": {"$in": variants}},
                {"customer_id": {"$in": variants}},
            ]
        },
        {
            "_id": 1,
            "customer_id": 1,
            "first_name": 1,
            "last_name": 1,
            "username": 1,
            "email": 1,
        },
    )
    names = {}
    for raw_customer in cursor:
        customer = Customer.from_dict(raw_customer)
        display_name = get_display_name(customer, fallback="Customer")
        names[str(raw_customer.get("_id"))] = display_name
        legacy_id = raw_customer.get("customer_id")
        if legacy_id is not None:
            names[str(legacy_id)] = display_name
    return names
