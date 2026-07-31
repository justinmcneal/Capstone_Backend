from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text
from rest_framework import status
from loans.models import LoanApplication, RepaymentSchedule, LoanProduct
from loans.views.officer.base import LoanOfficerRequiredMixin
from accounts.models import Customer
import re

class ActiveLoansView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Get active (disbursed) loans for payment recording.

    GET /api/loans/officer/active-loans/

    Query params:
        - search: Search by customer name, phone, customer ID, or loan/application ID
        - customer_id: Filter by specific customer ID
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result
        user = request.user
        user_role = getattr(user, "role", "")
        user_id = self._actor_id(user)

        search = sanitize_text(request.query_params.get("search", ""))
        customer_id_filter = sanitize_text(request.query_params.get("customer_id", ""))
        if customer_id_filter and not ObjectId.is_valid(customer_id_filter):
            return error_response(
                message="Invalid customer_id filter",
                errors={"customer_id": "customer_id must be a valid ID"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Build customer query and support direct ID lookups
        direct_schedules = []
        if customer_id_filter:
            # Direct customer ID filter - query by _id
            try:
                customer = Customer.find_one({"_id": ObjectId(customer_id_filter)})
                customers = [customer] if customer else []
            except Exception:
                customers = []
        elif search:
            # Search by name, phone, or email using Customer.find()
            # Split search query by spaces to handle multi-word searches
            search_words = search.strip().split()

            if len(search_words) > 1:
                # Multi-word search: match records where ALL words are found in the full name
                # Build conditions for each word to match against first_name OR last_name
                word_conditions = []
                for word in search_words:
                    word_regex = re.compile(f".*{re.escape(word)}.*", re.IGNORECASE)
                    word_conditions.append({
                        "$or": [
                            {"first_name": word_regex},
                            {"last_name": word_regex},
                        ]
                    })

                # Also include phone and email search with the full original query
                full_regex = re.compile(f".*{re.escape(search)}.*", re.IGNORECASE)
                customers = Customer.find(
                    {
                        "$or": [
                            {"$and": word_conditions},  # All words match in first_name or last_name
                            {"phone": full_regex},
                            {"email": full_regex},
                        ]
                    }
                )[:20]  # Limit to 20 results
            else:
                # Single word search: use original logic
                regex = re.compile(f".*{re.escape(search)}.*", re.IGNORECASE)
                customers = Customer.find(
                    {
                        "$or": [
                            {"first_name": regex},
                            {"last_name": regex},
                            {"phone": regex},
                            {"email": regex},
                        ]
                    }
                )[
                    :20
                ]  # Limit to 20 results

            # Exact customer ID lookup (MongoDB ObjectId string)
            if ObjectId.is_valid(search):
                customer_by_id = Customer.find_one({"_id": ObjectId(search)})
                if customer_by_id and not any(
                    c and c.id == customer_by_id.id for c in customers
                ):
                    customers.append(customer_by_id)

            # Exact loan/application ID lookup
            schedule_by_loan_id = RepaymentSchedule.find_by_loan(search)
            if schedule_by_loan_id:
                direct_schedules.append(schedule_by_loan_id)
        else:
            # Return empty if no search criteria
            return success_response(
                data={"loans": [], "total": 0},
                message="Provide search term or customer_id",
            )

        # Get loans for these customers + directly matched loan IDs
        loans_data = []
        customer_cache = {c.id: c for c in customers if c and c.id}
        seen_schedule_ids = set()

        def append_schedule(schedule, customer):
            if not schedule or not customer:
                return
            if schedule.id in seen_schedule_ids:
                return
            seen_schedule_ids.add(schedule.id)

            # Get application for product info
            app = LoanApplication.find_by_id(schedule.loan_id)
            if not app:
                return
            if user_role == "loan_officer":
                assigned_officer = str(getattr(app, "assigned_officer", "") or "")
                if assigned_officer and assigned_officer != user_id:
                    return
            product = None
            if app:
                product = LoanProduct.find_by_id(app.product_id)

            # Get next payment due
            next_payment = schedule.get_next_payment()

            # Calculate next due amount including penalty if applied
            next_due_amount = None
            if next_payment:
                next_due_amount = next_payment["total_amount"]
                if next_payment.get("penalty_status") == "applied":
                    next_due_amount += next_payment.get("penalty_amount", 0)

            loans_data.append(
                {
                    "loan_id": schedule.loan_id,
                    "schedule_id": schedule.id,
                    "customer_id": customer.id,
                    "customer_name": f"{customer.first_name} {customer.last_name}",
                    "customer_phone": getattr(customer, "phone", None),
                    "product_name": product.name if product else "Unknown",
                    "disbursed_amount": schedule.principal,
                    "monthly_payment": schedule.monthly_payment,
                    "remaining_balance": schedule.get_remaining_balance(),
                    "paid_installments": schedule.get_paid_count(),
                    "total_installments": schedule.term_months,
                    "next_due_installment": (
                        next_payment["number"] if next_payment else None
                    ),
                    "next_due_date": (
                        next_payment["due_date"].isoformat()
                        if next_payment and next_payment.get("due_date")
                        else None
                    ),
                    "next_due_amount": next_due_amount,
                }
            )

        for customer in customers:
            if not customer:
                continue

            # Get repayment schedules (active loans)
            schedules = RepaymentSchedule.find_by_customer(customer.id)

            for schedule in schedules:
                append_schedule(schedule, customer)

        # Add schedules found via direct loan/application ID lookup
        for schedule in direct_schedules:
            if not schedule or not schedule.customer_id:
                continue
            customer = customer_cache.get(schedule.customer_id)
            if not customer:
                try:
                    customer = Customer.find_one(
                        {"_id": ObjectId(schedule.customer_id)}
                    )
                except Exception:
                    customer = None
                if customer:
                    customer_cache[schedule.customer_id] = customer
            append_schedule(schedule, customer)

        return success_response(
            data={"loans": loans_data, "total": len(loans_data)},
            message="Active loans retrieved",
        )
