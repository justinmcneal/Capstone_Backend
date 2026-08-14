"""Officer quote and verified cash/check early-payoff endpoint."""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.validation_utils import sanitize_text
from analytics.models import AuditLog  # noqa: F401 - existing test patch target
from loans.models import LoanApplication, RepaymentSchedule
from loans.services.payment import (
    PaymentConflictError,
    PaymentServiceError,
    post_verified_early_payoff,
    scoped_idempotency_key,
)
from loans.utils import generate_payment_reference
from loans.utils.money import from_centavos, to_centavos
from loans.views.officer.base import LoanOfficerRequiredMixin


class EarlyPayoffView(LoanOfficerRequiredMixin, APIView):
    """Quote or post an exact verified payoff for an assigned loan."""

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def _load_scoped(self, request, application_id):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return None, None, result
        application = LoanApplication.find_by_id(application_id)
        if not application:
            return (
                None,
                None,
                error_response(
                    message="Application not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                ),
            )
        has_scope, scope_result = self.check_application_scope(
            request, application, allow_unassigned=False
        )
        if not has_scope:
            return None, None, scope_result

        schedule = RepaymentSchedule.find_by_loan(application_id)
        # Existing schedules are authoritative for legacy loans whose
        # application status was not advanced when the schedule was created.
        if not schedule and application.status not in {"disbursed", "completed"}:
            return (
                None,
                None,
                error_response(
                    message="Early payoff is only available for disbursed loans",
                    status_code=status.HTTP_400_BAD_REQUEST,
                ),
            )
        if not schedule:
            return (
                None,
                None,
                error_response(
                    message="Repayment schedule not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                ),
            )
        return application, schedule, None

    def get(self, request, application_id):
        application, schedule, error = self._load_scoped(request, application_id)
        if error:
            return error
        payoff_centavos = schedule.get_remaining_balance_centavos()
        return success_response(
            data={
                "loan_id": application.id,
                "payoff_amount": from_centavos(payoff_centavos),
                "payoff_amount_centavos": payoff_centavos,
                "currency": "PHP",
                "already_paid_off": payoff_centavos == 0,
            },
            message="Early payoff quote retrieved",
        )

    def post(self, request, application_id):
        application, schedule, error = self._load_scoped(request, application_id)
        if error:
            return error

        method = sanitize_text(request.data.get("payment_method", "cash")).lower()
        if method not in {"cash", "check"}:
            return error_response(
                message="Verified early payoff currently accepts cash or check",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            amount_centavos = to_centavos(request.data.get("amount"), "amount")
        except ValueError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_400_BAD_REQUEST
            )
        if amount_centavos <= 0:
            return error_response(
                message="amount must be greater than 0",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        actor_id = self._actor_id(request.user)
        try:
            key = scoped_idempotency_key(
                "officer-payoff",
                actor_id,
                request.headers.get("Idempotency-Key")
                or request.data.get("idempotency_key"),
            )
            payment, allocations, replayed = post_verified_early_payoff(
                schedule=schedule,
                amount=from_centavos(amount_centavos),
                payment_method=method,
                reference=sanitize_text(request.data.get("reference", ""))
                or generate_payment_reference(),
                notes=sanitize_text(request.data.get("notes", "")),
                recorded_by=actor_id,
                recorded_by_type=self._actor_type(request.user),
                idempotency_key=key,
                verification_source="officer_manual_payoff",
            )
        except PaymentConflictError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_409_CONFLICT
            )
        except RuntimeError:
            return error_response(
                message="The loan changed before payoff could be posted. Refresh the quote and retry.",
                status_code=status.HTTP_409_CONFLICT,
            )
        except (PaymentServiceError, ValueError) as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_400_BAD_REQUEST
            )

        completed = LoanApplication.find_by_id(application.id)
        return success_response(
            data={
                "loan_id": application.id,
                "payment_id": payment.id,
                "amount": payment.amount,
                "allocations": allocations,
                "status": completed.status if completed else "completed",
                "repayment_status": (
                    completed.repayment_status if completed else "paid_off"
                ),
                "remaining_balance": 0,
                "replayed": replayed,
            },
            message="Loan payoff already posted" if replayed else "Loan paid off",
        )
