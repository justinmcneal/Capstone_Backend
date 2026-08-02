from datetime import datetime
from io import StringIO

import csv
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text
from rest_framework import status
from loans.models import LoanApplication, LoanProduct, RepaymentSchedule
from loans.models.repayment import get_db
from loans.views.officer.base import LoanOfficerRequiredMixin
from accounts.models import Customer
import logging

logger = logging.getLogger("loans")


class BulkRepaymentScheduleExportView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer/Admin: Bulk export repayment schedules to CSV.

    GET /api/loans/officer/schedules/export/

    Query params:
        - customer_id: Filter by customer ID (optional)
        - status: Filter by installment status: pending, paid, overdue, partial (optional)
        - start_date: Filter schedules created after this date (ISO format, optional)
        - end_date: Filter schedules created before this date (ISO format, optional)
        - format: Export format - csv (default) or json (optional)

    Returns:
        CSV file download with one row per installment
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        user_role = getattr(request.user, "role", "")
        user_id = self._actor_id(request.user)

        # Parse filters
        customer_id_filter = sanitize_text(request.query_params.get("customer_id", ""))
        status_filter = sanitize_text(request.query_params.get("status", "")).lower()
        start_date_str = sanitize_text(request.query_params.get("start_date", ""))
        end_date_str = sanitize_text(request.query_params.get("end_date", ""))
        export_format = sanitize_text(request.query_params.get("format", "csv")).lower()

        # Validate status filter
        valid_statuses = {"pending", "paid", "overdue", "partial"}
        if status_filter and status_filter not in valid_statuses:
            return error_response(
                message=f"Invalid status filter. Must be one of: {', '.join(sorted(valid_statuses))}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Parse dates
        start_date = None
        end_date = None
        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str)
            except ValueError:
                return error_response(
                    message="Invalid start_date format. Use ISO format (YYYY-MM-DD).",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str)
            except ValueError:
                return error_response(
                    message="Invalid end_date format. Use ISO format (YYYY-MM-DD).",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        # Build query for schedules
        query = {}
        if customer_id_filter:
            if not ObjectId.is_valid(customer_id_filter):
                return error_response(
                    message="Invalid customer_id format",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            query["customer_id"] = customer_id_filter

        # Fetch schedules
        db = get_db()
        collection = db[RepaymentSchedule.collection_name]

        schedules = []
        if customer_id_filter:
            schedule = RepaymentSchedule.find_one({"customer_id": customer_id_filter})
            schedules = [schedule] if schedule else []
        else:
            schedules = RepaymentSchedule.find_all()

        # Apply date filter
        if start_date or end_date:
            filtered_schedules = []
            for schedule in schedules:
                schedule_date = schedule.created_at
                if hasattr(schedule_date, "date"):
                    schedule_date = schedule_date.date()
                elif isinstance(schedule_date, str):
                    try:
                        schedule_date = datetime.fromisoformat(schedule_date).date()
                    except ValueError:
                        continue

                if start_date and schedule_date < start_date.date():
                    continue
                if end_date and schedule_date > end_date.date():
                    continue
                filtered_schedules.append(schedule)
            schedules = filtered_schedules

        # Apply officer scope if not admin
        if user_role == "loan_officer":
            scoped_schedules = []
            for schedule in schedules:
                app = LoanApplication.find_by_id(schedule.loan_id)
                if app and str(getattr(app, "assigned_officer", "") or "") == user_id:
                    scoped_schedules.append(schedule)
            schedules = scoped_schedules

        # Prepare export data
        rows = []
        for schedule in schedules:
            app = LoanApplication.find_by_id(schedule.loan_id)
            product = LoanProduct.find_by_id(app.product_id) if app else None
            customer = Customer.find_one({"_id": ObjectId(schedule.customer_id)}) if schedule.customer_id else None

            customer_name = ""
            if customer:
                customer_name = f"{getattr(customer, 'first_name', '')} {getattr(customer, 'last_name', '')}".strip()

            for inst in schedule.installments:
                inst_status = inst.get("status", "pending")
                
                # Apply status filter
                if status_filter and inst_status != status_filter:
                    continue
                
                due_date = inst.get("due_date")
                if hasattr(due_date, "isoformat"):
                    due_date = due_date.isoformat()
                elif due_date:
                    due_date = str(due_date)

                # Calculate actual amount including penalties
                base_total = inst.get("total_amount", 0)
                penalty_status = inst.get("penalty_status")
                penalty_amount = inst.get("penalty_amount", 0)
                actual_total = base_total
                if penalty_status == "applied" and penalty_amount > 0:
                    actual_total = base_total + penalty_amount

                rows.append({
                    "loan_id": schedule.loan_id,
                    "schedule_id": schedule.id,
                    "customer_id": schedule.customer_id,
                    "customer_name": customer_name,
                    "product_name": product.name if product else "Unknown",
                    "principal": schedule.principal,
                    "interest_rate": schedule.interest_rate,
                    "term_months": schedule.term_months,
                    "monthly_payment": schedule.monthly_payment,
                    "total_amount": schedule.total_amount,
                    "total_interest": schedule.total_interest,
                    "start_date": schedule.start_date.isoformat() if hasattr(schedule.start_date, "isoformat") else str(schedule.start_date),
                    "created_at": schedule.created_at.isoformat() if hasattr(schedule.created_at, "isoformat") else str(schedule.created_at),
                    "installment_number": inst.get("number"),
                    "due_date": due_date,
                    "installment_principal": inst.get("principal", 0),
                    "installment_interest": inst.get("interest", 0),
                    "installment_total_amount": actual_total,
                    "base_amount": base_total,
                    "status": inst_status,
                    "paid_amount": inst.get("paid_amount", 0),
                    "penalty_status": penalty_status or "",
                    "penalty_amount": penalty_amount,
                    "penalty_reason": inst.get("penalty_reason", ""),
                    "blockchain_schedule_tx": schedule.blockchain_schedule_tx or "",
                })

        if export_format == "json":
            return success_response(
                data={"schedules": rows, "total": len(rows)},
                message=f"Exported {len(rows)} installments",
            )

        # Default: CSV export
        if not rows:
            return error_response(
                message="No repayment schedules found matching the filters",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Generate CSV
        fieldnames = [
            "loan_id", "schedule_id", "customer_id", "customer_name", "product_name",
            "principal", "interest_rate", "term_months", "monthly_payment",
            "total_amount", "total_interest", "start_date", "created_at",
            "installment_number", "due_date", "installment_principal", "installment_interest",
            "installment_total_amount", "base_amount", "status", "paid_amount",
            "penalty_status", "penalty_amount", "penalty_reason", "blockchain_schedule_tx",
        ]

        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        # Return as downloadable file
        from django.http import HttpResponse
        response = HttpResponse(csv_content, content_type="text/csv")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        response["Content-Disposition"] = f'attachment; filename="repayment_schedules_{timestamp}.csv"'
        return response
