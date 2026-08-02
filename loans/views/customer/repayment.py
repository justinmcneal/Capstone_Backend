import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.validation_utils import sanitize_text
from analytics.models import AuditLog  # noqa: F401 - existing test patch target
from loans.models import LoanApplication
from loans.services.audit import record_loan_audit
from loans.services.payment_queries import payment_history_page

logger = logging.getLogger("loans")


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

        amount_raw = request.data.get("amount")
        installment_number_raw = request.data.get("installment_number")
        payment_method = request.data.get("payment_method", "bank_transfer")
        reference = sanitize_text(request.data.get("reference", ""))
        notes = sanitize_text(request.data.get("notes", ""))

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

        try:
            amount = float(amount_raw)
        except (TypeError, ValueError):
            return error_response(
                message="amount must be a valid number",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if amount <= 0:
            return error_response(
                message="amount must be greater than 0",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

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

        valid_methods = {"gcash", "bank_transfer"}
        if payment_method not in valid_methods:
            return error_response(
                message="Invalid payment_method",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if not reference:
            return error_response(
                message="A provider or bank reference is required for verification",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        idempotency_key = request.headers.get("Idempotency-Key") or request.data.get(
            "idempotency_key"
        )

        from loans.models import RepaymentSchedule

        schedule = RepaymentSchedule.find_by_loan(application_id)
        if not schedule:
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if str(schedule.customer_id) != str(customer_id):
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        installment = schedule.get_installment(installment_number)
        if not installment:
            return error_response(
                message=f"Installment #{installment_number} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if installment.get("status") == "paid":
            return error_response(
                message=f"Installment #{installment_number} is already fully paid",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        remaining = installment["total_amount"] - installment.get("paid_amount", 0)

        # Include penalty in remaining amount if applied
        if installment.get("penalty_status") == "applied":
            remaining += installment.get("penalty_amount", 0)

        if amount - remaining > 0.01:
            return error_response(
                message=f"Amount exceeds remaining balance of ₱{remaining:.2f}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        from loans.services.payment import (
            PaymentConflictError,
            PaymentServiceError,
            create_pending_submission,
            scoped_idempotency_key,
        )

        try:
            payment, replayed = create_pending_submission(
                schedule=schedule,
                installment_number=installment_number,
                amount=amount,
                payment_method=payment_method,
                reference=reference,
                notes=notes,
                customer_id=customer_id,
                idempotency_key=scoped_idempotency_key(
                    "customer", customer_id, idempotency_key
                ),
            )
        except PaymentConflictError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_409_CONFLICT
            )
        except PaymentServiceError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_400_BAD_REQUEST
            )

        if not replayed:
            record_loan_audit(
                action="customer_payment_submitted",
                user_id=str(customer_id),
                user_type="customer",
                description=f"Customer payment submitted for verification - ₱{amount:,.2f} for installment #{installment_number}",
                resource_type="payment",
                resource_id=payment.id,
                details={
                    "loan_id": application_id,
                    "amount": amount,
                    "installment": installment_number,
                    "method": payment_method,
                    "payment_status": payment.payment_status,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

        logger.info(
            "Customer payment submitted: loan=%s installment=%s amount=%s customer=%s",
            application_id,
            installment_number,
            amount,
            customer_id,
        )

        return success_response(
            data={
                "payment_id": payment.id,
                "loan_id": application_id,
                "installment_number": installment_number,
                "amount": amount,
                "payment_method": payment_method,
                "payment_status": payment.payment_status,
                "reference": reference,
                "recorded_at": (
                    payment.recorded_at.isoformat() if payment.recorded_at else None
                ),
                "installment_status": installment["status"],
                "remaining_balance": schedule.get_remaining_balance(),
                "balance_applied": False,
                "replayed": replayed,
            },
            message="Payment submitted and pending verification",
            status_code=status.HTTP_202_ACCEPTED,
        )
