"""Read-only, application-bound tools for the loan-officer AI assistant."""
import json
import logging
from datetime import datetime

from bson import ObjectId
from django.conf import settings

from ai_assistant.services.officer_scope import (
    OfficerAssistantScope,
    has_current_ai_consent,
    revalidate_officer_scope,
)
from loans.models import LoanApplication
from loans.services.qualification import document_type_label

logger = logging.getLogger("ai_assistant")

DOCUMENT_RESULT_LIMIT = 20
INSTALLMENT_RESULT_LIMIT = 24

OFFICER_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_application_summary",
            "description": "Get the bound application's review summary.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_profile_readiness",
            "description": "Get completion and risk-readiness summaries for the bound customer.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_review_status",
            "description": "Get bounded document review statuses for the bound application.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_repayment_summary",
            "description": "Get the bound application's repayment progress summary.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def _error(code, error):
    return {"success": False, "error": error, "code": code}


def _scope_application_query(scope):
    if not ObjectId.is_valid(str(scope.application_id)):
        return None
    return {
        "_id": ObjectId(str(scope.application_id)),
        "customer_id": str(scope.customer_id),
        "assigned_officer": str(scope.officer_id),
    }


def _safe_missing_fields(codes):
    sensitive_parts = {
        "address",
        "birth",
        "contact",
        "date_of_birth",
        "email",
        "first_name",
        "government",
        "last_name",
        "mobile",
        "name",
        "phone",
        "wallet",
    }
    labels = []
    for code in codes or []:
        parts = str(code).lower().split(".")
        if any(part in sensitive_parts for part in parts):
            continue
        labels.append(parts[-1].replace("_", " "))
    return labels


def _format_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    return None


def _get_application_summary(scope):
    projection = {
        "status": 1,
        "product_id": 1,
        "requested_amount": 1,
        "recommended_amount": 1,
        "approved_amount": 1,
        "term_months": 1,
        "purpose": 1,
        "eligibility_score": 1,
        "risk_category": 1,
        "ai_recommendation.reason_codes": 1,
    }
    application = settings.MONGODB[LoanApplication.collection_name].find_one(
        _scope_application_query(scope), projection
    )
    if not application:
        raise LookupError("Bound application is unavailable")

    product_name = None
    product_id = application.get("product_id")
    if ObjectId.is_valid(str(product_id)):
        product = settings.MONGODB["loan_products"].find_one(
            {"_id": ObjectId(str(product_id))}, {"name": 1}
        )
        product_name = product.get("name") if product else None

    recommendation = application.get("ai_recommendation") or {}
    return {
        "status": application.get("status"),
        "product": product_name,
        "requested_amount": application.get("requested_amount"),
        "recommended_amount": application.get("recommended_amount"),
        "approved_amount": application.get("approved_amount"),
        "term_months": application.get("term_months"),
        "purpose": application.get("purpose"),
        "eligibility_score": application.get("eligibility_score"),
        "risk_category": application.get("risk_category"),
        "risk_reason_codes": recommendation.get("reason_codes", []),
        "review_readiness": (
            "ready_for_review"
            if application.get("status") == "under_review"
            else "not_ready_for_review"
        ),
    }


def _get_profile_readiness(scope):
    customer_id = str(scope.customer_id)
    collections = {
        "personal": "customer_profiles",
        "business": "business_profiles",
        "alternative": "alternative_data",
    }
    base_projection = {
        "completion_percentage": 1,
        "profile_completed": 1,
        "profile_missing_fields": 1,
    }
    result = {}
    for label, collection in collections.items():
        projection = dict(base_projection)
        if label == "alternative":
            projection.update(
                {
                    "risk_score_status": 1,
                    "risk_category": 1,
                    "risk_score_manual_review_required": 1,
                }
            )
        profile = settings.MONGODB[collection].find_one(
            {"customer_id": customer_id}, projection
        )
        if not profile:
            result[label] = {"available": False}
            continue
        result[label] = {
            "available": True,
            "completion_percentage": profile.get("completion_percentage", 0),
            "complete": bool(profile.get("profile_completed", False)),
            "missing_fields": _safe_missing_fields(profile.get("profile_missing_fields")),
        }
        if label == "alternative":
            result[label].update(
                {
                    "risk_score_status": profile.get("risk_score_status"),
                    "risk_category": profile.get("risk_category"),
                    "manual_review_required": bool(
                        profile.get("risk_score_manual_review_required", True)
                    ),
                }
            )
    return result


