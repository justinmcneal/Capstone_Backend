"""Read-only, application-bound tools for the loan-officer AI assistant."""
import json
import logging
import re
from collections import Counter

from bson import ObjectId
from bson.decimal128 import Decimal128
from django.conf import settings

from ai_assistant.services.officer_scope import (
    OfficerAssistantScope,
    has_current_ai_consent,
    revalidate_officer_scope,
)
from documents.models.document import Document
from loans.models import LoanApplication
from loans.models.product import LoanProduct
from loans.models.repayment import RepaymentSchedule
from loans.services.qualification import (
    document_type_label,
    resolve_required_document_types,
)
from loans.utils.money import from_centavos, to_centavos

logger = logging.getLogger("ai_assistant")

DOCUMENT_RESULT_LIMIT = 20
LOAN_PAYMENT_COLLECTION = "loan_payments"
SAFE_APPLICATION_STATUSES = frozenset(
    {
        "draft",
        "submitted",
        "under_review",
        "approved",
        "rejected",
        "disbursed",
        "completed",
        "written_off",
        "cancelled",
    }
)
SAFE_RISK_CATEGORIES = frozenset({"low", "medium", "high"})
SAFE_RISK_STATUSES = frozenset(
    {"not_calculated", "pending", "calculated", "failed", "stale"}
)
SAFE_DOCUMENT_STATUSES = frozenset(
    {"pending", "needs_review", "approved", "rejected", "expired"}
)
SAFE_INSTALLMENT_STATUSES = frozenset(
    {"pending", "partial", "overdue", "partial_overdue", "paid"}
)
SAFE_MISSING_FIELD_LABELS = {
    "personal.gender": "Gender",
    "personal.civil_status": "Civil status",
    "personal.nationality": "Nationality",
    "business.business_type": "Business type",
    "business.business_age_months": "Business age",
    "business.is_registered": "Business registration status",
    "business.estimated_monthly_income": "Monthly income",
    "business.income_range": "Income range",
    "business.estimated_monthly_expenses": "Monthly expenses",
    "business.number_of_employees": "Number of employees",
    "alternative.education_level": "Education level",
    "alternative.employment_status": "Employment status",
    "alternative.years_of_experience": "Business experience",
    "alternative.housing_status": "Housing status",
    "alternative.number_of_dependents": "Number of dependents",
    "alternative.has_existing_loans": "Existing loans status",
    "alternative.has_bank_account": "Bank account status",
    "alternative.has_ewallet": "E-wallet status",
    "alternative.pays_utilities": "Utility payment status",
    "alternative.is_coop_member": "Cooperative membership",
}
_UNSAFE_PURPOSE_PATTERN = re.compile(
    r"(?:@|\b(?:street|st\.?|road|rd\.?|avenue|ave\.?|barangay|address|phone|mobile)\b|\b\d{3,}\b|0x[0-9a-f]{8,})",
    re.IGNORECASE,
)

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


def _safe_enum(value, allowed, fallback="unknown"):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else fallback


