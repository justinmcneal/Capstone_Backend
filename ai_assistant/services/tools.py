"""
=============================================================================
CHATBOT TOOLS - Function calling tools for the AI assistant
=============================================================================

Defines tool schemas (OpenAI-compatible) and executor functions that query
MongoDB for real-time user data. The LLM decides which tool to call based
on the user's question, the backend executes it, and the result is fed
back to the LLM for a natural language response.

All tools are READ-ONLY — no mutations via chatbot.
=============================================================================
"""
import json
import logging
from datetime import datetime
from django.core.cache import cache
from django.conf import settings
from ai_assistant.services.context_builder import (
    ALTERNATIVE_DATA_REQUIRED_FIELDS,
    BUSINESS_PROFILE_REQUIRED_FIELDS,
    PERSONAL_PROFILE_REQUIRED_FIELDS,
)
from loans.services.qualification import resolve_required_document_types, document_type_label
from notifications.models.notification import get_db

logger = logging.getLogger('ai_assistant')

# Cache TTL for tool results
CACHE_TTL = getattr(settings, 'CACHE_TTL', {})
TOOL_CACHE_TTL = {
    'loan_products': CACHE_TTL.get('loan_products', 1800),  # 30 min - rarely changes
    'profile_status': 60,  # 1 min - changes occasionally
    'document_status': 60,  # 1 min - changes occasionally
    'loan_status': 30,  # 30 sec - may change during conversations
    'repayment': 30,  # 30 sec - payment status may update
    'customer_dashboard': 60,  # 1 min - aggregated summary
    'notification_status': 60,  # 1 min - inbox status
}


def _get_user_cache_key(customer_id: str, tool_name: str) -> str:
    """Generate a per-user cache key for tool results."""
    return f"ai_tool:{tool_name}:{customer_id}"


def invalidate_user_tool_cache(customer_id: str, tool_names: list | None = None):
    """
    Invalidate cached tool results for a user.
    Called when user data changes (e.g., after document upload).
    
    Args:
        customer_id: The customer's ID
        tool_names: List of tools to invalidate, or None for all
    """
    if tool_names is None:
        tool_names = ['profile_status', 'document_status', 'loan_status', 
                      'repayment_schedule', 'next_payment_due', 'application_readiness',
                      'customer_dashboard']
    
    for tool_name in tool_names:
        cache_key = _get_user_cache_key(customer_id, tool_name)
        cache.delete(cache_key)
        logger.debug(f"Invalidated cache: {cache_key}")


# =============================================================================
# TOOL SCHEMAS - OpenAI-compatible function definitions for Groq
# =============================================================================

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_profile_status",
            "description": "Get the user's profile completion status including what fields are missing. Call this when the user asks about their profile, completion percentage, or what they need to fill in.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_status",
            "description": "Get the status of all documents the user has uploaded, including verification status. Call this when the user asks about their documents, uploads, or what documents they still need.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_loan_status",
            "description": "Get the status of the user's OWN loan applications (submitted, approved, disbursed, etc). Call this ONLY when the user asks about THEIR loan status, THEIR applications, or whether THEY have active loans. Do NOT call this for available loan products.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_repayment_schedule",
            "description": "Get the user's full repayment schedule with installment progress (paid/total), remaining balance, and each installment's status. Call this when the user asks how much they owe, how many installments they have paid, their repayment progress, or remaining balance.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_next_payment_due",
            "description": "Get details about the user's next upcoming payment including amount and due date. Call this when the user asks when their next payment is due or how much they need to pay next.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_payment_history",
            "description": "Get the user's recent payment history. Call this when the user asks about their past payments, payment records, or transaction history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent payments to return. Default is 5.",
                        "default": 5
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_loan_products",
            "description": "Get all available loan PRODUCTS offered by the microfinance institution (names, interest rates, amount ranges, requirements). Call this when the user asks what loan products/options are available, what they can borrow, or about interest rates. This is NOT about the user's own applications.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_application_readiness",
            "description": "Check if the user is ready to apply for a loan by checking profile, business, and document status. Call this when the user asks what they still need to do before applying, if they are eligible, or what requirements are missing.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_dashboard",
            "description": "Get the customer's personal dashboard overview including application counts (total, pending, approved, rejected), document stats (total, verified, pending), profile completion percentage with section breakdown, and AI chat session count. Call this when the user asks for a summary, overview, or dashboard of their account, or asks about their overall stats.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_notification_status",
            "description": "Get the user's notification inbox status including unread count and recent notifications. Call this when the user asks about their notifications, alerts, messages, or if they have unread items.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
]


