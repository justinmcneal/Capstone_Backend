import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.validation_utils import sanitize_text
from analytics.models import AuditLog  # noqa: F401 - existing test patch target
from loans.models import (
    APPLICATION_STATUSES,
    LoanApplication,
    LoanProduct,
    LoanTransitionConflict,
)
from loans.serializers import LoanApplicationSerializer
from loans.services import (
    check_basic_eligibility,
    qualify_customer,
)
from loans.services.audit import record_loan_audit
from loans.services.product_rules import (
    ProductRuleViolation,
    normalized_recommendation,
    validate_application_terms,
)
from loans.services.related_data import find_models, model_map_by_ids
from loans.services.settlement_policy import SettlementRailUnavailable

logger = logging.getLogger("loans")


from loans.views.customer.base import (
    CustomerRoleRequiredMixin,
    _safe_customer_display_name,
    _serialize_customer_application_detail,
)


class LoanApplyView(CustomerRoleRequiredMixin, APIView):
    """
    Submit a loan application.

    POST /api/loans/apply/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Submit loan application"""
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            user = request.user
            customer_id = user.customer_id

            serializer = LoanApplicationSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid application data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            data = serializer.validated_data
            product = LoanProduct.find_by_id(data["product_id"])

            if not product or not product.active:
                return error_response(
                    message="Loan product not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            requested_amount = float(data["requested_amount"])
            term_months = int(data["term_months"])

            try:
                validate_application_terms(product, requested_amount, term_months)
            except ProductRuleViolation as exc:
                return error_response(
                    message=exc.message,
                    errors={exc.field: exc.message},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Check basic eligibility
            basic = check_basic_eligibility(
                customer_id,
                product,
                requirements_scope="product",
                require_approved_documents=True,
            )
            if not basic["can_apply"]:
                return error_response(
                    message="Cannot apply - requirements not met",
                    errors={"missing": basic["missing_requirements"]},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Run AI qualification
            qualification = qualify_customer(
                customer_id=customer_id,
                product=product,
                requested_amount=requested_amount,
                term_months=term_months,
                purpose=data.get("purpose", ""),
                require_approved_documents=True,
            )

            # Final safety clamp before persisting recommendation.
            # This guarantees DB values stay within product limits.
            recommended_amount = normalized_recommendation(
                product, requested_amount, qualification
            )

            # Create application
            application = LoanApplication(
                customer_id=customer_id,
                product_id=data["product_id"],
                requested_amount=requested_amount,
                recommended_amount=recommended_amount,
                term_months=term_months,
                purpose=data.get("purpose", ""),
                eligibility_score=qualification.get("eligibility_score"),
                ai_recommendation=qualification,
                risk_category=qualification.get("risk_category"),
                preferred_disbursement_method=data.get("preferred_disbursement_method")
                or None,
            )
            application.submit()

            logger.info(
                f"Loan application submitted: {application.id} by {customer_id}"
            )

            # Send confirmation email to customer
            try:
                from notifications.services import get_email_sender

                sender = get_email_sender()
                sender.send_loan_submitted(
                    customer_email=user.email if hasattr(user, "email") else "",
                    customer_name=_safe_customer_display_name(user),
                    loan_id=application.id,
                    product_name=product.name,
                    amount=data["requested_amount"],
                    customer_id=customer_id,
                    delivery_key=application.last_transition_id,
                )
            except Exception as e:
                logger.warning(f"Failed to send loan submitted email: {e}")

            # Audit log
            record_loan_audit(
                action="loan_submitted",
                user_id=customer_id,
                user_type="customer",
                user_email=user.email if hasattr(user, "email") else "",
                description=f"Loan application submitted for {product.name} - ₱{data['requested_amount']:,.2f}",
                resource_type="loan",
                resource_id=application.id,
                details={
                    "product": product.name,
                    "amount": data["requested_amount"],
                    "term": data["term_months"],
                    "transition_id": application.last_transition_id,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            # Blockchain sync (background thread, no Celery needed)
            try:
                from loans.blockchain.sync import sync_application

                sync_application(application.id, application.last_transition_id)
            except Exception as e:
                logger.warning(
                    f"Blockchain sync skipped for application {application.id}: {e}"
                )

            return success_response(
                data={
                    "application_id": application.id,
                    "status": application.status,
                    "eligibility_score": application.eligibility_score,
                    "recommended_amount": application.recommended_amount,
                    "message": "Your application has been submitted for review",
                },
                message="Application submitted successfully",
                status_code=status.HTTP_201_CREATED,
            )

        except Exception as e:
            logger.error(f"Apply error: {str(e)}")
            return error_response(
                message="Failed to submit application",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MyApplicationsView(CustomerRoleRequiredMixin, APIView):
    """
    List customer's loan applications.

    GET /api/loans/applications/

    Query Parameters:
        search (str): Search by product name (case-insensitive)
        status (str): Filter by status (e.g., 'pending', 'approved', 'rejected', 'active')
        page (int): Page number for pagination (default: 1)
        page_size (int): Items per page (default: 20, max: 100)
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get all applications for current customer with optional filtering"""
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        # Get query parameters
        search_query = sanitize_text(request.query_params.get("search", "")).lower()
        status_filter = sanitize_text(request.query_params.get("status", "")).lower()
        allowed_status_filters = set(APPLICATION_STATUSES) | {"pending"}
        if status_filter and status_filter not in allowed_status_filters:
            return error_response(
                message="Invalid status filter",
                errors={
                    "status": f"status must be one of: {', '.join(sorted(allowed_status_filters))}"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
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

        query = {"customer_id": str(customer_id)}
        if status_filter == "pending":
            query["status"] = {"$in": ["submitted", "under_review"]}
        elif status_filter:
            query["status"] = status_filter
        if search_query:
            import re

            products = find_models(
                LoanProduct,
                {"name": {"$regex": re.escape(search_query), "$options": "i"}},
                limit=100,
            )
            product_ids = [product.id for product in products if product]
            if not product_ids:
                query["_id"] = {"$exists": False}
            else:
                query["product_id"] = {"$in": product_ids}

        total_count = LoanApplication.count(query)
        total_pages = (total_count + page_size - 1) // page_size if total_count else 1
        applications = LoanApplication.find(
            query,
            sort=[("created_at", -1)],
            skip=(page - 1) * page_size,
            limit=page_size,
        )
        products = model_map_by_ids(
            LoanProduct, [application.product_id for application in applications]
        )

        apps_data = []
        for app in applications:
            product = products.get(str(app.product_id))
            product_name = product.name if product else "Unknown"

            apps_data.append(
                {
                    "id": app.id,
                    "product_name": product_name,
                    "requested_amount": app.requested_amount,
                    "recommended_amount": app.recommended_amount,
                    "approved_amount": app.approved_amount,
                    "term_months": app.term_months,
                    "status": app.status,
                    "eligibility_score": app.eligibility_score,
                    "submitted_at": (
                        app.submitted_at.isoformat() if app.submitted_at else None
                    ),
                    "created_at": app.created_at.isoformat(),
                }
            )

        return success_response(
            data={
                "applications": apps_data,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1,
            },
            message="Applications retrieved",
        )


class ApplicationDetailView(CustomerRoleRequiredMixin, APIView):
    """
    Get application details.

    GET /api/loans/applications/<id>/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        app = LoanApplication.find_by_id(application_id)

        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )

        product = LoanProduct.find_by_id(app.product_id)

        return success_response(
            data=_serialize_customer_application_detail(app, product),
            message="Application details retrieved",
        )

    def put(self, request, application_id):
        """
        Edit a draft application and submit the same record for review.

        PUT /api/loans/applications/<id>/
        """
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            user = request.user
            customer_id = user.customer_id

            app = LoanApplication.find_by_id(application_id)
            if not app or app.customer_id != customer_id:
                return error_response(
                    message="Application not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            if app.status != "draft":
                return error_response(
                    message="Only draft applications can be edited and submitted",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            serializer = LoanApplicationSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid application data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            data = serializer.validated_data
            product = LoanProduct.find_by_id(app.product_id)
            if not product or not product.active:
                return error_response(
                    message="Loan product not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            incoming_product_id = data["product_id"]
            if incoming_product_id != app.product_id:
                return error_response(
                    message="Changing the loan product is not allowed for draft resubmission",
                    errors={"product_id": "Must match the original draft product"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            requested_amount = float(data["requested_amount"])
            term_months = int(data["term_months"])

            try:
                validate_application_terms(product, requested_amount, term_months)
            except ProductRuleViolation as exc:
                return error_response(
                    message=exc.message,
                    errors={exc.field: exc.message},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            basic = check_basic_eligibility(
                customer_id,
                product,
                requirements_scope="product",
                require_approved_documents=True,
            )
            if not basic["can_apply"]:
                return error_response(
                    message="Cannot apply - requirements not met",
                    errors={"missing": basic["missing_requirements"]},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            qualification = qualify_customer(
                customer_id=customer_id,
                product=product,
                requested_amount=requested_amount,
                term_months=term_months,
                purpose=data.get("purpose", ""),
                require_approved_documents=True,
            )

            recommended_amount = normalized_recommendation(
                product, requested_amount, qualification
            )

            app.requested_amount = requested_amount
            app.recommended_amount = recommended_amount
            app.term_months = term_months
            app.purpose = data.get("purpose", "")
            app.eligibility_score = qualification.get("eligibility_score")
            app.ai_recommendation = qualification
            app.risk_category = qualification.get("risk_category")
            if "preferred_disbursement_method" in data:
                app.preferred_disbursement_method = (
                    data["preferred_disbursement_method"] or None
                )
            try:
                app.submit()
            except LoanTransitionConflict:
                return error_response(
                    message="The application changed. Refresh and retry.",
                    code="LOAN_TRANSITION_CONFLICT",
                    status_code=status.HTTP_409_CONFLICT,
                )

            logger.info(
                f"Draft application updated and submitted: {app.id} by {customer_id}"
            )

            try:
                from notifications.services import get_email_sender

                sender = get_email_sender()
                sender.send_loan_submitted(
                    customer_email=user.email if hasattr(user, "email") else "",
                    customer_name=_safe_customer_display_name(user),
                    loan_id=app.id,
                    product_name=product.name,
                    amount=requested_amount,
                    customer_id=customer_id,
                    delivery_key=app.last_transition_id,
                )
            except Exception as e:
                logger.warning(f"Failed to send loan submitted email: {e}")

            record_loan_audit(
                action="loan_draft_updated_and_submitted",
                user_id=customer_id,
                user_type="customer",
                user_email=user.email if hasattr(user, "email") else "",
                description=f"Draft loan application updated and submitted for {product.name} - ₱{requested_amount:,.2f}",
                resource_type="loan",
                resource_id=app.id,
                details={
                    "product": product.name,
                    "amount": requested_amount,
                    "term": term_months,
                    "transition_id": app.last_transition_id,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            return success_response(
                data=_serialize_customer_application_detail(app, product),
                message="Application updated and submitted successfully",
            )
        except Exception as e:
            logger.error(f"Draft update submit error: {str(e)}")
            return error_response(
                message="Failed to update and submit application",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ResubmitApplicationView(CustomerRoleRequiredMixin, APIView):
    """
    Resubmit a rejected application.

    POST /api/loans/applications/<id>/resubmit/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        app = LoanApplication.find_by_id(application_id)

        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )

        if not app.can_resubmit():
            return error_response(
                message="Only rejected applications can be resubmitted",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            app.resubmit(actor_id=customer_id)
        except LoanTransitionConflict:
            return error_response(
                message="The application changed. Refresh and retry.",
                code="LOAN_TRANSITION_CONFLICT",
                status_code=status.HTTP_409_CONFLICT,
            )

        return success_response(
            data={
                "id": app.id,
                "status": app.status,
                "message": "Application reset to draft. Please update and resubmit.",
            },
            message="Application ready for resubmission",
        )


class RejectionFeedbackView(CustomerRoleRequiredMixin, APIView):
    """
    Get AI-powered friendly feedback about why application was rejected.

    GET /api/loans/applications/<id>/feedback/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        app = LoanApplication.find_by_id(application_id)

        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )

        if app.status != "rejected":
            return error_response(
                message="Feedback is only available for rejected applications",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Generate AI feedback
        try:
            from ai_assistant.services import get_llm_service

            llm = get_llm_service()

            prompt = f"""A loan application was rejected. Please explain this to the customer in a friendly, empathetic way.

Rejection reason: {app.rejection_reason or "Not specified"}
Officer notes: {app.officer_notes or "None provided"}

Provide:
1. A simple explanation of why it was rejected
2. What they can do to improve their chances
3. Encouragement to try again

Keep the response under 200 words and use a warm, supportive tone."""

            feedback = llm.generate(prompt)

        except Exception:
            # Fallback if AI unavailable
            feedback = f"""We understand this isn't the news you were hoping for.

Your application was not approved because: {app.rejection_reason or "The requirements were not fully met."}

What you can do:
• Review and update your profile information
• Ensure all documents are clear and valid
• Consider applying for a smaller amount

Don't give up! Many successful borrowers were approved on their second try."""

        return success_response(
            data={
                "rejection_reason": app.rejection_reason,
                "feedback": feedback,
                "can_resubmit": app.can_resubmit(),
            },
            message="Feedback retrieved",
        )


class SetDisbursementMethodView(CustomerRoleRequiredMixin, APIView):
    """
    Customer: Set preferred disbursement method after loan approval.

    POST /api/loans/applications/<id>/set-disbursement-method/
    Body: { "disbursement_method": "cash" | "check" | "wallet" }

    Wallet is available only when blockchain support is enabled.
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        app = LoanApplication.find_by_id(application_id)

        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found", status_code=status.HTTP_404_NOT_FOUND
            )

        disbursement_method = (
            sanitize_text(request.data.get("disbursement_method", "")).lower().strip()
        )

        if not disbursement_method:
            return error_response(
                message="disbursement_method is required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            app.set_preferred_disbursement_method(disbursement_method)
        except SettlementRailUnavailable as exc:
            return error_response(
                message=str(exc),
                code=exc.code,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ValueError as e:
            return error_response(
                message=str(e), status_code=status.HTTP_400_BAD_REQUEST
            )

        # AuditLog writes go through the observable loan-domain wrapper.
        record_loan_audit(
            action="disbursement_method_set",
            user_id=customer_id,
            user_type="customer",
            user_email=user.email if hasattr(user, "email") else "",
            description=f"Borrower set preferred disbursement method to {disbursement_method}",
            resource_type="loan",
            resource_id=app.id,
            details={
                "disbursement_method": disbursement_method,
            },
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )

        logger.info(
            f"Disbursement method set: {disbursement_method} "
            f"for application {app.id} by customer {customer_id}"
        )

        return success_response(
            data={
                "id": app.id,
                "status": app.status,
                "preferred_disbursement_method": app.preferred_disbursement_method,
            },
            message="Disbursement method saved successfully",
        )
