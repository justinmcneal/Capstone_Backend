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
from analytics.models.audit_log import ACTION_GROUPS
from analytics.services.audit_queries import (
    AnalyticsQueryError,
    officer_search_conditions,
    parse_audit_filters,
    parse_pagination,
    serialize_log_entry,
    validate_query_params,
)

logger = logging.getLogger("analytics")


class LoanOfficerRequiredMixin(AccessControlMixin):
    """Mixin to require loan officer role"""

    def check_officer_permission(self, request):
        return self.require_officer_or_admin(request)


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

        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # My reviews - applications I've reviewed
        my_approved = db["loan_applications"].count_documents(
            {
                "assigned_officer": str(officer_id),
                "status": {"$in": ["approved", "disbursed"]},
            }
        )
        my_rejected = db["loan_applications"].count_documents(
            {"assigned_officer": str(officer_id), "status": "rejected"}
        )

        # Reviews today
        approved_today = db["loan_applications"].count_documents(
            {
                "assigned_officer": str(officer_id),
                "status": {"$in": ["approved", "disbursed"]},
                "decision_date": {"$gte": today},
            }
        )
        rejected_today = db["loan_applications"].count_documents(
            {
                "assigned_officer": str(officer_id),
                "status": "rejected",
                "decision_date": {"$gte": today},
            }
        )

        # Active queue assigned to this officer. Unassigned applications and
        # applications owned by another officer must not appear on a personal
        # dashboard.
        pending_queue = db["loan_applications"].count_documents(
            {
                "assigned_officer": str(officer_id),
                "status": {"$in": ["submitted", "under_review"]},
            }
        )

        # Assigned to me
        my_queue = db["loan_applications"].count_documents(
            {"assigned_officer": str(officer_id), "status": "under_review"}
        )

        # Approval rate
        total_reviewed = my_approved + my_rejected
        approval_rate = (
            (my_approved / total_reviewed * 100) if total_reviewed > 0 else 0
        )

        return success_response(
            data={
                "my_reviews": {
                    "total_approved": my_approved,
                    "total_rejected": my_rejected,
                    "approved_today": approved_today,
                    "rejected_today": rejected_today,
                },
                "queue": {"pending_total": pending_queue, "assigned_to_me": my_queue},
                "performance": {
                    "total_reviewed": total_reviewed,
                    "approval_rate": f"{approval_rate:.1f}%",
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
        action_filter = filters["action"]
        action_group = filters["action_group"]
        date_filters = filters["date_range"]
        search = filters["search"]

        assigned_ids = [
            str(doc.get("_id"))
            for doc in db["loan_applications"].find(
                {"assigned_officer": officer_id}, {"_id": 1}
            )
        ]

        base_or = [{"user_id": officer_id, "user_type": "loan_officer"}]
        if assigned_ids:
            base_or.append(
                {"resource_type": "loan", "resource_id": {"$in": assigned_ids}}
            )

        and_filters = [{"$or": base_or}]

        if action_filter:
            and_filters.append({"action": action_filter})

        if action_group:
            group_filter = {"action": {"$in": ACTION_GROUPS[action_group]}}
            if action_group == "delete":
                group_filter = {
                    "$or": [
                        group_filter,
                        {
                            "action": "admin_action",
                            "description": {
                                "$regex": "(delete|deleted|deactivate|deactivated|remove|removed)",
                                "$options": "i",
                            },
                        },
                    ]
                }
            and_filters.append(group_filter)

        if date_filters:
            and_filters.append({"timestamp": date_filters})

        if search:
            and_filters.append({"$or": officer_search_conditions(search)})

        query = and_filters[0] if len(and_filters) == 1 else {"$and": and_filters}

        collection = db["audit_logs"]
        total = collection.count_documents(query)
        skip = (page - 1) * page_size
        cursor = (
            collection.find(query)
            .sort([("timestamp", -1), ("_id", -1)])
            .skip(skip)
            .limit(page_size)
        )

        logs_data = [serialize_log_entry(AuditLog.from_dict(doc)) for doc in cursor]

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