# =============================================================================
# TOOL EXECUTORS - Functions that query MongoDB and return results
# =============================================================================

def execute_tool(tool_name, tool_args, customer_id):
    """
    Execute a tool by name and return the result as a JSON string.
    All tools are read-only and scoped to the authenticated customer.
    """
    executors = {
        'get_profile_status': _get_profile_status,
        'get_document_status': _get_document_status,
        'get_loan_status': _get_loan_status,
        'get_repayment_schedule': _get_repayment_schedule,
        'get_next_payment_due': _get_next_payment_due,
        'get_payment_history': _get_payment_history,
        'get_loan_products': _get_loan_products,
        'get_application_readiness': _get_application_readiness,
        'get_customer_dashboard': _get_customer_dashboard,
        'get_notification_status': _get_notification_status,
    }

    executor = executors.get(tool_name)
    if not executor:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    try:
        result = executor(customer_id=customer_id, **tool_args)
        return json.dumps(result, default=str)
    except Exception as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return json.dumps({"error": "Failed to retrieve data. Please try again."})


def _get_profile_status(customer_id, **kwargs):
    """Get profile status with short-term caching."""
    from profiles.models.profile_models import CustomerProfile, BusinessProfile, AlternativeData

    # Check cache first
    cache_key = _get_user_cache_key(customer_id, 'profile_status')
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = {"profile": None, "business": None, "alternative_data": None}

    profile = CustomerProfile.find_by_customer(customer_id)
    if profile:
        missing = [
            label for field, label in PERSONAL_PROFILE_REQUIRED_FIELDS
            if not getattr(profile, field, None)
        ]

        result["profile"] = {
            "completion_percentage": getattr(profile, 'completion_percentage', 0),
            "is_complete": getattr(profile, 'profile_completed', False),
            "missing_fields": missing,
        }

    business = BusinessProfile.find_by_customer(customer_id)
    if business:
        missing = [
            label for field, label in BUSINESS_PROFILE_REQUIRED_FIELDS
            if not getattr(business, field, None)
        ]
        result["business"] = {
            "business_name": getattr(business, 'business_name', None),
            "business_type": getattr(business, 'business_type', None),
            "business_age_months": getattr(business, 'business_age_months', None),
            "income_range": getattr(business, 'income_range', None),
            "estimated_monthly_income": getattr(business, 'estimated_monthly_income', None),
            "is_registered": getattr(business, 'is_registered', False),
            "is_complete": len(missing) == 0,
            "missing_fields": missing,
        }

    alternative = AlternativeData.find_by_customer(customer_id)
    if alternative:
        missing = [
            label for field, label in ALTERNATIVE_DATA_REQUIRED_FIELDS
            if not getattr(alternative, field, None)
        ]
        result["alternative_data"] = {
            "education_level": getattr(alternative, 'education_level', None),
            "housing_status": getattr(alternative, 'housing_status', None),
            "risk_score": getattr(alternative, 'risk_score', None),
            "risk_category": getattr(alternative, 'risk_category', None),
            "is_complete": len(missing) == 0,
            "missing_fields": missing,
        }

    # Cache for short period
    cache.set(cache_key, result, TOOL_CACHE_TTL['profile_status'])
    return result


