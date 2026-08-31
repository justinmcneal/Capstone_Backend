"""Read-only, application-bound tools for the loan-officer AI assistant."""
import json
import logging
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from bson import ObjectId
from bson.decimal128 import Decimal128
from django.conf import settings

from ai_assistant.services.officer_scope import (
    OfficerAssistantScope,
    has_current_ai_consent,
    revalidate_officer_scope,
)
from config.field_encryption import decrypt_fields
from documents.models.document import Document
from loans.models import LoanApplication
from loans.models.product import LoanProduct
from loans.models.repayment import RepaymentSchedule
from loans.services.qualification import (
    canonicalize_document_type,
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
    {"not_calculated", "pending", "complete", "failed", "stale"}
)
LEGACY_RISK_STATUS_ALIASES = {"calculated": "complete"}
SAFE_DOCUMENT_STATUSES = frozenset(
    {"pending", "needs_review", "approved", "rejected", "expired"}
)
SAFE_INSTALLMENT_STATUSES = frozenset(
    {"pending", "partial", "overdue", "partial_overdue", "paid"}
)
SAFE_SCHEDULE_STATUSES = frozenset(
    {"active", "paid_off", "restructured", "written_off"}
)
SAFE_REASON_CODES = frozenset(
    {
        "income_missing",
        "income_high",
        "income_moderate",
        "income_low",
        "no_existing_loans",
        "loan_history_on_time",
        "loan_history_sometimes_late",
        "loan_history_often_late",
        "loan_history_defaulted",
        "loan_history_no_history",
        "utility_history_on_time",
        "utility_history_sometimes_late",
        "utility_history_often_late",
        "utility_history_no_history",
        "community_participation_present",
        "community_participation_absent",
        "housing_owned",
        "housing_rented",
        "housing_living_with_family",
        "housing_company_provided",
        "housing_missing",
        "digital_accounts_present",
        "digital_accounts_absent",
        "manual-review",
    }
)
MAX_SAFE_MONEY = Decimal("10000000000000")
MAX_SAFE_CENTAVOS = 10**15
MAX_SAFE_TERM_MONTHS = 120
MAX_SAFE_INSTALLMENTS = 120
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
SAFE_PRODUCT_CATEGORIES = {
    "wcl": "working_capital",
    "working capital": "working_capital",
    "working_capital": "working_capital",
    "mbl": "micro_business",
    "micro business": "micro_business",
    "micro_business": "micro_business",
    "inventory": "inventory",
    "inventory loan": "inventory",
}
SAFE_PURPOSE_CATEGORIES = {
    "inventory": "inventory",
    "working capital": "working_capital",
    "working_capital": "working_capital",
    "equipment": "equipment",
    "expansion": "expansion",
    "operations": "operations",
}

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
    normalized = value.strip().lower() if isinstance(value, str) else ""
    return normalized if normalized in allowed else fallback


def _safe_risk_status(value):
    """Normalize legacy profile status values to the canonical contract."""
    normalized = value.strip().lower() if isinstance(value, str) else ""
    normalized = LEGACY_RISK_STATUS_ALIASES.get(normalized, normalized)
    return normalized if normalized in SAFE_RISK_STATUSES else "unknown"


def _safe_percentage(value):
    if isinstance(value, bool):
        return 0
    try:
        numeric = Decimal(str(value))
        if not numeric.is_finite() or numeric < 0 or numeric > 100:
            return 0
        return int(numeric)
    except (InvalidOperation, TypeError, ValueError):
        return 0


def _safe_codes(value, limit=10):
    codes = []
    for raw_code in value if isinstance(value, (list, tuple)) else []:
        code = raw_code.strip().lower() if isinstance(raw_code, str) else ""
        if code in SAFE_REASON_CODES and code not in codes:
            codes.append(code)
        if len(codes) >= limit:
            break
    return codes


def _safe_category(value, allowlist):
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return allowlist.get(normalized)


def _safe_purpose(value):
    return _safe_category(value, SAFE_PURPOSE_CATEGORIES)


def _safe_product(product_data):
    if not product_data:
        return None
    category = _safe_category(product_data.get("code"), SAFE_PRODUCT_CATEGORIES)
    if category is None:
        category = _safe_category(product_data.get("name"), SAFE_PRODUCT_CATEGORIES)
    return {"category": category or "other"}


def _safe_decimal(value):
    if isinstance(value, bool):
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return decimal_value if decimal_value.is_finite() else None


