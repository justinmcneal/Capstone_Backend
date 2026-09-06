from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text
from rest_framework import status
from accounts.views.admin_views import AdminRequiredMixin
from loans.models import LoanProduct, LoanApplication
from loans.serializers import LoanProductSerializer
import logging

logger = logging.getLogger("loans")


def invalidate_loan_products_cache():
    """Invalidate all loan products related caches when products are modified."""
    cache.delete("ai_tool_loan_products")
    logger.debug("Loan products cache invalidated")


class AdminProductListView(AdminRequiredMixin, APIView):
    """
    Admin: List and create loan products.

    GET /api/loans/admin/products/
    POST /api/loans/admin/products/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    required_permissions = ["manage_system"]

    def get(self, request):
        """List all products including inactive"""
        import re

        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        active_param = sanitize_text(request.query_params.get("active", "all")).lower()
        if active_param in {"true", "1", "yes", "on"}:
            active_filter = True
        elif active_param in {"false", "0", "no", "off"}:
            active_filter = False
        elif active_param in {"all", ""}:
            active_filter = None
        else:
            return error_response(
                message="Invalid active filter",
                errors={"active": "active must be true, false, or all"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        search = sanitize_text(request.query_params.get("search", ""))

        try:
            page = int(request.query_params.get("page", 1))
            page_size = min(int(request.query_params.get("page_size", 50)), 100)
        except (TypeError, ValueError):
            return error_response(
                message="Invalid product pagination",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if page < 1 or page_size < 1:
            return error_response(
                message="Product page and page_size must be positive",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        query = {}
        if active_filter is not None:
            query["active"] = active_filter
        if search:
            search_regex = re.compile(re.escape(search), re.IGNORECASE)
            query["$or"] = [{"name": search_regex}, {"code": search_regex}]
        total = LoanProduct.count(query, active_only=False)
        products = LoanProduct.find(
            query,
            active_only=False,
            skip=(page - 1) * page_size,
            limit=page_size,
        )

        products_data = [
            {
                "id": p.id,
                "name": p.name,
                "code": p.code,
                "description": p.description,
                "min_amount": p.min_amount,
                "max_amount": p.max_amount,
                "interest_rate": p.interest_rate,
                "min_term_months": p.min_term_months,
                "max_term_months": p.max_term_months,
                "required_documents": p.required_documents,
                "min_business_months": p.min_business_months,
                "min_monthly_income": p.min_monthly_income,
                "business_types": p.business_types,
                "target_description": p.target_description,
                "active": p.active,
                "created_at": p.created_at.isoformat(),
            }
            for p in products
        ]

        return success_response(
            data={
                "products": products_data,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            },
            message="Products retrieved",
        )

    def post(self, request):
        """Create a new loan product"""
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        serializer = LoanProductSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid product data",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        # Check code uniqueness
        if LoanProduct.find_by_code(data["code"]):
            return error_response(
                message="Product code already exists",
                errors={"code": "Product code already exists"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Check name uniqueness
        existing_by_name = LoanProduct.find_one({"name": data["name"], "active": True})
        if existing_by_name:
            return error_response(
                message="Product name already exists",
                errors={"name": "Product name already exists"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        product = LoanProduct(created_by=request.user.customer_id, **data)
        product.save()

        # Invalidate cache since products changed
        invalidate_loan_products_cache()

        logger.info(
            f"Loan product created: {product.code} by {request.user.customer_id}"
        )

        return success_response(
            data={"id": product.id, "code": product.code, "name": product.name},
            message="Product created successfully",
            status_code=status.HTTP_201_CREATED,
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
    required_permissions = ["manage_system"]

    def get(self, request, product_id):
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        product = LoanProduct.find_by_id(product_id)
        if not product:
            return error_response(
                message="Product not found", status_code=status.HTTP_404_NOT_FOUND
            )

        return success_response(
            data={
                "id": product.id,
                "name": product.name,
                "code": product.code,
                "description": product.description,
                "min_amount": product.min_amount,
                "max_amount": product.max_amount,
                "interest_rate": product.interest_rate,
                "min_term_months": product.min_term_months,
                "max_term_months": product.max_term_months,
                "required_documents": product.required_documents,
                "min_business_months": product.min_business_months,
                "min_monthly_income": product.min_monthly_income,
                "business_types": product.business_types,
                "target_description": product.target_description,
                "active": product.active,
                "created_at": product.created_at.isoformat(),
            }
        )

    def put(self, request, product_id):
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        product = LoanProduct.find_by_id(product_id)
        if not product:
            return error_response(
                message="Product not found", status_code=status.HTTP_404_NOT_FOUND
            )

        # DEBUG: Log incoming request data
        logger.info(f"[PUT Product {product_id}] Request data: {request.data}")

        # Check for active loans before allowing edits
        active_loans_count = LoanApplication.count_by_product(product_id)
        if active_loans_count > 0:
            return error_response(
                message=f"Cannot edit product with {active_loans_count} active loan(s). Please deactivate the product instead.",
                errors={
                    "product": f"This product has {active_loans_count} active loan application(s)"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Use serializer for validation
        serializer = LoanProductSerializer(
            instance=product, data=request.data, partial=True
        )
        if not serializer.is_valid():
            logger.error(
                f"[PUT Product {product_id}] Serializer errors: {serializer.errors}"
            )
            return error_response(
                message="Invalid product data",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        logger.info(f"[PUT Product {product_id}] Validated data: {data}")

        # Check name uniqueness if name is being updated
        if "name" in data and data["name"] != product.name:
            existing_by_name = LoanProduct.find_one(
                {"name": data["name"], "active": True}
            )
            if existing_by_name and existing_by_name.id != product.id:
                return error_response(
                    message="Product name already exists",
                    errors={"name": "Product name already exists"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        # DEBUG: Log values before update
        logger.info(
            f"[PUT Product {product_id}] BEFORE update - min_business_months: {product.min_business_months}, business_types: {product.business_types}"
        )

        # Update allowed fields (includes business_types now - fixes PROD-009)
        updatable = [
            "name",
            "description",
            "min_amount",
            "max_amount",
            "interest_rate",
            "min_term_months",
            "max_term_months",
            "required_documents",
            "min_business_months",
            "min_monthly_income",
            "business_types",
            "target_description",
            "active",
        ]

        updated_fields = []
        for field in updatable:
            if field in data:
                old_value = getattr(product, field, None)
                setattr(product, field, data[field])
                updated_fields.append(f"{field}: {old_value} → {data[field]}")

        logger.info(f"[PUT Product {product_id}] Updated fields: {updated_fields}")

        # DEBUG: Log values after setattr but before save
        logger.info(
            f"[PUT Product {product_id}] AFTER setattr - min_business_months: {product.min_business_months}, business_types: {product.business_types}"
        )

        product.save()

        # DEBUG: Verify what was actually saved to DB
        saved_product = LoanProduct.find_by_id(product_id)
        logger.info(
            f"[PUT Product {product_id}] AFTER save (from DB) - min_business_months: {saved_product.min_business_months}, business_types: {saved_product.business_types}"
        )

        # Invalidate cache since products changed
        invalidate_loan_products_cache()

        logger.info(f"Product updated: {product.code}")

        return success_response(data={"id": product.id}, message="Product updated")

    def delete(self, request, product_id):
        has_permission, result = self.check_admin_permission(request)
        if not has_permission:
            return result

        product = LoanProduct.find_by_id(product_id)
        if not product:
            return error_response(
                message="Product not found", status_code=status.HTTP_404_NOT_FOUND
            )

        # Check for active loans using this product
        active_loans_count = LoanApplication.count_by_product(product_id)
        if active_loans_count > 0:
            return error_response(
                message=f"Cannot delete product with {active_loans_count} active loan(s)",
                errors={
                    "product": f"This product has {active_loans_count} active loan application(s)"
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            product.delete()  # Soft delete
            logger.info(f"Product deactivated: {product.code}")

            # Invalidate cache since products changed
            invalidate_loan_products_cache()

            # Return updated product info for confirmation
            return success_response(
                data={"id": product.id, "code": product.code, "active": product.active},
                message="Product deactivated successfully",
            )
        except ValueError as e:
            logger.error(f"Failed to deactivate product {product_id}: {str(e)}")
            return error_response(
                message="Failed to deactivate product",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
