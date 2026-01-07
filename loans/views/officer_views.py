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
    Loan Officer: View application details.
    
    GET /api/loans/officer/applications/<id>/
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
                'decision_date': app.decision_date.isoformat() if app.decision_date else None
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
        
        if not reference:
            return error_response(
                message="Disbursement reference is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            app.disburse(
                amount=amount,
                method=method,
                reference=reference,
                processed_by=user.customer_id
            )
            
            logger.info(f"Loan disbursed: {app.id} by {user.customer_id}")
            
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
            
            return success_response(
                data={
                    'id': app.id,
                    'status': app.status,
                    'disbursed_amount': app.disbursed_amount,
                    'disbursement_method': app.disbursement_method,
                    'disbursement_reference': app.disbursement_reference,
                    'disbursed_at': app.disbursed_at.isoformat() if app.disbursed_at else None
                },
                message="Loan disbursed successfully"
            )
            
        except ValueError as e:
            return error_response(
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST
            )