def _get_document_review_status(scope):
    customer_id = str(scope.customer_id)
    projection = {"document_type": 1, "status": 1, "verified": 1}
    documents = list(
        settings.MONGODB["documents"]
        .find({"customer_id": customer_id}, projection)
        .sort("uploaded_at", -1)
        .limit(DOCUMENT_RESULT_LIMIT + 1)
    )
    truncated = len(documents) > DOCUMENT_RESULT_LIMIT
    documents = documents[:DOCUMENT_RESULT_LIMIT]
    return {
        "documents": [
            {
                "type": document_type_label(document.get("document_type", "unknown")),
                "status": document.get("status", "unknown"),
                "verified": bool(document.get("verified", False)),
            }
            for document in documents
        ],
        "truncated": truncated,
    }


def _get_repayment_summary(scope):
    projection = {
        "status": 1,
        "monthly_payment": 1,
        "installments.number": 1,
        "installments.status": 1,
        "installments.due_date": 1,
        "installments.total_amount": 1,
        "installments.paid_amount": 1,
    }
    schedule = settings.MONGODB["repayment_schedules"].find_one(
        {"loan_id": str(scope.application_id), "customer_id": str(scope.customer_id)},
        projection,
    )
    if not schedule:
        return {"schedule_available": False}

    installments = list(schedule.get("installments") or [])[:INSTALLMENT_RESULT_LIMIT]
    paid = sum(item.get("status") == "paid" for item in installments)
    remaining = sum(
        max((item.get("total_amount") or 0) - (item.get("paid_amount") or 0), 0)
        for item in installments
    )
    next_due = next((item for item in installments if item.get("status") != "paid"), None)
    return {
        "schedule_available": True,
        "schedule_status": schedule.get("status"),
        "monthly_amount": schedule.get("monthly_payment"),
        "installments_shown": len(installments),
        "installments_paid": paid,
        "remaining_balance": remaining,
        "next_due_date": _format_date(next_due.get("due_date")) if next_due else None,
        "next_due_status": next_due.get("status") if next_due else None,
    }


OFFICER_TOOL_EXECUTORS = {
    "get_application_summary": _get_application_summary,
    "get_profile_readiness": _get_profile_readiness,
    "get_document_review_status": _get_document_review_status,
    "get_repayment_summary": _get_repayment_summary,
}


def execute_officer_tool_result(tool_name, tool_args, scope: OfficerAssistantScope, request_id=None):
    """Execute one allowlisted tool against the current immutable officer scope."""
    executor = OFFICER_TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return _error("AI_OFFICER_TOOL_UNKNOWN", "Requested officer tool is unavailable.")
    if tool_args != {}:
        return _error(
            "AI_OFFICER_TOOL_VALIDATION_FAILED",
            "Officer tool arguments are invalid.",
        )
    try:
        scope_is_current = revalidate_officer_scope(scope)
    except Exception:
        scope_is_current = False
    if not scope_is_current:
        return _error(
            "AI_OFFICER_SCOPE_CHANGED",
            "Officer access to this application is no longer available.",
        )
    try:
        consent_is_current = has_current_ai_consent(scope)
    except Exception:
        consent_is_current = False
    if not consent_is_current:
        return _error(
            "AI_OFFICER_CONSENT_CHANGED",
            "Customer AI consent is no longer available.",
        )
    try:
        return {"success": True, "result": json.dumps(executor(scope), default=str)}
    except Exception:
        logger.warning(
            "Officer AI tool read failed",
            extra={"request_id": request_id, "tool": tool_name},
        )
        return _error("AI_OFFICER_TOOL_READ_FAILED", "Unable to retrieve officer tool data.")