def _get_document_status(customer_id, **kwargs):
    """Get document status with short-term caching."""
    from documents.models.document import Document

    # Check cache first
    cache_key = _get_user_cache_key(customer_id, 'document_status')
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    docs = Document.find_by_customer(customer_id)
    if not docs:
        result = {"documents": [], "summary": "No documents uploaded yet."}
        cache.set(cache_key, result, TOOL_CACHE_TTL['document_status'])
        return result

    doc_list = []
    for doc in docs:
        doc_list.append({
            "type": getattr(doc, 'document_type', 'unknown'),
            "type_label": document_type_label(getattr(doc, 'document_type', 'unknown')),
            "status": getattr(doc, 'status', 'unknown'),
            "verified": getattr(doc, 'verified', False),
        })

    approved = sum(1 for d in doc_list if d['status'] == 'approved')
    pending = sum(1 for d in doc_list if d['status'] in ('pending', 'needs_review'))
    rejected = sum(1 for d in doc_list if d['status'] == 'rejected')

    result = {
        "documents": doc_list,
        "summary": f"{len(doc_list)} document(s): {approved} approved, {pending} pending, {rejected} rejected"
    }
    cache.set(cache_key, result, TOOL_CACHE_TTL['document_status'])
    return result


def _get_loan_status(customer_id, **kwargs):
    """Get loan application status with short-term caching."""
    from loans.models.application import LoanApplication

    # Check cache first
    cache_key = _get_user_cache_key(customer_id, 'loan_status')
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    apps = LoanApplication.find_by_customer(customer_id)
    if not apps:
        result = {"applications": [], "summary": "No loan applications yet."}
        cache.set(cache_key, result, TOOL_CACHE_TTL['loan_status'])
        return result

    app_list = []
    for app in apps[:5]:
        app_data = {
            "status": getattr(app, 'status', 'unknown'),
            "requested_amount": getattr(app, 'requested_amount', None),
            "approved_amount": getattr(app, 'approved_amount', None),
            "term_months": getattr(app, 'term_months', None),
            "purpose": getattr(app, 'purpose', None),
            "created_at": getattr(app, 'created_at', None),
            "decision_date": getattr(app, 'decision_date', None),
        }
        # Include disbursed amount and blockchain status for disbursed loans
        if getattr(app, 'status', None) == 'disbursed':
            app_data["disbursed_amount"] = getattr(app, 'disbursed_amount', None)
            app_data["blockchain_tx_hashes"] = getattr(app, 'blockchain_tx_hashes', {})
        app_list.append(app_data)

    result = {
        "applications": app_list,
        "total": len(apps),
        "summary": f"{len(apps)} application(s). Most recent: {app_list[0]['status']}" if app_list else "None"
    }
    cache.set(cache_key, result, TOOL_CACHE_TTL['loan_status'])
    return result


def _get_repayment_schedule(customer_id, **kwargs):
    from loans.models.application import LoanApplication
    from loans.models.repayment import RepaymentSchedule

    apps = LoanApplication.find_by_customer(customer_id)
    disbursed = [a for a in apps if getattr(a, 'status', '') == 'disbursed']

    if not disbursed:
        return {"schedule": None, "summary": "No active loan with a repayment schedule."}

    app = disbursed[0]
    schedule = RepaymentSchedule.find_by_loan(str(app.id))
    if not schedule:
        return {"schedule": None, "summary": "Repayment schedule not yet created."}

    installments = getattr(schedule, 'installments', [])
    total = len(installments)
    paid = sum(1 for i in installments if i.get('status') == 'paid')
    partial = sum(1 for i in installments if i.get('status') == 'partial')
    overdue = sum(1 for i in installments if i.get('status') == 'overdue')
    remaining = schedule.get_remaining_balance()

    installment_summary = []
    for inst in installments:
        due_date = inst.get('due_date')
        installment_summary.append({
            "number": inst.get('number'),
            "due_date": due_date.strftime('%B %d, %Y') if isinstance(due_date, datetime) else str(due_date) if due_date else None,
            "principal": inst.get('principal'),
            "interest": inst.get('interest'),
            "total_amount": inst.get('total_amount'),
            "paid_amount": inst.get('paid_amount', 0),
            "status": inst.get('status'),
            "penalty_status": inst.get('penalty_status'),
            "penalty_amount": inst.get('penalty_amount', 0),
            "penalty_reason": inst.get('penalty_reason', ''),
        })

    return {
        "loan_amount": getattr(app, 'disbursed_amount', None) or getattr(app, 'approved_amount', None),
        "monthly_payment": getattr(schedule, 'monthly_payment', None),
        "total_installments": total,
        "paid": paid,
        "partial": partial,
        "overdue": overdue,
        "remaining_balance": remaining,
        "installments": installment_summary,
        "summary": f"{paid} of {total} paid, remaining ₱{remaining:,.0f}" + (f", {overdue} overdue" if overdue else "")
    }


