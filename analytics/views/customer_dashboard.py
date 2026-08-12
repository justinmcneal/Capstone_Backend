"""
Customer Dashboard - Personal stats for customers.
"""

import logging
from datetime import datetime, timezone
from typing import ClassVar

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response
from analytics.services.dashboard_metrics import (
    DOCUMENT_PENDING_STATUSES,
    LOAN_APPROVED_OUTCOME_STATUSES,
    LOAN_DISBURSED_STATUSES,
    LOAN_PENDING_STATUSES,
    METRIC_DEFINITION_VERSION,
    current_document_query,
    identity_query,
    status_query,
)
from analytics.services.operations import AnalyticsOperationalMixin, db_count
from profiles.models import AlternativeData, BusinessProfile, CustomerProfile

logger = logging.getLogger("analytics")


class CustomerDashboardView(AnalyticsOperationalMixin, AccessControlMixin, APIView):
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
        as_of = datetime.now(timezone.utc)
        loan_owner = identity_query("customer_id", customer_id)
        document_owner = identity_query("customer_id", customer_id)

        # My applications
        my_apps = {
            "total": db_count(db, "loan_applications", loan_owner),
            "draft": db_count(db, "loan_applications",
                status_query(loan_owner, {"draft"})
            ),
            "pending": db_count(db, "loan_applications",
                status_query(loan_owner, LOAN_PENDING_STATUSES)
            ),
            "approved": db_count(db, "loan_applications",
                status_query(loan_owner, LOAN_APPROVED_OUTCOME_STATUSES)
            ),
            "rejected": db_count(db, "loan_applications",
                status_query(loan_owner, {"rejected"})
            ),
            "disbursed": db_count(db, "loan_applications",
                status_query(loan_owner, LOAN_DISBURSED_STATUSES)
            ),
            "completed": db_count(db, "loan_applications",
                status_query(loan_owner, {"completed"})
            ),
            "written_off": db_count(db, "loan_applications",
                status_query(loan_owner, {"written_off"})
            ),
            "cancelled": db_count(db, "loan_applications",
                status_query(loan_owner, {"cancelled"})
            ),
        }

        # Current, storage-available documents only.
        current_documents = current_document_query(document_owner)
        my_docs = {
            "total": db_count(db, "documents", current_documents),
            "verified": db_count(db, "documents",
                status_query(current_documents, {"approved"})
            ),
            "pending": db_count(db, "documents",
                status_query(current_documents, DOCUMENT_PENDING_STATUSES)
            ),
            "needs_review": db_count(db, "documents",
                status_query(current_documents, {"needs_review"})
            ),
            "rejected": db_count(db, "documents",
                status_query(current_documents, {"rejected"})
            ),
            "expired": db_count(db, "documents",
                status_query(current_documents, {"expired"})
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
            db_count(db, "documents",
                status_query(
                    current_document_query(
                        {**document_owner, "document_type": "valid_id"}
                    ),
                    {"approved"},
                )
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
        ai_sessions = db_count(db, "ai_interactions",
            identity_query("customer_id", customer_id)
        )

        return success_response(
            data={
                "as_of": as_of.isoformat(),
                "metric_definition_version": METRIC_DEFINITION_VERSION,
                "applications": my_apps,
                "documents": my_docs,
                "profile_completion": profile_completion,
                "ai_sessions": ai_sessions,
            },
            message="Customer dashboard data retrieved",
        )
