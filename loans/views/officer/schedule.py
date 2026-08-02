from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text
from rest_framework import status
from loans.models import LoanApplication, RepaymentSchedule
from loans.views.officer.base import LoanOfficerRequiredMixin
from loans.services.audit import record_loan_audit
from loans.utils.time import utcnow
import logging

logger = logging.getLogger("loans")


class OfficerScheduleView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Get repayment schedule for a loan.

    GET /api/loans/officer/applications/<id>/schedule/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        # Get application
        app = LoanApplication.find_by_id(application_id)
        if not app:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )
        has_scope, scope_result = self.check_application_scope(
            request,
            app,
            allow_unassigned=False,
        )
        if not has_scope:
            return scope_result

        # Only disbursed loans have schedules
        if app.status not in {"disbursed", "completed", "written_off"}:
            return error_response(
                message="Repayment schedule is only available for disbursed loans",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        schedule = RepaymentSchedule.find_by_loan(application_id)

        if not schedule:
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Format installments
        installments = []
        now = utcnow()
        for inst in schedule.installments:
            due_date = inst.get("due_date")
            inst_status = inst.get("status", "pending")
            if (
                inst_status == "pending"
                and due_date
                and hasattr(due_date, "date")
                and due_date.date() < now.date()
            ):
                # Derive overdue dynamically so stale pending records still show correctly.
                inst_status = "overdue"

            penalty_applied_at = inst.get("penalty_applied_at")
            if hasattr(penalty_applied_at, "isoformat"):
                penalty_applied_at = penalty_applied_at.isoformat()
            penalty_waived_at = inst.get("penalty_waived_at")
            if hasattr(penalty_waived_at, "isoformat"):
                penalty_waived_at = penalty_waived_at.isoformat()

            # Calculate actual amount due including penalties
            base_total_amount = inst["total_amount"]
            penalty_amount = inst.get("penalty_amount", 0)
            penalty_status = inst.get("penalty_status")

            # Include penalty in total if applied and not waived
            actual_total_amount = base_total_amount
            if penalty_status == "applied" and penalty_amount > 0:
                actual_total_amount = base_total_amount + penalty_amount

            installments.append(
                {
                    "number": inst["number"],
                    "due_date": due_date.isoformat() if due_date else None,
                    "principal": inst["principal"],
                    "interest": inst["interest"],
                    "total_amount": actual_total_amount,  # Include penalty in total
                    "base_amount": base_total_amount,  # Original amount without penalty
                    "status": inst_status,
                    "paid_amount": inst.get("paid_amount", 0),
                    "penalty_status": inst.get("penalty_status"),
                    "penalty_amount": inst.get("penalty_amount"),
                    "penalty_reason": inst.get("penalty_reason", ""),
                    "penalty_applied_at": penalty_applied_at,
                    "penalty_applied_by": inst.get("penalty_applied_by"),
                    "penalty_waived_at": penalty_waived_at,
                    "penalty_waived_by": inst.get("penalty_waived_by"),
                    "penalty_waived_reason": inst.get("penalty_waived_reason", ""),
                }
            )

        return success_response(
            data={
                "loan_id": schedule.loan_id,
                "principal": schedule.principal,
                "interest_rate": schedule.interest_rate,
                "term_months": schedule.term_months,
                "monthly_payment": schedule.monthly_payment,
                "total_amount": schedule.total_amount,
                "total_interest": schedule.total_interest,
                "schedule_status": schedule.status,
                "paid_off_at": (
                    schedule.paid_off_at.isoformat() if schedule.paid_off_at else None
                ),
                "paid_count": schedule.get_paid_count(),
                "remaining_balance": schedule.get_remaining_balance(),
                "next_payment": schedule.get_next_payment(),
                "installments": installments,
            },
            message="Repayment schedule retrieved",
        )


class ApplyPenaltyView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Apply penalty to a repayment installment.

    POST /api/loans/officer/applications/<id>/penalties/apply/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        app = LoanApplication.find_by_id(application_id)
        if not app:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )
        has_scope, scope_result = self.check_application_scope(
            request,
            app,
            allow_unassigned=False,
        )
        if not has_scope:
            return scope_result

        if app.status != "disbursed":
            return error_response(
                message="Penalties can only be applied to disbursed loans",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        installment_number_raw = request.data.get("installment_number")
        amount_raw = request.data.get("penalty_amount")
        reason = sanitize_text(request.data.get("reason", ""))

        if installment_number_raw in (None, ""):
            return error_response(
                message="installment_number is required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            installment_number = int(installment_number_raw)
        except (TypeError, ValueError):
            return error_response(
                message="installment_number must be an integer",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if installment_number < 1:
            return error_response(
                message="installment_number must be at least 1",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if amount_raw in (None, ""):
            return error_response(
                message="penalty_amount is required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            penalty_amount = float(amount_raw)
        except (TypeError, ValueError):
            return error_response(
                message="penalty_amount must be a valid number",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if penalty_amount <= 0:
            return error_response(
                message="penalty_amount must be greater than 0",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        schedule = RepaymentSchedule.find_by_loan(application_id)
        if not schedule:
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        actor_id = self._actor_id(request.user)
        try:
            installment = schedule.apply_penalty(
                installment_number, penalty_amount, reason, actor_id
            )
        except ValueError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_400_BAD_REQUEST
            )
        penalty_amount = installment["penalty_amount"]
        now = installment["penalty_applied_at"]

        record_loan_audit(
            action="penalty_applied",
            user_id=actor_id,
            user_type=self._actor_type(request.user),
            description=f"Penalty applied - PHP{penalty_amount:,.2f} for installment #{installment_number}",
            resource_type="penalty",
            resource_id=f"{application_id}:{installment_number}",
            details={
                "loan_id": application_id,
                "installment_number": installment_number,
                "amount": penalty_amount,
                "reason": reason,
            },
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )

        # Blockchain sync — penalty apply (background thread, no Celery needed)
        try:
            from loans.blockchain.sync import sync_penalty

            sync_penalty(
                application_id, installment_number, penalty_amount, "apply", reason
            )
        except Exception as e:
            logger.warning(
                f"Blockchain sync skipped for penalty apply {application_id}: {e}"
            )

        return success_response(
            data={
                "loan_id": application_id,
                "installment_number": installment_number,
                "penalty_status": "applied",
                "penalty_amount": round(penalty_amount, 2),
                "penalty_reason": reason,
                "penalty_applied_at": now.isoformat(),
                "penalty_applied_by": actor_id,
            },
            message="Penalty applied successfully",
            status_code=status.HTTP_201_CREATED,
        )


class WaivePenaltyView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Waive penalty for a repayment installment.

    POST /api/loans/officer/applications/<id>/penalties/waive/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        app = LoanApplication.find_by_id(application_id)
        if not app:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )
        has_scope, scope_result = self.check_application_scope(
            request,
            app,
            allow_unassigned=False,
        )
        if not has_scope:
            return scope_result

        if app.status != "disbursed":
            return error_response(
                message="Penalties can only be waived for disbursed loans",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        installment_number_raw = request.data.get("installment_number")
        reason = sanitize_text(request.data.get("reason", ""))

        if installment_number_raw in (None, ""):
            return error_response(
                message="installment_number is required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            installment_number = int(installment_number_raw)
        except (TypeError, ValueError):
            return error_response(
                message="installment_number must be an integer",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if installment_number < 1:
            return error_response(
                message="installment_number must be at least 1",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        schedule = RepaymentSchedule.find_by_loan(application_id)
        if not schedule:
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        installment = schedule.get_installment(installment_number)
        penalty_amount = (
            float(installment.get("penalty_amount", 0) or 0) if installment else 0
        )
        actor_id = self._actor_id(request.user)
        try:
            installment = schedule.waive_penalty(installment_number, reason, actor_id)
        except ValueError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_400_BAD_REQUEST
            )
        penalty_amount = float(installment.get("penalty_amount", 0) or 0)
        now = installment["penalty_waived_at"]
        if schedule.is_paid_off():
            app.mark_paid_off(
                schedule.paid_off_at,
                actor_id=actor_id,
                actor_type=self._actor_type(request.user),
                source="penalty_waiver",
            )

        record_loan_audit(
            action="penalty_waived",
            user_id=actor_id,
            user_type=self._actor_type(request.user),
            description=f"Penalty waived - PHP{penalty_amount:,.2f} for installment #{installment_number}",
            resource_type="penalty",
            resource_id=f"{application_id}:{installment_number}",
            details={
                "loan_id": application_id,
                "installment_number": installment_number,
                "amount": penalty_amount,
                "reason": reason,
            },
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )

        # Blockchain sync — penalty waive (background thread, no Celery needed)
        try:
            from loans.blockchain.sync import sync_penalty

            sync_penalty(
                application_id, installment_number, penalty_amount, "waive", reason
            )
        except Exception as e:
            logger.warning(
                f"Blockchain sync skipped for penalty waive {application_id}: {e}"
            )

        return success_response(
            data={
                "loan_id": application_id,
                "installment_number": installment_number,
                "penalty_status": "waived",
                "penalty_amount": round(penalty_amount, 2),
                "penalty_waived_at": now.isoformat(),
                "penalty_waived_by": actor_id,
                "penalty_waived_reason": reason,
            },
            message="Penalty waived successfully",
        )
