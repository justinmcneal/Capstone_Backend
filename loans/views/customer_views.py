from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId
from django.conf import settings

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.throttles import PreQualifyRateThrottle
from accounts.utils.validation_utils import sanitize_text
from loans.models import LoanProduct, LoanApplication, APPLICATION_STATUSES
from loans.serializers import LoanApplicationSerializer, PreQualifyRequestSerializer
from loans.services import (
    qualify_customer,
    check_basic_eligibility,
    resolve_required_document_types,
)

from analytics.models import AuditLog
import logging

logger = logging.getLogger('loans')


class CustomerRoleRequiredMixin(AccessControlMixin):
    """Require customer role for customer-facing loan endpoints."""

    def check_customer_permission(self, request):
        return self.require_customer(request)


def _serialize_customer_application_detail(app, product):
    interest_rate_monthly_pct = None
    if product and product.interest_rate is not None:
        try:
            interest_rate_monthly_pct = round(float(product.interest_rate) * 100, 2)
        except (TypeError, ValueError):
            interest_rate_monthly_pct = None

    return {
        'id': app.id,
        'product': {
            'id': product.id if product else None,
            'name': product.name if product else 'Unknown'
        },
        'requested_amount': app.requested_amount,
        'recommended_amount': app.recommended_amount,
        'approved_amount': app.approved_amount,
        'term_months': app.term_months,
        'interest_rate': interest_rate_monthly_pct,
        'purpose': app.purpose,
        'status': app.status,
        'eligibility_score': app.eligibility_score,
        'risk_category': app.risk_category,
        'rejection_reason': app.rejection_reason,
        'submitted_at': app.submitted_at.isoformat() if app.submitted_at else None,
        'decision_date': app.decision_date.isoformat() if app.decision_date else None,
        'preferred_disbursement_method': app.preferred_disbursement_method,
        'disbursed_at': app.disbursed_at.isoformat() if app.disbursed_at else None,
        'created_at': app.created_at.isoformat()
    }


def _safe_customer_display_name(user):
    full_name = getattr(user, 'full_name', None)
    if isinstance(full_name, str) and full_name.strip():
        return full_name.strip()

    first_name = getattr(user, 'first_name', None)
    last_name = getattr(user, 'last_name', None)
    name_parts = [part.strip() for part in [first_name, last_name] if isinstance(part, str) and part.strip()]
    if name_parts:
        return ' '.join(name_parts)

    email = getattr(user, 'email', None)
    if isinstance(email, str) and email.strip():
        return email.strip()

    return 'Customer'


class LoanProductListView(CustomerRoleRequiredMixin, APIView):
    """
    List available loan products.
    
    GET /api/loans/products/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get all active loan products"""
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        products = LoanProduct.find(active_only=True)
        
        products_data = [{
            'id': p.id,
            'name': p.name,
            'code': p.code,
            'description': p.description,
            'min_amount': p.min_amount,
            'max_amount': p.max_amount,
            'interest_rate': p.interest_rate,
            'interest_rate_unit': 'decimal',
            'interest_rate_period': 'monthly',
            'interest_rate_display': f"{p.interest_rate * 100:.1f}% monthly",
            'min_term_months': p.min_term_months,
            'max_term_months': p.max_term_months,
            'required_documents': resolve_required_document_types(
                p,
                requirements_scope='product',
            ),
            'target_description': p.target_description
        } for p in products]
        
        return success_response(
            data={'products': products_data, 'total': len(products_data)},
            message="Loan products retrieved successfully"
        )


