"""
Loan Officer Dashboard - Review activity and queue stats.
"""

from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from datetime import datetime, timezone
from bson import ObjectId

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text
from django.conf import settings
from analytics.models import AuditLog
from analytics.models.audit_log import ACTION_GROUPS
import logging

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

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

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

        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

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

        # Pending queue - all applications waiting for any officer
        pending_queue = db["loan_applications"].count_documents(
            {"status": {"$in": ["submitted", "under_review"]}}
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

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import re

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

        # Pagination parameters
        try:
            page = max(int(request.query_params.get("page", 1)), 1)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid page parameter",
                errors={"page": "page must be an integer"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 200)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid page_size parameter",
                errors={"page_size": "page_size must be an integer"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Filters
        action_filter = sanitize_text(request.query_params.get("action", ""))
        action_group = sanitize_text(request.query_params.get("action_group", ""))
        date_from = sanitize_text(request.query_params.get("date_from", ""))
        date_to = sanitize_text(request.query_params.get("date_to", ""))
        search = sanitize_text(request.query_params.get("search", ""))

        # Loan IDs assigned to this officer
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
            group = str(action_group).strip().lower()
            if group in ACTION_GROUPS:
                and_filters.append({"action": {"$in": ACTION_GROUPS[group]}})
            elif group == "delete":
                and_filters.append(
                    {
                        "$and": [
                            {"action": "admin_action"},
                            {
                                "description": {
                                    "$regex": "(delete|deleted|deactivate|deactivated|remove|removed)",
                                    "$options": "i",
                                }
                            },
                        ]
                    }
                )

        if date_from or date_to:
            ts_filter = {}
            if date_from:
                try:
                    ts_filter["$gte"] = datetime.strptime(date_from, "%Y-%m-%d")
                except ValueError:
                    pass
            if date_to:
                try:
                    date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
                    ts_filter["$lte"] = date_to_obj.replace(
                        hour=23, minute=59, second=59, microsecond=999999
                    )
                except ValueError:
                    pass
            if ts_filter:
                and_filters.append({"timestamp": ts_filter})

        if search:
            regex = {"$regex": re.escape(search), "$options": "i"}
            and_filters.append(
                {
                    "$or": [
                        {"description": regex},
                        {"action": regex},
                        {"resource_id": regex},
                        {"resource_type": regex},
                    ]
                }
            )

        query = and_filters[0] if len(and_filters) == 1 else {"$and": and_filters}

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

        collection = db["audit_logs"]
        total = collection.count_documents(query)
        skip = (page - 1) * page_size
        cursor = (
            collection.find(query).sort("timestamp", -1).skip(skip).limit(page_size)
        )

        logs_data = []
        for doc in cursor:
            log = AuditLog.from_dict(doc)
            logs_data.append(
                {
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
            )

        return success_response(
            data={
                "logs": logs_data,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if total > 0 else 1,
            },
            message="Officer audit logs retrieved",
        )
