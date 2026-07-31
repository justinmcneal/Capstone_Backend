"""
Admin Dashboard - System-wide analytics for admins.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import ClassVar

from bson import ObjectId
from bson.errors import InvalidId
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.validation_utils import sanitize_text
from accounts.views.admin_views import AdminRequiredMixin
from analytics.models import AuditLog
from analytics.services.audit_queries import (
    build_paginated_response,
    parse_date_range,
    parse_pagination,
)

logger = logging.getLogger("analytics")


class AdminDashboardView(AdminRequiredMixin, APIView):
    """
    Admin dashboard with system-wide statistics.

    GET /api/analytics/admin/
    """

    authentication_classes: ClassVar[list[type]] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]
    required_permissions: ClassVar[list[str]] = ["view_analytics"]

    def get(self, request):
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        from django.conf import settings

        db = settings.MONGODB

        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # User counts - use correct collection names from models
        total_customers = db["customer"].count_documents(
            {}
        )  # Customer model uses 'customer'
        total_officers = db["loan_officers"].count_documents({})
        total_admins = db["admins"].count_documents({})
        new_customers_this_week = db["customer"].count_documents(
            {"created_at": {"$gte": week_ago}}
        )
        new_officers_this_month = db["loan_officers"].count_documents(
            {"created_at": {"$gte": month_start}}
        )

        # Loan stats - include ALL statuses for complete visibility
        loan_stats = {
            "total": db["loan_applications"].count_documents({}),
            "draft": db["loan_applications"].count_documents({"status": "draft"}),
            "pending": db["loan_applications"].count_documents({"status": "submitted"}),
            "under_review": db["loan_applications"].count_documents(
                {"status": "under_review"}
            ),
            "approved": db["loan_applications"].count_documents({"status": "approved"}),
            "rejected": db["loan_applications"].count_documents({"status": "rejected"}),
            "disbursed": db["loan_applications"].count_documents(
                {"status": "disbursed"}
            ),
            "cancelled": db["loan_applications"].count_documents(
                {"status": "cancelled"}
            ),
        }

        # Document stats
        doc_stats = {
            "total": db["documents"].count_documents({}),
            "pending": db["documents"].count_documents({"status": "pending"}),
            "verified": db["documents"].count_documents({"verified": True}),
        }

        # AI usage (last 7 days)
        ai_sessions = db["ai_interactions"].count_documents(
            {"created_at": {"$gte": week_ago}}
        )

        # Recent activity (last 10 audit logs, excluding standard noise)
        recent_logs = AuditLog.find(
            query={
                "action": {
                    "$nin": [
                        "user_login",
                        "user_logout",
                        "user_login_failed",
                        "loan_submitted",
                        "document_uploaded",
                    ]
                }
            },
            sort=[("timestamp", -1)],
            limit=10,
        )
        recent_activity = [
            {
                "action": log.action,
                "user_type": log.user_type,
                "description": log.description,
                "timestamp": log.timestamp.isoformat(),
            }
            for log in recent_logs
        ]

        # Loan products performance
        products = list(db["loan_products"].find({"active": True}))
        product_stats = []
        for p in products:
            approved = db["loan_applications"].count_documents(
                {"product_id": str(p["_id"]), "status": "approved"}
            )
            total = db["loan_applications"].count_documents(
                {"product_id": str(p["_id"])}
            )
            product_stats.append(
                {
                    "name": p["name"],
                    "applications": total,
                    "approved": approved,
                    "approval_rate": (
                        f"{(approved / total * 100):.1f}%" if total > 0 else "0%"
                    ),
                }
            )

        return success_response(
            data={
                "users": {
                    "customers": total_customers,
                    "loan_officers": total_officers,
                    "admins": total_admins,
                    "total": total_customers + total_officers + total_admins,
                    "new_customers_this_week": new_customers_this_week,
                    "new_loan_officers_this_month": new_officers_this_month,
                },
                "loans": loan_stats,
                "documents": doc_stats,
                "ai_usage": {"sessions_last_7_days": ai_sessions},
                "products": product_stats,
                "recent_activity": recent_activity,
            },
            message="Admin dashboard data retrieved",
        )


class AuditLogsView(AdminRequiredMixin, APIView):
    """
    View audit logs (admin only).

    GET /api/analytics/audit-logs/
    """

    required_permissions: ClassVar[list[str]] = ["view_logs"]
    authentication_classes: ClassVar[list[type]] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        try:
            page, page_size = parse_pagination(request)
        except ValueError as exc:
            return error_response(
                message=str(exc.args[0]),
                errors=exc.args[1] if len(exc.args) > 1 else {},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        action_filter = sanitize_text(request.query_params.get("action", ""))
        action_group = sanitize_text(request.query_params.get("action_group", ""))
        user_id = sanitize_text(request.query_params.get("user_id", ""))
        user_type = sanitize_text(request.query_params.get("user_type", ""))
        search = sanitize_text(request.query_params.get("search", ""))
        date_filters = parse_date_range(request)

        logs = AuditLog.find_with_filters(
            action=action_filter or None,
            action_group=action_group or None,
            user_id=user_id or None,
            user_type=user_type or None,
            date_from=(date_filters or {}).get("$gte"),
            date_to=(date_filters or {}).get("$lte"),
            search=search or None,
            skip=(page - 1) * page_size,
            limit=page_size,
        )

        total = AuditLog.count_with_filters(
            action=action_filter or None,
            action_group=action_group or None,
            user_id=user_id or None,
            user_type=user_type or None,
            date_from=(date_filters or {}).get("$gte"),
            date_to=(date_filters or {}).get("$lte"),
            search=search or None,
        )

        response_data = build_paginated_response(list(logs), total, page, page_size)
        return success_response(
            data=response_data,
            message="Audit logs retrieved",
        )


class AuditLogUsersView(AdminRequiredMixin, APIView):
    """
    List users present in audit logs for user-based filtering.

    GET /api/analytics/audit-logs/users/
    """

    required_permissions: ClassVar[list[str]] = ["view_logs"]
    authentication_classes: ClassVar[list[type]] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    def get(self, request):
        import re

        from django.conf import settings

        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        search = sanitize_text(request.query_params.get("search", ""))
        try:
            limit = min(max(int(request.query_params.get("limit", 200)), 1), 500)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid limit parameter",
                errors={"limit": "limit must be an integer"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        collection = settings.MONGODB["audit_logs"]
        match_stage = {"user_id": {"$nin": [None, ""]}}
        if search:
            regex = {"$regex": re.escape(search), "$options": "i"}
            match_stage["$or"] = [
                {"user_email": regex},
                {"user_type": regex},
                {"user_id": regex},
            ]

        pipeline = [
            {"$match": match_stage},
            {"$sort": {"timestamp": -1}},
            {
                "$group": {
                    "_id": "$user_id",
                    "user_id": {"$first": "$user_id"},
                    "user_type": {"$first": "$user_type"},
                    "user_email": {"$first": "$user_email"},
                    "latest_timestamp": {"$first": "$timestamp"},
                }
            },
            {"$sort": {"latest_timestamp": -1}},
            {"$limit": limit},
        ]

        users = []
        for doc in collection.aggregate(pipeline):
            user_id = doc.get("user_id")
            user_type = doc.get("user_type") or "unknown"
            user_email = doc.get("user_email") or ""
            short_id = f"{user_id[:8]}..." if isinstance(user_id, str) else ""
            label = (
                f"{user_email} ({user_type})"
                if user_email
                else f"{user_type} ({short_id})"
            )
            users.append(
                {
                    "user_id": user_id,
                    "user_type": user_type,
                    "user_email": user_email,
                    "label": label,
                }
            )

        return success_response(
            data={"users": users},
            message="Audit log users retrieved",
        )


class AuditLogDetailView(AdminRequiredMixin, APIView):
    """
    Get full detail for a specific audit log entry.

    GET /api/analytics/audit-logs/<log_id>/
    """

    required_permissions: ClassVar[list[str]] = ["view_logs"]
    authentication_classes: ClassVar[list[type]] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    def get(self, request, log_id):
        from django.conf import settings

        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        def serialize_details(value):
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, ObjectId):
                return str(value)
            if isinstance(value, dict):
                return {k: serialize_details(v) for k, v in value.items()}
            if isinstance(value, list):
                return [serialize_details(v) for v in value]
            return value

        try:
            oid = ObjectId(log_id)
        except InvalidId:
            return error_response(
                message="Invalid log ID",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        doc = settings.MONGODB["audit_logs"].find_one({"_id": oid})
        if not doc:
            return error_response(
                message="Audit log not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        log = AuditLog.from_dict(doc)
        return success_response(
            data={
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
            },
            message="Audit log detail retrieved",
        )