def _get_next_payment_due(customer_id, **kwargs):
    from loans.models.application import LoanApplication
    from loans.models.repayment import RepaymentSchedule

    apps = LoanApplication.find_by_customer(customer_id)
    disbursed = [a for a in apps if getattr(a, 'status', '') == 'disbursed']

    if not disbursed:
        return {"next_payment": None, "summary": "No active loan."}

    app = disbursed[0]
    schedule = RepaymentSchedule.find_by_loan(str(app.id))
    if not schedule:
        return {"next_payment": None, "summary": "Repayment schedule not yet created."}

    next_payment = schedule.get_next_payment()
    if not next_payment:
        return {"next_payment": None, "summary": "All installments are paid! Loan fully repaid."}

    due_date = next_payment.get('due_date')
    return {
        "next_payment": {
            "installment_number": next_payment.get('number'),
            "amount": next_payment.get('total_amount'),
            "principal": next_payment.get('principal'),
            "interest": next_payment.get('interest'),
            "due_date": due_date.strftime('%B %d, %Y') if isinstance(due_date, datetime) else str(due_date) if due_date else None,
            "status": next_payment.get('status'),
            "paid_amount": next_payment.get('paid_amount', 0),
            "penalty_status": next_payment.get('penalty_status'),
            "penalty_amount": next_payment.get('penalty_amount', 0),
        },
        "summary": f"Next: ₱{next_payment.get('total_amount', 0):,.0f} due {due_date.strftime('%B %d, %Y') if isinstance(due_date, datetime) else due_date}"
    }


def _get_payment_history(customer_id, limit=5, **kwargs):
    from loans.models.payment import LoanPayment

    payments = LoanPayment.find_by_customer(customer_id)
    if not payments:
        return {"payments": [], "summary": "No payment history yet."}

    recent = payments[:limit]
    payment_list = []
    for p in recent:
        recorded_at = getattr(p, 'recorded_at', None)
        payment_list.append({
            "amount": getattr(p, 'amount', 0),
            "payment_method": getattr(p, 'payment_method', 'unknown'),
            "installment_number": getattr(p, 'installment_number', None),
            "recorded_at": recorded_at.strftime('%B %d, %Y') if isinstance(recorded_at, datetime) else str(recorded_at) if recorded_at else None,
            "reference": getattr(p, 'reference', None),
        })

    return {
        "payments": payment_list,
        "total_payments": len(payments),
        "summary": f"{len(payments)} total payment(s). Showing last {len(recent)}."
    }


def _get_loan_products(customer_id, **kwargs):
    """Get available loan products. Results are cached for performance."""
    # Check cache first (loan products don't change frequently)
    cache_key = 'ai_tool_loan_products'
    cached_result = cache.get(cache_key)
    if cached_result:
        return cached_result
    
    from loans.models.product import LoanProduct

    products = LoanProduct.find(active_only=True)
    if not products:
        result = {"products": [], "summary": "No loan products available at this time."}
        cache.set(cache_key, result, TOOL_CACHE_TTL['loan_products'])
        return result

    product_list = []
    for p in products:
        product_list.append({
            "name": getattr(p, 'name', 'Unknown'),
            "code": getattr(p, 'code', None),
            "description": getattr(p, 'description', None),
            "min_amount": getattr(p, 'min_amount', None),
            "max_amount": getattr(p, 'max_amount', None),
            "interest_rate_monthly": getattr(p, 'interest_rate', None),
            "min_term_months": getattr(p, 'min_term_months', None),
            "max_term_months": getattr(p, 'max_term_months', None),
            "min_monthly_income": getattr(p, 'min_monthly_income', None),
            "min_business_months": getattr(p, 'min_business_months', None),
            "required_documents": getattr(p, 'required_documents', []),
        })

    result = {
        "products": product_list,
        "total": len(product_list),
        "summary": f"{len(product_list)} loan product(s) available."
    }
    
    # Cache for future requests
    cache.set(cache_key, result, TOOL_CACHE_TTL['loan_products'])
    return result


