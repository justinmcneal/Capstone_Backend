import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import ClassVar

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.validation_utils import sanitize_text
from accounts.views.admin_views import AdminRequiredMixin
from loans.utils.serialization import serialize_admin_blockchain_transaction

logger = logging.getLogger("loans")


class AdminBlockchainTransactionsView(AdminRequiredMixin, APIView):
    """
    Admin: List all blockchain transactions across the system.

    GET /api/loans/admin/blockchain/transactions/

    Query params:
        - action: filter by action (submit, approve, reject, disburse, schedule, payment)
        - status: filter by status (confirmed, pending, failed)
        - search: search by tx_hash or loan_id
        - start_date: filter by date range start (YYYY-MM-DD)
        - end_date: filter by date range end (YYYY-MM-DD)
        - page: page number (default 1)
        - page_size: items per page (default 20, max 100)
    """

    authentication_classes: ClassVar[list] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list] = [IsAuthenticated]
    required_permissions: ClassVar[list] = ["view_logs"]

    ALLOWED_QUERY_PARAMS = frozenset(
        {"action", "status", "search", "start_date", "end_date", "page", "page_size"}
    )
    ALLOWED_ACTIONS = frozenset(
        {
            "submit",
            "approve",
            "reject",
            "disburse",
            "schedule",
            "payment",
            "penalty_applied",
            "penalty_waived",
            "consent",
        }
    )
    ALLOWED_STATUSES = frozenset({"confirmed", "pending", "failed"})

    @staticmethod
    def _parse_positive_int(raw_value, field_name, *, maximum=None):
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return None, error_response(
                message=f"Invalid {field_name} parameter",
                errors={field_name: f"{field_name} must be an integer"},
                code="INVALID_BLOCKCHAIN_QUERY",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if value < 1 or (maximum is not None and value > maximum):
            upper = f" and at most {maximum}" if maximum is not None else ""
            return None, error_response(
                message=f"Invalid {field_name} parameter",
                errors={field_name: f"{field_name} must be at least 1{upper}"},
                code="INVALID_BLOCKCHAIN_QUERY",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return value, None

    @staticmethod
    def _parse_date(raw_value, field_name):
        if not raw_value:
            return None, None
        try:
            return date.fromisoformat(raw_value), None
        except (TypeError, ValueError):
            return None, error_response(
                message=f"Invalid {field_name} parameter",
                errors={field_name: f"{field_name} must use YYYY-MM-DD format"},
                code="INVALID_BLOCKCHAIN_QUERY",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def get(self, request):
        from django.conf import settings

        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        unknown = set(request.query_params.keys()) - self.ALLOWED_QUERY_PARAMS
        if unknown:
            return error_response(
                message="Unknown blockchain transaction query parameter",
                errors={
                    "query": f"Unsupported parameters: {', '.join(sorted(unknown))}"
                },
                code="INVALID_BLOCKCHAIN_QUERY",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        action = sanitize_text(request.query_params.get("action", "")).lower()
        tx_status = sanitize_text(request.query_params.get("status", "")).lower()
        search = sanitize_text(request.query_params.get("search", ""))
        start_date = sanitize_text(request.query_params.get("start_date", ""))
        end_date = sanitize_text(request.query_params.get("end_date", ""))

        page, parse_error = self._parse_positive_int(
            request.query_params.get("page", 1), "page"
        )
        if parse_error:
            return parse_error
        page_size, parse_error = self._parse_positive_int(
            request.query_params.get("page_size", 20), "page_size", maximum=100
        )
        if parse_error:
            return parse_error

        if action and action not in self.ALLOWED_ACTIONS:
            return error_response(
                message="Invalid blockchain action filter",
                errors={
                    "action": f"action must be one of: {', '.join(sorted(self.ALLOWED_ACTIONS))}"
                },
                code="INVALID_BLOCKCHAIN_QUERY",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if tx_status and tx_status not in self.ALLOWED_STATUSES:
            return error_response(
                message="Invalid blockchain status filter",
                errors={
                    "status": f"status must be one of: {', '.join(sorted(self.ALLOWED_STATUSES))}"
                },
                code="INVALID_BLOCKCHAIN_QUERY",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if len(search) > 100:
            return error_response(
                message="Invalid blockchain search",
                errors={"search": "search must contain at most 100 characters"},
                code="INVALID_BLOCKCHAIN_QUERY",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        start_day, parse_error = self._parse_date(start_date, "start_date")
        if parse_error:
            return parse_error
        end_day, parse_error = self._parse_date(end_date, "end_date")
        if parse_error:
            return parse_error
        if start_day and end_day and start_day > end_day:
            return error_response(
                message="Invalid blockchain date range",
                errors={"date_range": "start_date cannot be after end_date"},
                code="INVALID_BLOCKCHAIN_QUERY",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Build MongoDB query
        query = {}

        if action:
            query["action"] = action

        if tx_status:
            query["status"] = tx_status

        if search:
            escaped_search = re.escape(search)
            query["$or"] = [
                {"tx_hash": {"$regex": escaped_search, "$options": "i"}},
                {"loan_id": {"$regex": escaped_search, "$options": "i"}},
            ]

        if start_day:
            query.setdefault("created_at", {})["$gte"] = datetime.combine(
                start_day, time.min, tzinfo=timezone.utc
            )
        if end_day:
            query.setdefault("created_at", {})["$lt"] = datetime.combine(
                end_day + timedelta(days=1), time.min, tzinfo=timezone.utc
            )

        # Get collection
        db = getattr(settings, "MONGODB", None)
        if db is None:
            return error_response(
                message="Blockchain transaction history is temporarily unavailable",
                code="BLOCKCHAIN_HISTORY_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        collection = db["blockchain_transactions"]

        # Get total count
        try:
            total = collection.count_documents(query)
            total_pages = (total + page_size - 1) // page_size
            skip = (page - 1) * page_size
            cursor = (
                collection.find(query)
                .sort([("created_at", -1), ("_id", -1)])
                .skip(skip)
                .limit(page_size)
            )
            transactions = [
                serialize_admin_blockchain_transaction(doc) for doc in cursor
            ]
        except Exception:
            logger.exception("Admin blockchain transaction query failed")
            return error_response(
                message="Blockchain transaction history is temporarily unavailable",
                code="BLOCKCHAIN_HISTORY_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return success_response(
            data={
                "transactions": transactions,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            },
            message="Blockchain transactions retrieved",
        )
