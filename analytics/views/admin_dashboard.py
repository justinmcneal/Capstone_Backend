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
from accounts.views.admin_views import AdminRequiredMixin
from analytics.models import AuditLog
from analytics.services.access_audit import (
    AnalyticsAccessAuditError,
    record_privileged_read,
)
from analytics.services.audit_exports import (
    AuditExportLimitError,
    build_audit_export_response,
    collect_audit_export_rows,
)
from analytics.services.audit_queries import (
    AnalyticsQueryError,
    build_admin_audit_query,
    build_paginated_response,
    parse_audit_filters,
    parse_limit,
    parse_pagination,
    serialize_admin_log_detail,
    serialize_admin_log_summary,
    serialize_dashboard_activity,
    validate_query_params,
)
from analytics.services.dashboard_metrics import (
    DOCUMENT_PENDING_STATUSES,
    LOAN_APPROVED_OUTCOME_STATUSES,
    LOAN_DISBURSED_STATUSES,
    LOAN_PENDING_STATUSES,
    METRIC_DEFINITION_VERSION,
    approval_rate,
    current_document_query,
    identity_query,
    status_query,
)
from analytics.services.operations import (
    AnalyticsOperationalMixin,
    bounded_aggregate,
    bounded_count,
    bounded_cursor,
    db_count,
)

logger = logging.getLogger("analytics")


