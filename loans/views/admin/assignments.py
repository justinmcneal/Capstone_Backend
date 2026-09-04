import logging

from bson import ObjectId
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.validation_utils import sanitize_text
from accounts.views.admin_views import AdminRequiredMixin
from loans.models import LoanApplication, LoanTransitionConflict

logger = logging.getLogger("loans")


class AssignApplicationView(AdminRequiredMixin, APIView):
    """
    Admin: Manually assign application to officer.

    POST /api/loans/admin/applications/<id>/assign/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    required_permissions = ["manage_loan_officers"]

    def post(self, request, application_id):
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result
        assigning_admin = result

        app = LoanApplication.find_by_id(application_id)
        if not app:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )

        officer_id = sanitize_text(request.data.get("officer_id", ""))
        if not officer_id:
            return error_response(
                message="officer_id is required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if not ObjectId.is_valid(officer_id):
            return error_response(
                message="Invalid officer_id format",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        from loans.services import manual_assign_application

        try:
            officer = manual_assign_application(
                app, officer_id, assigned_by=assigning_admin
            )
            if not officer:
                return error_response(
                    message="Officer not found", status_code=status.HTTP_404_NOT_FOUND
                )

            return success_response(
                data={
                    "application_id": app.id,
                    "assigned_officer": officer.id,
                    "officer_name": officer.full_name,
                    "status": app.status,
                },
                message="Application assigned successfully",
            )
        except LoanTransitionConflict:
            return error_response(
                message="The application assignment changed. Refresh and retry.",
                code="LOAN_TRANSITION_CONFLICT",
                status_code=status.HTTP_409_CONFLICT,
            )
        except ValueError as e:
            return error_response(
                message=str(e), status_code=status.HTTP_400_BAD_REQUEST
            )


class ReassignApplicationView(AdminRequiredMixin, APIView):
    """
    Admin: Reassign application to a different officer.

    POST /api/loans/admin/applications/<id>/reassign/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    required_permissions = ["manage_loan_officers"]

    def post(self, request, application_id):
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result
        assigning_admin = result

        app = LoanApplication.find_by_id(application_id)
        if not app:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )

        new_officer_id = sanitize_text(request.data.get("officer_id", ""))
        if not new_officer_id:
            return error_response(
                message="officer_id is required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if not ObjectId.is_valid(new_officer_id):
            return error_response(
                message="Invalid officer_id format",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        from loans.services import reassign_application

        try:
            new_officer = reassign_application(
                app, new_officer_id, assigned_by=assigning_admin
            )
            if not new_officer:
                return error_response(
                    message="Officer not found", status_code=status.HTTP_404_NOT_FOUND
                )

            return success_response(
                data={
                    "application_id": app.id,
                    "assigned_officer": new_officer.id,
                    "officer_name": new_officer.full_name,
                    "status": app.status,
                },
                message="Application reassigned successfully",
            )
        except LoanTransitionConflict:
            return error_response(
                message="The application assignment changed. Refresh and retry.",
                code="LOAN_TRANSITION_CONFLICT",
                status_code=status.HTTP_409_CONFLICT,
            )
        except ValueError as e:
            return error_response(
                message=str(e), status_code=status.HTTP_400_BAD_REQUEST
            )
