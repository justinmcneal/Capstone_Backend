"""Bounded, audited repayment-schedule exports for officers and admins."""

import csv
import json
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO
from typing import ClassVar

from bson import ObjectId
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.models import Customer
from accounts.utils.response_helpers import error_response
from accounts.utils.validation_utils import sanitize_text
from loans.models import LoanApplication, LoanProduct, RepaymentSchedule
from loans.services.audit import LoanAuditUnavailable, record_loan_audit
from loans.views.officer.base import LoanOfficerRequiredMixin

EXPORT_BATCH_SIZE = 200
VALID_INSTALLMENT_STATUSES = {
    "pending",
    "partial",
    "overdue",
    "partial_overdue",
    "paid",
}
CSV_FIELDNAMES = [
    "loan_id",
    "schedule_id",
    "customer_id",
    "customer_name",
    "product_name",
    "principal",
    "interest_rate",
    "term_months",
    "monthly_payment",
    "total_amount",
    "total_interest",
    "start_date",
    "created_at",
    "installment_number",
    "due_date",
    "installment_principal",
    "installment_interest",
    "installment_total_amount",
    "base_amount",
    "status",
    "paid_amount",
    "penalty_status",
    "penalty_amount",
    "penalty_reason",
    "blockchain_schedule_tx",
]


def _object_id_candidates(values):
    """Return ObjectId/string candidates without failing on legacy identifiers."""
    candidates = []
    for value in values:
        if value is None:
            continue
        text = str(value)
        if text not in candidates:
            candidates.append(text)
        if ObjectId.is_valid(text):
            object_id = ObjectId(text)
            if object_id not in candidates:
                candidates.append(object_id)
    return candidates


