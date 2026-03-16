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

logger = logging.getLogger('ai_assistant')


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
            "description": "Get the status of all the user's loan applications. Call this when the user asks about their loan status, applications, or whether they have any active loans.",
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
            "description": "Get the user's repayment schedule including all installments, paid/pending status, and remaining balance. Call this when the user asks about their repayment schedule, installments, or remaining balance.",
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
            "description": "Get all available loan products with their interest rates, amount ranges, and requirements. Call this when the user asks about available loans, loan options, interest rates, or loan products.",
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
    from profiles.models.profile_models import CustomerProfile, BusinessProfile

    result = {"profile": None, "business": None}

    profile = CustomerProfile.find_by_customer(customer_id)
    if profile:
        missing = []
        if not getattr(profile, 'date_of_birth', None):
            missing.append('date of birth')
        if not getattr(profile, 'gender', None):
            missing.append('gender')
        if not getattr(profile, 'civil_status', None):
            missing.append('civil status')
        if not getattr(profile, 'mobile_number', None):
            missing.append('mobile number')
        if not getattr(profile, 'address_line1', None):
            missing.append('address')
        if not getattr(profile, 'emergency_contact_name', None):
            missing.append('emergency contact name')
        if not getattr(profile, 'emergency_contact_phone', None):
            missing.append('emergency contact phone')

        result["profile"] = {
            "completion_percentage": getattr(profile, 'completion_percentage', 0),
            "is_complete": getattr(profile, 'profile_completed', False),
            "missing_fields": missing,
        }

    business = BusinessProfile.find_by_customer(customer_id)
    if business:
        result["business"] = {
            "business_name": getattr(business, 'business_name', None),
            "business_type": getattr(business, 'business_type', None),
            "business_age_months": getattr(business, 'business_age_months', None),
            "estimated_monthly_income": getattr(business, 'estimated_monthly_income', None),
            "is_registered": getattr(business, 'is_registered', False),
        }

    return result


def _get_document_status(customer_id, **kwargs):
    from documents.models.document import Document

    docs = Document.find_by_customer(customer_id)
    if not docs:
        return {"documents": [], "summary": "No documents uploaded yet."}

    doc_list = []
    for doc in docs:
        doc_list.append({
            "type": getattr(doc, 'document_type', 'unknown'),
            "status": getattr(doc, 'status', 'unknown'),
            "verified": getattr(doc, 'verified', False),
        })

    approved = sum(1 for d in doc_list if d['status'] == 'approved')
    pending = sum(1 for d in doc_list if d['status'] == 'pending')
    rejected = sum(1 for d in doc_list if d['status'] == 'rejected')

    return {
        "documents": doc_list,
        "summary": f"{len(doc_list)} document(s): {approved} approved, {pending} pending, {rejected} rejected"
    }


def _get_loan_status(customer_id, **kwargs):
    from loans.models.application import LoanApplication

    apps = LoanApplication.find_by_customer(customer_id)
    if not apps:
        return {"applications": [], "summary": "No loan applications yet."}

    app_list = []
    for app in apps[:5]:
        app_list.append({
            "status": getattr(app, 'status', 'unknown'),
            "requested_amount": getattr(app, 'requested_amount', None),
            "approved_amount": getattr(app, 'approved_amount', None),
            "term_months": getattr(app, 'term_months', None),
            "purpose": getattr(app, 'purpose', None),
            "created_at": getattr(app, 'created_at', None),
            "decision_date": getattr(app, 'decision_date', None),
        })

    return {
        "applications": app_list,
        "total": len(apps),
        "summary": f"{len(apps)} application(s). Most recent: {app_list[0]['status']}" if app_list else "None"
    }


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
            "total_amount": inst.get('total_amount'),
            "paid_amount": inst.get('paid_amount', 0),
            "status": inst.get('status'),
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
    from loans.models.product import LoanProduct

    products = LoanProduct.find(active_only=True)
    if not products:
        return {"products": [], "summary": "No loan products available at this time."}

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

    return {
        "products": product_list,
        "total": len(product_list),
        "summary": f"{len(product_list)} loan product(s) available."
    }
