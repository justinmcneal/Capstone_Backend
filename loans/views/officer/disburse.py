from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text
from rest_framework import status
from loans.models import LoanApplication, LoanProduct, RepaymentSchedule
from loans.views.officer.base import LoanOfficerRequiredMixin
from analytics.models import AuditLog
import logging

logger = logging.getLogger("loans")


class DisburseView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Mark approved loan as disbursed.

    POST /api/loans/officer/applications/<id>/disburse/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, user = self.check_officer_permission(request)
        if not has_permission:
            return user  # This is the error response

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

        # Can only disburse approved applications
        if app.status != "approved":
            return error_response(
                message=f"Cannot disburse application with status: {app.status}. Must be 'approved'.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Get disbursement data
        amount_raw = request.data.get("amount", app.approved_amount)
        # Prefer the borrower's pre-set method; officer cannot override
        stored_method = getattr(app, "preferred_disbursement_method", None)
        if stored_method:
            method = stored_method
        else:
            # Fallback for legacy apps where borrower didn't set a preference
            method = (
                sanitize_text(request.data.get("method", "bank_transfer")).lower()
                or "bank_transfer"
            )
        reference = sanitize_text(request.data.get("reference", ""))
        external_reference = sanitize_text(
            request.data.get("external_reference", "")
        )  # Bank/check number
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
        allowed_methods = {"cash", "gcash", "bank_transfer", "check", "wallet"}
        if method not in allowed_methods:
            return error_response(
                message="Invalid disbursement method",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if not reference and external_reference:
            reference = external_reference

        # Auto-generate system reference if not provided
        if not reference:
            from loans.utils import generate_disbursement_reference

            reference = generate_disbursement_reference()

        try:
            app.disburse(
                amount=amount,
                method=method,
                reference=reference,
                processed_by=self._actor_id(user),
            )

            logger.info(f"Loan disbursed: {app.id} by {self._actor_id(user)}")

            # Audit log for disbursement
            AuditLog.log_action(
                action="loan_disbursed",
                user_id=self._actor_id(user),
                user_type="loan_officer",
                description=f"Loan disbursed - PHP{amount:,.2f} via {method}",
                resource_type="loan",
                resource_id=app.id,
                details={
                    "amount": amount,
                    "method": method,
                    "reference": reference,
                    "customer_id": app.customer_id,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            # Generate repayment schedule
            schedule = None
            try:
                product = LoanProduct.find_by_id(app.product_id)
                if product:
                    schedule = RepaymentSchedule.generate_for_loan(app, product)
                    logger.info(f"Repayment schedule generated for loan {app.id}")
            except Exception as e:
                logger.warning(f"Failed to generate repayment schedule: {e}")

            # Blockchain sync — disbursement + schedule (background thread, no Celery needed)
            try:
                from loans.blockchain.sync import sync_disbursement

                sync_disbursement(app.id, include_schedule=bool(schedule))
                # Reload app to pick up ETH disbursement fields written by sync
                app = LoanApplication.find_by_id(app.id)
            except Exception as e:
                logger.warning(
                    f"Blockchain sync skipped for disbursement {app.id}: {e}"
                )

            # Send disbursement email
            from accounts.models import Customer

            customer = None
            if app.customer_id:
                try:
                    customer = Customer.find_one({"_id": ObjectId(app.customer_id)})
                except Exception:
                    pass
            if customer and customer.email:
                try:
                    from notifications.services import get_email_sender

                    sender = get_email_sender()
                    sender.send_loan_disbursed(
                        customer_email=customer.email,
                        customer_name=f"{customer.first_name} {customer.last_name}",
                        loan_id=app.id,
                        amount=amount,
                        method=method,
                        reference=reference,
                        customer_id=app.customer_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send disbursement email: {e}")

            response_data = {
                "id": app.id,
                "status": app.status,
                "disbursed_amount": app.disbursed_amount,
                "disbursement_method": app.disbursement_method,
                "disbursement_reference": app.disbursement_reference,
                "disbursed_at": (
                    app.disbursed_at.isoformat() if app.disbursed_at else None
                ),
                "eth_disbursement_tx_hash": getattr(
                    app, "eth_disbursement_tx_hash", None
                ),
                "eth_disbursement_amount": getattr(
                    app, "eth_disbursement_amount", None
                ),
                "eth_disbursement_rate": getattr(app, "eth_disbursement_rate", None),
                "eth_disbursement_recipient": getattr(
                    app, "eth_disbursement_recipient", None
                ),
            }

            if schedule:
                response_data["schedule"] = {
                    "monthly_payment": schedule.monthly_payment,
                    "total_amount": schedule.total_amount,
                    "term_months": schedule.term_months,
                }

            return success_response(
                data=response_data, message="Loan disbursed successfully"
            )

        except ValueError as e:
            return error_response(
                message=str(e), status_code=status.HTTP_400_BAD_REQUEST
            )
