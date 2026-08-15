import logging

from bson import ObjectId
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from analytics.models import AuditLog  # noqa: F401 - existing test patch target
from loans.models import LoanApplication
from loans.services.audit import record_loan_audit
from loans.utils.serialization import (
    serialize_customer_blockchain_transaction,
    serialize_public_blockchain_audit_entry,
    serialize_public_blockchain_hashes,
)

logger = logging.getLogger("loans")


from loans.views.customer.base import CustomerRoleRequiredMixin


class CustomerBlockchainView(CustomerRoleRequiredMixin, APIView):
    """
    Customer: Get blockchain transaction status for own loan application.

    GET /api/loans/applications/<id>/blockchain/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        if not ObjectId.is_valid(application_id):
            return error_response(
                message="Invalid application ID",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        app = LoanApplication.find_by_id(application_id)
        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )

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
                    serialize_customer_blockchain_transaction(tx) for tx in txs
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


class WalletPaymentView(CustomerRoleRequiredMixin, APIView):
    """
    Customer: Verify and record an ETH wallet payment for a loan installment.

    The customer pays via MetaMask (WalletConnect), then submits the tx_hash here.
    Backend verifies the transaction on-chain before recording the payment.

    POST /api/loans/applications/<id>/wallet-payment/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        tx_hash = request.data.get("tx_hash", "").strip()
        installment_number_raw = request.data.get("installment_number")

        if not tx_hash:
            return error_response(
                message="tx_hash is required", status_code=status.HTTP_400_BAD_REQUEST
            )
        if not tx_hash.startswith("0x") or len(tx_hash) != 66:
            return error_response(
                message="Invalid transaction hash format",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
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

        app = LoanApplication.find_by_id(application_id)
        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )
        if app.status != "disbursed":
            return error_response(
                message="Loan is not in disbursed status",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Find schedule and validate installment
        from loans.models import LoanPayment, RepaymentSchedule

        schedule = RepaymentSchedule.find_by_loan(application_id)
        if not schedule:
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
            existing = LoanPayment.find_one({"eth_tx_hash": tx_hash})
            if not existing:
                return error_response(
                    message=f"Installment #{installment_number} is already fully paid",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        # A verified replay must not be re-priced using a newer exchange rate.
        existing = LoanPayment.find_one({"eth_tx_hash": tx_hash})
        if existing:
            same_payment = (
                existing.payment_status == "posted"
                and str(existing.loan_id) == str(application_id)
                and str(existing.customer_id) == str(customer_id)
                and existing.installment_number == installment_number
            )
            if not same_payment:
                return error_response(
                    message="This transaction has already been recorded for another payment",
                    status_code=status.HTTP_409_CONFLICT,
                )
            return success_response(
                data={
                    "status": "verified",
                    "payment_id": existing.id,
                    "installment_number": installment_number,
                    "installment_status": installment["status"],
                    "amount_php": existing.amount,
                    "amount_eth": existing.eth_amount,
                    "eth_rate": existing.eth_rate,
                    "tx_hash": existing.eth_tx_hash,
                    "block_number": existing.eth_block_number,
                    "remaining_balance": schedule.get_remaining_balance(),
                    "blockchain_sync_status": existing.blockchain_sync_status,
                    "blockchain_sync_message": "Payment was already recorded.",
                    "replayed": True,
                },
                message="Wallet payment already recorded",
            )

        # Verify the transaction on-chain
        try:
            from loans.blockchain.client import get_account, get_web3
            from loans.blockchain.services.eth_price_service import get_eth_php_rate

            w3 = get_web3()
            tx = w3.eth.get_transaction(tx_hash)
            receipt = w3.eth.get_transaction_receipt(tx_hash)

            if receipt["status"] != 1:
                return error_response(
                    message="Transaction failed on-chain",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            minimum_confirmations = int(
                getattr(settings, "LOANS_WALLET_MIN_CONFIRMATIONS", 3)
            )
            latest_block = int(w3.eth.block_number)
            confirmations = latest_block - int(receipt["blockNumber"]) + 1
            if confirmations < minimum_confirmations:
                return error_response(
                    message=(
                        "Transaction does not have enough confirmations "
                        f"({confirmations}/{minimum_confirmations})"
                    ),
                    status_code=status.HTTP_409_CONFLICT,
                )

            # Verify recipient is the system wallet
            system_address = get_account().address.lower()
            if tx["to"].lower() != system_address:
                return error_response(
                    message="Transaction recipient does not match system wallet",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Verify sender is the customer's wallet
            from profiles.models.profile_models import CustomerProfile

            profile = CustomerProfile.find_by_customer(customer_id)
            if not profile or not profile.wallet_address:
                return error_response(
                    message="Customer wallet address not configured",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if tx["from"].lower() != profile.wallet_address.lower():
                return error_response(
                    message="Transaction sender does not match your wallet address",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Verify amount (convert ETH received to PHP and compare)
            eth_received = float(w3.from_wei(tx["value"], "ether"))
            rate_info = get_eth_php_rate()
            php_received = eth_received * rate_info["rate"]
            expected_php = installment["total_amount"] - installment.get(
                "paid_amount", 0
            )

            # Include penalty in expected amount if applied
            if installment.get("penalty_status") == "applied":
                expected_php += installment.get("penalty_amount", 0)

            # Minimum payment threshold to prevent dust payments
            MIN_PAYMENT_PHP = 100.0
            # Allow small fluctuations in exchange rate: ±2% tolerance
            tolerance = 0.02
            lower_bound = expected_php * (1 - tolerance)
            upper_bound = expected_php * (1 + tolerance)

            if php_received < MIN_PAYMENT_PHP:
                return error_response(
                    message=f"Payment too small. Minimum: ₱{MIN_PAYMENT_PHP:.2f} "
                    f"(received {eth_received:.6f} ETH ≈ ₱{php_received:.2f})",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Reject payments that are significantly (more than tolerance) below expected amount
            if php_received < lower_bound:
                return error_response(
                    message=(
                        f"Payment is below the allowed tolerance of {tolerance * 100:.0f}% for this installment. "
                        f"Expected ~₱{expected_php:.2f}, received ₱{php_received:.2f}"
                    ),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if php_received > upper_bound:
                return error_response(
                    message=(
                        f"Payment exceeds the allowed tolerance of {tolerance * 100:.0f}%. "
                        f"Expected ~₱{expected_php:.2f}, received ₱{php_received:.2f}"
                    ),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        except Exception:
            logger.exception("Wallet payment verification failed")
            return error_response(
                message="Blockchain payment verification is temporarily unavailable",
                code="BLOCKCHAIN_VERIFICATION_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Both tolerance bounds were validated above. Apply exactly the remaining
        # PHP amount so exchange-rate noise cannot create dust or overpayment.
        payment_amount = expected_php
        from loans.services.payment import (
            PaymentConflictError,
            PaymentServiceError,
            post_verified_payment,
        )

        try:
            payment, updated_installment, replayed = post_verified_payment(
                schedule=schedule,
                installment_number=installment_number,
                amount=payment_amount,
                payment_method="wallet",
                reference=tx_hash,
                notes=f"ETH wallet payment: {eth_received:.6f} ETH @ {rate_info['rate']:.2f} PHP/ETH",
                recorded_by=customer_id,
                recorded_by_type="customer",
                idempotency_key=f"wallet:{tx_hash.lower()}",
                verification_source="ethereum_receipt",
                extra_fields={
                    "blockchain_sync_status": "pending",
                    "eth_tx_hash": tx_hash,
                    "eth_amount": str(eth_received),
                    "eth_rate": rate_info["rate"],
                    "eth_rate_source": rate_info["source"],
                    "eth_sender": profile.wallet_address,
                    "eth_block_number": receipt["blockNumber"],
                },
            )
        except PaymentConflictError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_409_CONFLICT
            )
        except PaymentServiceError as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_400_BAD_REQUEST
            )
        except (ValueError, RuntimeError) as exc:
            return error_response(
                message=str(exc), status_code=status.HTTP_409_CONFLICT
            )

        logger.info(
            "Wallet payment verified: loan=%s installment=%d amount=%.6f ETH tx=%s",
            application_id,
            installment_number,
            eth_received,
            tx_hash[:18],
        )

        # AuditLog writes go through the observable loan-domain wrapper.
        if not replayed:
            record_loan_audit(
                action="wallet_payment_verified",
                user_id=customer_id,
                user_type="customer",
                description=f"Wallet payment verified - {eth_received:.6f} ETH for installment #{installment_number}",
                resource_type="payment",
                resource_id=payment.id,
                details={
                    "loan_id": application_id,
                    "installment_number": installment_number,
                    "eth_amount": str(eth_received),
                    "php_amount": payment_amount,
                    "eth_rate": rate_info["rate"],
                    "tx_hash": tx_hash,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

        # Blockchain audit trail sync
        if not replayed:
            try:
                from loans.blockchain.sync import sync_payment

                sync_payment(application_id, payment.id)
            except Exception as e:
                logger.warning(
                    f"Blockchain sync skipped for wallet payment {payment.id}: {e}"
                )

        return success_response(
            data={
                "status": "verified",
                "payment_id": payment.id,
                "installment_number": installment_number,
                "installment_status": updated_installment["status"],
                "amount_php": payment_amount,
                "amount_eth": str(eth_received),
                "eth_rate": rate_info["rate"],
                "tx_hash": tx_hash,
                "block_number": receipt["blockNumber"],
                "remaining_balance": schedule.get_remaining_balance(),
                "blockchain_sync_status": "pending",
                "blockchain_sync_message": "Payment recorded. Blockchain audit trail sync in progress...",
                "replayed": replayed,
            },
            message=(
                "Wallet payment already recorded"
                if replayed
                else "Wallet payment verified and recorded"
            ),
            status_code=(status.HTTP_200_OK if replayed else status.HTTP_201_CREATED),
        )


class SystemWalletInfoView(CustomerRoleRequiredMixin, APIView):
    """
    Customer: Get system wallet address and current ETH/PHP rate.

    Mobile app uses this to construct the WalletConnect ETH transfer request.

    GET /api/loans/system-wallet/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        from loans.blockchain.client import get_account, get_web3

        if not getattr(settings, "BLOCKCHAIN_ENABLED", False):
            return error_response(
                message="Blockchain is not enabled",
                code="BLOCKCHAIN_DISABLED",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            account = get_account()
            get_web3()
        except Exception:
            logger.exception("System wallet blockchain connection failed")
            return error_response(
                message="Blockchain connection is temporarily unavailable",
                code="BLOCKCHAIN_CONNECTION_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Fetch live exchange rate
        from loans.blockchain.services.eth_price_service import (
            ExchangeRateUnavailableError,
            get_eth_php_rate,
        )

        try:
            rate_info = get_eth_php_rate()
        except ExchangeRateUnavailableError:
            return error_response(
                message="ETH/PHP exchange rate is currently unavailable. "
                "Wallet payments are temporarily disabled.",
                code="EXCHANGE_RATE_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        from datetime import datetime, timezone

        return success_response(
            data={
                "wallet_address": account.address,
                "chain_id": settings.BLOCKCHAIN_CHAIN_ID,
                "eth_php_rate": rate_info["rate"],
                "rate_source": rate_info["source"],
                "rate_basis": "verification_time",
                "rate_max_age_seconds": 300,
                "rate_cached_at": (
                    datetime.fromtimestamp(
                        rate_info["fetched_at"], tz=timezone.utc
                    ).isoformat()
                    if rate_info["fetched_at"]
                    else None
                ),
                # Also include rate_updated_at for backwards compatibility
                "rate_updated_at": (
                    datetime.fromtimestamp(
                        rate_info["fetched_at"], tz=timezone.utc
                    ).isoformat()
                    if rate_info["fetched_at"]
                    else None
                ),
            },
            message="System wallet info retrieved",
        )
