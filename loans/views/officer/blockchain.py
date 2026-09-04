import logging

from bson import ObjectId
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from loans.models import LoanApplication
from loans.utils.serialization import (
    serialize_officer_blockchain_transaction,
    serialize_public_blockchain_audit_entry,
    serialize_public_blockchain_hashes,
)
from loans.views.officer.base import LoanOfficerRequiredMixin

logger = logging.getLogger("loans")


class BlockchainStatusView(LoanOfficerRequiredMixin, APIView):
    """
    Get blockchain transaction status for a loan application.

    GET /api/loans/applications/<id>/blockchain/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        if not ObjectId.is_valid(application_id):
            return error_response(
                message="Invalid application ID",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        app = LoanApplication.find_by_id(application_id)
        if not app:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )
        has_scope, scope_result = self.check_application_scope(
            request, app, allow_unassigned=False
        )
        if not has_scope:
            return scope_result

        from django.conf import settings

        explorer_url = getattr(settings, "BLOCKCHAIN_EXPLORER_URL", "")
        data = {
            "application_id": app.id,
            "blockchain_enabled": getattr(settings, "BLOCKCHAIN_ENABLED", False),
            "explorer_url": f"{explorer_url}/tx" if explorer_url else "",
            "tx_hashes": serialize_public_blockchain_hashes(
                getattr(app, "blockchain_tx_hashes", {})
            ),
            "transactions": [],
            "transaction_history_available": False,
            "audit_trail": [],
            "audit_trail_available": False,
        }

        if getattr(settings, "BLOCKCHAIN_ENABLED", False):
            try:
                from loans.blockchain.models import BlockchainTransaction

                txs = BlockchainTransaction.find_by_loan(application_id)
                data["transactions"] = [
                    serialize_officer_blockchain_transaction(tx) for tx in txs
                ]
                data["transaction_history_available"] = True
            except Exception as e:
                logger.warning(f"Failed to fetch blockchain transactions: {e}")

            try:
                from loans.blockchain.services.audit_service import get_audit_trail

                trail = get_audit_trail(application_id)
                data["audit_trail"] = [
                    serialize_public_blockchain_audit_entry(entry) for entry in trail
                ]
                data["audit_trail_available"] = True
            except Exception as e:
                logger.warning(f"Failed to fetch on-chain audit trail: {e}")

        return success_response(data=data, message="Blockchain status retrieved")


class ExchangeRateView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Get current ETH/PHP exchange rate for wallet disbursements.

    GET /api/loans/officer/exchange-rate/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        from django.conf import settings

        if not getattr(settings, "BLOCKCHAIN_ENABLED", False):
            return error_response(
                message="Blockchain is not enabled",
                code="BLOCKCHAIN_DISABLED",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        from loans.blockchain.services.eth_price_service import (
            ExchangeRateUnavailableError,
            get_eth_php_rate,
        )

        try:
            rate_info = get_eth_php_rate()
        except ExchangeRateUnavailableError:
            return error_response(
                message="ETH/PHP exchange rate is currently unavailable",
                code="EXCHANGE_RATE_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        from datetime import datetime, timezone

        return success_response(
            data={
                "eth_php_rate": rate_info["rate"],
                "rate_source": rate_info["source"],
                "rate_cached_at": (
                    datetime.fromtimestamp(
                        rate_info["fetched_at"], tz=timezone.utc
                    ).isoformat()
                    if rate_info["fetched_at"]
                    else None
                ),
            },
            message="Exchange rate retrieved",
        )
