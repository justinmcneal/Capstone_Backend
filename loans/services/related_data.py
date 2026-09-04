"""Bounded bulk loaders for Mongo-backed loan response enrichment."""

from bson import ObjectId
from django.conf import settings


def id_candidates(values):
    candidates = []
    seen = set()
    for value in values:
        if value is None:
            continue
        text = str(value)
        if ("str", text) not in seen:
            candidates.append(text)
            seen.add(("str", text))
        if ObjectId.is_valid(text) and ("oid", text) not in seen:
            candidates.append(ObjectId(text))
            seen.add(("oid", text))
    return candidates


def model_map_by_ids(model, values):
    """Load model objects in one query and key them by normalized string ID."""
    candidates = id_candidates(values)
    if not candidates:
        return {}
    documents = settings.MONGODB[model.collection_name].find(
        {"_id": {"$in": candidates}}
    )
    objects = [model.from_dict(document) for document in documents]
    return {obj.id: obj for obj in objects if obj and obj.id}


def find_models(model, query, *, limit=100, sort=None):
    """Return a deliberately bounded model query for lookup/search endpoints."""
    cursor = settings.MONGODB[model.collection_name].find(query)
    if sort:
        cursor = cursor.sort(sort)
    if limit:
        cursor = cursor.limit(limit)
    return [model.from_dict(document) for document in cursor]


def find_models_bounded(model, query, *, limit=100, sort=None):
    """Return bounded results and report whether additional matches exist."""
    limit = max(1, int(limit))
    cursor = settings.MONGODB[model.collection_name].find(query)
    if sort:
        cursor = cursor.sort(sort)
    documents = list(cursor.limit(limit + 1))
    return (
        [model.from_dict(document) for document in documents[:limit]],
        len(documents) > limit,
    )


def application_related_maps(applications):
    """Bulk-load the customer, product, and officer rows for applications."""
    from accounts.models import Customer, LoanOfficer
    from loans.models import LoanProduct

    applications = [application for application in applications if application]
    return {
        "customers": model_map_by_ids(
            Customer, [application.customer_id for application in applications]
        ),
        "products": model_map_by_ids(
            LoanProduct, [application.product_id for application in applications]
        ),
        "officers": model_map_by_ids(
            LoanOfficer,
            [application.assigned_officer for application in applications],
        ),
    }
