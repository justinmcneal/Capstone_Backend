from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId
from django.conf import settings

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text, parse_bool
from loans.models import LoanProduct, LoanApplication
from loans.serializers import (
    LoanReviewSerializer,
    MissingDocumentsRequestSerializer,
    ApplicationInternalNoteSerializer,
)
from analytics.models import AuditLog
from loans.utils.time import utcnow
import logging

logger = logging.getLogger("loans")


def serialize_internal_note(note):
    """Normalize a stored note entry for API responses."""
    if not note:
        return None

    created_at = note.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()

    return {
        "content": note.get("content", ""),
        "author_id": note.get("author_id"),
        "author_role": note.get("author_role"),
        "created_at": created_at,
    }


def internal_note_summary(app):
    notes = app.internal_notes or []
    latest = serialize_internal_note(notes[-1]) if notes else None
    return {
        "internal_notes_count": len(notes),
        "latest_internal_note": latest,
    }


class LoanOfficerRequiredMixin(AccessControlMixin):
    """Mixin to require loan officer or admin role"""

    def check_officer_permission(self, request):
        return self.require_officer_or_admin(request)

    @staticmethod
    def _actor_id(actor):
        """
        Resolve a stable actor ID across auth/user object types.

        - AuthenticatedUser wrapper uses `customer_id` for all roles
        - LoanOfficer/Admin domain models expose `.id`
        """
        value = (
            getattr(actor, "customer_id", None)
            or getattr(actor, "user_id", None)
            or getattr(actor, "id", None)
            or getattr(actor, "_id", None)
        )
        return str(value or "")

    def check_application_scope(self, request, application, allow_unassigned=True):
        return self.require_application_scope(
            request,
            application,
            allow_unassigned=allow_unassigned,
            conceal_existence=True,
        )


