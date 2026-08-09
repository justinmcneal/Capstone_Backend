"""
Profile summary service.

Builds the cross-section readiness summary for /api/profile/summary/.
"""

import logging
from typing import Any

from profiles.models import (
    PROFILE_COMPLETION_POLICY_VERSION,
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
)

logger = logging.getLogger("profiles")


def get_profile_summary(customer_id: str) -> dict[str, Any]:
    personal = CustomerProfile.find_by_customer(customer_id) or CustomerProfile(
        customer_id=str(customer_id)
    )
    business = BusinessProfile.find_by_customer(customer_id) or BusinessProfile(
        customer_id=str(customer_id)
    )
    alternative = AlternativeData.find_by_customer(customer_id) or AlternativeData(
        customer_id=str(customer_id)
    )
    personal.calculate_completion()
    business.calculate_completion()
    alternative.calculate_completion()

    from documents.models import Document

    documents = Document.find_by_customer(customer_id)

    personal_complete = personal.profile_completed
    business_complete = business.profile_completed
    alternative_complete = alternative.profile_completed

    total_docs = len(documents)
    approved_docs = len([d for d in documents if d.status == "approved"])
    pending_docs = len([d for d in documents if d.status in ["pending", "needs_review"]])
    rejected_docs = len([d for d in documents if d.status == "rejected"])
    reupload_requested_docs = len([d for d in documents if d.reupload_requested])

    documents_ready = total_docs > 0 and approved_docs == total_docs

    profiles_complete = (
        personal_complete and business_complete and alternative_complete
    )

    documents_complete = total_docs > 0 and approved_docs > 0

    sections_complete = sum(
        [personal_complete, business_complete, alternative_complete]
    )
    overall_percentage = int(
        (
            personal.completion_percentage
            + business.completion_percentage
            + alternative.completion_percentage
        )
        / 3
    )

    profile_ready_for_application = profiles_complete
    ready_for_loan = profile_ready_for_application

    completed_sections = []
    if personal_complete:
        completed_sections.append("Personal Information")
    if business_complete:
        completed_sections.append("Business Information")
    if alternative_complete:
        completed_sections.append("Alternative Data")
    if documents_complete:
        completed_sections.append("Documents")

    missing = (
        []
        if ready_for_loan
        else [
            name
            for name, complete in [
                ("Complete personal profile", personal_complete),
                ("Complete business profile", business_complete),
                ("Complete alternative data", alternative_complete),
            ]
            if not complete
        ]
    )

    return {
        "customer_id": customer_id,
        "personal_profile": {
            "completed": personal_complete,
            "completion_percentage": personal.completion_percentage,
            "profile_revision": personal.profile_revision,
            "completion_policy_version": personal.profile_completion_policy_version,
            "missing_fields": personal.profile_missing_fields,
        },
        "business_profile": {
            "completed": business_complete,
            "has_business_type": bool(business.business_type),
            "has_income_info": bool(
                business.income_range or business.estimated_monthly_income
            ),
            "profile_revision": business.profile_revision,
            "completion_percentage": business.completion_percentage,
            "completion_policy_version": business.profile_completion_policy_version,
            "missing_fields": business.profile_missing_fields,
        },
        "alternative_data": {
            "completed": alternative_complete,
            "has_risk_score": alternative.risk_score is not None,
            "risk_category": alternative.risk_category,
            "risk_score_status": alternative.risk_score_status,
            "risk_score_policy_version": alternative.risk_score_policy_version,
            "risk_score_use": alternative.risk_score_use,
            "risk_score_manual_review_required": (
                alternative.risk_score_manual_review_required
            ),
            "risk_input_revision": alternative.risk_input_revision,
            "risk_calculated_revision": alternative.risk_calculated_revision,
            "profile_revision": alternative.profile_revision,
            "completion_percentage": alternative.completion_percentage,
            "completion_policy_version": (
                alternative.profile_completion_policy_version
            ),
            "missing_fields": alternative.profile_missing_fields,
        },
        "documents": {
            "total": total_docs,
            "approved": approved_docs,
            "pending": pending_docs,
            "rejected": rejected_docs,
            "reupload_requested": reupload_requested_docs,
            "all_approved": documents_ready,
            "has_documents": total_docs > 0,
        },
        "overall": {
            "profiles_complete": profiles_complete,
            "completion_policy_version": PROFILE_COMPLETION_POLICY_VERSION,
            "sections_complete": sections_complete,
            "total_sections": 3,
            "documents_complete": documents_complete,
            "documents_verified": documents_ready,
            "ready_for_loan": ready_for_loan,
            "ready_for_loan_deprecated": True,
            "profile_ready_for_application": profile_ready_for_application,
            "product_eligibility_evaluated": False,
            "completion_percentage": overall_percentage,
            "completed_section_names": completed_sections,
            "missing": missing,
            "missing_field_codes": (
                personal.profile_missing_fields
                + business.profile_missing_fields
                + alternative.profile_missing_fields
            ),
        },
    }
