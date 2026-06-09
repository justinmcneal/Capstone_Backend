"""
=============================================================================
USER CONTEXT BUILDER - Privacy-aware context for AI personalization
=============================================================================

This module builds user context for the AI assistant with:
- Safe redaction of sensitive fields
- Context summarization to minimize tokens
- Privacy controls for what data is exposed
- Structured formatting for consistent AI parsing

VERSION: 1.0
=============================================================================
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger('ai_assistant')


# =============================================================================
# PRIVACY CONFIGURATION
# =============================================================================

# Fields that should NEVER be included in AI context
REDACTED_FIELDS = [
    'password', 'pin', 'otp', 'secret', 'private_key', 'seed_phrase',
    'ssn', 'tax_id', 'bank_account', 'credit_card', 'cvv',
]

# Fields that should be partially masked (show last 4 chars)
MASKED_FIELDS = [
    'mobile_number', 'phone', 'email',
]

# Maximum items to include for lists (prevents token explosion)
MAX_DOCUMENTS = 5
MAX_APPLICATIONS = 3
MAX_PAYMENTS = 3
MAX_INSTALLMENTS = 6

PERSONAL_PROFILE_REQUIRED_FIELDS = [
    ('date_of_birth', 'date of birth'),
    ('gender', 'gender'),
    ('civil_status', 'civil status'),
    ('address_line1', 'address'),
    ('barangay', 'barangay'),
    ('city_municipality', 'city / municipality'),
    ('province', 'province'),
]

BUSINESS_PROFILE_REQUIRED_FIELDS = [
    ('business_type', 'business type'),
    ('income_range', 'income range'),
]

ALTERNATIVE_DATA_REQUIRED_FIELDS = [
    ('education_level', 'education level'),
    ('housing_status', 'housing status'),
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def mask_value(value: str, show_last: int = 4) -> str:
    """Mask a value, showing only the last N characters."""
    if not value or len(value) <= show_last:
        return value
    return '*' * (len(value) - show_last) + value[-show_last:]


def format_currency(amount: float) -> str:
    """Format amount as Philippine Peso."""
    if amount is None:
        return "N/A"
    return f"₱{amount:,.0f}"


def format_date(dt: datetime) -> str:
    """Format datetime for display."""
    if not dt:
        return "N/A"
    return dt.strftime('%b %d, %Y')


def days_until(dt: datetime) -> int:
    """Calculate days until a date."""
    if not dt:
        return 0
    delta = dt - datetime.now()
    return delta.days


def summarize_status(status: str) -> str:
    """Convert status codes to user-friendly text."""
    status_map = {
        'draft': 'Draft (not submitted)',
        'submitted': 'Submitted (awaiting review)',
        'under_review': 'Under Review',
        'approved': 'Approved ✓',
        'rejected': 'Rejected',
        'disbursed': 'Active (disbursed)',
        'cancelled': 'Cancelled',
        'pending': 'Pending',
        'paid': 'Paid ✓',
        'partial': 'Partially Paid',
        'overdue': 'Overdue ⚠',
        'verified': 'Verified ✓',
        'pending_review': 'Pending Review',
    }
    return status_map.get(status, status.replace('_', ' ').title())


# =============================================================================
# CONTEXT SUMMARY BUILDERS
# =============================================================================

def build_profile_summary(customer_id: str) -> dict:
    """
    Build a summarized profile context.
    
    Returns dict with:
        - completion_pct: Profile completion percentage
        - missing_fields: List of missing required fields
        - has_business: Whether business profile has started
        - business_summary: One-line business summary
    """
    from profiles.models.profile_models import CustomerProfile, BusinessProfile, AlternativeData
    
    result = {
        'completion_pct': 0,
        'missing_fields': [],
        'has_business': False,
        'business_complete': False,
        'missing_business_fields': [],
        'business_summary': None,
        'alternative_complete': False,
        'missing_alternative_fields': [],
        'risk_category': None,
    }
    
    # Personal profile
    profile = CustomerProfile.find_by_customer(customer_id)
    if profile:
        result['completion_pct'] = getattr(profile, 'completion_percentage', 0) or 0
        
        for field, label in PERSONAL_PROFILE_REQUIRED_FIELDS:
            if not getattr(profile, field, None):
                result['missing_fields'].append(label)
    
    # Business profile
    business = BusinessProfile.find_by_customer(customer_id)
    if business and any(getattr(business, field, None) for field, _ in BUSINESS_PROFILE_REQUIRED_FIELDS):
        result['has_business'] = True
        result['business_complete'] = all(
            getattr(business, field, None) for field, _ in BUSINESS_PROFILE_REQUIRED_FIELDS
        )
        for field, label in BUSINESS_PROFILE_REQUIRED_FIELDS:
            if not getattr(business, field, None):
                result['missing_business_fields'].append(label)

        name = getattr(business, 'business_name', None) or 'Business profile'
        btype = getattr(business, 'business_type', 'business')
        age = getattr(business, 'business_age_months', 0)
        income = getattr(business, 'estimated_monthly_income', 0)
        income_range = getattr(business, 'income_range', None)
        
        parts = [name]
        if btype:
            parts.append(f"({btype})")
        if age:
            years = age // 12
            months = age % 12
            if years > 0:
                parts.append(f"{years}y {months}m old")
            else:
                parts.append(f"{months} months old")
        if income:
            parts.append(f"income {format_currency(income)}/mo")
        elif income_range:
            parts.append(f"income range {income_range}")
        
        result['business_summary'] = ' '.join(parts)

    alternative = AlternativeData.find_by_customer(customer_id)
    if alternative:
        result['alternative_complete'] = all(
            getattr(alternative, field, None) for field, _ in ALTERNATIVE_DATA_REQUIRED_FIELDS
        )
        for field, label in ALTERNATIVE_DATA_REQUIRED_FIELDS:
            if not getattr(alternative, field, None):
                result['missing_alternative_fields'].append(label)
        result['risk_category'] = getattr(alternative, 'risk_category', None)
    
    return result


def build_documents_summary(customer_id: str) -> dict:
    """
    Build a summarized documents context.
    
    Returns dict with:
        - total: Total documents
        - verified: Number verified
        - pending: Number pending review
        - rejected: Number rejected
        - types: List of document types with status
    """
    from documents.models.document import Document
    
    result = {
        'total': 0,
        'verified': 0,
        'pending': 0,
        'rejected': 0,
        'types': [],
    }
    
    docs = Document.find_by_customer(customer_id)
    if not docs:
        return result
    
    result['total'] = len(docs)
    
    for doc in docs[:MAX_DOCUMENTS]:
        dtype = getattr(doc, 'document_type', 'unknown')
        dstatus = getattr(doc, 'status', 'unknown')
        
        if dstatus == 'approved':
            result['verified'] += 1
        elif dstatus in ('pending', 'needs_review'):
            result['pending'] += 1
        elif dstatus == 'rejected':
            result['rejected'] += 1
        
        label = dtype.replace('_', ' ').title()
        result['types'].append({'type': label, 'status': dstatus})
    
    return result


def build_loans_summary(customer_id: str) -> dict:
    """
    Build a summarized loans context.
    
    Returns dict with:
        - total_applications: Total loan applications
        - active_loans: Number of active (disbursed) loans
        - applications: List of application summaries
        - total_outstanding: Total outstanding balance
        - next_payment: Next payment due info
        - overdue_count: Number of overdue installments
    """
    from loans.models.application import LoanApplication
    from loans.models.repayment import RepaymentSchedule
    
    result = {
        'total_applications': 0,
        'active_loans': 0,
        'applications': [],
        'total_outstanding': 0,
        'next_payment': None,
        'overdue_count': 0,
    }
    
    apps = LoanApplication.find_by_customer(customer_id)
    if not apps:
        return result
    
    result['total_applications'] = len(apps)
    earliest_due = None
    earliest_payment = None
    
    for app in apps[:MAX_APPLICATIONS]:
        app_status = getattr(app, 'status', 'unknown')
        amount = getattr(app, 'approved_amount', None) or getattr(app, 'requested_amount', None)
        term = getattr(app, 'term_months', None)
        
        app_summary = {
            'status': app_status,
            'status_display': summarize_status(app_status),
            'amount': format_currency(amount) if amount else None,
            'term': f"{term} months" if term else None,
        }
        
        # For disbursed loans, get repayment info
        if app_status == 'disbursed' and hasattr(app, 'id'):
            result['active_loans'] += 1
            schedule = RepaymentSchedule.find_by_loan(str(app.id))
            
            if schedule:
                installments = getattr(schedule, 'installments', [])
                total_inst = len(installments)
                paid_inst = sum(1 for i in installments if i.get('status') == 'paid')
                overdue_inst = sum(1 for i in installments if i.get('status') == 'overdue')
                penalized_inst = sum(1 for i in installments if i.get('penalty_status') == 'applied')
                remaining = schedule.get_remaining_balance()
                
                result['total_outstanding'] += remaining
                result['overdue_count'] += overdue_inst
                
                app_summary['installments'] = f"{paid_inst}/{total_inst} paid"
                app_summary['remaining'] = format_currency(remaining)
                
                if overdue_inst > 0:
                    app_summary['overdue'] = overdue_inst
                if penalized_inst > 0:
                    app_summary['penalized'] = penalized_inst
                
                # Track next payment
                next_pay = schedule.get_next_payment()
                if next_pay:
                    due_date = next_pay.get('due_date')
                    if due_date and (earliest_due is None or due_date < earliest_due):
                        earliest_due = due_date
                        earliest_payment = {
                            'amount': format_currency(next_pay.get('total_amount', 0)),
                            'due_date': format_date(due_date),
                            'days_until': days_until(due_date),
                            'penalty_status': next_pay.get('penalty_status'),
                        }
        
        # Show blockchain status for disbursed loans with ETH disbursement
        if app_status == 'disbursed':
            disbursed_amount = getattr(app, 'disbursed_amount', None)
            if disbursed_amount:
                app_summary['disbursed_amount'] = format_currency(disbursed_amount)
        
        result['applications'].append(app_summary)
    
    result['next_payment'] = earliest_payment
    result['total_outstanding'] = format_currency(result['total_outstanding'])
    
    return result


# =============================================================================
# MAIN CONTEXT BUILDER
# =============================================================================

def build_user_context(
    customer_id: str,
    include_profile: bool = True,
    include_documents: bool = True,
    include_loans: bool = True,
    summarize: bool = True,
) -> str:
    """
    Build a privacy-aware, summarized user context for the AI.
    
    Args:
        customer_id: The customer's ID
        include_profile: Include profile/business info
        include_documents: Include document status
        include_loans: Include loan/payment info
        summarize: Use summarized format (fewer tokens)
    
    Returns:
        Context string to append to system prompt
    """
    try:
        lines = ["\n\n=== USER CONTEXT ==="]
        
        # Profile Summary
        if include_profile:
            profile = build_profile_summary(customer_id)
            
            if profile['completion_pct'] > 0:
                status = "✓ Complete" if profile['completion_pct'] >= 100 else f"{profile['completion_pct']}% complete"
                lines.append(f"Profile: {status}")
                
                if profile['missing_fields']:
                    lines.append(f"  Missing: {', '.join(profile['missing_fields'])}")
            else:
                lines.append("Profile: Not started")
            
            if profile['has_business']:
                lines.append(f"Business: {profile['business_summary']}")
                if profile['missing_business_fields']:
                    lines.append(f"  Missing business info: {', '.join(profile['missing_business_fields'])}")
            else:
                lines.append("Business: Not set up")

            if profile['alternative_complete']:
                alt_line = "Alternative Data: Complete"
                if profile['risk_category']:
                    alt_line += f" | Risk category: {profile['risk_category']}"
                lines.append(alt_line)
            elif profile['missing_alternative_fields']:
                lines.append(f"Alternative Data: Missing {', '.join(profile['missing_alternative_fields'])}")
            else:
                lines.append("Alternative Data: Not set up")
        
        # Documents Summary
        if include_documents:
            docs = build_documents_summary(customer_id)
            
            if docs['total'] > 0:
                parts = [f"{docs['total']} uploaded"]
                if docs['verified'] > 0:
                    parts.append(f"{docs['verified']} verified")
                if docs['pending'] > 0:
                    parts.append(f"{docs['pending']} pending")
                if docs['rejected'] > 0:
                    parts.append(f"{docs['rejected']} rejected")
                lines.append(f"Documents: {', '.join(parts)}")
                
                # List document types if not summarizing
                if not summarize:
                    for doc in docs['types']:
                        lines.append(f"  • {doc['type']}: {summarize_status(doc['status'])}")
            else:
                lines.append("Documents: None uploaded")
        
        # Loans Summary
        if include_loans:
            loans = build_loans_summary(customer_id)
            
            if loans['total_applications'] > 0:
                if loans['active_loans'] > 0:
                    lines.append(f"Active Loans: {loans['active_loans']}")
                    lines.append(f"Outstanding Balance: {loans['total_outstanding']}")
                    
                    if loans['overdue_count'] > 0:
                        lines.append(f"⚠ Overdue Installments: {loans['overdue_count']}")
                    
                    if loans['next_payment']:
                        np = loans['next_payment']
                        urgency = ""
                        if np['days_until'] < 0:
                            urgency = " (OVERDUE)"
                        elif np['days_until'] <= 3:
                            urgency = " (due soon)"
                        lines.append(f"Next Payment: {np['amount']} due {np['due_date']}{urgency}")
                
                # Application details
                for app in loans['applications']:
                    app_line = f"Loan: {app['status_display']}"
                    if app.get('amount'):
                        app_line += f" | {app['amount']}"
                    if app.get('installments'):
                        app_line += f" | {app['installments']}"
                    if app.get('remaining'):
                        app_line += f" | Remaining: {app['remaining']}"
                    if app.get('overdue'):
                        app_line += f" | ⚠{app['overdue']} overdue"
                    lines.append(f"  {app_line}")
            else:
                lines.append("Loans: No applications yet")
        
        # Instructions for AI
        lines.append("")
        lines.append("IMPORTANT: Use the data above to answer questions. Don't tell user to check the app - give them the actual values.")
        
        context = '\n'.join(lines)
        logger.info(f"Built context for {customer_id}: {len(context)} chars")
        return context
    
    except Exception as e:
        logger.error(f"Context build failed for {customer_id}: {e}", exc_info=True)
        return ""


def build_minimal_context(customer_id: str) -> str:
    """
    Build a minimal context with just key status indicators.
    Use for simple queries that don't need full context.
    
    Returns ~100 tokens instead of ~300.
    """
    try:
        from profiles.models.profile_models import CustomerProfile
        from documents.models.document import Document
        from loans.models.application import LoanApplication
        
        parts = []
        
        # Profile status
        profile = CustomerProfile.find_by_customer(customer_id)
        if profile:
            pct = getattr(profile, 'completion_percentage', 0) or 0
            parts.append(f"Profile: {pct}%")
        else:
            parts.append("Profile: 0%")
        
        # Document count
        docs = Document.find_by_customer(customer_id)
        doc_count = len(docs) if docs else 0
        parts.append(f"Docs: {doc_count}")
        
        # Loan status
        apps = LoanApplication.find_by_customer(customer_id)
        if apps:
            active = sum(1 for a in apps if getattr(a, 'status', '') == 'disbursed')
            parts.append(f"Active loans: {active}")
        else:
            parts.append("Loans: 0")
        
        return f"\n[User: {' | '.join(parts)}]"
    
    except Exception as e:
        logger.error(f"Minimal context failed: {e}")
        return ""


# =============================================================================
# CONTEXT MODE SELECTION
# =============================================================================

def get_context_for_intent(message: str, customer_id: str) -> str:
    """
    Select appropriate context detail level based on the user's question.
    
    - Status questions → Full context
    - Payment questions → Loans only
    - Document questions → Documents only
    - General questions → Minimal context
    """
    message_lower = message.lower()
    
    # Full context for overview questions
    overview_keywords = ['overview', 'summary', 'status', 'everything', 'all',
                         'dashboard', 'stats', 'analytics', 'how am i doing']
    if any(kw in message_lower for kw in overview_keywords):
        return build_user_context(customer_id, summarize=True)
    
    # Loans only for payment/loan questions
    loan_keywords = ['loan', 'payment', 'installment', 'balance', 'due', 'pay', 'bayad', 'utang', 'owe']
    if any(kw in message_lower for kw in loan_keywords):
        return build_user_context(customer_id, include_profile=False, include_documents=False)
    
    # Documents only for document questions
    doc_keywords = ['document', 'upload', 'id', 'permit', 'proof', 'papeles']
    if any(kw in message_lower for kw in doc_keywords):
        return build_user_context(customer_id, include_profile=False, include_loans=False)
    
    # Profile only for profile questions
    profile_keywords = ['profile', 'business', 'complete', 'fill', 'info', 'account']
    if any(kw in message_lower for kw in profile_keywords):
        return build_user_context(customer_id, include_documents=False, include_loans=False)
    
    # Minimal context for general questions
    return build_minimal_context(customer_id)