def _audit_admin_read(request, admin, endpoint):
    try:
        record_privileged_read(
            actor=admin,
            actor_type=str(getattr(request.user, "role", "admin") or "admin"),
            endpoint=endpoint,
        )
    except AnalyticsAccessAuditError:
        return error_response(
            message="Analytics access could not be audited",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return None


class AdminDashboardView(AnalyticsOperationalMixin, AdminRequiredMixin, APIView):
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

        as_of = datetime.now(timezone.utc)
        week_ago = as_of - timedelta(days=7)
        month_start = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # User counts - use correct collection names from models
        total_customers = db_count(db, "customer", {})
        total_officers = db_count(db, "loan_officers", {})
        total_admins = db_count(db, "admins", {})
        new_customers_this_week = db_count(
            db, "customer", {"created_at": {"$gte": week_ago}}
        )
        new_officers_this_month = db_count(
            db, "loan_officers", {"created_at": {"$gte": month_start}}
        )

        loans = db["loan_applications"]
        approved_outcomes = bounded_count(
            loans, {"status": {"$in": sorted(LOAN_APPROVED_OUTCOME_STATUSES)}}
        )
        rejected_outcomes = bounded_count(loans, {"status": "rejected"})
        # Outcome fields remain meaningful after disbursement/closure. `pending`
        # is the published aggregate of submitted plus under-review records.
        loan_stats = {
            "total": bounded_count(loans, {}),
            "draft": bounded_count(loans, {"status": "draft"}),
            "submitted": bounded_count(loans, {"status": "submitted"}),
            "pending": bounded_count(
                loans, {"status": {"$in": sorted(LOAN_PENDING_STATUSES)}}
            ),
            "under_review": bounded_count(loans, {"status": "under_review"}),
            "approved": approved_outcomes,
            "rejected": rejected_outcomes,
            "reviewed": approved_outcomes + rejected_outcomes,
            "disbursed": bounded_count(
                loans, {"status": {"$in": sorted(LOAN_DISBURSED_STATUSES)}}
            ),
            "completed": bounded_count(loans, {"status": "completed"}),
            "written_off": bounded_count(loans, {"status": "written_off"}),
            "cancelled": bounded_count(loans, {"status": "cancelled"}),
        }

        # Document metrics cover only the current metadata version whose object
        # remains available. Canonical status, not the legacy boolean, is used.
        current_documents = current_document_query()
        doc_stats = {
            "total": db_count(db, "documents", current_documents),
            "pending": db_count(
                db,
                "documents",
                status_query(current_documents, DOCUMENT_PENDING_STATUSES),
            ),
            "needs_review": db_count(
                db, "documents", status_query(current_documents, {"needs_review"})
            ),
            "approved": db_count(
                db, "documents", status_query(current_documents, {"approved"})
            ),
            "verified": db_count(
                db, "documents", status_query(current_documents, {"approved"})
            ),
            "rejected": db_count(
                db, "documents", status_query(current_documents, {"rejected"})
            ),
            "expired": db_count(
                db, "documents", status_query(current_documents, {"expired"})
            ),
        }

        # AI usage (last 7 days)
        ai_sessions = db_count(
            db, "ai_interactions", {"created_at": {"$gte": week_ago}}
        )

        # Audit-derived content is a separate permission boundary from metrics.
        can_view_logs = result.has_all_permissions(["view_logs"])
        recent_activity = []
        if can_view_logs:
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
                sort=[("timestamp", -1), ("_id", -1)],
                limit=10,
            )
            recent_activity = [serialize_dashboard_activity(log) for log in recent_logs]

        # Loan products performance
        products = list(
            bounded_cursor(db["loan_products"].find({"active": True}))
            .sort([("name", 1), ("_id", 1)])
            .limit(int(getattr(settings, "ANALYTICS_MAX_ACTIVE_PRODUCTS", 100)))
        )
        product_ids = []
        for product in products:
            product_ids.extend(
                identity_query("product_id", product["_id"])["product_id"].get(
                    "$in", [str(product["_id"])]
                )
            )
        grouped = {}
        if product_ids:
            pipeline = [
                {"$match": {"product_id": {"$in": product_ids}}},
                {
                    "$group": {
                        "_id": {"product_id": "$product_id", "status": "$status"},
                        "count": {"$sum": 1},
                    }
                },
            ]
            for row in bounded_aggregate(loans, pipeline):
                grouped[(str(row["_id"]["product_id"]), row["_id"]["status"])] = int(
                    row["count"]
                )
        product_stats = []
        for p in products:
            status_counts = {
                loan_status: grouped.get((str(p["_id"]), loan_status), 0)
                for loan_status in (
                    LOAN_APPROVED_OUTCOME_STATUSES
                    | {"rejected", "draft", "submitted", "under_review", "cancelled"}
                )
            }
            approved = sum(
                status_counts.get(loan_status, 0)
                for loan_status in LOAN_APPROVED_OUTCOME_STATUSES
            )
            rejected = status_counts.get("rejected", 0)
            reviewed = approved + rejected
            total = sum(status_counts.values())
            product_stats.append(
                {
                    "name": p["name"],
                    "applications": total,
                    "reviewed": reviewed,
                    "approved": approved,
                    "approval_rate": approval_rate(approved, reviewed),
                }
            )

        audit_error = _audit_admin_read(request, result, "admin_dashboard")
        if audit_error:
            return audit_error

        return success_response(
            data={
                "as_of": as_of.isoformat(),
                "metric_definition_version": METRIC_DEFINITION_VERSION,
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
                "recent_activity_restricted": not can_view_logs,
            },
            message="Admin dashboard data retrieved",
        )