class LoanProductDetailView(CustomerRoleRequiredMixin, APIView):
    """
    Get loan product details.
    
    GET /api/loans/products/<id>/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, product_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        product = LoanProduct.find_by_id(product_id)
        
        if not product or not product.active:
            return error_response(
                message="Loan product not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        return success_response(
            data={
                'id': product.id,
                'name': product.name,
                'code': product.code,
                'description': product.description,
                'min_amount': product.min_amount,
                'max_amount': product.max_amount,
                'interest_rate': product.interest_rate,
                'interest_rate_unit': 'decimal',
                'interest_rate_period': 'monthly',
                'interest_rate_display': f"{product.interest_rate * 100:.1f}% monthly",
                'min_term_months': product.min_term_months,
                'max_term_months': product.max_term_months,
                'required_documents': resolve_required_document_types(
                    product,
                    requirements_scope='product',
                ),
                'min_business_months': product.min_business_months,
                'min_monthly_income': product.min_monthly_income,
                'target_description': product.target_description
            },
            message="Product details retrieved"
        )


class PreQualifyView(CustomerRoleRequiredMixin, APIView):
    """
    Check customer eligibility for a loan product.
    Uses AI to analyze profile and provide recommendations.
    
    POST /api/loans/pre-qualify/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [PreQualifyRateThrottle]
    
    def post(self, request):
        """Check eligibility for a loan"""
        try:
            has_permission, result = self.check_customer_permission(request)
            if not has_permission:
                return result

            user = request.user
            customer_id = user.customer_id

            serializer = PreQualifyRequestSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid pre-qualification data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            data = serializer.validated_data
            product_id = data['product_id']
            requested_amount = data['amount']
            term_months = data.get('term_months', 12)
            purpose = data.get('purpose', '')
            requirements_scope = data.get('requirements_scope')
            
            product = LoanProduct.find_by_id(product_id)
            if not product or not product.active:
                return error_response(
                    message="Loan product not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            # Validate amount
            if requested_amount < product.min_amount or requested_amount > product.max_amount:
                return error_response(
                    message=f"Amount must be between ₱{product.min_amount:,.0f} and ₱{product.max_amount:,.0f}",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Validate term against selected product
            if term_months < product.min_term_months or term_months > product.max_term_months:
                return error_response(
                    message=(
                        f"Term must be between {product.min_term_months} and "
                        f"{product.max_term_months} months"
                    ),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            
            # Quick eligibility check
            basic = check_basic_eligibility(
                customer_id,
                product,
                requirements_scope=requirements_scope,
                require_approved_documents=False,
            )
            if not basic['can_apply']:
                return success_response(
                    data={
                        'eligible': False,
                        'can_apply': False,
                        'missing_requirements': basic['missing_requirements'],
                        'requirements_scope': basic.get('requirements_scope', 'product'),
                        'required_documents_resolved': basic.get('required_documents_resolved', []),
                        'message': 'Please complete requirements before applying'
                    },
                    message="Eligibility check complete"
                )
            
            # AI Qualification
            qualification = qualify_customer(
                customer_id=customer_id,
                product=product,
                requested_amount=requested_amount,
                term_months=term_months,
                purpose=purpose,
                requirements_scope=requirements_scope,
                require_approved_documents=False,
            )

            recommended_amount = qualification.get('recommended_amount') or 0
            quote_amount = 0.0
            monthly_payment = 0.0
            total_interest = 0.0
            total_repayment = 0.0
            if qualification.get('eligible') and qualification.get('can_apply'):
                try:
                    quote_amount = float(recommended_amount)
                except (TypeError, ValueError):
                    quote_amount = 0.0

                if quote_amount > 0 and term_months > 0:
                    monthly_interest = quote_amount * float(product.interest_rate or 0.0)
                    total_interest = monthly_interest * term_months
                    total_repayment = quote_amount + total_interest
                    monthly_payment = total_repayment / term_months
            
            return success_response(
                data={
                    'product': {
                        'id': product.id,
                        'name': product.name
                    },
                    'requested_amount': requested_amount,
                    'term_months': term_months,
                    'eligible': qualification.get('eligible', False),
                    'eligibility_score': qualification.get('eligibility_score'),
                    'risk_category': qualification.get('risk_category'),
                    'recommended_amount': qualification.get('recommended_amount'),
                    'interest_rate': product.interest_rate,
                    'interest_rate_unit': 'decimal',
                    'interest_rate_period': 'monthly',
                    'interest_rate_display': f"{product.interest_rate * 100:.1f}% monthly",
                    'monthly_payment': round(monthly_payment, 2) if monthly_payment else 0.0,
                    'total_interest': round(total_interest, 2) if total_interest else 0.0,
                    'total_repayment': round(total_repayment, 2) if total_repayment else 0.0,
                    'reasoning': qualification.get('reasoning'),
                    'strengths': qualification.get('strengths', []),
                    'concerns': qualification.get('concerns', []),
                    'missing_requirements': qualification.get('missing_requirements', []),
                    'can_apply': qualification.get(
                        'can_apply',
                        qualification.get('eligible', False),
                    ),
                    'requirements_scope': qualification.get(
                        'requirements_scope',
                        basic.get('requirements_scope', 'product'),
                    ),
                    'required_documents_resolved': qualification.get(
                        'required_documents_resolved',
                        basic.get('required_documents_resolved', []),
                    ),
                },
                message="Pre-qualification complete"
            )
            
        except Exception as e:
            logger.error(f"Pre-qualify error: {str(e)}")
            return error_response(
                message="Failed to check eligibility",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
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
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            data = serializer.validated_data
            product = LoanProduct.find_by_id(data['product_id'])
            
            if not product or not product.active:
                return error_response(
                    message="Loan product not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )

            requested_amount = float(data['requested_amount'])
            term_months = int(data['term_months'])

            # Validate amount against selected product
            if requested_amount < product.min_amount or requested_amount > product.max_amount:
                return error_response(
                    message=f"Amount must be between ₱{product.min_amount:,.0f} and ₱{product.max_amount:,.0f}",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Validate term against selected product
            if term_months < product.min_term_months or term_months > product.max_term_months:
                return error_response(
                    message=(
                        f"Term must be between {product.min_term_months} and "
                        f"{product.max_term_months} months"
                    ),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            
            # Check basic eligibility
            basic = check_basic_eligibility(
                customer_id,
                product,
                requirements_scope='product',
                require_approved_documents=True,
            )
            if not basic['can_apply']:
                return error_response(
                    message="Cannot apply - requirements not met",
                    errors={'missing': basic['missing_requirements']},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Run AI qualification
            qualification = qualify_customer(
                customer_id=customer_id,
                product=product,
                requested_amount=requested_amount,
                term_months=term_months,
                purpose=data.get('purpose', ''),
                require_approved_documents=True,
            )

            # Final safety clamp before persisting recommendation.
            # This guarantees DB values stay within product limits.
            eligible_or_can_apply = bool(
                qualification.get('can_apply', qualification.get('eligible', False))
            )
            recommended_amount = qualification.get('recommended_amount', 0)

            if not eligible_or_can_apply:
                recommended_amount = 0.0
            else:
                try:
                    recommended_amount = float(recommended_amount)
                except (TypeError, ValueError):
                    recommended_amount = 0.0

                lower_bound = float(product.min_amount or 0)
                upper_bound = min(float(product.max_amount or 0), requested_amount)
                if upper_bound < lower_bound:
                    upper_bound = lower_bound

                recommended_amount = max(lower_bound, min(recommended_amount, upper_bound))
            
            # Create application
            application = LoanApplication(
                customer_id=customer_id,
                product_id=data['product_id'],
                requested_amount=requested_amount,
                recommended_amount=recommended_amount,
                term_months=term_months,
                purpose=data.get('purpose', ''),
                eligibility_score=qualification.get('eligibility_score'),
                ai_recommendation=qualification,
                risk_category=qualification.get('risk_category'),
                preferred_disbursement_method=data.get('preferred_disbursement_method') or None,
            )
            application.submit()
            
            logger.info(f"Loan application submitted: {application.id} by {customer_id}")
            
            # Send confirmation email to customer
            try:
                from notifications.services import get_email_sender
                sender = get_email_sender()
                sender.send_loan_submitted(
                    customer_email=user.email if hasattr(user, 'email') else '',
                    customer_name=_safe_customer_display_name(user),
                    loan_id=application.id,
                    product_name=product.name,
                    amount=data['requested_amount'],
                    customer_id=customer_id,
                )
            except Exception as e:
                logger.warning(f"Failed to send loan submitted email: {e}")
            
            # Audit log
            AuditLog.log_action(
                action='loan_submitted',
                user_id=customer_id,
                user_type='customer',
                user_email=user.email if hasattr(user, 'email') else '',
                description=f'Loan application submitted for {product.name} - ₱{data["requested_amount"]:,.2f}',
                resource_type='loan',
                resource_id=application.id,
                details={'product': product.name, 'amount': data['requested_amount'], 'term': data['term_months']},
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            # Blockchain sync (background thread, no Celery needed)
            try:
                from loans.blockchain.sync import sync_application
                sync_application(application.id)
            except Exception as e:
                logger.warning(f"Blockchain sync skipped for application {application.id}: {e}")
            
            return success_response(
                data={
                    'application_id': application.id,
                    'status': application.status,
                    'eligibility_score': application.eligibility_score,
                    'recommended_amount': application.recommended_amount,
                    'message': 'Your application has been submitted for review'
                },
                message="Application submitted successfully",
                status_code=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Apply error: {str(e)}")
            return error_response(
                message="Failed to submit application",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
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
        search_query = sanitize_text(request.query_params.get('search', '')).lower()
        status_filter = sanitize_text(request.query_params.get('status', '')).lower()
        allowed_status_filters = set(APPLICATION_STATUSES) | {'pending'}
        if status_filter and status_filter not in allowed_status_filters:
            return error_response(
                message="Invalid status filter",
                errors={'status': f"status must be one of: {', '.join(sorted(allowed_status_filters))}"},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        try:
            page = int(request.query_params.get('page', 1))
        except (TypeError, ValueError):
            return error_response(
                message="Invalid page parameter",
                errors={'page': 'page must be an integer'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        try:
            page_size = min(int(request.query_params.get('page_size', 20)), 100)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid page_size parameter",
                errors={'page_size': 'page_size must be an integer'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        if page < 1:
            return error_response(
                message="Invalid page parameter",
                errors={'page': 'page must be at least 1'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        if page_size < 1:
            return error_response(
                message="Invalid page_size parameter",
                errors={'page_size': 'page_size must be at least 1'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        applications = LoanApplication.find_by_customer(customer_id)
        
        apps_data = []
        for app in applications:
            product = LoanProduct.find_by_id(app.product_id)
            product_name = product.name if product else 'Unknown'
            
            # Apply search filter (search in product name)
            if search_query and search_query not in product_name.lower():
                continue
            
            # Apply status filter
            if status_filter:
                app_status = (app.status or '').lower()
                if status_filter == 'pending':
                    if app_status not in {'submitted', 'under_review'}:
                        continue
                elif app_status != status_filter:
                    continue
            
            apps_data.append({
                'id': app.id,
                'product_name': product_name,
                'requested_amount': app.requested_amount,
                'recommended_amount': app.recommended_amount,
                'approved_amount': app.approved_amount,
                'term_months': app.term_months,
                'status': app.status,
                'eligibility_score': app.eligibility_score,
                'submitted_at': app.submitted_at.isoformat() if app.submitted_at else None,
                'created_at': app.created_at.isoformat()
            })
        
        # Calculate pagination
        total_count = len(apps_data)
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_apps = apps_data[start_idx:end_idx]
        
        return success_response(
            data={
                'applications': paginated_apps,
                'total': total_count,
                'page': page,
                'page_size': page_size,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_previous': page > 1,
            },
            message="Applications retrieved"
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
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        product = LoanProduct.find_by_id(app.product_id)
        
        return success_response(
            data=_serialize_customer_application_detail(app, product),
            message="Application details retrieved"
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
                    status_code=status.HTTP_404_NOT_FOUND
                )

            if app.status != 'draft':
                return error_response(
                    message="Only draft applications can be edited and submitted",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            serializer = LoanApplicationSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid application data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            data = serializer.validated_data
            product = LoanProduct.find_by_id(app.product_id)
            if not product or not product.active:
                return error_response(
                    message="Loan product not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )

            incoming_product_id = data['product_id']
            if incoming_product_id != app.product_id:
                return error_response(
                    message="Changing the loan product is not allowed for draft resubmission",
                    errors={'product_id': 'Must match the original draft product'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            requested_amount = float(data['requested_amount'])
            term_months = int(data['term_months'])

            if requested_amount < product.min_amount or requested_amount > product.max_amount:
                return error_response(
                    message=f"Amount must be between ₱{product.min_amount:,.0f} and ₱{product.max_amount:,.0f}",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            if term_months < product.min_term_months or term_months > product.max_term_months:
                return error_response(
                    message=(
                        f"Term must be between {product.min_term_months} and "
                        f"{product.max_term_months} months"
                    ),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            basic = check_basic_eligibility(
                customer_id,
                product,
                requirements_scope='product',
                require_approved_documents=True,
            )
            if not basic['can_apply']:
                return error_response(
                    message="Cannot apply - requirements not met",
                    errors={'missing': basic['missing_requirements']},
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            qualification = qualify_customer(
                customer_id=customer_id,
                product=product,
                requested_amount=requested_amount,
                term_months=term_months,
                purpose=data.get('purpose', ''),
                require_approved_documents=True,
            )

            eligible_or_can_apply = bool(
                qualification.get('can_apply', qualification.get('eligible', False))
            )
            recommended_amount = qualification.get('recommended_amount', 0)

            if not eligible_or_can_apply:
                recommended_amount = 0.0
            else:
                try:
                    recommended_amount = float(recommended_amount)
                except (TypeError, ValueError):
                    recommended_amount = 0.0

                lower_bound = float(product.min_amount or 0)
                upper_bound = min(float(product.max_amount or 0), requested_amount)
                if upper_bound < lower_bound:
                    upper_bound = lower_bound
                recommended_amount = max(lower_bound, min(recommended_amount, upper_bound))

            app.requested_amount = requested_amount
            app.recommended_amount = recommended_amount
            app.term_months = term_months
            app.purpose = data.get('purpose', '')
            app.eligibility_score = qualification.get('eligibility_score')
            app.ai_recommendation = qualification
            app.risk_category = qualification.get('risk_category')
            app.submit()

            logger.info(f"Draft application updated and submitted: {app.id} by {customer_id}")

            try:
                from notifications.services import get_email_sender
                sender = get_email_sender()
                sender.send_loan_submitted(
                    customer_email=user.email if hasattr(user, 'email') else '',
                    customer_name=_safe_customer_display_name(user),
                    loan_id=app.id,
                    product_name=product.name,
                    amount=requested_amount,
                    customer_id=customer_id,
                )
            except Exception as e:
                logger.warning(f"Failed to send loan submitted email: {e}")

            AuditLog.log_action(
                action='loan_draft_updated_and_submitted',
                user_id=customer_id,
                user_type='customer',
                user_email=user.email if hasattr(user, 'email') else '',
                description=f'Draft loan application updated and submitted for {product.name} - ₱{requested_amount:,.2f}',
                resource_type='loan',
                resource_id=app.id,
                details={'product': product.name, 'amount': requested_amount, 'term': term_months},
                ip_address=request.META.get('REMOTE_ADDR', '')
            )

            return success_response(
                data=_serialize_customer_application_detail(app, product),
                message="Application updated and submitted successfully"
            )
        except Exception as e:
            logger.error(f"Draft update submit error: {str(e)}")
            return error_response(
                message="Failed to update and submit application",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RepaymentScheduleView(CustomerRoleRequiredMixin, APIView):
    """
    Get repayment schedule for a loan application.
    
    GET /api/loans/applications/<id>/schedule/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id
        
        # Verify application belongs to customer
        app = LoanApplication.find_by_id(application_id)
        
        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # Only disbursed loans have schedules
        if app.status != 'disbursed':
            return error_response(
                message="Repayment schedule is only available for disbursed loans",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        from loans.models import RepaymentSchedule
        schedule = RepaymentSchedule.find_by_loan(application_id)
        
        if not schedule:
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # Format installments
        installments = []
        for inst in schedule.installments:
            penalty_applied_at = inst.get('penalty_applied_at')
            if hasattr(penalty_applied_at, 'isoformat'):
                penalty_applied_at = penalty_applied_at.isoformat()
            penalty_waived_at = inst.get('penalty_waived_at')
            if hasattr(penalty_waived_at, 'isoformat'):
                penalty_waived_at = penalty_waived_at.isoformat()
            installments.append({
                'number': inst['number'],
                'due_date': inst['due_date'].isoformat() if inst.get('due_date') else None,
                'principal': inst['principal'],
                'interest': inst['interest'],
                'total_amount': inst['total_amount'],
                'status': inst['status'],
                'paid_amount': inst.get('paid_amount', 0),
                'penalty_status': inst.get('penalty_status'),
                'penalty_amount': inst.get('penalty_amount'),
                'penalty_reason': inst.get('penalty_reason', ''),
                'penalty_applied_at': penalty_applied_at,
                'penalty_applied_by': inst.get('penalty_applied_by'),
                'penalty_waived_at': penalty_waived_at,
                'penalty_waived_by': inst.get('penalty_waived_by'),
                'penalty_waived_reason': inst.get('penalty_waived_reason', ''),
            })
        
        return success_response(
            data={
                'loan_id': schedule.loan_id,
                'principal': schedule.principal,
                'interest_rate': schedule.interest_rate,
                'term_months': schedule.term_months,
                'monthly_payment': schedule.monthly_payment,
                'total_amount': schedule.total_amount,
                'total_interest': schedule.total_interest,
                'paid_count': schedule.get_paid_count(),
                'remaining_balance': schedule.get_remaining_balance(),
                'next_payment': schedule.get_next_payment(),
                'installments': installments
            },
            message="Repayment schedule retrieved"
        )


class PaymentHistoryView(CustomerRoleRequiredMixin, APIView):
    """
    Get or record payments for a loan application.
    
    GET /api/loans/applications/<id>/payments/
    POST /api/loans/applications/<id>/payments/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id
        
        # Verify application belongs to customer
        app = LoanApplication.find_by_id(application_id)
        
        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        from loans.models import LoanPayment
        payments = LoanPayment.find_by_loan(application_id)
        
        payments_data = [{
            'id': p.id,
            'amount': p.amount,
            'installment_number': p.installment_number,
            'payment_method': p.payment_method,
            'reference': p.reference,
            'recorded_at': p.recorded_at.isoformat() if p.recorded_at else None
        } for p in payments]
        
        total_paid = sum(p.amount for p in payments)
        
        return success_response(
            data={
                'payments': payments_data,
                'total_paid': total_paid,
                'count': len(payments_data)
            },
            message="Payment history retrieved"
        )

    def post(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        app = LoanApplication.find_by_id(application_id)
        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )

        if app.status != 'disbursed':
            return error_response(
                message="Payments can only be recorded for disbursed loans",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        amount_raw = request.data.get('amount')
        installment_number_raw = request.data.get('installment_number')
        payment_method = request.data.get('payment_method', 'bank_transfer')
        reference = sanitize_text(request.data.get('reference', ''))
        notes = sanitize_text(request.data.get('notes', ''))

        if installment_number_raw in (None, ''):
            return error_response(
                message="installment_number is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            installment_number = int(installment_number_raw)
        except (TypeError, ValueError):
            return error_response(
                message="installment_number must be an integer",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if installment_number < 1:
            return error_response(
                message="installment_number must be at least 1",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            amount = float(amount_raw)
        except (TypeError, ValueError):
            return error_response(
                message="amount must be a valid number",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if amount <= 0:
            return error_response(
                message="amount must be greater than 0",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if payment_method in {'cash', 'check'}:
            return error_response(
                message="Cash and check payments must be paid at the office and recorded by a loan officer",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        valid_methods = {'gcash', 'bank_transfer', 'wallet'}
        if payment_method not in valid_methods:
            return error_response(
                message="Invalid payment_method",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if not reference:
            from loans.utils import generate_payment_reference
            reference = generate_payment_reference()

        from loans.models import RepaymentSchedule, LoanPayment

        schedule = RepaymentSchedule.find_by_loan(application_id)
        if not schedule:
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND
            )

        if str(schedule.customer_id) != str(customer_id):
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND
            )

        installment = schedule.get_installment(installment_number)
        if not installment:
            return error_response(
                message=f"Installment #{installment_number} not found",
                status_code=status.HTTP_404_NOT_FOUND
            )

        if installment.get('status') == 'paid':
            return error_response(
                message=f"Installment #{installment_number} is already fully paid",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        remaining = installment['total_amount'] - installment.get('paid_amount', 0)
        if amount - remaining > 0.01:
            return error_response(
                message=f"Amount exceeds remaining balance of ₱{remaining:.2f}",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        unpaid_before = schedule.count_unpaid_before(installment_number)
        updated_installment = schedule.record_payment(installment_number, amount)

        payment = LoanPayment(
            loan_id=application_id,
            schedule_id=schedule.id,
            customer_id=str(customer_id),
            installment_number=installment_number,
            amount=amount,
            payment_method=payment_method,
            reference=reference,
            notes=notes,
            recorded_by=str(customer_id),
        )
        payment.save()

        AuditLog.log_action(
            action='customer_payment_recorded',
            user_id=str(customer_id),
            user_type='customer',
            description=f'Customer payment recorded - ₱{amount:,.2f} for installment #{installment_number}',
            resource_type='payment',
            resource_id=payment.id,
            details={
                'loan_id': application_id,
                'amount': amount,
                'installment': installment_number,
                'method': payment_method,
            },
            ip_address=request.META.get('REMOTE_ADDR', ''),
        )

        logger.info(
            "Customer payment recorded: loan=%s installment=%s amount=%s customer=%s",
            application_id,
            installment_number,
            amount,
            customer_id,
        )

        # Blockchain sync — payment
        try:
            from loans.blockchain.sync import sync_payment
            sync_payment(application_id, payment.id)
        except Exception as e:
            logger.warning(f"Blockchain sync skipped for payment {payment.id}: {e}")

        return success_response(
            data={
                'payment_id': payment.id,
                'loan_id': application_id,
                'installment_number': installment_number,
                'amount': amount,
                'payment_method': payment_method,
                'reference': reference,
                'recorded_at': payment.recorded_at.isoformat() if payment.recorded_at else None,
                'installment_status': updated_installment['status'],
                'remaining_balance': schedule.get_remaining_balance(),
                'skipped_installments': unpaid_before,
            },
            message="Payment recorded successfully"
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
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        if not app.can_resubmit():
            return error_response(
                message="Only rejected applications can be resubmitted",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        app.resubmit()
        
        return success_response(
            data={
                'id': app.id,
                'status': app.status,
                'message': 'Application reset to draft. Please update and resubmit.'
            },
            message="Application ready for resubmission"
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
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        if app.status != 'rejected':
            return error_response(
                message="Feedback is only available for rejected applications",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate AI feedback
        try:
            from ai_assistant.services import get_llm_service
            llm = get_llm_service()
            
            prompt = f"""A loan application was rejected. Please explain this to the customer in a friendly, empathetic way.

Rejection reason: {app.rejection_reason or 'Not specified'}
Officer notes: {app.officer_notes or 'None provided'}

Provide:
1. A simple explanation of why it was rejected
2. What they can do to improve their chances
3. Encouragement to try again

Keep the response under 200 words and use a warm, supportive tone."""

            feedback = llm.generate(prompt)
            
        except Exception:
            # Fallback if AI unavailable
            feedback = f"""We understand this isn't the news you were hoping for.

Your application was not approved because: {app.rejection_reason or 'The requirements were not fully met.'}

What you can do:
• Review and update your profile information
• Ensure all documents are clear and valid
• Consider applying for a smaller amount

Don't give up! Many successful borrowers were approved on their second try."""
        
        return success_response(
            data={
                'rejection_reason': app.rejection_reason,
                'feedback': feedback,
                'can_resubmit': app.can_resubmit()
            },
            message="Feedback retrieved"
        )


class SetDisbursementMethodView(CustomerRoleRequiredMixin, APIView):
    """
    Customer: Set preferred disbursement method after loan approval.
    
    POST /api/loans/applications/<id>/set-disbursement-method/
    Body: { "disbursement_method": "gcash" | "bank_transfer" }
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
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        disbursement_method = sanitize_text(
            request.data.get('disbursement_method', '')
        ).lower().strip()
        
        if not disbursement_method:
            return error_response(
                message="disbursement_method is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            app.set_preferred_disbursement_method(disbursement_method)
        except ValueError as e:
            return error_response(
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Audit log
        AuditLog.log_action(
            action='disbursement_method_set',
            user_id=customer_id,
            user_type='customer',
            user_email=user.email if hasattr(user, 'email') else '',
            description=f'Borrower set preferred disbursement method to {disbursement_method}',
            resource_type='loan',
            resource_id=app.id,
            details={
                'disbursement_method': disbursement_method,
            },
            ip_address=request.META.get('REMOTE_ADDR', '')
        )
        
        logger.info(
            f"Disbursement method set: {disbursement_method} "
            f"for application {app.id} by customer {customer_id}"
        )
        
        return success_response(
            data={
                'id': app.id,
                'status': app.status,
                'preferred_disbursement_method': app.preferred_disbursement_method,
            },
            message="Disbursement method saved successfully"
        )


class CustomerBlockchainView(CustomerRoleRequiredMixin, APIView):
    """
    Customer: Get blockchain transaction status for own loan application.

    GET /api/loans/applications/<id>/blockchain/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        if not ObjectId.is_valid(application_id):
            return error_response(
                message="Invalid application ID",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        app = LoanApplication.find_by_id(application_id)
        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )

        explorer_url = getattr(settings, 'BLOCKCHAIN_EXPLORER_URL', '')
        data = {
            'application_id': app.id,
            'blockchain_enabled': getattr(settings, 'BLOCKCHAIN_ENABLED', False),
            'explorer_url': f"{explorer_url}/tx" if explorer_url else '',
            'tx_hashes': getattr(app, 'blockchain_tx_hashes', {}),
            'transactions': [],
        }

        if getattr(settings, 'BLOCKCHAIN_ENABLED', False):
            try:
                from loans.blockchain.models import BlockchainTransaction
                txs = BlockchainTransaction.find_by_loan(application_id)
                data['transactions'] = [tx.to_dict() for tx in txs]
            except Exception as e:
                logger.warning(f"Failed to fetch blockchain transactions: {e}")

            try:
                from loans.blockchain.services.audit_service import get_audit_trail
                trail = get_audit_trail(application_id)
                data['audit_trail'] = trail
            except Exception as e:
                logger.warning(f"Failed to fetch on-chain audit trail: {e}")

        return success_response(
            data=data,
            message="Blockchain status retrieved"
        )


class WalletPaymentView(CustomerRoleRequiredMixin, APIView):
    """
    Customer: Verify and record an ETH wallet payment for a loan installment.

    The customer pays via MetaMask (WalletConnect), then submits the tx_hash here.
    Backend verifies the transaction on-chain before recording the payment.

    POST /api/loans/applications/<id>/wallet-payment/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id

        tx_hash = request.data.get('tx_hash', '').strip()
        installment_number_raw = request.data.get('installment_number')

        if not tx_hash:
            return error_response(
                message="tx_hash is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        if not tx_hash.startswith('0x') or len(tx_hash) != 66:
            return error_response(
                message="Invalid transaction hash format",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        if installment_number_raw in (None, ''):
            return error_response(
                message="installment_number is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        try:
            installment_number = int(installment_number_raw)
        except (TypeError, ValueError):
            return error_response(
                message="installment_number must be an integer",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        if installment_number < 1:
            return error_response(
                message="installment_number must be at least 1",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        app = LoanApplication.find_by_id(application_id)
        if not app or app.customer_id != customer_id:
            return error_response(
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        if app.status != 'disbursed':
            return error_response(
                message="Loan is not in disbursed status",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        # Find schedule and validate installment
        from loans.models import RepaymentSchedule, LoanPayment
        schedule = RepaymentSchedule.find_by_loan(application_id)
        if not schedule:
            return error_response(
                message="Repayment schedule not found",
                status_code=status.HTTP_404_NOT_FOUND
            )

        installment = schedule.get_installment(installment_number)
        if not installment:
            return error_response(
                message=f"Installment #{installment_number} not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        if installment.get('status') == 'paid':
            return error_response(
                message=f"Installment #{installment_number} is already fully paid",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        # Verify the transaction on-chain
        try:
            from loans.blockchain.client import get_web3, get_account
            from loans.blockchain.services.eth_price_service import get_eth_php_rate

            w3 = get_web3()
            tx = w3.eth.get_transaction(tx_hash)
            receipt = w3.eth.get_transaction_receipt(tx_hash)

            if receipt['status'] != 1:
                return error_response(
                    message="Transaction failed on-chain",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Verify recipient is the system wallet
            system_address = get_account().address.lower()
            if tx['to'].lower() != system_address:
                return error_response(
                    message="Transaction recipient does not match system wallet",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Verify sender is the customer's wallet
            from profiles.models.profile_models import CustomerProfile
            profile = CustomerProfile.find_by_customer(customer_id)
            if not profile or not profile.wallet_address:
                return error_response(
                    message="Customer wallet address not configured",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if tx['from'].lower() != profile.wallet_address.lower():
                return error_response(
                    message="Transaction sender does not match your wallet address",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Verify amount (convert ETH received to PHP and compare)
            eth_received = float(w3.from_wei(tx['value'], 'ether'))
            rate_info = get_eth_php_rate()
            php_received = eth_received * rate_info['rate']
            expected_php = installment['total_amount'] - installment.get('paid_amount', 0)

            # Minimum payment threshold to prevent dust payments
            MIN_PAYMENT_PHP = 100.0
            # Allow small fluctuations in exchange rate: ±2% tolerance
            tolerance = 0.02
            lower_bound = expected_php * (1 - tolerance)
            upper_bound = expected_php * (1 + tolerance)
            
            if php_received < MIN_PAYMENT_PHP:
                return error_response(
                    message=f"Payment too small. Minimum: ₱{MIN_PAYMENT_PHP:.2f} "
                            f"(received {eth_received:.6f} ETH ≈ ₱{php_received:.2f})",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Reject payments that are significantly (more than tolerance) below expected amount
            if php_received < lower_bound:
                return error_response(
                    message=(
                        f"Payment is below the allowed tolerance of {tolerance*100:.0f}% for this installment. "
                        f"Expected ~₱{expected_php:.2f}, received ₱{php_received:.2f}"
                    ),
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Check for duplicate tx_hash
            existing = settings.MONGODB['loan_payments'].find_one(
                {'eth_tx_hash': tx_hash}
            )
            if existing:
                return error_response(
                    message="This transaction has already been recorded",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

        except error_response.__class__:
            raise
        except Exception as exc:
            logger.error("Wallet payment verification failed: %s", exc)
            return error_response(
                message=f"Failed to verify transaction on-chain: {str(exc)}",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        # Record the payment (accept full amount received, including overpayments)
        payment_amount = php_received
        unpaid_before = schedule.count_unpaid_before(installment_number)
        updated_installment = schedule.record_payment(installment_number, payment_amount)

        payment = LoanPayment(
            loan_id=application_id,
            schedule_id=schedule.id,
            customer_id=customer_id,
            installment_number=installment_number,
            amount=payment_amount,
            payment_method='wallet',
            reference=tx_hash[:18],
            notes=f"ETH wallet payment: {eth_received:.6f} ETH @ {rate_info['rate']:.2f} PHP/ETH",
            recorded_by=customer_id,
            blockchain_sync_status='pending',
        )
        payment.save()

        # Store ETH-specific details IMMEDIATELY (before blockchain sync starts)
        settings.MONGODB['loan_payments'].update_one(
            {'_id': ObjectId(payment.id)},
            {'$set': {
                'eth_tx_hash': tx_hash,
                'eth_amount': str(eth_received),
                'eth_rate': rate_info['rate'],
                'eth_rate_source': rate_info['source'],
                'eth_sender': profile.wallet_address,
                'eth_block_number': receipt['blockNumber'],
            }}
        )

        logger.info(
            "Wallet payment verified: loan=%s installment=%d amount=%.6f ETH tx=%s",
            application_id, installment_number, eth_received, tx_hash[:18]
        )

        # Audit log
        from analytics.models import AuditLog
        AuditLog.log_action(
            action='wallet_payment_verified',
            user_id=customer_id,
            user_type='customer',
            description=f'Wallet payment verified - {eth_received:.6f} ETH for installment #{installment_number}',
            resource_type='payment',
            resource_id=payment.id,
            details={
                'loan_id': application_id,
                'installment_number': installment_number,
                'eth_amount': str(eth_received),
                'php_amount': payment_amount,
                'eth_rate': rate_info['rate'],
                'tx_hash': tx_hash,
            },
            ip_address=request.META.get('REMOTE_ADDR', '')
        )

        # Blockchain audit trail sync
        try:
            from loans.blockchain.sync import sync_payment
            sync_payment(application_id, payment.id)
        except Exception as e:
            logger.warning(f"Blockchain sync skipped for wallet payment {payment.id}: {e}")

        return success_response(
            data={
                'status': 'verified',
                'payment_id': payment.id,
                'installment_number': installment_number,
                'installment_status': updated_installment['status'],
                'amount_php': payment_amount,
                'amount_eth': str(eth_received),
                'eth_rate': rate_info['rate'],
                'tx_hash': tx_hash,
                'block_number': receipt['blockNumber'],
                'remaining_balance': schedule.get_remaining_balance(),
                'blockchain_sync_status': 'pending',
                'blockchain_sync_message': 'Payment recorded. Blockchain audit trail sync in progress...',
            },
            message="Wallet payment verified and recorded",
            status_code=status.HTTP_201_CREATED
        )


class SystemWalletInfoView(CustomerRoleRequiredMixin, APIView):
    """
    Customer: Get system wallet address and current ETH/PHP rate.

    Mobile app uses this to construct the WalletConnect ETH transfer request.

    GET /api/loans/system-wallet/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.check_customer_permission(request)
        if not has_permission:
            return result

        from loans.blockchain.client import get_account, get_web3

        if not getattr(settings, 'BLOCKCHAIN_ENABLED', False):
            return error_response(
                message="Blockchain is not enabled",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        try:
            account = get_account()
            w3 = get_web3()
        except Exception as exc:
            return error_response(
                message=f"Blockchain connection unavailable: {str(exc)}",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        # Fetch live exchange rate
        from loans.blockchain.services.eth_price_service import (
            get_eth_php_rate,
            ExchangeRateUnavailableError,
        )
        try:
            rate_info = get_eth_php_rate()
        except ExchangeRateUnavailableError:
            return error_response(
                message="ETH/PHP exchange rate is currently unavailable. "
                        "Wallet payments are temporarily disabled.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        from datetime import datetime, timezone
        return success_response(
            data={
                'wallet_address': account.address,
                'chain_id': settings.BLOCKCHAIN_CHAIN_ID,
                'rpc_url': settings.BLOCKCHAIN_RPC_URL,
                'eth_php_rate': rate_info['rate'],
                'rate_source': rate_info['source'],
                'rate_cached_at': datetime.fromtimestamp(
                    rate_info['fetched_at'], tz=timezone.utc
                ).isoformat() if rate_info['fetched_at'] else None,
                # Also include rate_updated_at for backwards compatibility
                'rate_updated_at': datetime.fromtimestamp(
                    rate_info['fetched_at'], tz=timezone.utc
                ).isoformat() if rate_info['fetched_at'] else None,
            },
            message="System wallet info retrieved"
        )