class OfficerApplicationListView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: List and search applications with advanced filtering.

    GET /api/loans/officer/applications/

    Query params:
        - status: Filter by status ('pending', 'mine', 'submitted', 'under_review', 'approved', 'rejected', 'disbursed')
        - search: Keyword search (customer name, product name, application ID)
        - min_amount: Minimum requested amount
        - max_amount: Maximum requested amount
        - start_date: Filter applications submitted on or after this date (YYYY-MM-DD)
        - end_date: Filter applications submitted on or before this date (YYYY-MM-DD)
        - risk_category: Filter by risk category ('low', 'medium', 'high')
        - page: Page number (default 1)
        - page_size: Items per page (default 20, max 100)
        - sort_by: Sort field ('submitted_at', 'requested_amount', 'eligibility_score')
        - sort_order: 'asc' or 'desc' (default 'desc')
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import re
        from datetime import datetime
        from accounts.models import Customer

        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result
        user = request.user
        user_role = getattr(user, "role", "")
        user_id = self._actor_id(user)

        # Extract query params
        status_filter = (
            sanitize_text(request.query_params.get("status", "pending")).lower()
            or "pending"
        )
        search_query = sanitize_text(request.query_params.get("search", ""))
        min_amount = sanitize_text(request.query_params.get("min_amount", ""))
        max_amount = sanitize_text(request.query_params.get("max_amount", ""))
        start_date = sanitize_text(request.query_params.get("start_date", ""))
        end_date = sanitize_text(request.query_params.get("end_date", ""))
        risk_category = sanitize_text(
            request.query_params.get("risk_category", "")
        ).lower()
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
        sort_by = sanitize_text(request.query_params.get("sort_by", "submitted_at"))
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

        valid_statuses = {
            "pending",
            "mine",
            "submitted",
            "under_review",
            "approved",
            "rejected",
            "disbursed",
            "all",
        }
        if status_filter not in valid_statuses:
            return error_response(
                message="Invalid status filter",
                errors={
                    "status": f"status must be one of: {', '.join(sorted(valid_statuses))}"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if risk_category and risk_category not in {"low", "medium", "high"}:
            return error_response(
                message="Invalid risk_category filter",
                errors={
                    "risk_category": "risk_category must be one of: low, medium, high"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        valid_sort_fields = {
            "submitted_at",
            "requested_amount",
            "eligibility_score",
            "created_at",
        }
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

        # Build base query
        query = {}

        # Status filter
        if status_filter == "pending":
            query["status"] = {"$in": ["submitted", "under_review"]}
        elif status_filter == "mine":
            query["assigned_officer"] = user_id
        elif status_filter != "all":
            query["status"] = status_filter

        # ABAC scope: loan officers can only access their own assigned apps.
        if user_role == "loan_officer":
            query["assigned_officer"] = user_id

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
            query.setdefault("requested_amount", {})["$gte"] = parsed_min_amount
        if max_amount:
            try:
                parsed_max_amount = float(max_amount)
            except ValueError:
                return error_response(
                    message="Invalid max_amount filter",
                    errors={"max_amount": "max_amount must be a number"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            query.setdefault("requested_amount", {})["$lte"] = parsed_max_amount
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
                query.setdefault("submitted_at", {})["$gte"] = start_dt
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
                query.setdefault("submitted_at", {})["$lte"] = end_dt
            except ValueError:
                return error_response(
                    message="Invalid end_date filter",
                    errors={"end_date": "end_date must use YYYY-MM-DD format"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        # Risk category filter
        if risk_category:
            query["risk_category"] = risk_category

        # Keyword search - need to handle customer name search
        customer_ids = []
        if search_query:
            # First, search for matching customers
            regex = re.compile(f".*{re.escape(search_query)}.*", re.IGNORECASE)
            customers = Customer.find(
                {
                    "$or": [
                        {"first_name": regex},
                        {"last_name": regex},
                        {"phone": regex},
                        {"email": regex},
                    ]
                }
            )
            customer_ids = [c.id for c in customers if c]

        # Get applications from database
        db = settings.MONGODB
        collection = db["loan_applications"]

        # Build final query with customer search
        final_query = query.copy()
        if search_query:
            search_conditions = [
                (
                    {"_id": {"$regex": re.escape(search_query), "$options": "i"}}
                    if len(search_query) == 24
                    else {}
                ),
            ]
            if customer_ids:
                search_conditions.append({"customer_id": {"$in": customer_ids}})

            # Product name search happens after DB query
            final_query = (
                {
                    "$and": [
                        query,
                        (
                            {"$or": search_conditions}
                            if search_conditions and any(search_conditions)
                            else {}
                        ),
                    ]
                }
                if customer_ids
                else query
            )

        # Sorting
        sort_field = sort_by
        sort_direction = 1 if sort_order == "asc" else -1

        # Get total count for pagination
        total_count = collection.count_documents(final_query if final_query else query)

        # Get paginated results
        skip = (page - 1) * page_size
        cursor = (
            collection.find(final_query if final_query else query)
            .sort(sort_field, sort_direction)
            .skip(skip)
            .limit(page_size)
        )

        applications = [LoanApplication.from_dict(doc) for doc in cursor]

        # Build response with product names
        apps_data = []
        for app in applications:
            if not app:
                continue
            product = LoanProduct.find_by_id(app.product_id)
            product_name = product.name if product else "Unknown"

            # Secondary filter: product name search (if search query provided)
            if search_query and search_query.lower() not in product_name.lower():
                if not customer_ids or app.customer_id not in customer_ids:
                    if search_query.lower() not in (app.id or "").lower():
                        continue

            # Get customer name for display
            customer = None
            if app.customer_id:
                try:
                    customer = Customer.find_one({"_id": ObjectId(app.customer_id)})
                except Exception:
                    pass
            customer_name = (
                f"{customer.first_name} {customer.last_name}" if customer else "Unknown"
            )

            apps_data.append(
                {
                    "id": app.id,
                    "customer_id": app.customer_id,
                    "customer_name": customer_name,
                    "product_name": product_name,
                    "requested_amount": app.requested_amount,
                    "recommended_amount": app.recommended_amount,
                    "approved_amount": app.approved_amount,
                    "term_months": app.term_months,
                    "status": app.status,
                    "eligibility_score": app.eligibility_score,
                    "risk_category": app.risk_category,
                    "assigned_officer": app.assigned_officer,
                    "assigned_officer_name": None,
                    "submitted_at": (
                        app.submitted_at.isoformat() if app.submitted_at else None
                    ),
                    "decision_date": (
                        app.decision_date.isoformat() if app.decision_date else None
                    ),
                    **internal_note_summary(app),
                }
            )

        # Resolve assigned officer names
        from accounts.models.loan_officer import LoanOfficer as LO

        officer_ids = {
            a["assigned_officer"] for a in apps_data if a.get("assigned_officer")
        }
        officer_name_map = {}
        for oid in officer_ids:
            try:
                o = LO.find_one({"_id": ObjectId(oid)})
                if o:
                    officer_name_map[oid] = (
                        f"{o.first_name} {o.last_name}".strip() or "Unknown"
                    )
            except Exception:
                pass
        for a in apps_data:
            if a.get("assigned_officer"):
                a["assigned_officer_name"] = officer_name_map.get(a["assigned_officer"])

        return success_response(
            data={
                "applications": apps_data,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": (total_count + page_size - 1) // page_size,
            },
            message="Applications retrieved",
        )


class OfficerApplicationDetailView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: View application details with complete customer data.

    GET /api/loans/officer/applications/<id>/

    Returns:
        - Application details
        - Product info
        - Complete customer profiles (personal, business, alternative)
        - Customer documents with verification status
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

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

        product = LoanProduct.find_by_id(app.product_id)

        # Get complete customer profiles
        from profiles.models import CustomerProfile, BusinessProfile, AlternativeData
        from documents.models import Document
        from accounts.models import Customer
        from bson import ObjectId

        customer = Customer.find_one({"_id": ObjectId(app.customer_id)})
        personal = CustomerProfile.get_or_create(app.customer_id)
        business = BusinessProfile.get_or_create(app.customer_id)
        alternative = AlternativeData.get_or_create(app.customer_id)
        documents = Document.find_by_customer(app.customer_id)

        # Build customer data
        customer_data = {
            "customer_id": app.customer_id,
            "email": customer.email if customer else None,
            "personal_profile": {
                "first_name": customer.first_name if customer else None,
                "last_name": customer.last_name if customer else None,
                "phone_number": personal.mobile_number
                or (customer.phone if customer else None),
                "civil_status": personal.civil_status,
                "city_municipality": personal.city_municipality,
                "province": personal.province,
                "barangay": personal.barangay,
                "street_address": personal.address_line1,
                "emergency_contact_name": personal.emergency_contact_name,
                "emergency_contact_phone": personal.emergency_contact_phone,
                "wallet_address": personal.wallet_address,
                "profile_completed": personal.profile_completed,
                "completion_percentage": personal.completion_percentage,
            },
            "business_profile": {
                "business_name": business.business_name,
                "business_type": business.business_type,
                "business_address": business.business_address,
                "business_age_months": business.business_age_months,
                "is_registered": business.is_registered,
                "income_range": business.income_range,
                "estimated_monthly_income": (
                    float(business.estimated_monthly_income)
                    if business.estimated_monthly_income
                    else None
                ),
                "number_of_employees": business.number_of_employees,
                "business_description": business.business_description,
            },
            "alternative_data": {
                "education_level": alternative.education_level,
                "employment_status": alternative.employment_status,
                "housing_status": alternative.housing_status,
                "years_at_residence": alternative.years_at_current_address,
                "has_bank_account": alternative.has_bank_account,
                "has_ewallet": alternative.has_ewallet,
                "ewallet_usage": alternative.ewallet_usage,
                "has_existing_loans": alternative.has_existing_loans,
                "utility_payment_history": alternative.utility_payment_history,
                "risk_score": alternative.risk_score,
                "risk_category": alternative.risk_category,
            },
        }

        # Build documents data
        from documents.storage import get_storage_backend

        storage = get_storage_backend()

        documents_data = [
            {
                "id": doc.id,
                "document_type": doc.document_type,
                "filename": doc.original_filename,
                "file_url": storage.get_url(doc.file_path),
                "file_size": doc.file_size,
                "status": doc.status,
                "verified": doc.verified,
                "verified_at": doc.verified_at.isoformat() if doc.verified_at else None,
                "reupload_requested": doc.reupload_requested,
                "reupload_reason": doc.reupload_reason,
                "ai_analysis": doc.ai_analysis,
                "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            }
            for doc in documents
        ]

        # Resolve assigned officer name
        assigned_officer_name = None
        if app.assigned_officer:
            try:
                from accounts.models.loan_officer import LoanOfficer

                officer = LoanOfficer.find_one({"_id": ObjectId(app.assigned_officer)})
                if officer:
                    assigned_officer_name = (
                        f"{officer.first_name} {officer.last_name}".strip() or None
                    )
            except Exception:
                pass

        # Build customer name
        customer_name = (
            f"{customer.first_name} {customer.last_name}".strip()
            if customer
            else "Unknown"
        )

        return success_response(
            data={
                "id": app.id,
                "customer_id": app.customer_id,
                "customer_name": customer_name,
                "product": {
                    "id": product.id if product else None,
                    "name": product.name if product else "Unknown",
                    "code": product.code if product else None,
                    "required_documents": product.required_documents if product else [],
                },
                "requested_amount": app.requested_amount,
                "recommended_amount": app.recommended_amount,
                "approved_amount": app.approved_amount,
                "term_months": app.term_months,
                "purpose": app.purpose,
                "status": app.status,
                "eligibility_score": app.eligibility_score,
                "risk_category": app.risk_category,
                "ai_recommendation": app.ai_recommendation,
                "assigned_officer": app.assigned_officer,
                "assigned_officer_name": assigned_officer_name,
                "officer_notes": app.officer_notes,
                "rejection_reason": app.rejection_reason,
                "submitted_at": (
                    app.submitted_at.isoformat() if app.submitted_at else None
                ),
                "decision_date": (
                    app.decision_date.isoformat() if app.decision_date else None
                ),
                "disbursed_amount": app.disbursed_amount,
                "preferred_disbursement_method": app.preferred_disbursement_method,
                "disbursement_method": app.disbursement_method,
                "disbursement_reference": app.disbursement_reference,
                "disbursed_at": (
                    app.disbursed_at.isoformat() if app.disbursed_at else None
                ),
                # ETH disbursement details (populated after wallet disbursement)
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
                "internal_notes": [
                    serialize_internal_note(note) for note in (app.internal_notes or [])
                ],
                **internal_note_summary(app),
                "missing_documents_requested": app.missing_documents_requested,
                "missing_documents_reason": app.missing_documents_reason,
                "missing_documents_requested_at": (
                    app.missing_documents_requested_at.isoformat()
                    if app.missing_documents_requested_at
                    else None
                ),
                # New: Complete customer data
                "customer": customer_data,
                "documents": documents_data,
            },
            message="Application details retrieved",
        )


class OfficerApplicationNotesView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer/Admin: Add standalone internal notes on an application.

    POST /api/loans/officer/applications/<id>/notes/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, user = self.check_officer_permission(request)
        if not has_permission:
            return user

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

        if app.status in ["draft", "cancelled"]:
            return error_response(
                message=f"Cannot add notes for application with status: {app.status}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ApplicationInternalNoteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid note data",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            app.add_internal_note(
                author_id=self._actor_id(user),
                author_role=getattr(user, "role", "loan_officer"),
                content=serializer.validated_data["note"],
            )
        except ValueError as e:
            return error_response(
                message=str(e), status_code=status.HTTP_400_BAD_REQUEST
            )

        latest_note = serialize_internal_note((app.internal_notes or [])[-1])
        AuditLog.log_action(
            action="loan_internal_note_added",
            user_id=self._actor_id(user),
            user_type=getattr(user, "role", "loan_officer"),
            description="Added internal note to loan application",
            resource_type="loan",
            resource_id=app.id,
            details={
                "customer_id": app.customer_id,
                "note_preview": serializer.validated_data["note"][:120],
            },
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )

        return success_response(
            data={
                "id": app.id,
                "status": app.status,
                "internal_notes_count": len(app.internal_notes or []),
                "latest_internal_note": latest_note,
            },
            message="Internal note saved",
        )


class OfficerRequestMissingDocumentsView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Request missing documents that have not been uploaded yet.

    POST /api/loans/officer/applications/<id>/request-missing-documents/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, user = self.check_officer_permission(request)
        if not has_permission:
            return user

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

        if app.status not in ["submitted", "under_review"]:
            return error_response(
                message=f"Cannot request documents for application with status: {app.status}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = MissingDocumentsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid missing document request data",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        officer_id = self._actor_id(user)

        from documents.models import Document

        uploaded_docs = Document.find_by_customer(app.customer_id)
        uploaded_types = {doc.document_type for doc in uploaded_docs}

        already_uploaded = [
            document_type
            for document_type in data["missing_documents"]
            if document_type in uploaded_types
        ]
        if already_uploaded:
            return error_response(
                message="Some selected documents are already uploaded",
                errors={"already_uploaded": already_uploaded},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            app.request_missing_documents(
                officer_id=officer_id,
                missing_documents=data["missing_documents"],
                reason=data.get("reason", ""),
            )
        except ValueError as e:
            return error_response(
                message=str(e), status_code=status.HTTP_400_BAD_REQUEST
            )

        # Audit log
        AuditLog.log_action(
            action="loan_missing_documents_requested",
            user_id=officer_id,
            user_type="loan_officer",
            description="Requested missing documents for loan application",
            resource_type="loan",
            resource_id=app.id,
            details={
                "customer_id": app.customer_id,
                "missing_documents": app.missing_documents_requested,
                "reason": app.missing_documents_reason,
            },
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )

        # Send email notification to customer
        customer = None
        if app.customer_id:
            try:
                from accounts.models import Customer

                customer = Customer.find_one({"_id": ObjectId(app.customer_id)})
            except Exception:
                customer = None

        if customer and customer.email:
            try:
                from notifications.services import get_email_sender

                sender = get_email_sender()
                sender.send_missing_documents_requested(
                    customer_email=customer.email,
                    customer_name=f"{customer.first_name} {customer.last_name}".strip()
                    or "Customer",
                    loan_id=app.id,
                    missing_documents=app.missing_documents_requested,
                    reason=app.missing_documents_reason,
                    customer_id=app.customer_id,
                )
            except Exception as e:
                logger.warning(f"Failed to send missing documents email: {e}")

        return success_response(
            data={
                "id": app.id,
                "status": app.status,
                "missing_documents_requested": app.missing_documents_requested,
                "missing_documents_reason": app.missing_documents_reason,
                "missing_documents_requested_at": (
                    app.missing_documents_requested_at.isoformat()
                    if app.missing_documents_requested_at
                    else None
                ),
            },
            message="Missing document request sent",
        )


class OfficerReviewView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Approve or reject application.

    PUT /api/loans/officer/applications/<id>/review/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def put(self, request, application_id):
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

        # Can only review submitted/under_review applications
        if app.status not in ["submitted", "under_review"]:
            return error_response(
                message=f"Cannot review application with status: {app.status}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = LoanReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid review data",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        officer_id = self._actor_id(user)

        # Get customer email for notification
        from accounts.models import Customer

        customer = None
        if app.customer_id:
            try:
                customer = Customer.find_one({"_id": ObjectId(app.customer_id)})
            except Exception:
                pass
        customer_email = customer.email if customer else None
        customer_name = (
            f"{customer.first_name} {customer.last_name}" if customer else "Customer"
        )

        if data["action"] == "approve":
            app.approve(
                officer_id=officer_id,
                approved_amount=data["approved_amount"],
                notes=data.get("notes", ""),
            )
            logger.info(f"Application approved: {app.id} by {officer_id}")
            message = "Application approved"

            # Audit log for approval
            AuditLog.log_action(
                action="loan_approved",
                user_id=officer_id,
                user_type="loan_officer",
                description=f'Loan application approved - ₱{data["approved_amount"]:,.2f}',
                resource_type="loan",
                resource_id=app.id,
                details={
                    "approved_amount": data["approved_amount"],
                    "customer_id": app.customer_id,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            # Send approval email
            if customer_email:
                try:
                    from notifications.services import get_email_sender

                    sender = get_email_sender()
                    sender.send_loan_approved(
                        customer_email=customer_email,
                        customer_name=customer_name,
                        loan_id=app.id,
                        approved_amount=data["approved_amount"],
                        customer_id=app.customer_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send approval email: {e}")

            # Blockchain sync — approval (background thread, no Celery needed)
            try:
                from loans.blockchain.sync import sync_approval

                sync_approval(app.id)
            except Exception as e:
                logger.warning(f"Blockchain sync skipped for approval {app.id}: {e}")

        else:
            app.reject(
                officer_id=officer_id,
                reason=data["rejection_reason"],
                notes=data.get("notes", ""),
            )
            logger.info(f"Application rejected: {app.id} by {officer_id}")
            message = "Application rejected"

            # Audit log for rejection
            AuditLog.log_action(
                action="loan_rejected",
                user_id=officer_id,
                user_type="loan_officer",
                description=f'Loan application rejected - {data["rejection_reason"][:50]}',
                resource_type="loan",
                resource_id=app.id,
                details={
                    "reason": data["rejection_reason"],
                    "customer_id": app.customer_id,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            # Send rejection email
            if customer_email:
                try:
                    from notifications.services import get_email_sender

                    sender = get_email_sender()
                    sender.send_loan_rejected(
                        customer_email=customer_email,
                        customer_name=customer_name,
                        loan_id=app.id,
                        reason=data["rejection_reason"],
                        customer_id=app.customer_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send rejection email: {e}")
            # Blockchain sync — rejection (background thread, no Celery needed)
            try:
                from loans.blockchain.sync import sync_rejection

                sync_rejection(app.id)
            except Exception as e:
                logger.warning(f"Blockchain sync skipped for rejection {app.id}: {e}")

        return success_response(
            data={
                "id": app.id,
                "status": app.status,
                "approved_amount": app.approved_amount,
            },
            message=message,
        )


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
                description=f"Loan disbursed - ₱{amount:,.2f} via {method}",
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
                from loans.models import LoanProduct, RepaymentSchedule

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
        from loans.models import RepaymentSchedule, LoanPayment

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

        # VALIDATION 2: Prevent duplicate payment on fully paid installments
        if installment.get("status") == "paid":
            return error_response(
                message=f"Installment #{installment_number} is already fully paid",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # VALIDATION 3: Prevent overpayment (allow 1 cent tolerance for float noise)
        remaining = installment["total_amount"] - installment.get("paid_amount", 0)
        if amount - remaining > 0.01:
            return error_response(
                message=f"Amount exceeds remaining balance of ₱{remaining:.2f}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # VALIDATION 4: Warn about skipped installments (don't block, just track)
        unpaid_before = schedule.count_unpaid_before(installment_number)

        # Record payment in schedule
        updated_installment = schedule.record_payment(installment_number, amount)

        # Create payment record
        payment = LoanPayment(
            loan_id=loan_id,
            schedule_id=schedule.id,
            customer_id=schedule.customer_id,
            installment_number=installment_number,
            amount=amount,
            payment_method=payment_method,
            reference=reference,
            notes=notes,
            recorded_by=self._actor_id(user),
        )
        payment.save()

        logger.info(
            f"Payment recorded: {amount} for loan {loan_id} installment {installment_number}"
        )

        # Audit log for payment
        AuditLog.log_action(
            action="payment_recorded",
            user_id=self._actor_id(user),
            user_type="loan_officer",
            description=f"Payment recorded - ₱{amount:,.2f} for installment #{installment_number}",
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
            },
            message=(
                "Payment recorded successfully"
                if unpaid_before == 0
                else f"Payment recorded. Note: {unpaid_before} earlier installment(s) still unpaid."
            ),
            status_code=status.HTTP_201_CREATED,
        )


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

        from loans.models import RepaymentSchedule, LoanProduct
        from accounts.models import Customer

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
            import re

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
                    "next_due_amount": (
                        next_payment["total_amount"] if next_payment else None
                    ),
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


class OfficerScheduleView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Get repayment schedule for a loan.

    GET /api/loans/officer/applications/<id>/schedule/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

        # Get application
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

        # Only disbursed loans have schedules
        if app.status != "disbursed":
            return error_response(
                message="Repayment schedule is only available for disbursed loans",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        from loans.models import RepaymentSchedule

        schedule = RepaymentSchedule.find_by_loan(application_id)

        if not schedule:
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Format installments
        installments = []
        now = utcnow()
        for inst in schedule.installments:
            due_date = inst.get("due_date")
            inst_status = inst.get("status", "pending")
            if (
                inst_status == "pending"
                and due_date
                and hasattr(due_date, "date")
                and due_date.date() < now.date()
            ):
                # Derive overdue dynamically so stale pending records still show correctly.
                inst_status = "overdue"

            penalty_applied_at = inst.get("penalty_applied_at")
            if hasattr(penalty_applied_at, "isoformat"):
                penalty_applied_at = penalty_applied_at.isoformat()
            penalty_waived_at = inst.get("penalty_waived_at")
            if hasattr(penalty_waived_at, "isoformat"):
                penalty_waived_at = penalty_waived_at.isoformat()

            installments.append(
                {
                    "number": inst["number"],
                    "due_date": due_date.isoformat() if due_date else None,
                    "principal": inst["principal"],
                    "interest": inst["interest"],
                    "total_amount": inst["total_amount"],
                    "status": inst_status,
                    "paid_amount": inst.get("paid_amount", 0),
                    "penalty_status": inst.get("penalty_status"),
                    "penalty_amount": inst.get("penalty_amount"),
                    "penalty_reason": inst.get("penalty_reason", ""),
                    "penalty_applied_at": penalty_applied_at,
                    "penalty_applied_by": inst.get("penalty_applied_by"),
                    "penalty_waived_at": penalty_waived_at,
                    "penalty_waived_by": inst.get("penalty_waived_by"),
                    "penalty_waived_reason": inst.get("penalty_waived_reason", ""),
                }
            )

        return success_response(
            data={
                "loan_id": schedule.loan_id,
                "principal": schedule.principal,
                "interest_rate": schedule.interest_rate,
                "term_months": schedule.term_months,
                "monthly_payment": schedule.monthly_payment,
                "total_amount": schedule.total_amount,
                "total_interest": schedule.total_interest,
                "paid_count": schedule.get_paid_count(),
                "remaining_balance": schedule.get_remaining_balance(),
                "next_payment": schedule.get_next_payment(),
                "installments": installments,
            },
            message="Repayment schedule retrieved",
        )


class ApplyPenaltyView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Apply penalty to a repayment installment.

    POST /api/loans/officer/applications/<id>/penalties/apply/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

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

        if app.status != "disbursed":
            return error_response(
                message="Penalties can only be applied to disbursed loans",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        installment_number_raw = request.data.get("installment_number")
        amount_raw = request.data.get("penalty_amount")
        reason = sanitize_text(request.data.get("reason", ""))

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

        if amount_raw in (None, ""):
            return error_response(
                message="penalty_amount is required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            penalty_amount = float(amount_raw)
        except (TypeError, ValueError):
            return error_response(
                message="penalty_amount must be a valid number",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if penalty_amount <= 0:
            return error_response(
                message="penalty_amount must be greater than 0",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        from loans.models import RepaymentSchedule

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
            return error_response(
                message=f"Installment #{installment_number} is already paid",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if installment.get("penalty_status") == "applied":
            return error_response(
                message=f"Penalty already applied for installment #{installment_number}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        actor_id = self._actor_id(request.user)
        now = utcnow()
        for i, inst in enumerate(schedule.installments):
            if inst.get("number") == installment_number:
                inst["penalty_status"] = "applied"
                inst["penalty_amount"] = round(penalty_amount, 2)
                inst["penalty_reason"] = reason
                inst["penalty_applied_at"] = now
                inst["penalty_applied_by"] = actor_id
                inst["penalty_waived_at"] = None
                inst["penalty_waived_by"] = None
                inst["penalty_waived_reason"] = ""
                schedule.installments[i] = inst
                break
        schedule.save()

        AuditLog.log_action(
            action="penalty_applied",
            user_id=actor_id,
            user_type="loan_officer",
            description=f"Penalty applied - ₱{penalty_amount:,.2f} for installment #{installment_number}",
            resource_type="penalty",
            resource_id=f"{application_id}:{installment_number}",
            details={
                "loan_id": application_id,
                "installment_number": installment_number,
                "amount": penalty_amount,
                "reason": reason,
            },
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )

        # Blockchain sync — penalty apply (background thread, no Celery needed)
        try:
            from loans.blockchain.sync import sync_penalty

            sync_penalty(
                application_id, installment_number, penalty_amount, "apply", reason
            )
        except Exception as e:
            logger.warning(
                f"Blockchain sync skipped for penalty apply {application_id}: {e}"
            )

        return success_response(
            data={
                "loan_id": application_id,
                "installment_number": installment_number,
                "penalty_status": "applied",
                "penalty_amount": round(penalty_amount, 2),
                "penalty_reason": reason,
                "penalty_applied_at": now.isoformat(),
                "penalty_applied_by": actor_id,
            },
            message="Penalty applied successfully",
            status_code=status.HTTP_201_CREATED,
        )


class WaivePenaltyView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Waive penalty for a repayment installment.

    POST /api/loans/officer/applications/<id>/penalties/waive/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result

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

        if app.status != "disbursed":
            return error_response(
                message="Penalties can only be waived for disbursed loans",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        installment_number_raw = request.data.get("installment_number")
        reason = sanitize_text(request.data.get("reason", ""))

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

        from loans.models import RepaymentSchedule

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
        if installment.get("penalty_status") != "applied":
            return error_response(
                message=f"No applied penalty found for installment #{installment_number}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        penalty_amount = float(installment.get("penalty_amount", 0) or 0)
        actor_id = self._actor_id(request.user)
        now = utcnow()
        for i, inst in enumerate(schedule.installments):
            if inst.get("number") == installment_number:
                inst["penalty_status"] = "waived"
                inst["penalty_waived_at"] = now
                inst["penalty_waived_by"] = actor_id
                inst["penalty_waived_reason"] = reason
                schedule.installments[i] = inst
                break
        schedule.save()

        AuditLog.log_action(
            action="penalty_waived",
            user_id=actor_id,
            user_type="loan_officer",
            description=f"Penalty waived - ₱{penalty_amount:,.2f} for installment #{installment_number}",
            resource_type="penalty",
            resource_id=f"{application_id}:{installment_number}",
            details={
                "loan_id": application_id,
                "installment_number": installment_number,
                "amount": penalty_amount,
                "reason": reason,
            },
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )

        # Blockchain sync — penalty waive (background thread, no Celery needed)
        try:
            from loans.blockchain.sync import sync_penalty

            sync_penalty(
                application_id, installment_number, penalty_amount, "waive", reason
            )
        except Exception as e:
            logger.warning(
                f"Blockchain sync skipped for penalty waive {application_id}: {e}"
            )

        return success_response(
            data={
                "loan_id": application_id,
                "installment_number": installment_number,
                "penalty_status": "waived",
                "penalty_amount": round(penalty_amount, 2),
                "penalty_waived_at": now.isoformat(),
                "penalty_waived_by": actor_id,
                "penalty_waived_reason": reason,
            },
            message="Penalty waived successfully",
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

        from loans.models import LoanPayment

        payments = LoanPayment.find_by_loan(application_id)

        payments_data = [
            {
                "id": p.id,
                "amount": p.amount,
                "payment_method": p.payment_method,
                "reference": p.reference,
                "installment_number": p.installment_number,
                "notes": p.notes,
                "recorded_at": p.recorded_at.isoformat() if p.recorded_at else None,
            }
            for p in payments
        ]

        total_paid = sum(p.amount for p in payments)

        return success_response(
            data={
                "payments": payments_data,
                "total_paid": total_paid,
                "count": len(payments_data),
            },
            message="Payment history retrieved",
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
        from loans.models import LoanPayment, RepaymentSchedule

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
                if not app or app.status != "disbursed":
                    return _empty_payment_result()
                allowed_loan_ids = [loan_id]
            else:
                app_collection = settings.MONGODB["loan_applications"]
                disbursed_ids = app_collection.distinct("_id", {"status": "disbursed"})
                allowed_loan_ids = [str(app_id) for app_id in disbursed_ids]
                if not allowed_loan_ids:
                    return _empty_payment_result()

        # ABAC scope for loan officers: only payments for assigned applications.
        if user_role == "loan_officer":
            app_collection = settings.MONGODB["loan_applications"]
            officer_assigned_ids = [
                str(doc["_id"])
                for doc in app_collection.find(
                    {"assigned_officer": user_id}, {"_id": 1}
                )
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
            # Search for customers
            regex = re.compile(f".*{re.escape(search_query)}.*", re.IGNORECASE)
            customers = Customer.find(
                {"$or": [{"first_name": regex}, {"last_name": regex}, {"phone": regex}]}
            )
            customer_ids = [c.id for c in customers if c]

            # Also search by reference
            search_regex = re.compile(f".*{re.escape(search_query)}.*", re.IGNORECASE)

        # Get payments from database
        db = settings.MONGODB
        collection = db["loan_payments"]

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
            all_cursor = collection.find(final_query).sort(sort_field, sort_direction)
            all_payments = [LoanPayment.from_dict(doc) for doc in all_cursor]

            status_filtered = []
            for payment in all_payments:
                if not payment:
                    continue
                status_value, _ = resolve_payment_status(payment)
                if status_value == payment_status:
                    status_filtered.append(payment)

            total_count = len(status_filtered)
            skip = (page - 1) * page_size
            payments = status_filtered[skip : skip + page_size]
        else:
            total_count = collection.count_documents(final_query)
            skip = (page - 1) * page_size
            cursor = (
                collection.find(final_query)
                .sort(sort_field, sort_direction)
                .skip(skip)
                .limit(page_size)
            )
            payments = [LoanPayment.from_dict(doc) for doc in cursor]

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

        # Calculate summary stats
        total_amount = sum(p["amount"] for p in payments_data)

        return success_response(
            data={
                "payments": payments_data,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": (total_count + page_size - 1) // page_size,
                "summary": {"total_amount": total_amount, "count": len(payments_data)},
            },
            message="Payments retrieved",
        )


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

        explorer_url = getattr(settings, "BLOCKCHAIN_EXPLORER_URL", "")
        data = {
            "application_id": app.id,
            "blockchain_enabled": getattr(settings, "BLOCKCHAIN_ENABLED", False),
            "explorer_url": f"{explorer_url}/tx" if explorer_url else "",
            "tx_hashes": getattr(app, "blockchain_tx_hashes", {}),
            "transactions": [],
        }

        if getattr(settings, "BLOCKCHAIN_ENABLED", False):
            try:
                from loans.blockchain.models import BlockchainTransaction

                txs = BlockchainTransaction.find_by_loan(application_id)
                data["transactions"] = [tx.to_dict() for tx in txs]
            except Exception as e:
                logger.warning(f"Failed to fetch blockchain transactions: {e}")

            try:
                from loans.blockchain.services.audit_service import get_audit_trail

                trail = get_audit_trail(application_id)
                data["audit_trail"] = trail
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

        if not getattr(settings, "BLOCKCHAIN_ENABLED", False):
            return error_response(
                message="Blockchain is not enabled",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        from loans.blockchain.services.eth_price_service import (
            get_eth_php_rate,
            ExchangeRateUnavailableError,
        )

        try:
            rate_info = get_eth_php_rate()
        except ExchangeRateUnavailableError as e:
            return error_response(
                message=str(e), status_code=status.HTTP_503_SERVICE_UNAVAILABLE
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
