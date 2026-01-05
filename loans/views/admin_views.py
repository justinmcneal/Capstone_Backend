from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId
from datetime import datetime

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.mixins import AdminRequiredMixin
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
        active_only = request.query_params.get('active', 'all') == 'true'
        products = LoanProduct.find(active_only=active_only)
        
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
        product = LoanProduct.find_by_id(product_id)
        if not product:
            return error_response(message="Product not found", status_code=status.HTTP_404_NOT_FOUND)
        
        # Update allowed fields
        updatable = ['name', 'description', 'min_amount', 'max_amount', 'interest_rate',
                     'min_term_months', 'max_term_months', 'required_documents',
                     'min_business_months', 'min_monthly_income', 'target_description', 'active']
        
        for field in updatable:
            if field in request.data:
                setattr(product, field, request.data[field])
        
        product.save()
        logger.info(f"Product updated: {product.code}")
        
        return success_response(data={'id': product.id}, message="Product updated")
    
    def delete(self, request, product_id):
        product = LoanProduct.find_by_id(product_id)
        if not product:
            return error_response(message="Product not found", status_code=status.HTTP_404_NOT_FOUND)
        
        product.delete()  # Soft delete
        logger.info(f"Product deactivated: {product.code}")
        
        return success_response(message="Product deactivated")
