"""Read-only, application-bound tools for the loan-officer AI assistant."""
import json
import logging

from bson import ObjectId
from django.conf import settings

from ai_assistant.services.officer_scope import (
    OfficerAssistantScope,
    has_current_ai_consent,
    revalidate_officer_scope,
)
from documents.models.document import Document
from loans.models import LoanApplication
from loans.models.product import LoanProduct
from loans.services.qualification import document_type_label, resolve_required_document_types
from loans.utils.money import from_centavos, to_centavos

logger = logging.getLogger("ai_assistant")

DOCUMENT_RESULT_LIMIT = 20
LOAN_PAYMENT_COLLECTION = "loan_payments"

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


def _get_application_summary(scope):
    projection = {
        "status": 1,
        "product_id": 1,
        "requested_amount": 1,
        "recommended_amount": 1,
        "approved_amount": 1,
        "term_months": 1,
        "eligibility_score": 1,
        "risk_category": 1,
    }
    application = settings.MONGODB[LoanApplication.collection_name].find_one(
        _scope_application_query(scope), projection
    )
    if not application:
        raise LookupError("Bound application is unavailable")

    return {
        "status": application.get("status"),
        "product_assigned": bool(application.get("product_id")),
        "requested_amount": application.get("requested_amount"),
        "recommended_amount": application.get("recommended_amount"),
        "approved_amount": application.get("approved_amount"),
        "term_months": application.get("term_months"),
        "eligibility_score": application.get("eligibility_score"),
        "risk_category": application.get("risk_category"),
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
    application = settings.MONGODB[LoanApplication.collection_name].find_one(
        _scope_application_query(scope), {"product_id": 1}
    )
    if not application:
        raise LookupError("Bound application is unavailable")
    product_id = application.get("product_id")
    if not ObjectId.is_valid(str(product_id)):
        raise LookupError("Bound application product is unavailable")
    product_data = settings.MONGODB[LoanProduct.collection_name].find_one(
        {"_id": ObjectId(str(product_id))}, {"required_documents": 1}
    )
    if not product_data:
        raise LookupError("Bound application product is unavailable")
    product = LoanProduct.from_dict(product_data)
    required_types = resolve_required_document_types(product)
    projection = {"document_type": 1, "status": 1, "verified": 1}
    documents = list(
        settings.MONGODB["documents"]
        .find(
            {
                **Document.available_query(Document._customer_query(customer_id)),
                "document_type": {"$in": required_types},
            },
            projection,
        )
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


def _summarize_posted_payments(loan_id, customer_id):
    """Return a one-row aggregate for posted and legacy status-less payments."""
    rows = list(
        settings.MONGODB[LOAN_PAYMENT_COLLECTION].aggregate(
            [
                {
                    "$match": {
                        "loan_id": str(loan_id),
                        "customer_id": str(customer_id),
                        "$or": [
                            {"payment_status": "posted"},
                            {"payment_status": {"$exists": False}},
                        ],
                    }
                },
                {
                    "$project": {
                        "amount_centavos": {
                            "$cond": [
                                {
                                    "$eq": [
                                        {"$ifNull": ["$amount_centavos", None]},
                                        None,
                                    ]
                                },
                                {
                                    "$toLong": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    {"$ifNull": ["$amount", 0]},
                                                    100,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                {"$toLong": "$amount_centavos"},
                            ]
                        }
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "count": {"$sum": 1},
                        "total_centavos": {"$sum": "$amount_centavos"},
                    }
                },
                {
                    "$project": {
                        "_id": 0,
                        "count": 1,
                        "total_centavos": 1,
                    }
                },
                {"$limit": 1},
            ]
        )
    )
    if not rows:
        return {"count": 0, "total_centavos": 0}

    aggregate = rows[0]
    return {
        "count": int(aggregate.get("count") or 0),
        "total_centavos": int(aggregate.get("total_centavos") or 0),
    }


def _get_repayment_summary(scope):
    projection = {
        "status": 1,
        "term_months": 1,
        "monthly_payment": 1,
        "monthly_payment_centavos": 1,
        "total_amount": 1,
        "total_amount_centavos": 1,
    }
    schedule = settings.MONGODB["repayment_schedules"].find_one(
        {"loan_id": str(scope.application_id), "customer_id": str(scope.customer_id)},
        projection,
    )
    if not schedule:
        return {"schedule_available": False}

    payment_summary = _summarize_posted_payments(
        scope.application_id, scope.customer_id
    )
    monthly_payment_centavos = schedule.get("monthly_payment_centavos")
    if monthly_payment_centavos is None:
        monthly_payment_centavos = to_centavos(
            schedule.get("monthly_payment") or 0, "monthly_payment"
        )
    total_amount_centavos = schedule.get("total_amount_centavos")
    if total_amount_centavos is None:
        total_amount_centavos = to_centavos(
            schedule.get("total_amount") or 0, "total_amount"
        )
    total_paid_centavos = payment_summary["total_centavos"]
    return {
        "schedule_available": True,
        "schedule_status": schedule.get("status"),
        "term_months": schedule.get("term_months"),
        "monthly_amount": from_centavos(monthly_payment_centavos),
        "total_amount": from_centavos(total_amount_centavos),
        "total_paid": from_centavos(total_paid_centavos),
        "posted_payment_count": payment_summary["count"],
        "remaining_balance": from_centavos(
            max(total_amount_centavos - total_paid_centavos, 0)
        ),
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
    if tool_args != {}:
        return _error(
            "AI_OFFICER_TOOL_VALIDATION_FAILED",
            "Officer tool arguments are invalid.",
        )
    try:
        return {"success": True, "result": json.dumps(executor(scope), default=str)}
    except Exception:
        logger.warning(
            "Officer AI tool read failed",
            extra={"request_id": request_id, "tool": tool_name},
        )
        return _error("AI_OFFICER_TOOL_READ_FAILED", "Unable to retrieve officer tool data.")
