"""Officer loan-disbursement endpoint."""

import logging
from typing import ClassVar

from bson import ObjectId
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.validation_utils import sanitize_text
from analytics.models import AuditLog  # noqa: F401 - existing test patch target
from loans.models import LoanApplication
from loans.services.disbursement import (
    EXTERNAL_DISBURSEMENT_METHODS,
    MANUAL_DISBURSEMENT_METHODS,
    begin_disbursement,
    disbursement_idempotency_key,
    execute_manual_disbursement,
)
from loans.services.payment import PaymentServiceError
from loans.services.settlement_policy import (
    SettlementRailUnavailable,
    require_disbursement_method,
)
from loans.utils.serialization import disbursement_failure_code
from loans.views.officer.base import LoanOfficerRequiredMixin

logger = logging.getLogger("loans")


class DisburseView(LoanOfficerRequiredMixin, APIView):
    """Reserve or execute an approved loan disbursement."""

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]

    @staticmethod
    def _response_data(application, schedule=None, replayed=False):
        data = {
            "id": application.id,
            "status": application.status,
            "disbursement_status": application.disbursement_status,
            "disbursed_amount": application.disbursed_amount,
            "disbursement_method": application.disbursement_method,
            "disbursement_reference": application.disbursement_reference,
            "disbursement_requested_at": (
                application.disbursement_requested_at.isoformat()
                if application.disbursement_requested_at
                else None
            ),
            "disbursed_at": (
                application.disbursed_at.isoformat()
                if application.disbursed_at
                else None
            ),
            "disbursement_failure_code": disbursement_failure_code(application),
            "replayed": replayed,
            "eth_disbursement_tx_hash": application.eth_disbursement_tx_hash,
            "eth_disbursement_amount": application.eth_disbursement_amount,
            "eth_disbursement_rate": application.eth_disbursement_rate,
            "eth_disbursement_recipient": application.eth_disbursement_recipient,
        }
        if schedule:
            data["schedule"] = {
                "monthly_payment": schedule.monthly_payment,
                "total_amount": schedule.total_amount,
                "term_months": schedule.term_months,
            }
        return data

    def post(self, request, application_id):
        has_permission, user = self.check_officer_permission(request)
        if not has_permission:
            return user

        application = LoanApplication.find_by_id(application_id)
        if not application:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )
        has_scope, scope_result = self.check_application_scope(
            request, application, allow_unassigned=False
        )
        if not has_scope:
            return scope_result

        actor_id = self._actor_id(user)
        client_key = request.headers.get("Idempotency-Key") or request.data.get(
            "idempotency_key"
        )
        try:
            idempotency_key = disbursement_idempotency_key(actor_id, client_key)
        except PaymentServiceError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_400_BAD_REQUEST
            )

        amount_raw = request.data.get("amount", application.approved_amount)
        try:
            amount = float(amount_raw)
        except (TypeError, ValueError):
            return error_response(
                message="amount must be a valid number",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        stored_method = application.preferred_disbursement_method
        method = stored_method or (
            sanitize_text(request.data.get("method", "cash")).lower() or "cash"
        )
        if method not in MANUAL_DISBURSEMENT_METHODS | EXTERNAL_DISBURSEMENT_METHODS:
            return error_response(
                message="Invalid disbursement method",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            method = require_disbursement_method(method)
        except SettlementRailUnavailable as exc:
            return error_response(
                message=str(exc),
                code=exc.code,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        reference = sanitize_text(request.data.get("reference", ""))
        external_reference = sanitize_text(request.data.get("external_reference", ""))
        reference = (
            reference or external_reference or f"DSB-{idempotency_key[-16:].upper()}"
        )

        if method in EXTERNAL_DISBURSEMENT_METHODS:
            try:
                application, replayed = begin_disbursement(
                    application=application,
                    amount=amount,
                    method=method,
                    reference=reference,
                    actor_id=actor_id,
                    idempotency_key=idempotency_key,
                    actor_type=self._actor_type(user),
                )
            except ValueError as exc:
                return error_response(
                    message=str(exc), status_code=status.HTTP_400_BAD_REQUEST
                )

            if application.disbursement_status == "executed":
                return success_response(
                    data=self._response_data(application, replayed=True),
                    message="Loan disbursement already completed",
                )

            if method == "wallet":
                try:
                    from loans.tasks import execute_wallet_disbursement_task

                    execute_wallet_disbursement_task.delay(application.id)
                except Exception as exc:  # reconciliation will enqueue it later
                    logger.exception(
                        "Could not enqueue wallet disbursement for loan %s: %s",
                        application.id,
                        exc,
                    )

            return success_response(
                data=self._response_data(application, replayed=replayed),
                message=(
                    "Disbursement is already pending external confirmation"
                    if replayed
                    else "Disbursement accepted and pending external confirmation"
                ),
                status_code=status.HTTP_202_ACCEPTED,
            )

        try:
            application, schedule, replayed = execute_manual_disbursement(
                application=application,
                amount=amount,
                method=method,
                reference=reference,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                actor_type=self._actor_type(user),
            )
        except ValueError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_400_BAD_REQUEST
            )
        except Exception:
            logger.exception("Manual disbursement failed for loan %s", application.id)
            return error_response(
                message="Loan disbursement could not be completed",
                code="DISBURSEMENT_EXECUTION_FAILED",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not replayed:
            self._send_disbursement_email(application, amount, method, reference)
            try:
                from loans.blockchain.sync import sync_disbursement

                sync_disbursement(application.id, include_schedule=True)
            except Exception as exc:  # durable reconciliation remains available
                logger.warning("Could not enqueue disbursement sync: %s", exc)

        return success_response(
            data=self._response_data(application, schedule, replayed),
            message=(
                "Loan disbursement already completed"
                if replayed
                else "Loan disbursed successfully"
            ),
        )

    @staticmethod
    def _send_disbursement_email(application, amount, method, reference):
        try:
            from accounts.models import Customer
            from notifications.services import get_email_sender

            customer = None
            if application.customer_id and ObjectId.is_valid(application.customer_id):
                customer = Customer.find_one({"_id": ObjectId(application.customer_id)})
            if customer and customer.email:
                get_email_sender().send_loan_disbursed(
                    customer_email=customer.email,
                    customer_name=f"{customer.first_name} {customer.last_name}",
                    loan_id=application.id,
                    amount=amount,
                    method=method,
                    reference=reference,
                    customer_id=application.customer_id,
                )
        except Exception as exc:  # noqa: BLE001 - notification is best effort
            logger.warning("Failed to send disbursement email: %s", exc)
