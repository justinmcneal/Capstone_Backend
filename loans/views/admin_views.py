from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId
from datetime import datetime

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.views.admin_views import AdminRequiredMixin
from loans.models import LoanProduct, LoanApplication
from loans.serializers import LoanProductSerializer
import logging

logger = logging.getLogger('loans')


class AdminProductListView(AdminRequiredMixin, APIView):
    """
    Admin: List and create loan products.
    
    GET /api/loans/admin/products/
    POST /api/loans/admin/products/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """List all products including inactive"""
        import re
        
        active_only = request.query_params.get('active', 'all') == 'true'
        search = request.query_params.get('search', '').strip()
        
        products = LoanProduct.find(active_only=active_only)
        
        # Filter by search term (name or code)
        if search:
            search_regex = re.compile(re.escape(search), re.IGNORECASE)
            products = [
                p for p in products
                if search_regex.search(p.name) or search_regex.search(p.code)
            ]
        
        products_data = [{
            'id': p.id,
            'name': p.name,
            'code': p.code,
            'description': p.description,
            'min_amount': p.min_amount,
            'max_amount': p.max_amount,
            'interest_rate': p.interest_rate,
            'min_term_months': p.min_term_months,
            'max_term_months': p.max_term_months,
            'required_documents': p.required_documents,
            'min_business_months': p.min_business_months,
            'min_monthly_income': p.min_monthly_income,
            'business_types': p.business_types,
            'target_description': p.target_description,
            'active': p.active,
            'created_at': p.created_at.isoformat()
        } for p in products]
        
        return success_response(
            data={'products': products_data, 'total': len(products_data)},
            message="Products retrieved"
        )
    
    def post(self, request):
        """Create a new loan product"""
        serializer = LoanProductSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid product data",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        data = serializer.validated_data
        
        # Check code uniqueness
        if LoanProduct.find_by_code(data['code']):
            return error_response(
                message="Product code already exists",
                errors={'code': 'Product code already exists'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Check name uniqueness
        existing_by_name = LoanProduct.find_one({'name': data['name'], 'active': True})
        if existing_by_name:
            return error_response(
                message="Product name already exists",
                errors={'name': 'Product name already exists'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        product = LoanProduct(
            created_by=request.user.customer_id,
            **data
        )
        product.save()
        
        logger.info(f"Loan product created: {product.code} by {request.user.customer_id}")
        
        return success_response(
            data={'id': product.id, 'code': product.code, 'name': product.name},
            message="Product created successfully",
            status_code=status.HTTP_201_CREATED
        )


class AdminProductDetailView(AdminRequiredMixin, APIView):
    """
    Admin: Update or delete loan products.
    
    GET /api/loans/admin/products/<id>/
    PUT /api/loans/admin/products/<id>/
    DELETE /api/loans/admin/products/<id>/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, product_id):
        product = LoanProduct.find_by_id(product_id)
        if not product:
            return error_response(message="Product not found", status_code=status.HTTP_404_NOT_FOUND)
        
        return success_response(data={
            'id': product.id,
            'name': product.name,
            'code': product.code,
            'description': product.description,
            'min_amount': product.min_amount,
            'max_amount': product.max_amount,
            'interest_rate': product.interest_rate,
            'min_term_months': product.min_term_months,
            'max_term_months': product.max_term_months,
            'required_documents': product.required_documents,
            'min_business_months': product.min_business_months,
            'min_monthly_income': product.min_monthly_income,
            'business_types': product.business_types,
            'target_description': product.target_description,
            'active': product.active,
            'created_at': product.created_at.isoformat()
        })
    
    def put(self, request, product_id):
        from loans.models.application import LoanApplication
        
        product = LoanProduct.find_by_id(product_id)
        if not product:
            return error_response(message="Product not found", status_code=status.HTTP_404_NOT_FOUND)
        
        # DEBUG: Log incoming request data
        logger.info(f"[PUT Product {product_id}] Request data: {request.data}")
        
        # Check for active loans before allowing edits
        active_loans_count = LoanApplication.count_by_product(product_id)
        if active_loans_count > 0:
            return error_response(
                message=f"Cannot edit product with {active_loans_count} active loan(s). Please deactivate the product instead.",
                errors={'product': f'This product has {active_loans_count} active loan application(s)'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Use serializer for validation
        serializer = LoanProductSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            logger.error(f"[PUT Product {product_id}] Serializer errors: {serializer.errors}")
            return error_response(
                message="Invalid product data",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        data = serializer.validated_data
        logger.info(f"[PUT Product {product_id}] Validated data: {data}")
        
        # Check name uniqueness if name is being updated
        if 'name' in data and data['name'] != product.name:
            existing_by_name = LoanProduct.find_one({'name': data['name'], 'active': True})
            if existing_by_name and existing_by_name.id != product.id:
                return error_response(
                    message="Product name already exists",
                    errors={'name': 'Product name already exists'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
        
        # DEBUG: Log values before update
        logger.info(f"[PUT Product {product_id}] BEFORE update - min_business_months: {product.min_business_months}, business_types: {product.business_types}")
        
        # Update allowed fields (includes business_types now - fixes PROD-009)
        updatable = ['name', 'description', 'min_amount', 'max_amount', 'interest_rate',
                     'min_term_months', 'max_term_months', 'required_documents',
                     'min_business_months', 'min_monthly_income', 'business_types',
                     'target_description', 'active']
        
        updated_fields = []
        for field in updatable:
            if field in data:
                old_value = getattr(product, field, None)
                setattr(product, field, data[field])
                updated_fields.append(f"{field}: {old_value} → {data[field]}")
        
        logger.info(f"[PUT Product {product_id}] Updated fields: {updated_fields}")
        
        # DEBUG: Log values after setattr but before save
        logger.info(f"[PUT Product {product_id}] AFTER setattr - min_business_months: {product.min_business_months}, business_types: {product.business_types}")
        
        product.save()
        
        # DEBUG: Verify what was actually saved to DB
        saved_product = LoanProduct.find_by_id(product_id)
        logger.info(f"[PUT Product {product_id}] AFTER save (from DB) - min_business_months: {saved_product.min_business_months}, business_types: {saved_product.business_types}")
        
        logger.info(f"Product updated: {product.code}")
        
        return success_response(data={'id': product.id}, message="Product updated")
    
    def delete(self, request, product_id):
        from loans.models.application import LoanApplication
        
        product = LoanProduct.find_by_id(product_id)
        if not product:
            return error_response(message="Product not found", status_code=status.HTTP_404_NOT_FOUND)
        
        # Check for active loans using this product
        active_loans_count = LoanApplication.count_by_product(product_id)
        if active_loans_count > 0:
            return error_response(
                message=f"Cannot delete product with {active_loans_count} active loan(s)",
                errors={'product': f'This product has {active_loans_count} active loan application(s)'},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            product.delete()  # Soft delete
            logger.info(f"Product deactivated: {product.code}")
            
            # Return updated product info for confirmation
            return success_response(
                data={
                    'id': product.id,
                    'code': product.code,
                    'active': product.active
                },
                message="Product deactivated successfully"
            )
        except ValueError as e:
            logger.error(f"Failed to deactivate product {product_id}: {str(e)}")
            return error_response(
                message="Failed to deactivate product",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AssignApplicationView(AdminRequiredMixin, APIView):
    """
    Admin: Manually assign application to officer.
    
    POST /api/loans/admin/applications/<id>/assign/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, application_id):
        app = LoanApplication.find_by_id(application_id)
        if not app:
            return error_response(
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        officer_id = request.data.get('officer_id')
        if not officer_id:
            return error_response(
                message="officer_id is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        from loans.services import manual_assign_application
        
        try:
            officer = manual_assign_application(app, officer_id)
            if not officer:
                return error_response(
                    message="Officer not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            return success_response(
                data={
                    'application_id': app.id,
                    'assigned_officer': officer.id,
                    'officer_name': officer.full_name,
                    'status': app.status
                },
                message="Application assigned successfully"
            )
        except ValueError as e:
            return error_response(
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST
            )


class ReassignApplicationView(AdminRequiredMixin, APIView):
    """
    Admin: Reassign application to a different officer.
    
    POST /api/loans/admin/applications/<id>/reassign/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, application_id):
        app = LoanApplication.find_by_id(application_id)
        if not app:
            return error_response(
                message="Application not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        new_officer_id = request.data.get('officer_id')
        if not new_officer_id:
            return error_response(
                message="officer_id is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        from loans.services import reassign_application
        
        try:
            new_officer = reassign_application(app, new_officer_id)
            if not new_officer:
                return error_response(
                    message="Officer not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            return success_response(
                data={
                    'application_id': app.id,
                    'assigned_officer': new_officer.id,
                    'officer_name': new_officer.full_name,
                    'status': app.status
                },
                message="Application reassigned successfully"
            )
        except ValueError as e:
            return error_response(
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST
            )


class OfficerWorkloadView(AdminRequiredMixin, APIView):
    """
    Admin: View officer workloads and pending applications.
    
    GET /api/loans/admin/officers/workload/
    Query params:
        - search: Filter by officer name/email
        - page: Page number (default 1)
        - page_size: Items per page (default 20)
        - pending_page: Page number for pending applications (default 1)
        - pending_page_size: Items per page for pending apps (default 20)
        - pending_search: Search term for pending applications
        - assigned_page: Page number for assigned applications (default 1)
        - assigned_page_size: Items per page for assigned apps (default 20)
        - assigned_search: Search term for assigned applications
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        from loans.services import get_officers_workload
        
        # Get query parameters for officers
        search = request.query_params.get('search', '').strip()
        try:
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 20))
            
            # Validate pagination params
            if page < 1:
                page = 1
            if page_size < 1 or page_size > 100:
                page_size = 20
        except ValueError:
            page = 1
            page_size = 20
        
        # Get query parameters for pending applications
        pending_search = request.query_params.get('pending_search', '').strip()
        try:
            pending_page = int(request.query_params.get('pending_page', 1))
            pending_page_size = int(request.query_params.get('pending_page_size', 20))
            
            # Validate pagination params
            if pending_page < 1:
                pending_page = 1
            if pending_page_size < 1 or pending_page_size > 100:
                pending_page_size = 20
        except ValueError:
            pending_page = 1
            pending_page_size = 20
        
        # Get query parameters for assigned applications
        assigned_search = request.query_params.get('assigned_search', '').strip()
        try:
            assigned_page = int(request.query_params.get('assigned_page', 1))
            assigned_page_size = int(request.query_params.get('assigned_page_size', 20))
            
            # Validate pagination params
            if assigned_page < 1:
                assigned_page = 1
            if assigned_page_size < 1 or assigned_page_size > 100:
                assigned_page_size = 20
        except ValueError:
            assigned_page = 1
            assigned_page_size = 20
        
        # Get paginated workload
        workload_data = get_officers_workload(
            page=page,
            page_size=page_size,
            search=search if search else None
        )
        
        # Get paginated pending applications
        pending_data = LoanApplication.find_pending_paginated(
            page=pending_page,
            page_size=pending_page_size,
            search=pending_search if pending_search else None
        )
        
        # Get paginated assigned applications
        assigned_data = LoanApplication.find_assigned_paginated(
            page=assigned_page,
            page_size=assigned_page_size,
            search=assigned_search if assigned_search else None,
            officer_id=None  # Get all assigned apps, not filtered by officer
        )
        
        # Format pending applications for response
        pending_apps = [{
            'id': app.id,
            'customer_id': app.customer_id,
            'requested_amount': app.requested_amount,
            'term_months': app.term_months,
            'status': app.status,
            'eligibility_score': app.eligibility_score,
            'risk_category': app.risk_category,
            'assigned_officer': app.assigned_officer,
            'submitted_at': app.submitted_at.isoformat() if app.submitted_at else None
        } for app in pending_data['applications']]
        
        # Format assigned applications for response
        assigned_apps = [{
            'id': app.id,
            'customer_id': app.customer_id,
            'requested_amount': app.requested_amount,
            'term_months': app.term_months,
            'status': app.status,
            'eligibility_score': app.eligibility_score,
            'risk_category': app.risk_category,
            'assigned_officer': app.assigned_officer,
            'submitted_at': app.submitted_at.isoformat() if app.submitted_at else None
        } for app in assigned_data['applications']]
        
        return success_response(
            data={
                'officers': workload_data['officers'],
                'total': workload_data['total'],
                'page': workload_data['page'],
                'page_size': workload_data['page_size'],
                'total_pages': workload_data['total_pages'],
                'pending_applications': pending_apps,
                'pending_count': pending_data['total'],
                'pending_page': pending_data['page'],
                'pending_page_size': pending_data['page_size'],
                'pending_total_pages': pending_data['total_pages'],
                'assigned_applications': assigned_apps,
                'assigned_count': assigned_data['total'],
                'assigned_page': assigned_data['page'],
                'assigned_page_size': assigned_data['page_size'],
                'assigned_total_pages': assigned_data['total_pages']
            },
            message="Officer workload retrieved"
        )