def _chunks(cursor, size=EXPORT_BATCH_SIZE):
    batch = []
    for document in cursor:
        batch.append(document)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _iso(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _csv_safe(value):
    """Prevent spreadsheet formula execution while preserving displayed text."""
    if not isinstance(value, str):
        return value
    if value.startswith(("\t", "\r")) or value.lstrip(" ").startswith(
        ("=", "+", "-", "@")
    ):
        return f"'{value}"
    return value


class BulkRepaymentScheduleExportView(LoanOfficerRequiredMixin, APIView):
    """Stream flattened installment rows for every matching repayment schedule."""

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]

    @staticmethod
    def _parse_date(raw_value, field_name):
        if not raw_value:
            return None, None
        try:
            return date.fromisoformat(raw_value), None
        except (TypeError, ValueError):
            return None, error_response(
                message=f"Invalid {field_name} format. Use YYYY-MM-DD.",
                errors={field_name: "Use a valid calendar date in YYYY-MM-DD format."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    @staticmethod
    def _schedule_query(customer_id, start_date, end_date):
        query = {}
        if customer_id:
            query["customer_id"] = customer_id
        if start_date or end_date:
            created_at = {}
            if start_date:
                created_at["$gte"] = datetime.combine(start_date, time.min)
            if end_date:
                created_at["$lt"] = datetime.combine(
                    end_date + timedelta(days=1), time.min
                )
            query["created_at"] = created_at
        return query

    @staticmethod
    def _related_maps(db, schedules):
        loan_ids = [schedule.loan_id for schedule in schedules]
        app_documents = db[LoanApplication.collection_name].find(
            {"_id": {"$in": _object_id_candidates(loan_ids)}}
        )
        applications = [LoanApplication.from_dict(doc) for doc in app_documents]
        application_map = {app.id: app for app in applications if app}

        product_ids = [app.product_id for app in applications if app and app.product_id]
        product_documents = db[LoanProduct.collection_name].find(
            {"_id": {"$in": _object_id_candidates(product_ids)}}
        )
        products = [LoanProduct.from_dict(doc) for doc in product_documents]
        product_map = {product.id: product for product in products if product}

        customer_ids = [schedule.customer_id for schedule in schedules]
        customer_documents = db[Customer.collection_name].find(
            {"_id": {"$in": _object_id_candidates(customer_ids)}}
        )
        customers = [Customer.from_dict(doc) for doc in customer_documents]
        customer_map = {customer.id: customer for customer in customers if customer}
        return application_map, product_map, customer_map

    def _iter_rows(self, query, status_filter, actor_type, actor_id):
        db = settings.MONGODB
        cursor = db[RepaymentSchedule.collection_name].find(query).sort(
            [("created_at", 1), ("_id", 1)]
        )
        for documents in _chunks(cursor):
            schedules = [RepaymentSchedule.from_dict(doc) for doc in documents]
            schedules = [schedule for schedule in schedules if schedule]
            application_map, product_map, customer_map = self._related_maps(
                db, schedules
            )

            for schedule in schedules:
                application = application_map.get(str(schedule.loan_id))
                if actor_type == "loan_officer" and (
                    not application
                    or str(application.assigned_officer or "") != actor_id
                ):
                    continue
                product = (
                    product_map.get(str(application.product_id))
                    if application and application.product_id
                    else None
                )
                customer = customer_map.get(str(schedule.customer_id))
                customer_name = customer.full_name if customer else ""

                for installment in schedule.installments or []:
                    installment_status = installment.get("status", "pending")
                    if status_filter and installment_status != status_filter:
                        continue
                    base_total = installment.get("total_amount", 0) or 0
                    penalty_status = installment.get("penalty_status")
                    penalty_amount = installment.get("penalty_amount", 0) or 0
                    actual_total = base_total
                    if penalty_status == "applied" and penalty_amount > 0:
                        actual_total += penalty_amount

                    yield {
                        "loan_id": str(schedule.loan_id or ""),
                        "schedule_id": schedule.id or "",
                        "customer_id": str(schedule.customer_id or ""),
                        "customer_name": customer_name,
                        "product_name": product.name if product else "Unknown",
                        "principal": schedule.principal,
                        "interest_rate": schedule.interest_rate,
                        "term_months": schedule.term_months,
                        "monthly_payment": schedule.monthly_payment,
                        "total_amount": schedule.total_amount,
                        "total_interest": schedule.total_interest,
                        "start_date": _iso(schedule.start_date),
                        "created_at": _iso(schedule.created_at),
                        "installment_number": installment.get("number"),
                        "due_date": _iso(installment.get("due_date")),
                        "installment_principal": installment.get("principal", 0),
                        "installment_interest": installment.get("interest", 0),
                        "installment_total_amount": actual_total,
                        "base_amount": base_total,
                        "status": installment_status,
                        "paid_amount": installment.get("paid_amount", 0),
                        "penalty_status": penalty_status or "",
                        "penalty_amount": penalty_amount,
                        "penalty_reason": installment.get("penalty_reason", ""),
                        "blockchain_schedule_tx": (
                            schedule.blockchain_schedule_tx or ""
                        ),
                    }

    def _audit_export(self, request, row_count, export_format, filters):
        try:
            record_loan_audit(
                required=True,
                action="repayment_schedule_exported",
                user_id=self._actor_id(request.user),
                user_type=self._actor_type(request.user),
                description="Exported sensitive repayment schedule data",
                resource_type="repayment_schedule_export",
                details={
                    "format": export_format,
                    "row_count": row_count,
                    "filters": filters,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )
        except LoanAuditUnavailable:
            return error_response(
                message=(
                    "Export is temporarily unavailable because access could not "
                    "be audited"
                ),
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return None

    @staticmethod
    def _csv_stream(rows):
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        for row in rows:
            writer.writerow({key: _csv_safe(value) for key, value in row.items()})
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    @staticmethod
    def _json_stream(rows, row_count):
        yield (
            '{"status":"success","message":'
            + json.dumps(f"Exported {row_count} installments")
            + ',"data":{"installments":['
        )
        first = True
        for row in rows:
            if not first:
                yield ","
            first = False
            yield json.dumps(row, cls=DjangoJSONEncoder, separators=(",", ":"))
        yield f'],"total":{row_count}}}}}'

    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        actor_type = self._actor_type(request.user)
        actor_id = self._actor_id(request.user)
        customer_id = sanitize_text(request.query_params.get("customer_id", ""))
        status_filter = sanitize_text(
            request.query_params.get("status", "")
        ).lower()
        start_date_raw = sanitize_text(request.query_params.get("start_date", ""))
        end_date_raw = sanitize_text(request.query_params.get("end_date", ""))
        export_format = sanitize_text(
            request.query_params.get("format", "csv")
        ).lower()

        if export_format not in {"csv", "json"}:
            return error_response(
                message="Invalid export format. Must be csv or json.",
                errors={"format": "Supported values are csv and json."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if status_filter and status_filter not in VALID_INSTALLMENT_STATUSES:
            return error_response(
                message=(
                    "Invalid status filter. Must be one of: "
                    + ", ".join(sorted(VALID_INSTALLMENT_STATUSES))
                ),
                errors={"status": "Unsupported installment status."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if customer_id and not ObjectId.is_valid(customer_id):
            return error_response(
                message="Invalid customer_id format",
                errors={"customer_id": "Use a valid customer ObjectId."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        start_date, date_error = self._parse_date(start_date_raw, "start_date")
        if date_error:
            return date_error
        end_date, date_error = self._parse_date(end_date_raw, "end_date")
        if date_error:
            return date_error
        if start_date and end_date and start_date > end_date:
            return error_response(
                message="start_date cannot be after end_date",
                errors={"date_range": "Choose a start date on or before end_date."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        query = self._schedule_query(customer_id, start_date, end_date)
        def row_factory():
            return self._iter_rows(query, status_filter, actor_type, actor_id)
        row_count = sum(1 for _row in row_factory())
        if not row_count:
            return error_response(
                message="No repayment schedules found matching the filters",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        filters = {
            "customer_id": customer_id,
            "status": status_filter,
            "start_date": start_date_raw,
            "end_date": end_date_raw,
        }
        audit_error = self._audit_export(
            request, row_count, export_format, filters
        )
        if audit_error:
            return audit_error

        if export_format == "json":
            response = StreamingHttpResponse(
                self._json_stream(row_factory(), row_count),
                content_type="application/json",
            )
        else:
            response = StreamingHttpResponse(
                self._csv_stream(row_factory()), content_type="text/csv"
            )
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            response["Content-Disposition"] = (
                f'attachment; filename="repayment_schedules_{timestamp}.csv"'
            )
        response["X-Export-Row-Count"] = str(row_count)
        return response