class AuditLogsView(AnalyticsOperationalMixin, AdminRequiredMixin, APIView):
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
            validate_query_params(
                request,
                {
                    "page",
                    "page_size",
                    "action",
                    "action_group",
                    "user_id",
                    "user_type",
                    "date_from",
                    "date_to",
                    "search",
                },
            )
            page, page_size = parse_pagination(request)
            filters = parse_audit_filters(request, allow_actor_filters=True)
        except AnalyticsQueryError as exc:
            return error_response(
                message=str(exc),
                errors=exc.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        date_filters = filters.pop("date_range")

        logs = AuditLog.find_with_filters(
            date_from=(date_filters or {}).get("$gte"),
            date_to=(date_filters or {}).get("$lte"),
            skip=(page - 1) * page_size,
            limit=page_size,
            **filters,
        )

        total = AuditLog.count_with_filters(
            date_from=(date_filters or {}).get("$gte"),
            date_to=(date_filters or {}).get("$lte"),
            **filters,
        )

        response_data = build_paginated_response(list(logs), total, page, page_size)
        audit_error = _audit_admin_read(request, result, "audit_log_list")
        if audit_error:
            return audit_error
        return success_response(
            data=response_data,
            message="Audit logs retrieved",
        )


class AuditLogExportView(AnalyticsOperationalMixin, AdminRequiredMixin, APIView):
    """Export one bounded, server-authored administrator audit snapshot."""

    required_permissions: ClassVar[list[str]] = ["view_logs"]
    authentication_classes: ClassVar[list[type]] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        try:
            validate_query_params(
                request,
                {
                    "export_format",
                    "action",
                    "action_group",
                    "user_id",
                    "user_type",
                    "date_from",
                    "date_to",
                    "search",
                },
            )
            export_format = str(
                request.query_params.get("export_format", "csv")
            ).lower()
            if export_format not in {"csv", "excel"}:
                raise AnalyticsQueryError(
                    "Invalid export_format parameter",
                    errors={"export_format": "export_format must be csv or excel"},
                )
            filters = parse_audit_filters(request, allow_actor_filters=True)
        except AnalyticsQueryError as exc:
            return error_response(
                message=str(exc),
                errors=exc.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        snapshot_at = datetime.now(timezone.utc)
        audit_error = _audit_admin_read(request, result, "audit_log_export")
        if audit_error:
            return audit_error

        query = build_admin_audit_query(filters, snapshot_at=snapshot_at)
        try:
            rows = collect_audit_export_rows(
                query, serializer=serialize_admin_log_summary
            )
        except AuditExportLimitError as exc:
            return error_response(
                message=str(exc),
                errors={"filters": "Use narrower filters before exporting"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if not rows:
            return error_response(
                message="No audit logs match the selected filters",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return build_audit_export_response(
            rows,
            export_format=export_format,
            filename_prefix="audit-logs",
            snapshot_at=snapshot_at,
            include_actor_type=True,
        )


class AuditLogUsersView(AnalyticsOperationalMixin, AdminRequiredMixin, APIView):
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

        try:
            validate_query_params(request, {"search", "limit"})
            limit = parse_limit(request)
            search = str(request.query_params.get("search", "") or "").strip()
            if len(search) > 100:
                raise AnalyticsQueryError(
                    "Invalid search parameter",
                    errors={"search": "search must be at most 100 characters"},
                )
        except AnalyticsQueryError as exc:
            return error_response(
                message=str(exc),
                errors=exc.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        collection = settings.MONGODB["audit_logs"]
        match_stage = {"user_id": {"$nin": [None, ""]}}
        if search:
            regex = {"$regex": f"^{re.escape(search)}", "$options": "i"}
            match_stage["$or"] = [{"user_type": regex}, {"user_id": regex}]

        pipeline = [
            {"$match": match_stage},
            {"$sort": {"timestamp": -1}},
            {
                "$group": {
                    "_id": "$user_id",
                    "user_id": {"$first": "$user_id"},
                    "user_type": {"$first": "$user_type"},
                    "latest_timestamp": {"$first": "$timestamp"},
                }
            },
            {"$sort": {"latest_timestamp": -1}},
            {"$limit": limit},
        ]

        users = []
        for doc in bounded_aggregate(collection, pipeline):
            user_id = str(doc.get("user_id"))
            user_type = doc.get("user_type") or "unknown"
            short_id = f"{user_id[:8]}..."
            label = f"{user_type} ({short_id})"
            users.append(
                {
                    "user_id": user_id,
                    "user_type": user_type,
                    "label": label,
                }
            )

        audit_error = _audit_admin_read(request, result, "audit_log_actor_directory")
        if audit_error:
            return audit_error
        return success_response(
            data={"users": users},
            message="Audit log users retrieved",
        )


class AuditLogDetailView(AnalyticsOperationalMixin, AdminRequiredMixin, APIView):
    """
    Get minimized privileged detail for a specific audit log entry.

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
        audit_error = _audit_admin_read(request, result, "audit_log_detail")
        if audit_error:
            return audit_error
        return success_response(
            data=serialize_admin_log_detail(log),
            message="Audit log detail retrieved",
        )