def _get_application_readiness(customer_id, **kwargs):
    """Check profile, business, and document completeness for loan application readiness."""
    from profiles.models.profile_models import CustomerProfile, BusinessProfile, AlternativeData
    from documents.models.document import Document

    blockers = []
    completed = []

    # Profile check
    profile = CustomerProfile.find_by_customer(customer_id)
    if profile:
        pct = getattr(profile, 'completion_percentage', 0)
        if pct >= 100:
            completed.append("Personal profile is complete")
        else:
            missing = [
                label for field, label in PERSONAL_PROFILE_REQUIRED_FIELDS
                if not getattr(profile, field, None)
            ]
            blockers.append(f"Profile is {pct}% complete — missing: {', '.join(missing)}")
    else:
        blockers.append("Personal profile has not been created yet")

    # Business check
    business = BusinessProfile.find_by_customer(customer_id)
    if business:
        missing = [
            label for field, label in BUSINESS_PROFILE_REQUIRED_FIELDS
            if not getattr(business, field, None)
        ]
        if missing:
            blockers.append(f"Business profile is incomplete — missing: {', '.join(missing)}")
        else:
            name = getattr(business, 'business_name', None) or 'business profile'
            completed.append(f"Business profile is complete ({name})")
    else:
        blockers.append("Business profile has not been set up yet")

    # Alternative data check
    alternative = AlternativeData.find_by_customer(customer_id)
    if alternative:
        missing = [
            label for field, label in ALTERNATIVE_DATA_REQUIRED_FIELDS
            if not getattr(alternative, field, None)
        ]
        if missing:
            blockers.append(f"Alternative data is incomplete — missing: {', '.join(missing)}")
        else:
            completed.append("Alternative data is complete")
            risk_category = getattr(alternative, 'risk_category', None)
            if risk_category:
                completed.append(f"Risk category calculated: {risk_category}")
    else:
        blockers.append("Alternative data has not been set up yet")

    # Document check
    docs = Document.find_by_customer(customer_id)
    required_types = resolve_required_document_types(requirements_scope='baseline')
    if docs:
        uploaded_types = [getattr(d, 'document_type', '') for d in docs]
        approved_types = [getattr(d, 'document_type', '') for d in docs if getattr(d, 'status', '') == 'approved']
        pending_types = [getattr(d, 'document_type', '') for d in docs if getattr(d, 'status', '') in ('pending', 'needs_review')]
        rejected_types = [getattr(d, 'document_type', '') for d in docs if getattr(d, 'status', '') == 'rejected']

        missing_docs = [document_type_label(t) for t in required_types if t not in uploaded_types]
        if missing_docs:
            baseline_msg = "At a minimum, a valid ID is required." if 'valid_id' in missing_docs else ""
            blockers.append(f"Missing documents (upload required): {', '.join(missing_docs)}. {baseline_msg}")
        if rejected_types:
            blockers.append(f"Rejected documents need re-upload: {', '.join(document_type_label(t) for t in rejected_types)}")
        if pending_types:
            completed.append(f"{len(pending_types)} document(s) pending verification - please wait for verification")
        if approved_types:
            completed.append(f"{len(approved_types)} document(s) approved")
    else:
        blockers.append(f"No documents uploaded — required: {', '.join(document_type_label(t) for t in required_types)}")

    ready = len(blockers) == 0
    return {
        "ready_to_apply": ready,
        "blockers": blockers,
        "completed": completed,
        "summary": "Ready to apply!" if ready else f"{len(blockers)} thing(s) to complete before applying"
    }