def _safe_percentage(value):
    try:
        return max(0, min(100, int(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def _safe_codes(value, limit=10):
    codes = []
    for raw_code in value if isinstance(value, (list, tuple)) else []:
        code = str(raw_code or "").strip().lower()
        if (
            code
            and len(code) <= 64
            and re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", code)
            and code not in codes
        ):
            codes.append(code)
        if len(codes) >= limit:
            break
    return codes


def _safe_purpose(value):
    purpose = str(value or "").strip()
    if not purpose or len(purpose) > 80 or _UNSAFE_PURPOSE_PATTERN.search(purpose):
        return None
    return purpose


def _safe_missing_fields(profile):
    missing = []
    seen = set()
    for raw_code in profile.get("profile_missing_fields", []):
        code = str(raw_code or "").strip().lower()
        label = SAFE_MISSING_FIELD_LABELS.get(code)
        if label and code not in seen:
            seen.add(code)
            missing.append({"code": code, "label": label})
        if len(missing) >= 12:
            break
    return missing


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
        "purpose": 1,
        "ai_recommendation": 1,
    }
    application = settings.MONGODB[LoanApplication.collection_name].find_one(
        _scope_application_query(scope), projection
    )
    if not application:
        raise LookupError("Bound application is unavailable")

    application_model = LoanApplication.from_dict(application)
    recommendation = application_model.ai_recommendation
    if not isinstance(recommendation, dict):
        recommendation = {}
    status = _safe_enum(application_model.status, SAFE_APPLICATION_STATUSES)
    product = None
    product_id = application_model.product_id
    if ObjectId.is_valid(str(product_id)):
        product_data = settings.MONGODB[LoanProduct.collection_name].find_one(
            {"_id": ObjectId(str(product_id))}, {"name": 1, "code": 1}
        )
        if product_data:
            product = {
                key: str(product_data[key])[:80]
                for key in ("name", "code")
                if product_data.get(key)
            }
    manual_review_required = bool(
        recommendation.get("manual_review_required") or status == "under_review"
    )
    return {
        "status": status,
        "product": product,
        "product_assigned": bool(product_id),
        "requested_amount": application_model.requested_amount,
        "recommended_amount": application_model.recommended_amount,
        "approved_amount": application_model.approved_amount,
        "term_months": application_model.term_months,
        "purpose": _safe_purpose(application_model.purpose),
        "eligibility_score": application_model.eligibility_score,
        "risk_category": _safe_enum(
            application_model.risk_category, SAFE_RISK_CATEGORIES
        ),
        "reason_codes": _safe_codes(recommendation.get("reason_codes")),
        "review_readiness": {
            "status": (
                "ready_for_review"
                if status == "under_review"
                else "not_ready_for_review"
            ),
            "is_reviewable": status in {"submitted", "under_review"},
            "manual_review_required": manual_review_required,
        },
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
            "completion_percentage": _safe_percentage(
                profile.get("completion_percentage", 0)
            ),
            "complete": bool(profile.get("profile_completed", False)),
            "missing_fields": _safe_missing_fields(profile),
        }
        if label == "alternative":
            risk_status = _safe_enum(
                profile.get("risk_score_status"), SAFE_RISK_STATUSES
            )
            manual_review_required = bool(
                profile.get("risk_score_manual_review_required", True)
            )
            result[label].update(
                {
                    "risk_status": risk_status,
                    "risk_score_status": risk_status,
                    "risk_category": _safe_enum(
                        profile.get("risk_category"), SAFE_RISK_CATEGORIES
                    ),
                    "manual_review_required": manual_review_required,
                    "manual_review_flags": ["risk_score"]
                    if manual_review_required
                    else [],
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
        "required_document_types": [
            {"code": document_type, "label": document_type_label(document_type)}
            for document_type in required_types
        ],
        "documents": [
            {
                "type": document_type_label(document.get("document_type", "unknown")),
                "status": _safe_enum(
                    document.get("status"), SAFE_DOCUMENT_STATUSES
                ),
                "verified": bool(document.get("verified", False)),
                "verification_status": (
                    "verified" if document.get("verified", False) else "unverified"
                ),
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
                                        "$floor": {
                                            "$add": [
                                                {
                                                    "$multiply": [
                                                        {
                                                            "$toDecimal": {
                                                                "$ifNull": [
                                                                    "$amount",
                                                                    0,
                                                                ]
                                                            }
                                                        },
                                                        Decimal128("100"),
                                                    ]
                                                },
                                                Decimal128("0.5"),
                                            ]
                                        }
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


def _summarize_installment_statuses(installments):
    counts = Counter(
        _safe_enum(item.get("status"), SAFE_INSTALLMENT_STATUSES)
        for item in installments
    )
    return [
        {"status": status, "count": counts[status]}
        for status in sorted(counts)
    ]


def _get_repayment_summary(scope):
    projection = {
        "status": 1,
        "term_months": 1,
        "monthly_payment": 1,
        "monthly_payment_centavos": 1,
        "total_amount": 1,
        "total_amount_centavos": 1,
        "installments": 1,
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
    installments = RepaymentSchedule.from_dict(schedule).installments or []
    paid_count = sum(
        1 for installment in installments if installment.get("status") == "paid"
    )
    next_installment = next(
        (
            installment
            for installment in installments
            if installment.get("status") != "paid"
        ),
        None,
    )
    next_due_date = next_installment.get("due_date") if next_installment else None
    if hasattr(next_due_date, "isoformat"):
        next_due_date = next_due_date.isoformat()
    installment_count = len(installments)
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
        "schedule_progress": {
            "paid_count": paid_count,
            "installment_count": installment_count,
            "completed_percentage": (
                int(paid_count * 100 / installment_count)
                if installment_count
                else 0
            ),
        },
        "next_due_date": next_due_date,
        "payment_status_summaries": _summarize_installment_statuses(installments),
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
