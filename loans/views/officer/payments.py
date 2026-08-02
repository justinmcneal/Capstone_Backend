from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId

from accounts.authentication import CustomJWTAuthentication
from analytics.models import AuditLog  # noqa: F401 - existing test patch target
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text, parse_bool
from rest_framework import status
from loans.models import LoanApplication, LoanProduct, LoanPayment, RepaymentSchedule
from loans.views.officer.base import LoanOfficerRequiredMixin
from loans.services.audit import record_loan_audit
from datetime import datetime
import logging
from loans.utils.money import from_centavos

logger = logging.getLogger("loans")


class RecordPaymentView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Record a payment for a loan.

    POST /api/loans/officer/payments/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        has_permission, user = self.check_officer_permission(request)
        if not has_permission:
            return user

        # Required fields
        loan_id = sanitize_text(request.data.get("loan_id", ""))
        installment_number_raw = request.data.get("installment_number")
        amount_raw = request.data.get("amount", 0)
        payment_method = (
            sanitize_text(request.data.get("payment_method", "cash")).lower() or "cash"
        )
        reference = sanitize_text(request.data.get("reference", ""))
        external_reference = sanitize_text(
            request.data.get("external_reference", "")
        )  # Cash/check reference
        notes = sanitize_text(request.data.get("notes", ""))
        idempotency_key = request.headers.get("Idempotency-Key") or request.data.get(
            "idempotency_key"
        )

        # Validation
        if not loan_id:
            return error_response(
                message="loan_id is required", status_code=status.HTTP_400_BAD_REQUEST
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
        if payment_method not in {"cash", "check"}:
            return error_response(
                message="Manual payment recording only accepts cash or check",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if not reference and external_reference:
            reference = external_reference

        # Auto-generate system reference if not provided
        if not reference:
            from loans.utils import generate_payment_reference

            reference = generate_payment_reference()

        # Find schedule
        schedule = RepaymentSchedule.find_by_loan(loan_id)

        if not schedule:
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        app = LoanApplication.find_by_id(loan_id)
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

        # VALIDATION 1: Check if installment exists
        installment = schedule.get_installment(installment_number)
        if not installment:
            return error_response(
                message=f"Installment #{installment_number} not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Balance and paid-state validation happens inside the atomic service so
        # an identical replay can still return its original completed payment.
        unpaid_before = schedule.count_unpaid_before(installment_number)

        from loans.services.payment import (
            PaymentConflictError,
            PaymentServiceError,
            post_verified_payment,
            scoped_idempotency_key,
        )

        try:
            payment, updated_installment, replayed = post_verified_payment(
                schedule=schedule,
                installment_number=installment_number,
                amount=amount,
                payment_method=payment_method,
                reference=reference,
                notes=notes,
                recorded_by=self._actor_id(user),
                recorded_by_type=self._actor_type(user),
                idempotency_key=scoped_idempotency_key(
                    "officer", self._actor_id(user), idempotency_key
                ),
                verification_source="officer_manual",
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

        if replayed:
            return success_response(
                data={
                    "payment_id": payment.id,
                    "loan_id": loan_id,
                    "installment_number": installment_number,
                    "amount": amount,
                    "installment_status": updated_installment["status"],
                    "remaining_balance": schedule.get_remaining_balance(),
                    "reference": payment.reference,
                    "skipped_installments": unpaid_before,
                    "replayed": True,
                },
                message="Payment already recorded",
            )

        logger.info(
            f"Payment recorded: {amount} for loan {loan_id} installment {installment_number}"
        )

        # Audit log for payment
        record_loan_audit(
            action="payment_recorded",
            user_id=self._actor_id(user),
            user_type=self._actor_type(user),
            description=f"Payment recorded - PHP{amount:,.2f} for installment #{installment_number}",
            resource_type="payment",
            resource_id=payment.id,
            details={
                "loan_id": loan_id,
                "amount": amount,
                "installment": installment_number,
                "method": payment_method,
            },
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )

        # Send notification email
        try:
            from accounts.models import Customer
            from notifications.services import get_email_sender

            customer = None
            if schedule.customer_id:
                try:
                    customer = Customer.find_one(
                        {"_id": ObjectId(schedule.customer_id)}
                    )
                except Exception:
                    pass
            if customer and customer.email:
                sender = get_email_sender()
                sender.send_payment_received(
                    customer_email=customer.email,
                    customer_name=f"{customer.first_name} {customer.last_name}",
                    loan_id=loan_id,
                    amount=amount,
                    installment=installment_number,
                    remaining=schedule.get_remaining_balance(),
                    customer_id=schedule.customer_id,
                )
        except Exception as e:
            logger.warning(f"Failed to send payment email: {e}")

        # Blockchain sync — payment (background thread, no Celery needed)
        try:
            from loans.blockchain.sync import sync_payment

            sync_payment(loan_id, payment.id)
        except Exception as e:
            logger.warning(f"Blockchain sync skipped for payment {payment.id}: {e}")

        return success_response(
            data={
                "payment_id": payment.id,
                "loan_id": loan_id,
                "installment_number": installment_number,
                "amount": amount,
                "installment_status": updated_installment["status"],
                "remaining_balance": schedule.get_remaining_balance(),
                "reference": reference,
                "skipped_installments": unpaid_before,  # Warning: earlier unpaid installments
                "replayed": False,
            },
            message=(
                "Payment recorded successfully"
                if unpaid_before == 0
                else f"Payment recorded. Note: {unpaid_before} earlier installment(s) still unpaid."
            ),
            status_code=status.HTTP_201_CREATED,
        )


class OfficerPaymentHistoryView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Get payment history for a loan.

    GET /api/loans/officer/applications/<id>/payments/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        # Verify application exists
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

        payments = LoanPayment.find_by_loan(application_id)

        payments_data = [
            {
                "id": p.id,
                "amount": p.amount,
                "payment_method": p.payment_method,
                "payment_status": p.payment_status,
                "reference": p.reference,
                "installment_number": p.installment_number,
                "notes": p.notes,
                "recorded_at": p.recorded_at.isoformat() if p.recorded_at else None,
            }
            for p in payments
        ]

        total_paid = LoanPayment.get_total_paid(application_id)

        return success_response(
            data={
                "payments": payments_data,
                "total_paid": total_paid,
                "count": len(payments_data),
            },
            message="Payment history retrieved",
        )


class RecentPaymentsView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Get the latest payments across accessible loans.

    GET /api/loans/officer/payments/recent/?limit=5
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        try:
            limit = int(request.query_params.get("limit", 5))
        except (TypeError, ValueError):
            return error_response(
                message="Invalid limit parameter",
                errors={"limit": "limit must be an integer"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if not 1 <= limit <= 50:
            return error_response(
                message="Invalid limit parameter",
                errors={"limit": "limit must be between 1 and 50"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        query = {}
        if getattr(user, "role", "") == "loan_officer":
            officer_id = self._actor_id(user)
            assigned_apps = LoanApplication.find_by_officer(officer_id)
            assigned_loan_ids = [app.id for app in assigned_apps]
            if not assigned_loan_ids:
                return success_response(
                    data={"payments": []},
                    message="Recent payments retrieved",
                )
            query["loan_id"] = {"$in": assigned_loan_ids}

        from accounts.models import Customer

        payment_documents = LoanPayment.find(
            query, sort=[("recorded_at", -1)], limit=limit
        )
        customer_cache = {}
        payments_data = []

        for payment in payment_documents:
            if not payment:
                continue

            customer_id = payment.customer_id
            if customer_id not in customer_cache:
                customer = None
                if customer_id and ObjectId.is_valid(customer_id):
                    customer = Customer.find_one({"_id": ObjectId(customer_id)})
                customer_cache[customer_id] = customer

            customer = customer_cache[customer_id]
            payments_data.append(
                {
                    "id": payment.id,
                    "customer_name": customer.full_name if customer else "Unknown",
                    "reference": payment.reference,
                    "amount": payment.amount,
                    "recorded_at": (
                        payment.recorded_at.isoformat() if payment.recorded_at else None
                    ),
                }
            )

        return success_response(
            data={"payments": payments_data},
            message="Recent payments retrieved",
        )


class PaymentSearchView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Search and filter all payments with advanced options.

    GET /api/loans/officer/payments/search/

    Query params:
        - search: Keyword search (customer name, reference number)
        - loan_id: Filter by loan ID
        - customer_id: Filter by customer ID
        - disbursed_only: If true (default), only include payments from disbursed loans
        - payment_status: Filter by payment timing status ('on_time', 'late')
        - payment_method: Filter by payment method ('cash', 'gcash', 'bank_transfer', 'check', 'wallet')
        - min_amount: Minimum payment amount
        - max_amount: Maximum payment amount
        - start_date: Filter payments recorded on or after this date (YYYY-MM-DD)
        - end_date: Filter payments recorded on or before this date (YYYY-MM-DD)
        - page: Page number (default 1)
        - page_size: Items per page (default 20, max 100)
        - sort_by: Sort field ('recorded_at', 'amount', 'installment_number')
        - sort_order: 'asc' or 'desc' (default 'desc')
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import re
        from accounts.models import Customer

        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result
        user = request.user
        user_role = getattr(user, "role", "")
        user_id = self._actor_id(user)

        # Extract query params
        search_query = sanitize_text(request.query_params.get("search", ""))
        loan_id = sanitize_text(request.query_params.get("loan_id", ""))
        customer_id = sanitize_text(request.query_params.get("customer_id", ""))
        disbursed_only_raw = sanitize_text(
            request.query_params.get("disbursed_only", "true")
        ).lower()
        payment_status = sanitize_text(
            request.query_params.get("payment_status", "")
        ).lower()
        payment_method = sanitize_text(
            request.query_params.get("payment_method", "")
        ).lower()
        min_amount = sanitize_text(request.query_params.get("min_amount", ""))
        max_amount = sanitize_text(request.query_params.get("max_amount", ""))
        start_date = sanitize_text(request.query_params.get("start_date", ""))
        end_date = sanitize_text(request.query_params.get("end_date", ""))
        try:
            page = int(request.query_params.get("page", 1))
        except (TypeError, ValueError):
            return error_response(
                message="Invalid page parameter",
                errors={"page": "page must be an integer"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            page_size = min(int(request.query_params.get("page_size", 20)), 100)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid page_size parameter",
                errors={"page_size": "page_size must be an integer"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        sort_by = sanitize_text(request.query_params.get("sort_by", "recorded_at"))
        sort_order = sanitize_text(
            request.query_params.get("sort_order", "desc")
        ).lower()
        if page < 1:
            return error_response(
                message="Invalid page parameter",
                errors={"page": "page must be at least 1"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if page_size < 1:
            return error_response(
                message="Invalid page_size parameter",
                errors={"page_size": "page_size must be at least 1"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        valid_payment_statuses = ["on_time", "late"]
        disbursed_valid, disbursed_only, disbursed_error = parse_bool(
            disbursed_only_raw, "disbursed_only"
        )
        if not disbursed_valid:
            return error_response(
                message="Invalid disbursed_only filter",
                errors={"disbursed_only": disbursed_error},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if payment_status and payment_status not in valid_payment_statuses:
            return error_response(
                message="Invalid payment_status filter",
                errors={
                    "payment_status": "payment_status must be one of: on_time, late"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        def _empty_payment_result():
            return success_response(
                data={
                    "payments": [],
                    "total": 0,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": 0,
                    "summary": {"total_amount": 0, "count": 0},
                },
                message="Payments retrieved",
            )

        # Build query
        query = {}
        allowed_loan_ids = None

        # Restrict to disbursed loans by default
        if disbursed_only:
            if loan_id:
                app = LoanApplication.find_by_id(loan_id)
                if not app or app.status not in {
                    "disbursed",
                    "completed",
                    "written_off",
                }:
                    return _empty_payment_result()
                allowed_loan_ids = [loan_id]
            else:
                disbursed_apps = LoanApplication.find(
                    {"status": {"$in": ["disbursed", "completed", "written_off"]}}
                )
                allowed_loan_ids = [app.id for app in disbursed_apps]
                if not allowed_loan_ids:
                    return _empty_payment_result()

        # ABAC scope for loan officers: only payments for assigned applications.
        if user_role == "loan_officer":
            officer_assigned_ids = [
                app.id for app in LoanApplication.find_by_officer(user_id)
            ]
            if allowed_loan_ids is None:
                allowed_loan_ids = officer_assigned_ids
            else:
                officer_set = set(officer_assigned_ids)
                allowed_loan_ids = [
                    loan for loan in allowed_loan_ids if loan in officer_set
                ]
            if not allowed_loan_ids:
                return _empty_payment_result()

        # Loan scope filter after deriving all constraints.
        if loan_id:
            if allowed_loan_ids is not None and loan_id not in set(allowed_loan_ids):
                return _empty_payment_result()
            query["loan_id"] = loan_id
        elif allowed_loan_ids is not None:
            query["loan_id"] = {"$in": allowed_loan_ids}

        # Customer ID filter
        if customer_id:
            query["customer_id"] = customer_id

        # Payment method filter
        valid_methods = ["cash", "gcash", "bank_transfer", "check", "wallet"]
        if payment_method:
            if payment_method not in valid_methods:
                return error_response(
                    message="Invalid payment_method filter",
                    errors={
                        "payment_method": f"payment_method must be one of: {', '.join(valid_methods)}"
                    },
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            query["payment_method"] = payment_method

        # Amount range filter
        parsed_min_amount = None
        parsed_max_amount = None
        if min_amount:
            try:
                parsed_min_amount = float(min_amount)
            except ValueError:
                return error_response(
                    message="Invalid min_amount filter",
                    errors={"min_amount": "min_amount must be a number"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            query.setdefault("amount", {})["$gte"] = parsed_min_amount
        if max_amount:
            try:
                parsed_max_amount = float(max_amount)
            except ValueError:
                return error_response(
                    message="Invalid max_amount filter",
                    errors={"max_amount": "max_amount must be a number"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            query.setdefault("amount", {})["$lte"] = parsed_max_amount
        if (
            parsed_min_amount is not None
            and parsed_max_amount is not None
            and parsed_min_amount > parsed_max_amount
        ):
            return error_response(
                message="Invalid amount range",
                errors={"amount_range": "min_amount cannot be greater than max_amount"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Date range filter
        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                query.setdefault("recorded_at", {})["$gte"] = start_dt
            except ValueError:
                return error_response(
                    message="Invalid start_date filter",
                    errors={"start_date": "start_date must use YYYY-MM-DD format"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59
                )
                query.setdefault("recorded_at", {})["$lte"] = end_dt
            except ValueError:
                return error_response(
                    message="Invalid end_date filter",
                    errors={"end_date": "end_date must use YYYY-MM-DD format"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        # Keyword search - find customer IDs matching the search
        customer_ids = []
        if search_query:
            search_terms = search_query.strip().split()
            if len(search_terms) == 1:
                regex = re.compile(f".*{re.escape(search_terms[0])}.*", re.IGNORECASE)
                customers = Customer.find(
                    {
                        "$or": [
                            {"first_name": regex},
                            {"last_name": regex},
                            {"phone": regex},
                        ]
                    }
                )
            else:
                customer_and_conditions = []
                for term in search_terms:
                    term_regex = re.compile(f".*{re.escape(term)}.*", re.IGNORECASE)
                    customer_and_conditions.append(
                        {
                            "$or": [
                                {"first_name": term_regex},
                                {"last_name": term_regex},
                                {"phone": term_regex},
                            ]
                        }
                    )
                customers = Customer.find({"$and": customer_and_conditions})
            customer_ids = [c.id for c in customers if c]

        # Build final query with search
        if search_query:
            search_conditions = []
            if customer_ids:
                search_conditions.append({"customer_id": {"$in": customer_ids}})
            search_conditions.append(
                {"reference": {"$regex": re.escape(search_query), "$options": "i"}}
            )

            if query:
                final_query = {"$and": [query, {"$or": search_conditions}]}
            else:
                final_query = {"$or": search_conditions}
        else:
            final_query = query

        # Sorting
        valid_sort_fields = {"recorded_at", "amount", "installment_number"}
        if sort_by not in valid_sort_fields:
            return error_response(
                message="Invalid sort_by parameter",
                errors={
                    "sort_by": f"sort_by must be one of: {', '.join(sorted(valid_sort_fields))}"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if sort_order not in {"asc", "desc"}:
            return error_response(
                message="Invalid sort_order parameter",
                errors={"sort_order": "sort_order must be asc or desc"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        sort_field = sort_by
        sort_direction = 1 if sort_order == "asc" else -1
        schedule_cache = {}

        def resolve_payment_status(payment):
            """Classify payment as on_time/late based on installment due date."""
            if not payment:
                return "unknown", None

            loan_key = payment.loan_id
            if loan_key not in schedule_cache:
                schedule_cache[loan_key] = RepaymentSchedule.find_by_loan(loan_key)
            schedule = schedule_cache.get(loan_key)
            if not schedule:
                return "unknown", None

            installment = schedule.get_installment(payment.installment_number)
            if not installment:
                return "unknown", None

            due_date = installment.get("due_date")
            if not due_date or not payment.recorded_at:
                return "unknown", due_date

            status_value = (
                "on_time" if payment.recorded_at.date() <= due_date.date() else "late"
            )
            return status_value, due_date

        # Get filtered + paginated results
        if payment_status:
            all_payments = LoanPayment.find(
                final_query, sort=[(sort_field, sort_direction)]
            )

            status_filtered = []
            for payment in all_payments:
                if not payment:
                    continue
                status_value, _ = resolve_payment_status(payment)
                if status_value == payment_status:
                    status_filtered.append(payment)

            total_count = len(status_filtered)
            summary = {
                "total_amount": from_centavos(
                    sum(payment.amount_centavos for payment in status_filtered)
                ),
                "count": total_count,
            }
            skip = (page - 1) * page_size
            payments = status_filtered[skip : skip + page_size]
        else:
            total_count = LoanPayment.count(final_query)
            summary = LoanPayment.summarize(final_query)
            skip = (page - 1) * page_size
            payments = LoanPayment.find(
                final_query,
                sort=[(sort_field, sort_direction)],
                limit=page_size,
                skip=skip,
            )

        # Build response with customer names
        payments_data = []
        customer_cache = {}

        for payment in payments:
            if not payment:
                continue

            # Cache customer lookups
            cust_id = payment.customer_id
            if cust_id not in customer_cache:
                customer = None
                if cust_id:
                    try:
                        customer = Customer.find_one({"_id": ObjectId(cust_id)})
                    except Exception:
                        pass
                customer_cache[cust_id] = customer

            customer = customer_cache.get(cust_id)
            customer_name = (
                f"{customer.first_name} {customer.last_name}" if customer else "Unknown"
            )

            # Get loan application for product info
            app = LoanApplication.find_by_id(payment.loan_id)
            product_name = "Unknown"
            if app:
                product = LoanProduct.find_by_id(app.product_id)
                product_name = product.name if product else "Unknown"
            status_value, due_date = resolve_payment_status(payment)

            payments_data.append(
                {
                    "id": payment.id,
                    "loan_id": payment.loan_id,
                    "customer_id": payment.customer_id,
                    "customer_name": customer_name,
                    "product_name": product_name,
                    "installment_number": payment.installment_number,
                    "due_date": due_date.isoformat() if due_date else None,
                    "payment_status": status_value,
                    "amount": payment.amount,
                    "payment_method": payment.payment_method,
                    "reference": payment.reference,
                    "notes": payment.notes,
                    "recorded_by": payment.recorded_by,
                    "recorded_at": (
                        payment.recorded_at.isoformat() if payment.recorded_at else None
                    ),
                }
            )

        return success_response(
            data={
                "payments": payments_data,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": (total_count + page_size - 1) // page_size,
                "summary": summary,
            },
            message="Payments retrieved",
        )
