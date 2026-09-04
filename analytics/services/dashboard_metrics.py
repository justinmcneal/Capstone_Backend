"""Canonical, versioned Analytics dashboard metric definitions."""

from bson import ObjectId

METRIC_DEFINITION_VERSION = "2026-08-12-v1"

LOAN_PENDING_STATUSES = frozenset({"submitted", "under_review"})
LOAN_APPROVED_OUTCOME_STATUSES = frozenset(
    {"approved", "disbursed", "completed", "written_off"}
)
LOAN_DISBURSED_STATUSES = frozenset({"disbursed", "completed", "written_off"})
LOAN_REVIEWED_STATUSES = LOAN_APPROVED_OUTCOME_STATUSES | {"rejected"}

DOCUMENT_PENDING_STATUSES = frozenset({"pending", "needs_review"})


def id_variants(value):
    """Return canonical string and legacy ObjectId representations."""
    text = str(value or "").strip()
    if not text:
        return []
    values = [text]
    if ObjectId.is_valid(text):
        values.insert(0, ObjectId(text))
    return values


def identity_query(field, value):
    values = id_variants(value)
    if not values:
        return {field: value}
    if len(values) == 1:
        return {field: values[0]}
    return {field: {"$in": values}}


def with_conditions(base=None, *conditions):
    clauses = []
    if base:
        clauses.append(dict(base))
    clauses.extend(condition for condition in conditions if condition)
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def current_document_query(base=None):
    """Restrict counts to current metadata backed by available storage."""
    return with_conditions(
        base,
        {
            "$or": [
                {"storage_state": "available"},
                {"storage_state": {"$exists": False}},
            ]
        },
        {
            "$or": [
                {"superseded_by_document_id": None},
                {"superseded_by_document_id": {"$exists": False}},
            ]
        },
    )


def status_query(base, statuses):
    statuses = sorted(set(statuses))
    condition = statuses[0] if len(statuses) == 1 else {"$in": statuses}
    return with_conditions(base, {"status": condition})


def approval_rate(approved, reviewed):
    return f"{(approved / reviewed * 100):.1f}%" if reviewed else "0.0%"
