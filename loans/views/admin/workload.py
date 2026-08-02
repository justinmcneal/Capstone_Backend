from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text
from rest_framework import status
from accounts.views.admin_views import AdminRequiredMixin
from loans.models import LoanApplication
from loans.services import get_officers_workload
from loans.services.related_data import application_related_maps
from loans.utils.serialization import serialize_internal_note
import logging

logger = logging.getLogger("loans")


class OfficerWorkloadView(AdminRequiredMixin, APIView):
    """
    Admin: View officer workloads and pending applications.

    GET /api/loans/admin/officers/workload/
    Query params:
        - search: Filter by officer name/email
        - page: Page number (default 1)
        - page_size: Items per page (default 20)
        - pending_page: Page number for pending applications (default 1)
        - pending_page_size: Items per page for pending apps (default 20)
        - pending_search: Search term for pending applications
        - assigned_page: Page number for assigned applications (default 1)
        - assigned_page_size: Items per page for assigned apps (default 20)
        - assigned_search: Search term for assigned applications
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    required_permissions = ["manage_loan_officers"]

    def get(self, request):
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        # Get query parameters for officers
        search = sanitize_text(request.query_params.get("search", ""))
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 20))
        except (TypeError, ValueError):
            return error_response(
                message="Invalid officer pagination parameters",
                errors={"pagination": "page and page_size must be integers"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if page < 1 or page_size < 1 or page_size > 100:
            return error_response(
                message="Invalid officer pagination parameters",
                errors={
                    "pagination": "page must be >= 1 and page_size must be between 1 and 100"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Get query parameters for pending applications
        pending_search = sanitize_text(request.query_params.get("pending_search", ""))
        try:
            pending_page = int(request.query_params.get("pending_page", 1))
            pending_page_size = int(request.query_params.get("pending_page_size", 20))
        except (TypeError, ValueError):
            return error_response(
                message="Invalid pending pagination parameters",
                errors={
                    "pending_pagination": "pending_page and pending_page_size must be integers"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if pending_page < 1 or pending_page_size < 1 or pending_page_size > 100:
            return error_response(
                message="Invalid pending pagination parameters",
                errors={
                    "pending_pagination": "pending_page must be >= 1 and pending_page_size must be between 1 and 100"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Get query parameters for assigned applications
        assigned_search = sanitize_text(request.query_params.get("assigned_search", ""))
        try:
            assigned_page = int(request.query_params.get("assigned_page", 1))
            assigned_page_size = int(request.query_params.get("assigned_page_size", 20))
        except (TypeError, ValueError):
            return error_response(
                message="Invalid assigned pagination parameters",
                errors={
                    "assigned_pagination": "assigned_page and assigned_page_size must be integers"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if assigned_page < 1 or assigned_page_size < 1 or assigned_page_size > 100:
            return error_response(
                message="Invalid assigned pagination parameters",
                errors={
                    "assigned_pagination": "assigned_page must be >= 1 and assigned_page_size must be between 1 and 100"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Get paginated workload
        workload_data = get_officers_workload(
            page=page, page_size=page_size, search=search if search else None
        )

        # Get paginated pending applications
        pending_data = LoanApplication.find_pending_paginated(
            page=pending_page,
            page_size=pending_page_size,
            search=pending_search if pending_search else None,
        )

        # Get paginated assigned applications
        assigned_data = LoanApplication.find_assigned_paginated(
            page=assigned_page,
            page_size=assigned_page_size,
            search=assigned_search if assigned_search else None,
            officer_id=None,  # Get all assigned apps, not filtered by officer
        )

        all_apps = list(pending_data["applications"]) + list(
            assigned_data["applications"]
        )
        related = application_related_maps(all_apps)
        customer_names = {
            customer_id: customer.full_name or "Unknown"
            for customer_id, customer in related["customers"].items()
        }
        officer_names = {
            officer_id: officer.full_name or "Unknown"
            for officer_id, officer in related["officers"].items()
        }

        # Format pending applications for response
        pending_apps = [
            {
                "id": app.id,
                "customer_id": app.customer_id,
                "customer_name": customer_names.get(app.customer_id, "Unknown"),
                "requested_amount": app.requested_amount,
                "term_months": app.term_months,
                "status": app.status,
                "eligibility_score": app.eligibility_score,
                "risk_category": app.risk_category,
                "assigned_officer": app.assigned_officer,
                "assigned_officer_name": (
                    officer_names.get(app.assigned_officer, None)
                    if app.assigned_officer
                    else None
                ),
                "submitted_at": (
                    app.submitted_at.isoformat() if app.submitted_at else None
                ),
                "internal_notes_count": len(app.internal_notes or []),
                "latest_internal_note": serialize_internal_note(
                    (app.internal_notes or [])[-1]
                    if (app.internal_notes or [])
                    else None
                ),
            }
            for app in pending_data["applications"]
        ]

        # Format assigned applications for response
        assigned_apps = [
            {
                "id": app.id,
                "customer_id": app.customer_id,
                "customer_name": customer_names.get(app.customer_id, "Unknown"),
                "requested_amount": app.requested_amount,
                "term_months": app.term_months,
                "status": app.status,
                "eligibility_score": app.eligibility_score,
                "risk_category": app.risk_category,
                "assigned_officer": app.assigned_officer,
                "assigned_officer_name": (
                    officer_names.get(app.assigned_officer, None)
                    if app.assigned_officer
                    else None
                ),
                "submitted_at": (
                    app.submitted_at.isoformat() if app.submitted_at else None
                ),
                "internal_notes_count": len(app.internal_notes or []),
                "latest_internal_note": serialize_internal_note(
                    (app.internal_notes or [])[-1]
                    if (app.internal_notes or [])
                    else None
                ),
            }
            for app in assigned_data["applications"]
        ]

        return success_response(
            data={
                "officers": workload_data["officers"],
                "total": workload_data["total"],
                "page": workload_data["page"],
                "page_size": workload_data["page_size"],
                "total_pages": workload_data["total_pages"],
                "pending_applications": pending_apps,
                "pending_count": pending_data["total"],
                "pending_page": pending_data["page"],
                "pending_page_size": pending_data["page_size"],
                "pending_total_pages": pending_data["total_pages"],
                "assigned_applications": assigned_apps,
                "assigned_count": assigned_data["total"],
                "assigned_page": assigned_data["page"],
                "assigned_page_size": assigned_data["page_size"],
                "assigned_total_pages": assigned_data["total_pages"],
            },
            message="Officer workload retrieved",
        )
