"""Officer operations for inspecting and recovering wallet disbursements."""

import logging
from typing import ClassVar

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.validation_utils import sanitize_text
from analytics.models import AuditLog
from loans.models import LoanApplication
from loans.tasks import execute_wallet_disbursement_task
from loans.views.officer.base import LoanOfficerRequiredMixin

logger = logging.getLogger("loans")


class WalletDisbursementRecoveryView(LoanOfficerRequiredMixin, APIView):
    """Inspect, retry, reconcile, or safely cancel a wallet transfer."""

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]

    @staticmethod
    def _data(application):
        return {
            "id": application.id,
            "status": application.status,
            "disbursement_status": application.disbursement_status,
            "disbursement_error": application.disbursement_error,
            "tx_hash": application.eth_disbursement_tx_hash,
            "tx_status": application.eth_disbursement_tx_status,
            "nonce": application.eth_disbursement_nonce,
            "prepared_at": application.eth_disbursement_prepared_at,
            "broadcast_at": application.eth_disbursement_broadcast_at,
            "last_checked_at": application.eth_disbursement_last_checked_at,
            "block_number": application.eth_disbursement_block_number,
            "rebroadcast_count": application.eth_disbursement_rebroadcast_count,
            "recipient": application.eth_disbursement_recipient,
            "amount_wei": application.eth_disbursement_amount_wei,
            "recovery_history": application.eth_disbursement_recovery_history,
        }

    def _application(self, request, application_id):
        allowed, actor = self.check_officer_permission(request)
        if not allowed:
            return None, actor, None
        application = LoanApplication.find_by_id(application_id)
        if not application:
            return None, error_response(
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND,
            ), None
        in_scope, response = self.check_application_scope(
            request, application, allow_unassigned=False
        )
        if not in_scope:
            return None, response, None
        if application.disbursement_method != "wallet":
            return None, error_response(
                message="Application is not a wallet disbursement",
                status_code=status.HTTP_400_BAD_REQUEST,
            ), None
        return application, None, actor

    def get(self, request, application_id):
        application, response, _actor = self._application(request, application_id)
        if response:
            return response
        return success_response(data=self._data(application))

    def post(self, request, application_id):
        application, response, actor = self._application(request, application_id)
        if response:
            return response
        action = sanitize_text(request.data.get("action", "reconcile")).lower()
        actor_id = self._actor_id(actor)

        if action in {"retry", "reconcile"}:
            if application.disbursement_status in {"failed", "cancelled"}:
                if application.eth_disbursement_tx_status in {
                    "pending",
                    "broadcast",
                }:
                    return error_response(
                        message="Cannot create a new transfer while the existing transaction may settle",
                        status_code=status.HTTP_409_CONFLICT,
                    )
                if application.eth_disbursement_tx_status in {
                    "reverted",
                    "failed",
                    "dropped",
                }:
                    LoanApplication.clear_eth_disbursement_fields(
                        application.id,
                        "tx_hash",
                        "raw_transaction",
                        "nonce",
                        "prepared_at",
                        "broadcast_at",
                        "block_number",
                        "last_checked_at",
                        "tx_status",
                    )
                application = LoanApplication.reopen_wallet_disbursement(
                    application.id, actor_id
                )
            if not application or application.disbursement_status != "pending":
                return error_response(
                    message="Wallet disbursement is not recoverable",
                    status_code=status.HTTP_409_CONFLICT,
                )
            execute_wallet_disbursement_task.apply_async(
                args=[application.id], retry=False
            )
            self._audit(application, actor_id, action, request)
            return success_response(
                data=self._data(LoanApplication.find_by_id(application.id)),
                message="Wallet reconciliation queued",
                status_code=status.HTTP_202_ACCEPTED,
            )

        if action == "cancel":
            reason = sanitize_text(request.data.get("reason", ""))
            cancelled = LoanApplication.cancel_wallet_disbursement(
                application.id, actor_id, reason
            )
            if not cancelled:
                return error_response(
                    message="A prepared, broadcast, or active wallet transfer cannot be cancelled",
                    status_code=status.HTTP_409_CONFLICT,
                )
            self._audit(cancelled, actor_id, action, request)
            return success_response(
                data=self._data(cancelled), message="Wallet disbursement cancelled"
            )

        return error_response(
            message="action must be reconcile, retry, or cancel",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    @staticmethod
    def _audit(application, actor_id, action, request):
        try:
            AuditLog.log_action(
                action=f"wallet_disbursement_{action}",
                user_id=actor_id,
                user_type="loan_officer",
                description=f"Wallet disbursement {action} requested",
                resource_type="loan",
                resource_id=application.id,
                details={
                    "tx_hash": application.eth_disbursement_tx_hash,
                    "tx_status": application.eth_disbursement_tx_status,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )
        except Exception as exc:  # audit remains best effort in the existing domain
            logger.warning("Failed to audit wallet recovery action: %s", exc)
