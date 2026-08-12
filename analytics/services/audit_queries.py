"""
Shared audit query helpers for analytics views.

Provides common pagination parsing, detail serialization, log serialization,
and search helpers used by both admin and officer dashboard views.
"""

import re
from datetime import datetime, timezone

from analytics.models import (
    AUDIT_ACTION_REGISTRY,
    AUDIT_ACTIONS,
    AUDIT_USER_TYPES,
    AuditLog,
)
from analytics.models.audit_log import ACTION_GROUPS

MAX_SEARCH_LENGTH = 100
MAX_IDENTIFIER_LENGTH = 100


class AnalyticsQueryError(ValueError):
    """Stable validation error for privileged Analytics query parameters."""

    def __init__(self, message: str, *, errors: dict[str, str]):
        super().__init__(message)
        self.errors = errors


def validate_query_params(request, allowed):
    """Reject unknown parameters so a misspelled filter cannot broaden reads."""
    unknown = sorted(set(request.query_params.keys()) - set(allowed))
    if unknown:
        raise AnalyticsQueryError(
            "Unknown query parameter",
            errors={name: "This query parameter is not supported" for name in unknown},
        )


def _parse_bounded_integer(raw_value, *, field, default, minimum, maximum):
    if raw_value in (None, ""):
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsQueryError(
            f"Invalid {field} parameter",
            errors={field: f"{field} must be an integer"},
        ) from exc
    if not minimum <= value <= maximum:
        raise AnalyticsQueryError(
            f"Invalid {field} parameter",
            errors={field: f"{field} must be between {minimum} and {maximum}"},
        )
    return value


def parse_pagination(request, default_page_size: int = 20, max_page_size: int = 200):
    """Parse validated pagination parameters from request query params."""
    page = _parse_bounded_integer(
        request.query_params.get("page"),
        field="page",
        default=1,
        minimum=1,
        maximum=1_000_000,
    )
    page_size = _parse_bounded_integer(
        request.query_params.get("page_size"),
        field="page_size",
        default=default_page_size,
        minimum=1,
        maximum=max_page_size,
    )
    return page, page_size


def parse_limit(request, *, default=200, maximum=500):
    return _parse_bounded_integer(
        request.query_params.get("limit"),
        field="limit",
        default=default,
        minimum=1,
        maximum=maximum,
    )


def parse_date_range(request):
    """Parse an optional inclusive UTC date range exactly once."""
    date_from = request.query_params.get("date_from", "")
    date_to = request.query_params.get("date_to", "")

    ts_filter = {}
    if date_from:
        try:
            ts_filter["$gte"] = datetime.strptime(date_from, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError as exc:
            raise AnalyticsQueryError(
                "Invalid date_from parameter",
                errors={"date_from": "date_from must use YYYY-MM-DD"},
            ) from exc
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            ts_filter["$lte"] = date_to_obj.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
        except ValueError as exc:
            raise AnalyticsQueryError(
                "Invalid date_to parameter",
                errors={"date_to": "date_to must use YYYY-MM-DD"},
            ) from exc
    if (
        ts_filter.get("$gte")
        and ts_filter.get("$lte")
        and ts_filter["$gte"] > ts_filter["$lte"]
    ):
        raise AnalyticsQueryError(
            "Invalid date range",
            errors={"date_to": "date_to must be on or after date_from"},
        )
    return ts_filter if ts_filter else None


def parse_audit_filters(request, *, allow_actor_filters):
    """Validate and return normalized audit filters without silent fallback."""
    action = str(request.query_params.get("action", "") or "").strip()
    action_group = (
        str(request.query_params.get("action_group", "") or "").strip().lower()
    )
    user_id = str(request.query_params.get("user_id", "") or "").strip()
    user_type = str(request.query_params.get("user_type", "") or "").strip().lower()
    search = str(request.query_params.get("search", "") or "").strip()

    if action and action not in AUDIT_ACTIONS:
        raise AnalyticsQueryError(
            "Invalid action parameter",
            errors={"action": "action must be a registered audit action"},
        )
    if action_group and action_group not in ACTION_GROUPS:
        raise AnalyticsQueryError(
            "Invalid action_group parameter",
            errors={
                "action_group": "action_group must be login, read, create, update, or delete"
            },
        )
    if not allow_actor_filters and (user_id or user_type):
        raise AnalyticsQueryError(
            "Unsupported actor filter",
            errors={
                key: "This filter is not available on the officer endpoint"
                for key, value in (("user_id", user_id), ("user_type", user_type))
                if value
            },
        )
    if user_type and user_type not in AUDIT_USER_TYPES:
        raise AnalyticsQueryError(
            "Invalid user_type parameter",
            errors={"user_type": "user_type must be a registered audit actor type"},
        )
    if len(user_id) > MAX_IDENTIFIER_LENGTH:
        raise AnalyticsQueryError(
            "Invalid user_id parameter",
            errors={
                "user_id": f"user_id must be at most {MAX_IDENTIFIER_LENGTH} characters"
            },
        )
    if len(search) > MAX_SEARCH_LENGTH:
        raise AnalyticsQueryError(
            "Invalid search parameter",
            errors={"search": f"search must be at most {MAX_SEARCH_LENGTH} characters"},
        )

    return {
        "action": action or None,
        "action_group": action_group or None,
        "user_id": user_id or None,
        "user_type": user_type or None,
        "search": search or None,
        "date_range": parse_date_range(request),
    }


def default_search_conditions(search: str):
    """Build generic search conditions across common audit log fields."""
    regex = {"$regex": re.escape(search), "$options": "i"}
    return [
        {"action": regex},
        {"resource_id": regex},
        {"resource_type": regex},
    ]


def officer_search_conditions(search: str):
    """Build an officer search without profile expansion or sensitive fields."""
    return default_search_conditions(search)


def _safe_identifier(value):
    return str(value) if value is not None else None


def _common_event_fields(log: AuditLog):
    """Return non-secret fields shared by role-specific response contracts."""
    return {
        "id": log.id,
        "action": log.action,
        "action_group": log.action_group or AUDIT_ACTION_REGISTRY.get(log.action),
        "resource_type": log.resource_type,
        "resource_id": _safe_identifier(log.resource_id),
        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
    }


def serialize_dashboard_activity(log: AuditLog):
    """Serialize the minimal audit summary allowed on the admin dashboard."""
    return {
        "action": log.action,
        "action_group": log.action_group or AUDIT_ACTION_REGISTRY.get(log.action),
        "actor_type": log.user_type,
        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
    }


def serialize_admin_log_summary(log: AuditLog):
    """Serialize an audit event for the privileged administrator list."""
    data = _common_event_fields(log)
    data["actor_type"] = log.user_type
    return data


def serialize_admin_log_detail(log: AuditLog):
    """Serialize one event without stored email, IP, description, or details."""
    data = _common_event_fields(log)
    data.update(
        {
            "event_schema_version": log.event_schema_version,
            "actor": {"id": _safe_identifier(log.user_id), "type": log.user_type},
        }
    )
    return data


def serialize_officer_log_entry(log: AuditLog):
    """Serialize an assigned-scope event without identifying another actor."""
    return _common_event_fields(log)


def build_paginated_response(
    logs, total, page: int, page_size: int, *, serializer=serialize_admin_log_summary
):
    """Build the standard paginated audit log response payload."""
    return {
        "logs": [serializer(log) for log in logs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }
