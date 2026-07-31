from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from datetime import datetime

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text
from accounts.views.admin_views import AdminRequiredMixin
import logging

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

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    required_permissions = ["view_logs"]

    def get(self, request):
        from django.conf import settings

        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        # Get query params
        action = sanitize_text(request.query_params.get("action", "")).lower()
        tx_status = sanitize_text(request.query_params.get("status", "")).lower()
        search = sanitize_text(request.query_params.get("search", ""))
        start_date = sanitize_text(request.query_params.get("start_date", ""))
        end_date = sanitize_text(request.query_params.get("end_date", ""))

        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except ValueError:
            page = 1
            page_size = 20

        # Build MongoDB query
        query = {}

        if action and action in [
            "submit",
            "approve",
            "reject",
            "disburse",
            "schedule",
            "payment",
            "penalty_applied",
            "penalty_waived",
            "consent",
        ]:
            query["action"] = action

        if tx_status and tx_status in ["confirmed", "pending", "failed"]:
            query["status"] = tx_status

        if search:
            query["$or"] = [
                {"tx_hash": {"$regex": search, "$options": "i"}},
                {"loan_id": {"$regex": search, "$options": "i"}},
            ]

        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                query.setdefault("created_at", {})["$gte"] = start_dt
            except ValueError:
                pass

        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59
                )
                query.setdefault("created_at", {})["$lte"] = end_dt
            except ValueError:
                pass

        # Get collection
        db = getattr(settings, "MONGODB", None)
        if db is None:
            return success_response(
                data={
                    "transactions": [],
                    "total": 0,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": 0,
                },
                message="Blockchain not configured",
            )

        collection = db["blockchain_transactions"]

        # Get total count
        total = collection.count_documents(query)
        total_pages = (total + page_size - 1) // page_size

        # Get paginated results
        skip = (page - 1) * page_size
        cursor = (
            collection.find(query).sort("created_at", -1).skip(skip).limit(page_size)
        )

        transactions = []
        for doc in cursor:
            created_at = doc.get("created_at")
            completed_at = doc.get("completed_at")

            transactions.append(
                {
                    "id": str(doc.get("_id", "")),
                    "tx_hash": doc.get("tx_hash", ""),
                    "contract_name": doc.get("contract_name", ""),
                    "method": doc.get("method", ""),
                    "loan_id": doc.get("loan_id", ""),
                    "action": doc.get("action", ""),
                    "status": doc.get("status", ""),
                    "gas_used": doc.get("gas_used", 0),
                    "gas_price": doc.get("gas_price", 0),
                    "block_number": doc.get("block_number", 0),
                    "error": doc.get("error", ""),
                    "details": doc.get("details", {}),
                    "created_at": (
                        created_at.isoformat()
                        if hasattr(created_at, "isoformat")
                        else created_at
                    ),
                    "completed_at": (
                        completed_at.isoformat()
                        if hasattr(completed_at, "isoformat")
                        else completed_at
                    ),
                }
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
