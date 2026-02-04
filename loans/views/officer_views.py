from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId
from datetime import datetime

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from loans.models import LoanProduct, LoanApplication
from loans.serializers import LoanReviewSerializer
import logging

logger = logging.getLogger('loans')


class LoanOfficerRequiredMixin:
    """Mixin to require loan officer or admin role"""
    
    def check_officer_permission(self, request):
        user = request.user
        if not hasattr(user, 'role') or user.role not in ['loan_officer', 'admin']:
            return False, error_response(
                message="Loan officer access required",
                status_code=status.HTTP_403_FORBIDDEN
            )
        return True, user


class OfficerApplicationListView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: List pending applications.
    
    GET /api/loans/officer/applications/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result
        
        # Filter by status
        status_filter = request.query_params.get('status', 'pending')
        
        if status_filter == 'pending':
            applications = LoanApplication.find_pending()
        elif status_filter == 'mine':
            applications = LoanApplication.find_by_officer(result.customer_id)
        else:
            applications = LoanApplication.find({'status': status_filter})
        
        apps_data = []
        for app in applications:
            product = LoanProduct.find_by_id(app.product_id)
            apps_data.append({
                'id': app.id,
                'customer_id': app.customer_id,
                'product_name': product.name if product else 'Unknown',
                'requested_amount': app.requested_amount,
                'recommended_amount': app.recommended_amount,
                'term_months': app.term_months,
                'status': app.status,
                'eligibility_score': app.eligibility_score,
                'risk_category': app.risk_category,
                'submitted_at': app.submitted_at.isoformat() if app.submitted_at else None
            })
        
        return success_response(
            data={'applications': apps_data, 'total': len(apps_data)},
            message="Applications retrieved"
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
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        product = LoanProduct.find_by_id(app.product_id)
        
        # Get complete customer profiles
        from profiles.models import CustomerProfile, BusinessProfile, AlternativeData
        from documents.models import Document
        from accounts.models import Customer
        
        customer = Customer.find_one({'customer_id': app.customer_id})
        personal = CustomerProfile.get_or_create(app.customer_id)
        business = BusinessProfile.get_or_create(app.customer_id)
        alternative = AlternativeData.get_or_create(app.customer_id)
        documents = Document.find_by_customer(app.customer_id)
        
        # Build customer data
        customer_data = {
            'customer_id': app.customer_id,
            'email': customer.email if customer else None,
            'personal_profile': {
                'first_name': customer.first_name if customer else None,
                'last_name': customer.last_name if customer else None,
                'phone_number': customer.phone if customer else None,
                'civil_status': personal.civil_status,
                'city_municipality': personal.city_municipality,
                'province': personal.province,
                'barangay': personal.barangay,
                'street_address': personal.address_line1,
                'emergency_contact_name': personal.emergency_contact_name,
                'emergency_contact_phone': personal.emergency_contact_phone,
                'profile_completed': personal.profile_completed,
                'completion_percentage': personal.completion_percentage
            },
            'business_profile': {
                'business_name': business.business_name,
                'business_type': business.business_type,
                'business_address': business.business_address,
                'years_in_operation': business.years_in_operation,
                'is_registered': business.is_registered,
                'income_range': business.income_range,
                'estimated_monthly_income': float(business.estimated_monthly_income) if business.estimated_monthly_income else None,
                'number_of_employees': business.number_of_employees,
                'business_description': business.business_description
            },
            'alternative_data': {
                'education_level': alternative.education_level,
                'employment_status': alternative.employment_status,
                'housing_status': alternative.housing_status,
                'years_at_residence': alternative.years_at_current_address,
                'has_bank_account': alternative.has_bank_account,
                'has_ewallet': alternative.has_ewallet,
                'ewallet_usage': alternative.ewallet_usage,
                'has_existing_loans': alternative.has_existing_loans,
                'utility_payment_history': alternative.utility_payment_history,
                'risk_score': alternative.risk_score,
                'risk_category': alternative.risk_category
            }
        }
        
        # Build documents data
        from documents.storage import get_storage_backend
        storage = get_storage_backend()
        
        documents_data = [{
            'id': doc.id,
            'document_type': doc.document_type,
            'filename': doc.original_filename,
            'file_url': storage.get_url(doc.file_path),
            'file_size': doc.file_size,
            'status': doc.status,
            'verified': doc.verified,
            'verified_at': doc.verified_at.isoformat() if doc.verified_at else None,
            'reupload_requested': doc.reupload_requested,
            'reupload_reason': doc.reupload_reason,
            'ai_analysis': doc.ai_analysis,
            'uploaded_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None
        } for doc in documents]
        
        return success_response(
            data={
                'id': app.id,
                'customer_id': app.customer_id,
                'product': {
                    'id': product.id if product else None,
                    'name': product.name if product else 'Unknown',
                    'code': product.code if product else None
                },
                'requested_amount': app.requested_amount,
                'recommended_amount': app.recommended_amount,
                'approved_amount': app.approved_amount,
                'term_months': app.term_months,
                'purpose': app.purpose,
                'status': app.status,
                'eligibility_score': app.eligibility_score,
                'risk_category': app.risk_category,
                'ai_recommendation': app.ai_recommendation,
                'assigned_officer': app.assigned_officer,
                'officer_notes': app.officer_notes,
                'rejection_reason': app.rejection_reason,
                'submitted_at': app.submitted_at.isoformat() if app.submitted_at else None,
                'decision_date': app.decision_date.isoformat() if app.decision_date else None,
                # New: Complete customer data
                'customer': customer_data,
                'documents': documents_data
            },
            message="Application details retrieved"
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
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # Can only review submitted/under_review applications
        if app.status not in ['submitted', 'under_review']:
            return error_response(
                message=f"Cannot review application with status: {app.status}",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = LoanReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid review data",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        data = serializer.validated_data
        officer_id = user.customer_id
        
        # Get customer email for notification
        from accounts.models import Customer
        customer = Customer.find_one({'customer_id': app.customer_id})
        customer_email = customer.email if customer else None
        customer_name = f"{customer.first_name} {customer.last_name}" if customer else "Customer"
        
        if data['action'] == 'approve':
            app.approve(
                officer_id=officer_id,
                approved_amount=data['approved_amount'],
                notes=data.get('notes', '')
            )
            logger.info(f"Application approved: {app.id} by {officer_id}")
            message = "Application approved"
            
            # Send approval email
            if customer_email:
                try:
                    from notifications.services import get_email_sender
                    sender = get_email_sender()
                    sender.send_loan_approved(
                        customer_email=customer_email,
                        customer_name=customer_name,
                        loan_id=app.id,
                        approved_amount=data['approved_amount']
                    )
                except Exception as e:
                    logger.warning(f"Failed to send approval email: {e}")
        else:
            app.reject(
                officer_id=officer_id,
                reason=data['rejection_reason'],
                notes=data.get('notes', '')
            )
            logger.info(f"Application rejected: {app.id} by {officer_id}")
            message = "Application rejected"
            
            # Send rejection email
            if customer_email:
                try:
                    from notifications.services import get_email_sender
                    sender = get_email_sender()
                    sender.send_loan_rejected(
                        customer_email=customer_email,
                        customer_name=customer_name,
                        loan_id=app.id,
                        reason=data['rejection_reason']
                    )
                except Exception as e:
                    logger.warning(f"Failed to send rejection email: {e}")
        
        return success_response(
            data={
                'id': app.id,
                'status': app.status,
                'approved_amount': app.approved_amount
            },
            message=message
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
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # Can only disburse approved applications
        if app.status != 'approved':
            return error_response(
                message=f"Cannot disburse application with status: {app.status}. Must be 'approved'.",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Get disbursement data
        amount = request.data.get('amount', app.approved_amount)
        method = request.data.get('method', 'bank_transfer')
        reference = request.data.get('reference', '')
        external_reference = request.data.get('external_reference', '')  # Bank/check number
        
        # Auto-generate system reference if not provided
        if not reference:
            from loans.utils import generate_disbursement_reference
            reference = generate_disbursement_reference()
        
        
        try:
            app.disburse(
                amount=amount,
                method=method,
                reference=reference,
                processed_by=user.customer_id
            )
            
            logger.info(f"Loan disbursed: {app.id} by {user.customer_id}")
            
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
            
            # Send disbursement email
            from accounts.models import Customer
            customer = Customer.find_one({'customer_id': app.customer_id})
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
                        reference=reference
                    )
                except Exception as e:
                    logger.warning(f"Failed to send disbursement email: {e}")
            
            response_data = {
                'id': app.id,
                'status': app.status,
                'disbursed_amount': app.disbursed_amount,
                'disbursement_method': app.disbursement_method,
                'disbursement_reference': app.disbursement_reference,
                'disbursed_at': app.disbursed_at.isoformat() if app.disbursed_at else None
            }
            
            if schedule:
                response_data['schedule'] = {
                    'monthly_payment': schedule.monthly_payment,
                    'total_amount': schedule.total_amount,
                    'term_months': schedule.term_months
                }
            
            return success_response(
                data=response_data,
                message="Loan disbursed successfully"
            )
            
        except ValueError as e:
            return error_response(
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST
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
        loan_id = request.data.get('loan_id')
        installment_number = request.data.get('installment_number')
        amount = request.data.get('amount', 0)
        payment_method = request.data.get('payment_method', 'cash')
        reference = request.data.get('reference', '')
        external_reference = request.data.get('external_reference', '')  # GCash/Bank ref
        notes = request.data.get('notes', '')
        
        # Validation
        if not loan_id:
            return error_response(
                message="loan_id is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        if not installment_number:
            return error_response(
                message="installment_number is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        if amount <= 0:
            return error_response(
                message="amount must be greater than 0",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
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
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # VALIDATION 1: Check if installment exists
        installment = schedule.get_installment(installment_number)
        if not installment:
            return error_response(
                message=f"Installment #{installment_number} not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        # VALIDATION 2: Prevent duplicate payment on fully paid installments
        if installment.get('status') == 'paid':
            return error_response(
                message=f"Installment #{installment_number} is already fully paid",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # VALIDATION 3: Prevent overpayment (with 1% tolerance for rounding)
        remaining = installment['total_amount'] - installment.get('paid_amount', 0)
        if amount > remaining * 1.01:
            return error_response(
                message=f"Amount exceeds remaining balance of ₱{remaining:.2f}",
                status_code=status.HTTP_400_BAD_REQUEST
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
            recorded_by=user.customer_id
        )
        payment.save()
        
        logger.info(f"Payment recorded: {amount} for loan {loan_id} installment {installment_number}")
        
        # Send notification email
        try:
            from accounts.models import Customer
            from notifications.services import get_email_sender
            
            customer = Customer.find_one({'customer_id': schedule.customer_id})
            if customer and customer.email:
                sender = get_email_sender()
                sender.send_payment_received(
                    customer_email=customer.email,
                    customer_name=f"{customer.first_name} {customer.last_name}",
                    loan_id=loan_id,
                    amount=amount,
                    installment=installment_number,
                    remaining=schedule.get_remaining_balance()
                )
        except Exception as e:
            logger.warning(f"Failed to send payment email: {e}")
        
        return success_response(
            data={
                'payment_id': payment.id,
                'loan_id': loan_id,
                'installment_number': installment_number,
                'amount': amount,
                'installment_status': updated_installment['status'],
                'remaining_balance': schedule.get_remaining_balance(),
                'reference': reference,
                'skipped_installments': unpaid_before  # Warning: earlier unpaid installments
            },
            message="Payment recorded successfully" if unpaid_before == 0 
                    else f"Payment recorded. Note: {unpaid_before} earlier installment(s) still unpaid.",
            status_code=status.HTTP_201_CREATED
        )


class ActiveLoansView(LoanOfficerRequiredMixin, APIView):
    """
    Loan Officer: Get active (disbursed) loans for payment recording.
    
    GET /api/loans/officer/active-loans/
    
    Query params:
        - search: Search by customer name, phone, or ID
        - customer_id: Filter by specific customer ID
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        has_permission, result = self.check_officer_permission(request)
        if not has_permission:
            return result
        
        from loans.models import RepaymentSchedule, LoanProduct
        from accounts.models import Customer
        
        search = request.query_params.get('search', '').strip()
        customer_id_filter = request.query_params.get('customer_id', '')
        
        # Build customer query
        if customer_id_filter:
            # Direct customer ID filter
            customers = [Customer.find_one({'customer_id': customer_id_filter})]
            customers = [c for c in customers if c]
        elif search:
            # Search by name, phone, or email using Customer.find()
            import re
            regex = re.compile(f'.*{re.escape(search)}.*', re.IGNORECASE)
            customers = Customer.find({
                '$or': [
                    {'first_name': regex},
                    {'last_name': regex},
                    {'phone': regex},
                    {'email': regex}
                ]
            })[:20]  # Limit to 20 results
        else:
            # Return empty if no search criteria
            return success_response(
                data={'loans': [], 'total': 0},
                message="Provide search term or customer_id"
            )
        
        # Get loans for these customers
        loans_data = []
        for customer in customers:
            if not customer:
                continue
                
            # Get repayment schedules (active loans)
            schedules = RepaymentSchedule.find_by_customer(customer.id)
            
            for schedule in schedules:
                if not schedule:
                    continue
                
                # Get application for product info
                app = LoanApplication.find_by_id(schedule.loan_id)
                product = None
                if app:
                    product = LoanProduct.find_by_id(app.product_id)
                
                # Get next payment due
                next_payment = schedule.get_next_payment()
                
                loans_data.append({
                    'loan_id': schedule.loan_id,
                    'schedule_id': schedule.id,
                    'customer_id': customer.id,
                    'customer_name': f"{customer.first_name} {customer.last_name}",
                    'customer_phone': getattr(customer, 'phone', None),
                    'product_name': product.name if product else 'Unknown',
                    'disbursed_amount': schedule.principal,
                    'monthly_payment': schedule.monthly_payment,
                    'remaining_balance': schedule.get_remaining_balance(),
                    'paid_installments': schedule.get_paid_count(),
                    'total_installments': schedule.term_months,
                    'next_due_installment': next_payment['number'] if next_payment else None,
                    'next_due_date': next_payment['due_date'].isoformat() if next_payment and next_payment.get('due_date') else None,
                    'next_due_amount': next_payment['total_amount'] if next_payment else None
                })
        
        return success_response(
            data={'loans': loans_data, 'total': len(loans_data)},
            message="Active loans retrieved"
        )
