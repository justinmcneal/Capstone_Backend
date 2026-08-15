import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.throttles import PreQualifyRateThrottle
from loans.models import LoanProduct
from loans.serializers import PreQualifyRequestSerializer
from loans.services import (
    check_basic_eligibility,
    qualify_customer,
    resolve_required_document_types,
)
from loans.services.product_rules import (
    ProductRuleViolation,
    validate_application_terms,
)
from loans.services.settlement_policy import public_settlement_policy

logger = logging.getLogger("loans")


from loans.views.customer.base import CustomerRoleRequiredMixin


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

        products = LoanProduct.find(active_only=True, limit=200)

        products_data = [
            {
                "id": p.id,
                "name": p.name,
                "code": p.code,
                "description": p.description,
                "min_amount": p.min_amount,
                "max_amount": p.max_amount,
                "interest_rate": p.interest_rate,
                "interest_rate_unit": "decimal",
                "interest_rate_period": "monthly",
                "interest_rate_display": f"{p.interest_rate * 100:.1f}% monthly",
                "min_term_months": p.min_term_months,
                "max_term_months": p.max_term_months,
                "required_documents": resolve_required_document_types(
                    p,
                    requirements_scope="product",
                ),
                "target_description": p.target_description,
            }
            for p in products
        ]

        return success_response(
            data={
                "products": products_data,
                "total": len(products_data),
                "settlement_policy": public_settlement_policy(),
            },
            message="Loan products retrieved successfully",
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
                message="Loan product not found", status_code=status.HTTP_404_NOT_FOUND
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
                "interest_rate_unit": "decimal",
                "interest_rate_period": "monthly",
                "interest_rate_display": f"{product.interest_rate * 100:.1f}% monthly",
                "min_term_months": product.min_term_months,
                "max_term_months": product.max_term_months,
                "required_documents": resolve_required_document_types(
                    product,
                    requirements_scope="product",
                ),
                "min_business_months": product.min_business_months,
                "min_monthly_income": product.min_monthly_income,
                "target_description": product.target_description,
                "settlement_policy": public_settlement_policy(),
            },
            message="Product details retrieved",
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
            product_id = data["product_id"]
            requested_amount = data["amount"]
            term_months = data.get("term_months", 12)
            purpose = data.get("purpose", "")
            requirements_scope = data.get("requirements_scope")

            product = LoanProduct.find_by_id(product_id)
            if not product or not product.active:
                return error_response(
                    message="Loan product not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            try:
                validate_application_terms(product, requested_amount, term_months)
            except ProductRuleViolation as exc:
                return error_response(
                    message=exc.message,
                    errors={exc.field: exc.message},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Quick eligibility check
            basic = check_basic_eligibility(
                customer_id,
                product,
                requirements_scope=requirements_scope,
                require_approved_documents=False,
            )
            if not basic["can_apply"]:
                return success_response(
                    data={
                        "eligible": False,
                        "can_apply": False,
                        "missing_requirements": basic["missing_requirements"],
                        "requirements_scope": basic.get(
                            "requirements_scope", "product"
                        ),
                        "required_documents_resolved": basic.get(
                            "required_documents_resolved", []
                        ),
                        "message": "Please complete requirements before applying",
                    },
                    message="Eligibility check complete",
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

            recommended_amount = qualification.get("recommended_amount") or 0
            quote_amount = 0.0
            monthly_payment = 0.0
            total_interest = 0.0
            total_repayment = 0.0
            if qualification.get("eligible") and qualification.get("can_apply"):
                try:
                    quote_amount = float(recommended_amount)
                except (TypeError, ValueError):
                    quote_amount = 0.0

                if quote_amount > 0 and term_months > 0:
                    monthly_interest = quote_amount * float(
                        product.interest_rate or 0.0
                    )
                    total_interest = monthly_interest * term_months
                    total_repayment = quote_amount + total_interest
                    monthly_payment = total_repayment / term_months

            return success_response(
                data={
                    "product": {"id": product.id, "name": product.name},
                    "requested_amount": requested_amount,
                    "term_months": term_months,
                    "eligible": qualification.get("eligible", False),
                    "eligibility_score": qualification.get("eligibility_score"),
                    "risk_category": qualification.get("risk_category"),
                    "recommended_amount": qualification.get("recommended_amount"),
                    "interest_rate": product.interest_rate,
                    "interest_rate_unit": "decimal",
                    "interest_rate_period": "monthly",
                    "interest_rate_display": f"{product.interest_rate * 100:.1f}% monthly",
                    "monthly_payment": (
                        round(monthly_payment, 2) if monthly_payment else 0.0
                    ),
                    "total_interest": (
                        round(total_interest, 2) if total_interest else 0.0
                    ),
                    "total_repayment": (
                        round(total_repayment, 2) if total_repayment else 0.0
                    ),
                    "reasoning": qualification.get("reasoning"),
                    "strengths": qualification.get("strengths", []),
                    "concerns": qualification.get("concerns", []),
                    "missing_requirements": qualification.get(
                        "missing_requirements", []
                    ),
                    "can_apply": qualification.get(
                        "can_apply",
                        qualification.get("eligible", False),
                    ),
                    "requirements_scope": qualification.get(
                        "requirements_scope",
                        basic.get("requirements_scope", "product"),
                    ),
                    "required_documents_resolved": qualification.get(
                        "required_documents_resolved",
                        basic.get("required_documents_resolved", []),
                    ),
                },
                message="Pre-qualification complete",
            )

        except Exception as e:
            logger.error(f"Pre-qualify error: {str(e)}")
            return error_response(
                message="Failed to check eligibility",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