def _safe_money(value):
    decimal_value = _safe_decimal(value)
    if (
        decimal_value is None
        or decimal_value < 0
        or decimal_value > MAX_SAFE_MONEY
    ):
        return 0
    try:
        normalized = decimal_value.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, ValueError):
        return 0
    if normalized == normalized.to_integral_value():
        return int(normalized)
    return float(normalized)


def _safe_integer(value, *, minimum=0, maximum=MAX_SAFE_TERM_MONTHS, fallback=0):
    decimal_value = _safe_decimal(value)
    if (
        decimal_value is None
        or decimal_value < minimum
        or decimal_value > maximum
        or decimal_value != decimal_value.to_integral_value()
    ):
        return fallback
    integer_value = int(decimal_value)
    return integer_value


def _safe_bool(value, fallback=False):
    return value if isinstance(value, bool) else fallback


def _safe_centavos(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        integer_value = value
    elif isinstance(value, (Decimal, Decimal128)):
        decimal_value = _safe_decimal(value)
        if (
            decimal_value is None
            or decimal_value != decimal_value.to_integral_value()
        ):
            return None
        integer_value = int(decimal_value)
    else:
        return None
    if integer_value < 0 or integer_value > MAX_SAFE_CENTAVOS:
        return None
    return integer_value


def _safe_iso_datetime(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).isoformat()
    except ValueError:
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            return None


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
            product = _safe_product(product_data)
    manual_review_required = (
        _safe_bool(recommendation.get("manual_review_required"))
        or status == "under_review"
    )
    return {
        "status": status,
        "product": product,
        "product_assigned": product is not None,
        "requested_amount": _safe_money(application_model.requested_amount),
        "recommended_amount": _safe_money(application_model.recommended_amount),
        "approved_amount": _safe_money(application_model.approved_amount),
        "term_months": _safe_integer(application_model.term_months),
        "purpose": _safe_purpose(application_model.purpose),
        "eligibility_score": _safe_money(
            application_model.eligibility_score
        )
        if _safe_decimal(application_model.eligibility_score) is not None
        and 0 <= _safe_decimal(application_model.eligibility_score) <= 100
        else 0,
        "risk_category": _safe_enum(
            application_model.risk_category, SAFE_RISK_CATEGORIES
        ),
        "reason_codes": _safe_codes(recommendation.get("reason_codes")),
        "review_readiness": {
            "status": (
                "ready_for_review"
                if status in {"submitted", "under_review"}
                else (
                    "not_ready_for_review"
                    if status == "draft"
                    else "review_complete"
                )
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
            "complete": _safe_bool(profile.get("profile_completed", False)),
            "missing_fields": _safe_missing_fields(profile),
        }
        if label == "alternative":
            risk_status = _safe_risk_status(profile.get("risk_score_status"))
            raw_manual_review = profile.get("risk_score_manual_review_required")
            manual_review_required = (
                True if raw_manual_review is None else _safe_bool(raw_manual_review)
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
    raw_required_documents = product_data.get("required_documents")
    if "required_documents" in product_data and raw_required_documents is None:
        raise LookupError("Bound application product requirements are unavailable")
    if raw_required_documents is not None and not isinstance(raw_required_documents, list):
        raise LookupError("Bound application product requirements are invalid")
    if raw_required_documents is not None and any(
        not isinstance(raw_type, str)
        or canonicalize_document_type(raw_type) is None
        for raw_type in raw_required_documents
    ):
        raise LookupError("Bound application product requirements are invalid")
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
    safe_required_types = [
        document_type
        for document_type in required_types
        if isinstance(document_type, str) and document_type
    ]
    return {
        "required_document_types": [
            {"code": document_type, "label": document_type_label(document_type)}
            for document_type in safe_required_types
        ],
        "documents": [
            {
                "type_code": canonicalize_document_type(
                    document.get("document_type")
                )
                or "other",
                "type": document_type_label(document.get("document_type", "unknown")),
                "status": _safe_enum(
                    document.get("status"), SAFE_DOCUMENT_STATUSES
                ),
                "verified": _safe_bool(document.get("verified", False)),
                "verification_status": (
                    "verified"
                    if _safe_bool(document.get("verified", False))
                    else "unverified"
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
                {"$limit": MAX_SAFE_INSTALLMENTS + 1},
                {
                    "$project": {
                        "amount_centavos": {"$ifNull": ["$amount_centavos", None]},
                        "amount": {"$ifNull": ["$amount", None]},
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "payments": {
                            "$push": {
                                "amount_centavos": "$amount_centavos",
                                "amount": "$amount",
                            }
                        },
                    }
                },
                {
                    "$project": {
                        "_id": 0,
                        "payments": 1,
                    }
                },
                {"$limit": 1},
            ]
        )
    )
    if not rows:
        return {"count": 0, "total_centavos": 0}

    aggregate = rows[0]
    if "count" in aggregate and "total_centavos" in aggregate:
        count = _safe_centavos(aggregate.get("count"))
        total_centavos = _safe_centavos(aggregate.get("total_centavos"))
        return {
            "count": min(MAX_SAFE_INSTALLMENTS, count or 0),
            "total_centavos": total_centavos or 0,
            **({"truncated": True} if count > MAX_SAFE_INSTALLMENTS else {}),
        }

    count = 0
    total_centavos = 0
    payments = aggregate.get("payments") or []
    truncated = len(payments) > MAX_SAFE_INSTALLMENTS
    for payment in payments[:MAX_SAFE_INSTALLMENTS]:
        if not isinstance(payment, dict):
            continue
        if payment.get("amount_centavos") is not None:
            amount_centavos = _safe_centavos(payment.get("amount_centavos"))
        else:
            legacy_amount = _safe_decimal(payment.get("amount"))
            amount_centavos = None
            if (
                legacy_amount is not None
                and legacy_amount >= 0
                and legacy_amount <= MAX_SAFE_MONEY
            ):
                try:
                    amount_centavos = to_centavos(legacy_amount, "amount")
                except (InvalidOperation, TypeError, ValueError):
                    amount_centavos = None
        if amount_centavos is None or total_centavos + amount_centavos > MAX_SAFE_CENTAVOS:
            continue
        total_centavos += amount_centavos
        count += 1
    return {
        "count": count,
        "total_centavos": total_centavos,
        **({"truncated": True} if truncated else {}),
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


def _schedule_centavos(schedule, field, *, fallback_field=None):
    raw_value = schedule.get(f"{field}_centavos")
    if raw_value is not None:
        return _safe_centavos(raw_value) or 0
    if fallback_field is None:
        return 0
    legacy_value = _safe_decimal(schedule.get(fallback_field))
    if (
        legacy_value is None
        or legacy_value < 0
        or legacy_value > MAX_SAFE_MONEY
    ):
        return 0
    try:
        return min(MAX_SAFE_CENTAVOS, to_centavos(legacy_value, fallback_field))
    except (InvalidOperation, TypeError, ValueError):
        return 0


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
    schedule_data = decrypt_fields(schedule, RepaymentSchedule.encrypted_fields)
    monthly_payment_centavos = _schedule_centavos(
        schedule, "monthly_payment", fallback_field="monthly_payment"
    )
    total_amount_centavos = _schedule_centavos(
        schedule, "total_amount", fallback_field="total_amount"
    )
    total_paid_centavos = payment_summary["total_centavos"]
    installments = [
        installment
        for installment in (schedule_data.get("installments") or [])
        if isinstance(installment, dict)
    ][:MAX_SAFE_INSTALLMENTS]
    installment_statuses = [
        _safe_enum(installment.get("status"), SAFE_INSTALLMENT_STATUSES)
        for installment in installments
    ]
    paid_count = sum(1 for status in installment_statuses if status == "paid")
    next_due_date = None
    for installment, installment_status in zip(installments, installment_statuses):
        if installment_status != "paid":
            next_due_date = _safe_iso_datetime(installment.get("due_date"))
            if next_due_date:
                break
    installment_count = len(installments)
    return {
        "schedule_available": True,
        "schedule_status": _safe_enum(
            schedule.get("status"), SAFE_SCHEDULE_STATUSES
        ),
        "term_months": _safe_integer(schedule.get("term_months")),
        "monthly_amount": from_centavos(monthly_payment_centavos),
        "total_amount": from_centavos(total_amount_centavos),
        "total_paid": from_centavos(total_paid_centavos),
        "posted_payment_count": payment_summary["count"],
        "payments_truncated": bool(payment_summary.get("truncated")),
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
        result = executor(scope)
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
        return {"success": True, "result": json.dumps(result, default=str)}
    except Exception:
        logger.warning(
            "Officer AI tool read failed",
            extra={"request_id": request_id, "tool": tool_name},
        )
        return _error("AI_OFFICER_TOOL_READ_FAILED", "Unable to retrieve officer tool data.")
