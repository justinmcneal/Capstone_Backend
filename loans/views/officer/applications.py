from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text
from rest_framework import status
from loans.models import LoanProduct, LoanApplication
from loans.serializers import (
    LoanReviewSerializer,
    MissingDocumentsRequestSerializer,
    ApplicationInternalNoteSerializer,
)
from analytics.models import AuditLog
from loans.utils.time import utcnow
from loans.utils.serialization import serialize_internal_note
from loans.views.officer.base import LoanOfficerRequiredMixin, internal_note_summary
from datetime import datetime
import logging

logger = logging.getLogger("loans")


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
            "cancelled",
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

        # Keyword search - need to handle customer name search with multi-word support
        customer_ids = []
        product_ids = []
        if search_query:
            # Split search query into terms for multi-word search
            search_terms = search_query.strip().split()

            if len(search_terms) == 1:
                # Single term - simple regex search
                regex = re.compile(f".*{re.escape(search_terms[0])}.*", re.IGNORECASE)
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

                # Search products
                products = LoanProduct.find({"name": regex})
                product_ids = [p.id for p in products if p]
            else:
                # Multiple terms - match all terms across customer fields
                customer_and_conditions = []
                for term in search_terms:
                    term_regex = re.compile(f".*{re.escape(term)}.*", re.IGNORECASE)
                    customer_and_conditions.append({
                        "$or": [
                            {"first_name": term_regex},
                            {"last_name": term_regex},
                            {"phone": term_regex},
                            {"email": term_regex},
                        ]
                    })

                customers = Customer.find({"$and": customer_and_conditions})
                customer_ids = [c.id for c in customers if c]

                # For products with multi-word search, all terms must appear in product name
                product_and_conditions = []
                for term in search_terms:
                    term_regex = re.compile(f".*{re.escape(term)}.*", re.IGNORECASE)
                    product_and_conditions.append({"name": term_regex})

                products = LoanProduct.find({"$and": product_and_conditions})
                product_ids = [p.id for p in products if p]

        # Build final query with customer and product search
        final_query = query.copy()
        if search_query:
            search_conditions = []

            # Application ID search (only if query looks like an ID)
            if len(search_query) >= 8:
                search_conditions.append(
                    {"_id": {"$regex": re.escape(search_query), "$options": "i"}}
                )

            # Customer ID search
            if customer_ids:
                search_conditions.append({"customer_id": {"$in": customer_ids}})

            # Product ID search
            if product_ids:
                search_conditions.append({"product_id": {"$in": product_ids}})

            # If we have search conditions, apply them
            if search_conditions:
                if query:
                    final_query = {"$and": [query, {"$or": search_conditions}]}
                else:
                    final_query = {"$or": search_conditions}
            else:
                # No matches found in customers or products, return empty result
                final_query = {"_id": {"$exists": False}}

        # Sorting
        sort_field = sort_by
        sort_direction = 1 if sort_order == "asc" else -1

        # Get total count for pagination
        total_count = LoanApplication.count(final_query if final_query else query)

        # Get paginated results
        skip = (page - 1) * page_size
        applications = LoanApplication.find(
            final_query if final_query else query,
            sort=[(sort_field, sort_direction)],
            skip=skip,
            limit=page_size,
        )

        # Build response with product names and customer names
        apps_data = []
        for app in applications:
            if not app:
                continue
            product = LoanProduct.find_by_id(app.product_id)
            product_name = product.name if product else "Unknown"

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
                "mobile_number": personal.mobile_number
                or (customer.phone if customer else None),
                "phone_number": personal.mobile_number
                or (customer.phone if customer else None),
                "date_of_birth": (
                    personal.date_of_birth.isoformat()
                    if personal.date_of_birth
                    else None
                ),
                "gender": personal.gender,
                "civil_status": personal.civil_status,
                "nationality": personal.nationality,
                "address_line1": personal.address_line1,
                "street_address": personal.address_line1,
                "address_line2": personal.address_line2,
                "barangay": personal.barangay,
                "city_municipality": personal.city_municipality,
                "province": personal.province,
                "zip_code": personal.zip_code,
                "emergency_contact_name": personal.emergency_contact_name,
                "emergency_contact_phone": personal.emergency_contact_phone,
                "emergency_contact_relationship": personal.emergency_contact_relationship,
                "wallet_address": personal.wallet_address,
                "profile_completed": personal.profile_completed,
                "completion_percentage": personal.completion_percentage,
            },
            "business_profile": {
                "business_name": business.business_name,
                "business_type": business.business_type,
                "business_type_other": business.business_type_other,
                "business_description": business.business_description,
                "business_address": business.business_address,
                "business_barangay": business.business_barangay,
                "business_city": business.business_city,
                "business_province": business.business_province,
                "business_age_months": business.business_age_months,
                "is_registered": business.is_registered,
                "registration_type": business.registration_type,
                "registration_number": business.registration_number,
                "estimated_monthly_income": (
                    float(business.estimated_monthly_income)
                    if business.estimated_monthly_income
                    else None
                ),
                "income_range": business.income_range,
                "estimated_monthly_expenses": (
                    float(business.estimated_monthly_expenses)
                    if business.estimated_monthly_expenses
                    else None
                ),
                "number_of_employees": business.number_of_employees,
            },
            "alternative_data": {
                "education_level": alternative.education_level,
                "employment_status": alternative.employment_status,
                "years_of_experience": alternative.years_of_experience,
                "housing_status": alternative.housing_status,
                "years_at_current_address": alternative.years_at_current_address,
                "years_at_residence": alternative.years_at_current_address,
                "monthly_rent": alternative.monthly_rent,
                "number_of_dependents": alternative.number_of_dependents,
                "household_income": alternative.household_income,
                "has_existing_loans": alternative.has_existing_loans,
                "existing_loan_amount": alternative.existing_loan_amount,
                "existing_loan_source": alternative.existing_loan_source,
                "loan_payment_history": alternative.loan_payment_history,
                "has_bank_account": alternative.has_bank_account,
                "bank_account_duration": alternative.bank_account_duration,
                "has_ewallet": alternative.has_ewallet,
                "ewallet_usage": alternative.ewallet_usage,
                "pays_utilities": alternative.pays_utilities,
                "utility_payment_history": alternative.utility_payment_history,
                "is_coop_member": alternative.is_coop_member,
                "community_involvement": alternative.community_involvement,
                "risk_score": alternative.risk_score,
                "risk_category": alternative.risk_category,
                "score_calculated_at": (
                    alternative.score_calculated_at.isoformat()
                    if alternative.score_calculated_at
                    else None
                ),
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
                "file_size_display": doc.file_size_display,
                "mime_type": doc.mime_type,
                "status": doc.status,
                "verified": doc.verified,
                "verified_by": str(doc.verified_by) if doc.verified_by else None,
                "verified_at": doc.verified_at.isoformat() if doc.verified_at else None,
                "rejection_reason": doc.rejection_reason or None,
                "reupload_requested": doc.reupload_requested,
                "reupload_reason": doc.reupload_reason or None,
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
            # Validate approved_amount does not exceed requested_amount
            if data["approved_amount"] > float(app.requested_amount):
                return error_response(
                    message=(
                        f"Approved amount (PHP{data['approved_amount']:,.2f}) cannot exceed "
                        f"requested amount (PHP{float(app.requested_amount):,.2f})"
                    ),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

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
                description=f'Loan application approved - PHP{data["approved_amount"]:,.2f}',
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
