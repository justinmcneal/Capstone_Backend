"""
Loan Officer Dashboard - Review activity and queue stats.
"""

import logging
from datetime import datetime, timezone
from typing import ClassVar

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import error_response, success_response
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
    build_officer_audit_query,
    parse_audit_filters,
    parse_pagination,
    serialize_officer_log_entry,
    validate_query_params,
)
from analytics.services.dashboard_metrics import (
    LOAN_APPROVED_OUTCOME_STATUSES,
    LOAN_PENDING_STATUSES,
    METRIC_DEFINITION_VERSION,
    approval_rate,
    identity_query,
)
from analytics.services.operations import (
    AnalyticsOperationalMixin,
    bounded_count,
    bounded_cursor,
    db_count,
)

logger = logging.getLogger("analytics")


class LoanOfficerRequiredMixin(AnalyticsOperationalMixin, AccessControlMixin):
    """Mixin to require loan officer role"""

    def check_officer_permission(self, request):
        return self.require_roles(request, {"loan_officer"})

    def audit_officer_read(self, officer, endpoint):
        try:
            record_privileged_read(
                actor=officer,
                actor_type="loan_officer",
                endpoint=endpoint,
            )
        except AnalyticsAccessAuditError:
            return error_response(
                message="Analytics access could not be audited",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return None


class OfficerDashboardView(LoanOfficerRequiredMixin, APIView):
    """
    Loan officer dashboard - their review activity.

    GET /api/analytics/officer/
    """

    authentication_classes: ClassVar[list[type]] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        user = result
        officer_id = str(getattr(user, "id", "") or "").strip()
        if not officer_id:
            return error_response(
                message="Authenticated account not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        db = settings.MONGODB

        as_of = datetime.now(timezone.utc)
        today = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        officer_query = identity_query("assigned_officer", officer_id)

        # My reviews - applications I've reviewed
        my_approved = db_count(
            db,
            "loan_applications",
            {
                **officer_query,
                "status": {"$in": sorted(LOAN_APPROVED_OUTCOME_STATUSES)},
            },
        )
        my_rejected = db_count(
            db, "loan_applications", {**officer_query, "status": "rejected"}
        )

        # Reviews today
        approved_today = db_count(
            db,
            "loan_applications",
            {
                **officer_query,
                "status": {"$in": sorted(LOAN_APPROVED_OUTCOME_STATUSES)},
                "decision_date": {"$gte": today},
            },
        )
        rejected_today = db_count(
            db,
            "loan_applications",
            {
                **officer_query,
                "status": "rejected",
                "decision_date": {"$gte": today},
            },
        )

        # Active queue assigned to this officer. Unassigned applications and
        # applications owned by another officer must not appear on a personal
        # dashboard.
        pending_queue = db_count(
            db,
            "loan_applications",
            {
                **officer_query,
                "status": {"$in": sorted(LOAN_PENDING_STATUSES)},
            },
        )

        # Assigned to me
        my_queue = db_count(
            db, "loan_applications", {**officer_query, "status": "under_review"}
        )

        # Approval rate
        total_reviewed = my_approved + my_rejected
        rate = approval_rate(my_approved, total_reviewed)

        audit_error = self.audit_officer_read(user, "officer_dashboard")
        if audit_error:
            return audit_error

        return success_response(
            data={
                "as_of": as_of.isoformat(),
                "metric_definition_version": METRIC_DEFINITION_VERSION,
                "my_reviews": {
                    "total_approved": my_approved,
                    "total_rejected": my_rejected,
                    "approved_today": approved_today,
                    "rejected_today": rejected_today,
                },
                "queue": {"pending_total": pending_queue, "assigned_to_me": my_queue},
                "performance": {
                    "total_reviewed": total_reviewed,
                    "approval_rate": rate,
                },
            },
            message="Officer dashboard data retrieved",
        )


class OfficerAuditLogsView(LoanOfficerRequiredMixin, APIView):
    """
    Loan officer audit logs scoped to the officer and assigned applications.

    GET /api/analytics/officer/audit-logs/
    """

    authentication_classes: ClassVar[list[type]] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        user = result
        officer_id = str(getattr(user, "id", "") or "").strip()
        if not officer_id:
            return error_response(
                message="Authenticated account not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            validate_query_params(
                request,
                {
                    "page",
                    "page_size",
                    "action",
                    "action_group",
                    "date_from",
                    "date_to",
                    "search",
                },
            )
            page, page_size = parse_pagination(request)
            filters = parse_audit_filters(request, allow_actor_filters=False)
        except AnalyticsQueryError as exc:
            return error_response(
                message=str(exc),
                errors=exc.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        db = settings.MONGODB
        query = build_officer_audit_query(officer_id, filters)

        collection = db["audit_logs"]
        total = bounded_count(collection, query)
        skip = (page - 1) * page_size
        cursor = (
            bounded_cursor(collection.find(query))
            .sort([("timestamp", -1), ("_id", -1)])
            .skip(skip)
            .limit(page_size)
        )

        logs_data = [
            serialize_officer_log_entry(AuditLog.from_dict(doc)) for doc in cursor
        ]

        audit_error = self.audit_officer_read(user, "officer_audit_log_list")
        if audit_error:
            return audit_error

        return success_response(
            data={
                "logs": logs_data,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
            },
            message="Officer audit logs retrieved",
        )


class OfficerAuditLogExportView(LoanOfficerRequiredMixin, APIView):
    """Export one bounded, server-authored officer-scoped audit snapshot."""

    authentication_classes: ClassVar[list[type]] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        officer_id = str(getattr(result, "id", "") or "").strip()
        if not officer_id:
            return error_response(
                message="Authenticated account not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        try:
            validate_query_params(
                request,
                {
                    "export_format",
                    "action",
                    "action_group",
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
            filters = parse_audit_filters(request, allow_actor_filters=False)
        except AnalyticsQueryError as exc:
            return error_response(
                message=str(exc),
                errors=exc.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        snapshot_at = datetime.now(timezone.utc)
        audit_error = self.audit_officer_read(result, "officer_audit_log_export")
        if audit_error:
            return audit_error

        query = build_officer_audit_query(officer_id, filters, snapshot_at=snapshot_at)
        try:
            rows = collect_audit_export_rows(
                query, serializer=serialize_officer_log_entry
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
            filename_prefix="officer-audit-logs",
            snapshot_at=snapshot_at,
            include_actor_type=False,
        )
