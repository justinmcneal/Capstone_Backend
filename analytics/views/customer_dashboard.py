"""
Customer Dashboard - Personal stats for customers.
"""

import logging
from typing import ClassVar

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response
from profiles.models import AlternativeData, BusinessProfile, CustomerProfile

logger = logging.getLogger("analytics")


class CustomerDashboardView(AccessControlMixin, APIView):
    """
    Customer dashboard - personal statistics.

    GET /api/analytics/customer/
    """

    authentication_classes: ClassVar[list[type]] = [CustomJWTAuthentication]
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]

    def get(self, request):
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result

        user = request.user
        customer_id = user.customer_id
        db = settings.MONGODB

        # My applications
        my_apps = {
            "total": db["loan_applications"].count_documents(
                {"customer_id": str(customer_id)}
            ),
            "pending": db["loan_applications"].count_documents(
                {
                    "customer_id": str(customer_id),
                    "status": {"$in": ["submitted", "under_review"]},
                }
            ),
            "approved": db["loan_applications"].count_documents(
                {"customer_id": str(customer_id), "status": "approved"}
            ),
            "rejected": db["loan_applications"].count_documents(
                {"customer_id": str(customer_id), "status": "rejected"}
            ),
        }

        # My documents
        my_docs = {
            "total": db["documents"].count_documents({"customer_id": str(customer_id)}),
            "verified": db["documents"].count_documents(
                {"customer_id": str(customer_id), "verified": True}
            ),
            "pending": db["documents"].count_documents(
                {"customer_id": str(customer_id), "status": "pending"}
            ),
        }

        # Profile completion
        personal = CustomerProfile.find_by_customer(customer_id)
        business = BusinessProfile.find_by_customer(customer_id)
        alternative = AlternativeData.find_by_customer(customer_id)
        has_personal = bool(personal and personal.profile_completed)
        has_business = bool(business and business.profile_completed)
        has_alternative = bool(alternative and alternative.profile_completed)
        has_id = (
            db["documents"].count_documents(
                {"customer_id": str(customer_id), "document_type": "valid_id"}
            )
            > 0
        )

        section_percentages = [
            personal.completion_percentage if personal else 0,
            business.completion_percentage if business else 0,
            alternative.completion_percentage if alternative else 0,
        ]
        completion = sum(section_percentages) / len(section_percentages)

        profile_completion = {
            "percentage": f"{completion:.0f}%",
            "personal_profile": has_personal,
            "business_profile": has_business,
            "alternative_data": has_alternative,
            "valid_id_uploaded": has_id,
        }

        # AI interactions
        ai_sessions = db["ai_interactions"].count_documents(
            {"customer_id": str(customer_id)}
        )

        return success_response(
            data={
                "applications": my_apps,
                "documents": my_docs,
                "profile_completion": profile_completion,
                "ai_sessions": ai_sessions,
            },
            message="Customer dashboard data retrieved",
        )
