from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from loans.models import LoanProduct, LoanApplication
from loans.serializers import LoanApplicationSerializer
from loans.services import qualify_customer, check_basic_eligibility

from analytics.models import AuditLog
import logging

logger = logging.getLogger('loans')


class LoanProductListView(APIView):
    """
    List available loan products.
    
    GET /api/loans/products/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get all active loan products"""
        products = LoanProduct.find(active_only=True)
        
        products_data = [{
            'id': p.id,
            'name': p.name,
            'code': p.code,
            'description': p.description,
            'min_amount': p.min_amount,
            'max_amount': p.max_amount,
            'interest_rate': p.interest_rate,
            'interest_rate_display': f"{p.interest_rate * 100:.1f}% monthly",
            'min_term_months': p.min_term_months,
            'max_term_months': p.max_term_months,
            'required_documents': [],
            'target_description': p.target_description
        } for p in products]
        
        return success_response(
            data={'products': products_data, 'total': len(products_data)},
            message="Loan products retrieved successfully"
        )


class LoanProductDetailView(APIView):
    """
    Get loan product details.
    
    GET /api/loans/products/<id>/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, product_id):
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
                'min_term_months': product.min_term_months,
                'max_term_months': product.max_term_months,
                'required_documents': [],
                'min_business_months': product.min_business_months,
                'min_monthly_income': product.min_monthly_income,
                'target_description': product.target_description
            },
            message="Product details retrieved"
        )


class PreQualifyView(APIView):
    """
    Check customer eligibility for a loan product.
    Uses AI to analyze profile and provide recommendations.
    
    POST /api/loans/pre-qualify/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Check eligibility for a loan"""
        try:
            user = request.user
            customer_id = user.customer_id
            
            product_id = request.data.get('product_id')
            requested_amount = request.data.get('amount', 0)
            term_months = request.data.get('term_months', 12)
            purpose = request.data.get('purpose', '')
            requirements_scope = request.data.get('requirements_scope')
            
            if not product_id:
                return error_response(
                    message="product_id is required",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
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
            
            # Quick eligibility check
            basic = check_basic_eligibility(
                customer_id,
                product,
                requirements_scope=requirements_scope,
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
            )
            
            return success_response(
                data={
                    'product': {
                        'id': product.id,
                        'name': product.name
                    },
                    'requested_amount': requested_amount,
                    'eligible': qualification.get('eligible', False),
                    'eligibility_score': qualification.get('eligibility_score'),
                    'risk_category': qualification.get('risk_category'),
                    'recommended_amount': qualification.get('recommended_amount'),
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


class LoanApplyView(APIView):
    """
    Submit a loan application.
    
    POST /api/loans/apply/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Submit loan application"""
        try:
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
            
            # Check basic eligibility
            basic = check_basic_eligibility(
                customer_id,
                product,
                requirements_scope='product',
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
                requested_amount=data['requested_amount'],
                term_months=data['term_months'],
                purpose=data.get('purpose', '')
            )
            
            # Create application
            application = LoanApplication(
                customer_id=customer_id,
                product_id=data['product_id'],
                requested_amount=data['requested_amount'],
                recommended_amount=qualification.get('recommended_amount'),
                term_months=data['term_months'],
                purpose=data.get('purpose', ''),
                eligibility_score=qualification.get('eligibility_score'),
                ai_recommendation=qualification,
                risk_category=qualification.get('risk_category')
            )
            application.submit()
            
            logger.info(f"Loan application submitted: {application.id} by {customer_id}")
            
            # Send confirmation email to customer
            try:
                from notifications.services import get_email_sender
                sender = get_email_sender()
                sender.send_loan_submitted(
                    customer_email=user.email if hasattr(user, 'email') else '',
                    customer_name=user.full_name if hasattr(user, 'full_name') else f"{user.first_name} {user.last_name}",
                    loan_id=application.id,
                    product_name=product.name,
                    amount=data['requested_amount']
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


class MyApplicationsView(APIView):
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
        user = request.user
        customer_id = user.customer_id
        
        # Get query parameters
        search_query = request.query_params.get('search', '').strip().lower()
        status_filter = request.query_params.get('status', '').strip().lower()
        page = int(request.query_params.get('page', 1))
        page_size = min(int(request.query_params.get('page_size', 20)), 100)
        
        applications = LoanApplication.find_by_customer(customer_id)
        
        apps_data = []
        for app in applications:
            product = LoanProduct.find_by_id(app.product_id)
            product_name = product.name if product else 'Unknown'
            
            # Apply search filter (search in product name)
            if search_query and search_query not in product_name.lower():
                continue
            
            # Apply status filter
            if status_filter and app.status.lower() != status_filter:
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


class ApplicationDetailView(APIView):
    """
    Get application details.
    
    GET /api/loans/applications/<id>/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, application_id):
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
            data={
                'id': app.id,
                'product': {
                    'id': product.id if product else None,
                    'name': product.name if product else 'Unknown'
                },
                'requested_amount': app.requested_amount,
                'recommended_amount': app.recommended_amount,
                'approved_amount': app.approved_amount,
                'term_months': app.term_months,
                'purpose': app.purpose,
                'status': app.status,
                'eligibility_score': app.eligibility_score,
                'risk_category': app.risk_category,
                'rejection_reason': app.rejection_reason,
                'submitted_at': app.submitted_at.isoformat() if app.submitted_at else None,
                'decision_date': app.decision_date.isoformat() if app.decision_date else None,
                'created_at': app.created_at.isoformat()
            },
            message="Application details retrieved"
        )


class RepaymentScheduleView(APIView):
    """
    Get repayment schedule for a loan application.
    
    GET /api/loans/applications/<id>/schedule/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, application_id):
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
            installments.append({
                'number': inst['number'],
                'due_date': inst['due_date'].isoformat() if inst.get('due_date') else None,
                'principal': inst['principal'],
                'interest': inst['interest'],
                'total_amount': inst['total_amount'],
                'status': inst['status'],
                'paid_amount': inst.get('paid_amount', 0)
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


class PaymentHistoryView(APIView):
    """
    Get payment history for a loan application.
    
    GET /api/loans/applications/<id>/payments/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, application_id):
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


class ResubmitApplicationView(APIView):
    """
    Resubmit a rejected application.
    
    POST /api/loans/applications/<id>/resubmit/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, application_id):
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


class RejectionFeedbackView(APIView):
    """
    Get AI-powered friendly feedback about why application was rejected.
    
    GET /api/loans/applications/<id>/feedback/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, application_id):
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
