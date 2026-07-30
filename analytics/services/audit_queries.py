"""
Shared audit query helpers for analytics views.

Provides common pagination parsing, detail serialization, log serialization,
and search helpers used by both admin and officer dashboard views.
"""

import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from analytics.models import AuditLog


def parse_pagination(request, default_page_size: int = 20, max_page_size: int = 200):
    """Parse validated pagination parameters from request query params."""
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
    except (TypeError, ValueError):
        raise ValueError(
            "Invalid page parameter",
            errors={"page": "page must be an integer"},
        )
    try:
        page_size = min(
            max(int(request.query_params.get("page_size", default_page_size)), 1),
            max_page_size,
        )
    except (TypeError, ValueError):
        raise ValueError(
            "Invalid page_size parameter",
            errors={"page_size": "page_size must be an integer"},
        )
    return page, page_size


def parse_date_range(request):
    """Parse optional date_from and date_to strings into UTC datetime ranges."""
    date_from = request.query_params.get("date_from", "")
    date_to = request.query_params.get("date_to", "")

    ts_filter = {}
    if date_from:
        try:
            ts_filter["$gte"] = datetime.strptime(date_from, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            ts_filter["$lte"] = date_to_obj.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
        except ValueError:
            pass
    return ts_filter if ts_filter else None


def default_search_conditions(search: str):
    """Build generic search conditions across common audit log fields."""
    regex = {"$regex": re.escape(search), "$options": "i"}
    return [
        {"description": regex},
        {"action": regex},
        {"resource_id": regex},
        {"resource_type": regex},
    ]


def officer_search_conditions(search: str):
    """Build officer-scoped search conditions including customer name matching."""
    conditions = default_search_conditions(search)
    from accounts.models import Customer

    customer_ids = []
    search_terms = search.strip().split()
    if len(search_terms) == 1:
        name_regex = re.compile(f".*{re.escape(search_terms[0])}.*", re.IGNORECASE)
        matched_customers = Customer.find(
            {
                "$or": [
                    {"first_name": name_regex},
                    {"last_name": name_regex},
                ]
            }
        )
    else:
        customer_and_conditions = []
        for term in search_terms:
            term_regex = re.compile(f".*{re.escape(term)}.*", re.IGNORECASE)
            customer_and_conditions.append(
                {
                    "$or": [
                        {"first_name": term_regex},
                        {"last_name": term_regex},
                    ]
                }
            )
        matched_customers = Customer.find({"$and": customer_and_conditions})
    customer_ids = [c.id for c in matched_customers if c]
    if customer_ids:
        conditions.append({"details.customer_id": {"$in": customer_ids}})
    return conditions


def default_log_search(logs, search: str):
    """In-memory search filter for admin-style log lists."""
    search_regex = re.compile(re.escape(search), re.IGNORECASE)
    return [
        log
        for log in logs
        if (
            search_regex.search(log.description or "")
            or search_regex.search(log.user_email or "")
            or search_regex.search(log.action or "")
            or search_regex.search(log.user_id or "")
            or search_regex.search(log.user_type or "")
        )
    ]


def serialize_details(value: Any):
    """Ensure a value is JSON-serializable for API responses."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {k: serialize_details(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_details(v) for v in value]
    return value


def serialize_log_entry(log: AuditLog):
    """Convert an AuditLog instance into a dict response."""
    return {
        "id": log.id,
        "user_id": log.user_id,
        "user_type": log.user_type,
        "user_email": log.user_email,
        "action": log.action,
        "description": log.description,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "details": serialize_details(log.details or {}),
        "ip_address": log.ip_address,
        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
    }


def build_paginated_response(logs, total, page: int, page_size: int):
    """Build the standard paginated audit log response payload."""
    return {
        "logs": [serialize_log_entry(log) for log in logs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 1,
    }
