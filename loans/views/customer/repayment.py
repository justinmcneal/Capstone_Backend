from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from loans.models import LoanApplication
from loans.services.payment_queries import payment_history_page
from loans.services.settlement_policy import (
    SettlementRailUnavailable,
    require_customer_provider_payment,
)
from loans.views.customer.base import CustomerRoleRequiredMixin


class RepaymentScheduleView(CustomerRoleRequiredMixin, APIView):
    """
    Get repayment schedule for a loan application.

    GET /api/loans/applications/<id>/schedule/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        # Verify application belongs to customer
        app = LoanApplication.find_by_id(application_id)

        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )

        # Only disbursed loans have schedules
        if app.status not in {"disbursed", "completed", "written_off"}:
            return error_response(
                message="Repayment schedule is only available for disbursed loans",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        from loans.models import RepaymentSchedule

        schedule = RepaymentSchedule.find_by_loan(application_id)

        if not schedule:
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Format installments
        installments = []
        for inst in schedule.installments:
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
                    "due_date": (
                        inst["due_date"].isoformat() if inst.get("due_date") else None
                    ),
                    "principal": inst["principal"],
                    "interest": inst["interest"],
                    "total_amount": actual_total_amount,  # Include penalty in total
                    "base_amount": base_total_amount,  # Original amount without penalty
                    "status": inst["status"],
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


class PaymentHistoryView(CustomerRoleRequiredMixin, APIView):
    """
    Get or record payments for a loan application.

    GET /api/loans/applications/<id>/payments/
    POST /api/loans/applications/<id>/payments/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        # Verify application belongs to customer
        app = LoanApplication.find_by_id(application_id)

        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )

        try:
            page = int(request.query_params.get("page", 1))
            page_size = min(int(request.query_params.get("page_size", 50)), 100)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid payment-history pagination",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if page < 1 or page_size < 1:
            return error_response(
                message="Payment-history page and page_size must be positive",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        history = payment_history_page(application_id, page, page_size)
        payments = history["payments"]

        payments_data = [
            {
                "id": p.id,
                "amount": p.amount,
                "installment_number": p.installment_number,
                "payment_method": p.payment_method,
                "payment_status": p.payment_status,
                "reference": p.reference,
                "recorded_at": p.recorded_at.isoformat() if p.recorded_at else None,
            }
            for p in payments
        ]

        return success_response(
            data={
                "payments": payments_data,
                "total_paid": history["total_paid"],
                "count": history["total"],
                "page": history["page"],
                "page_size": history["page_size"],
                "total_pages": history["total_pages"],
            },
            message="Payment history retrieved",
        )

    def post(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        app = LoanApplication.find_by_id(application_id)
        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )

        if app.status != "disbursed":
            return error_response(
                message="Payments can only be recorded for disbursed loans",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        payment_method = request.data.get("payment_method", "bank_transfer")

        if payment_method in {"cash", "check"}:
            return error_response(
                message="Cash and check payments must be paid at the office and recorded by a loan officer",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if payment_method == "wallet":
            return error_response(
                message="Wallet payments must use the verified wallet-payment endpoint",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            require_customer_provider_payment(payment_method)
        except SettlementRailUnavailable as exc:
            return error_response(
                message=str(exc),
                code=exc.code,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ValueError as exc:
            return error_response(
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