def _get_customer_dashboard(customer_id, **kwargs):
    """
    Get customer's personal dashboard overview — aggregated summary
    mirroring the analytics customer dashboard endpoint.
    """
    from profiles.models.profile_models import CustomerProfile, BusinessProfile, AlternativeData
    from documents.models.document import Document
    from loans.models.application import LoanApplication
    from django.conf import settings

    # Check cache first
    cache_key = _get_user_cache_key(customer_id, 'customer_dashboard')
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    db = settings.MONGODB

    # Application counts
    applications = {
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
        "disbursed": db["loan_applications"].count_documents(
            {"customer_id": str(customer_id), "status": "disbursed"}
        ),
    }

    # Document counts
    documents = {
        "total": db["documents"].count_documents(
            {"customer_id": str(customer_id)}
        ),
        "verified": db["documents"].count_documents(
            {"customer_id": str(customer_id), "verified": True}
        ),
        "pending": db["documents"].count_documents(
             {"customer_id": str(customer_id), "status": {"$in": ["pending", "needs_review"]}}
        ),
    }

    # Profile completion (same 3-section logic as analytics customer dashboard)
    personal = db["customer_profiles"].find_one(
        {"customer_id": str(customer_id)},
        sort=[("updated_at", -1), ("created_at", -1)],
    )
    business = db["business_profiles"].find_one(
        {"customer_id": str(customer_id)},
        sort=[("updated_at", -1), ("created_at", -1)],
    )
    alternative = db["alternative_data"].find_one(
        {"customer_id": str(customer_id)},
        sort=[("updated_at", -1), ("created_at", -1)],
    )

    has_personal = bool((personal or {}).get("completion_percentage", 0) > 0)
    has_business = bool(
        (business or {}).get("business_type")
        and (
            (business or {}).get("income_range")
            or (business or {}).get("estimated_monthly_income")
        )
    )
    has_alternative = bool(
        (alternative or {}).get("education_level")
        and (alternative or {}).get("housing_status")
    )
    has_id = (
        db["documents"].count_documents(
            {"customer_id": str(customer_id), "document_type": "valid_id"}
        )
        > 0
    )

    profile_items = [has_personal, has_business, has_alternative]
    completion = (sum(profile_items) / len(profile_items)) * 100

    profile_completion = {
        "percentage": f"{completion:.0f}%",
        "personal_profile": has_personal,
        "business_profile": has_business,
        "alternative_data": has_alternative,
        "valid_id_uploaded": has_id,
    }

    # AI session count
    ai_sessions = db["ai_interactions"].count_documents(
        {"customer_id": str(customer_id)}
    )

    result = {
        "applications": applications,
        "documents": documents,
        "profile_completion": profile_completion,
        "ai_sessions": ai_sessions,
        "summary": (
            f"Profile {profile_completion['percentage']} complete. "
            f"{applications['total']} application(s) "
            f"({applications['pending']} pending, {applications['approved']} approved, "
            f"{applications['disbursed']} active). "
            f"{documents['total']} document(s) ({documents['verified']} verified). "
            f"{ai_sessions} AI chat interaction(s)."
        ),
    }

    cache.set(cache_key, result, TOOL_CACHE_TTL['customer_dashboard'])
    return result


def _get_notification_status(customer_id, **kwargs):
    """Get notification inbox status with unread count and recent notifications."""
    from notifications.models.notification import Notification

    cache_key = _get_user_cache_key(customer_id, 'notification_status')
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    db = get_db()
    collection = db[Notification.collection_name]

    # Build owner query (customers strictly by user_id)
    owner_query = {'user_id': str(customer_id)}
    if not customer_id:
        return {"unread_count": 0, "recent_notifications": [], "summary": "No notifications."}

    unread_query = {**owner_query, 'status': {'$nin': ['read']}}
    unread_count = collection.count_documents(unread_query)

    recent_cursor = collection.find(owner_query).sort('created_at', -1).limit(5)
    recent_notifications = []
    for doc in recent_cursor:
        recent_notifications.append({
            "id": str(doc.get('_id')),
            "notification_type": doc.get('notification_type'),
            "subject": doc.get('subject'),
            "status": doc.get('status'),
            "is_read": doc.get('status') == 'read',
            "created_at": doc.get('created_at'),
        })

    result = {
        "unread_count": unread_count,
        "recent_notifications": recent_notifications,
        "summary": f"{unread_count} unread notification(s)." if unread_count else "No unread notifications."
    }

    cache.set(cache_key, result, TOOL_CACHE_TTL['customer_dashboard'])
    return result
