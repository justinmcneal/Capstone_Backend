"""
=============================================================================
AI KNOWLEDGE BASE - Single Source of Truth for MSME Pathways AI Assistant
=============================================================================

This module centralizes all platform knowledge used by the AI chatbot.
Update this file when platform features, policies, or details change.

VERSION HISTORY:
- v1.0 (2026-03-18): Initial centralized knowledge base
- v1.1 (2026-06-06): Accounts/auth alignment (consent, signup, language, 2FA); fix loan status and risk category labels
- v1.2 (2026-06-06): Loan alignment pass (product ranges, blockchain wording, FAQ answers, readiness document labels)
- v1.3 (2026-06-06): Account-help filter alignment; allow password reset/OTP/2FA guidance while blocking credential collection
- v1.4 (2026-06-06): Profile alignment pass (personal completion fields, business months/income range, alternative data readiness)
- v1.5 (2026-06-06): Loan alignment update - penalty fields in repayment tools
- v1.6 (2026-06-06): Analytics alignment - customer dashboard tool, dashboard navigation, AI session awareness
- v1.7 (2026-06-06): Notifications tool - get unread count and recent notifications

USAGE:
- Import KNOWLEDGE_BASE dict for structured access
- Import build_system_prompt() for the full system prompt
- Import PROHIBITED_TOPICS for content filtering
=============================================================================
"""
import re

# Knowledge base version - increment when making significant changes
KNOWLEDGE_VERSION = "1.7"

# =============================================================================
# PLATFORM INFORMATION
# =============================================================================

PLATFORM_INFO = {
    "name": "MSME Pathways",
    "tagline": "Smart Loan Support System for Filipino Microentrepreneurs",
    "type": "Blockchain-backed microfinance mobile app",
    "target_users": "Filipino MSME (Micro, Small, Medium Enterprise) owners",
    "blockchain": "Ethereum",
    "blockchain_purpose": "Transparent, tamper-proof recording of all loan events",
}

# =============================================================================
# ACCOUNTS & ACCESS - Aligned with accounts/ module (/api/auth/)
# =============================================================================

ACCOUNTS_INFO = {
    "base_url": "/api/auth",
    "customer_registration": {
        "flow": [
            "POST /api/auth/signup/ with first_name, last_name, email, password, password_confirm; optional middle_name, phone, language (en|tl)",
            "Verify email via POST /api/auth/verify-email/ with OTP from email",
            "Login via POST /api/auth/login/ with email and password",
        ],
        "note": "Signup does NOT auto-enable AI consent. Consent is recorded separately after login.",
    },
    "consent": {
        "endpoint": "POST /api/auth/consent/",
        "fields": {
            "data_consent": "Required to allow platform data collection/processing",
            "ai_consent": "Required to use AI chat, AI pre-qualification, and document AI analysis",
        },
        "manage": "GET /api/auth/consent/ to check status; PUT /api/auth/consent/ to update preferences",
        "ai_chat_requirement": "Customer must set ai_consent=true before POST /api/ai/chat/",
        "consent_version": "1.0",
        "blockchain": "Consent changes are synced to the on-chain audit trail when blockchain is enabled",
    },
    "language": {
        "signup_field": "language (en|tl, default en) on POST /api/auth/signup/",
        "update_endpoint": "PATCH /api/auth/language/ with {\"language\": \"en\"|\"tl\"}",
        "ai_usage": "AI chat defaults to the customer's saved language preference when language is omitted",
    },
    "password_management": {
        "forgot": "POST /api/auth/forgot-password/ → POST /api/auth/verify-reset-otp/ → POST /api/auth/reset-password/",
        "change": "POST /api/auth/change-password/ (authenticated)",
        "ai_policy": "Never ask users for passwords, OTPs, or reset codes in chat",
    },
    "two_factor_auth": {
        "customer": "Optional — POST /api/auth/2fa/setup/, /api/auth/2fa/confirm/, verify at login via /api/auth/2fa/verify/",
        "admin": "Required for admin login; cannot be disabled",
        "ai_policy": "Direct users to app Settings or login screens for 2FA setup — do not collect TOTP codes in chat",
    },
    "session": {
        "auth": "JWT Bearer token (Authorization header) for API access including AI endpoints",
        "refresh": "POST /api/auth/refresh-token/; POST /api/auth/logout/ blacklists tokens",
        "customer_access_token_ttl": "10 minutes",
    },
}

# =============================================================================
# PROFILES - Aligned with profiles/ module (/api/profile/)
# =============================================================================

PROFILES_INFO = {
    "base_url": "/api/profile",
    "personal_profile": {
        "endpoint": "GET/PUT /api/profile/",
        "completion_fields": [
            "date_of_birth",
            "gender",
            "civil_status",
            "address_line1",
            "barangay",
            "city_municipality",
            "province",
        ],
        "optional_sensitive_fields": [
            "mobile_number",
            "emergency_contact_name",
            "emergency_contact_phone",
            "wallet_address",
        ],
        "note": "Personal profile completion percentage is calculated from the 7 completion fields above. Mobile number, emergency contact, and wallet address are useful but do not determine profile_completed.",
    },
    "business_profile": {
        "endpoint": "GET/PUT /api/profile/business/",
        "completion_rule": "Business profile is complete when business_type and income_range are present.",
        "business_age_unit": "business_age_months is the canonical unit; older years_in_operation data is normalized to months.",
        "optional_fields": [
            "business_name",
            "business_description",
            "business_address",
            "estimated_monthly_income",
            "is_registered",
            "registration_type",
            "number_of_employees",
        ],
    },
    "alternative_data": {
        "endpoint": "GET/PUT /api/profile/alternative-data/",
        "completion_rule": "Alternative data is complete when education_level and housing_status are present.",
        "risk": "risk_score is 0-100 and risk_category is low, medium, or high when calculated.",
    },
    "summary": {
        "endpoint": "GET /api/profile/summary/",
        "sections": "Personal profile, business profile, and alternative data are the 3 required profile sections.",
        "ready_for_loan": "At the profile stage, ready_for_loan means those 3 profile sections are complete. Product-specific document requirements are enforced later during loan application.",
    },
}

# =============================================================================
# ANALYTICS & DASHBOARDS - Aligned with analytics/ module (/api/analytics/)
# =============================================================================

ANALYTICS_INFO = {
    "base_url": "/api/analytics",
    "customer_dashboard": {
        "endpoint": "GET /api/analytics/customer/",
        "description": "Personal dashboard showing application counts, document stats, profile completion, and AI session count",
        "app_location": "Dashboard tab (home screen)",
        "ai_tool": "get_customer_dashboard provides the same data via chat",
    },
    "admin_dashboard": {
        "endpoint": "GET /api/analytics/admin/",
        "description": "System-wide statistics for admins (user counts, loan stats, product performance, recent activity)",
        "access": "Admin role with view_analytics permission",
    },
    "officer_dashboard": {
        "endpoint": "GET /api/analytics/officer/",
        "description": "Loan officer review activity, queue stats, and approval rate",
        "access": "Loan officer or admin role",
    },
    "audit_logs": {
        "description": "All important system actions are recorded in audit logs for transparency and accountability",
        "admin_endpoint": "GET /api/analytics/audit-logs/",
        "officer_endpoint": "GET /api/analytics/officer/audit-logs/",
        "note": "Customers do not have direct access to audit logs; they can track their own activity through the dashboard",
    },
}

# =============================================================================
# LOAN PRODUCTS - Canonical ranges and defaults
# =============================================================================

LOAN_PRODUCTS_INFO = {
    "amount_range": {
        "min": 5000,
        "max": 50000,
        "currency": "PHP",
        "display": "₱5,000 – ₱50,000"
    },
    "term_range": {
        "min_months": 3,
        "max_months": 24,
        "display": "3–24 months"
    },
    "interest": {
        "type": "flat",
        "default_monthly_rate": 1.5,
        "display": "~1.5% per month (flat rate)",
        "explanation": "Flat rate means same interest amount each month, not compounding"
    },
    "note": "Specific amounts, terms, and rates vary by product. Use get_loan_products tool for current offerings."
}

# =============================================================================
# LOAN PROCESS - Step by step
# =============================================================================

LOAN_PROCESS_STEPS = [
    {
        "step": 1,
        "title": "Complete Profile",
        "description": "Fill in your personal details and business information so we can review your application",
        "app_location": "Menu → Profile"
    },
    {
        "step": 2,
        "title": "Upload Documents",
        "description": "Upload your government ID first. Depending on the loan product, you may also need proof of address, a business permit, a business photo, or proof of income",
        "app_location": "Apply → Documents"
    },
    {
        "step": 3,
        "title": "Check Pre-qualification",
        "description": "The app checks how ready you are and gives a simple result like low, medium, or high fit. This is not a guarantee of approval.",
        "app_location": "Apply → select product → Pre-qualify"
    },
    {
        "step": 4,
        "title": "Submit Application",
        "description": "Choose loan product, amount, term (months), purpose, and disbursement method",
        "app_location": "Apply → select product → Apply Now"
    },
    {
        "step": 5,
        "title": "Officer Review",
        "description": "A loan officer reviews your application and may ask for a clearer copy or another document if something is missing.",
        "app_location": "Track → Applications (status: 'under_review')"
    },
    {
        "step": 6,
        "title": "Decision",
        "description": "Application is approved or rejected. If rejected, AI provides feedback on what to improve.",
        "app_location": "Track → Applications"
    },
    {
        "step": 7,
        "title": "Disbursement",
        "description": "Approved loans are disbursed via your chosen method (GCash, bank, cash, check, or ETH wallet)",
        "app_location": "Track → select loan"
    },
    {
        "step": 8,
        "title": "Repayment",
        "description": "Make monthly payments according to your schedule. Track progress in the app.",
        "app_location": "Track → select loan → Schedule/Payments"
    },
]

# =============================================================================
# REPAYMENT
# =============================================================================

REPAYMENT_INFO = {
    "schedule": "Created after disbursement with equal monthly installments",
    "statuses": {
        "pending": "Not yet due or not yet paid",
        "paid": "Fully paid",
        "partial": "Partially paid (some amount remaining)",
        "overdue": "Past due date and not fully paid",
    },
    "penalties": {
        "applied": "Extra amount added for late payment; officer action required",
        "waived": "Penalty removed after review; contact support for hardship",
    },
    "notes": "Partial payments are supported. Penalties and waivers are recorded in the installment details.",
}

PAYMENT_METHODS = {
    "automatic": {
        "description": "Recorded instantly when you pay",
        "methods": [
            {"name": "GCash", "description": "Pay via GCash mobile wallet"},
            {"name": "Bank Transfer", "description": "Pay via electronic bank transfer"},
            {"name": "Wallet (ETH)", "description": "Pay using Ethereum cryptocurrency wallet"},
        ]
    },
    "manual": {
        "description": "Loan officer records the payment for you",
        "methods": [
            {"name": "Cash", "description": "Pay at a partner location"},
            {"name": "Check", "description": "Pay by check; recorded after clearance"},
        ]
    }
}

# =============================================================================
# DOCUMENT TYPES
# =============================================================================

DOCUMENT_TYPES = {
    "always_required": ["Valid Government ID"],
    "commonly_required": [
        "Selfie with ID",
        "Proof of Address (utility bill, barangay certificate)",
    ],
    "sometimes_required": [
        "Business Permit (DTI/SEC/Mayor's permit)",
        "Business Photo",
        "Income Proof (bank statements, sales records)",
    ],
    "note": "Many MSMEs operate informally. Business permit is NOT always required."
}

# =============================================================================
# APPLICATION STATUSES
# =============================================================================

APPLICATION_STATUSES = {
    "draft": "Application started but not submitted",
    "submitted": "Submitted, waiting for review",
    "under_review": "Loan officer is reviewing",
    "approved": "Approved, awaiting disbursement",
    "rejected": "Not approved (feedback provided; can resubmit)",
    "disbursed": "Loan money has been sent to you — repayment schedule active",
    "cancelled": "Cancelled by customer",
}

# =============================================================================
# NOTIFICATIONS INFO
# =============================================================================

NOTIFICATIONS_INFO = {
    "endpoint": "/api/notifications/",
    "features": {
        "unread_badge": "Bell icon shows unread count; refreshes in real-time",
        "notification_types": [
            "loan_submitted", "loan_approved", "loan_rejected", "loan_disbursed",
            "payment_received", "missing_documents_requested", "document_verified",
            "document_flagged", "document_pending_review", "new_application", "welcome"
        ],
        "actions": ["view notifications", "mark as read", "mark all read"],
    },
    "delivery": {
        "email": "Emails are sent when email is configured; status: pending, sent, or failed",
        "in_app": "All notifications appear in the bell icon inbox regardless of email status",
    },
}

# =============================================================================
# INSTALLMENT STATUSES
# =============================================================================

INSTALLMENT_STATUSES = {
    "pending": "Not yet due or not yet paid",
    "paid": "Fully paid",
    "partial": "Partially paid (some amount remaining)",
    "overdue": "Past due date and not fully paid",
}

# =============================================================================
# APP NAVIGATION GUIDE
# =============================================================================

APP_NAVIGATION = {
    "apply_for_loan": "Dashboard → 'Apply' button or Apply tab",
    "track_applications": "Track → Applications",
    "view_loan_details": "Track → select a loan",
    "view_schedule": "Track → select loan → Schedule tab",
    "view_payments": "Track → select loan → Payments tab",
    "make_payment": "Track → select loan → 'Make Payment' button",
    "upload_documents": "Apply → Documents",
    "edit_profile": "Menu → Profile",
    "view_notifications": "Bell icon (top right)",
    "manage_consent": "Settings → Consent (or POST /api/auth/consent/)",
    "change_language": "Settings → Language (or PATCH /api/auth/language/)",
    "enable_ai_chat": "Grant ai_consent via POST /api/auth/consent/ before using AI assistant",
    "view_dashboard": "Dashboard tab (home screen) — shows application counts, document stats, profile completion",
    "view_activity": "Dashboard tab — AI session count and overall account summary",
}

# =============================================================================
# PROHIBITED TOPICS - Things the AI should NOT discuss or do
# =============================================================================

PROHIBITED_TOPICS = [
    "specific_financial_advice",  # "You should definitely take this loan"
    "guarantee_approval",         # "You will be approved"
    "predict_exact_amounts",      # "You'll get exactly ₱50,000"
    "ask_for_credentials",        # Passwords, PINs, private keys, OTPs
    "competitor_comparisons",     # Comparing to other lending apps
    "legal_advice",              # Tax, legal, court matters
    "investment_advice",          # Where to invest money
    "political_topics",           # Politics, elections
    "medical_advice",            # Health recommendations
]

REDIRECT_RESPONSES = {
    "credentials": "I never ask for passwords, PINs, OTPs, or private keys. If someone asks for these, it's a scam. Contact support if concerned.",
    "guarantee": "I can't guarantee loan approval. Decisions depend on your profile, documents, and the loan officer's review.",
    "specific_advice": "I can explain how loans work, but for specific financial decisions, consider consulting a financial advisor.",
    "legal": "For legal questions, please consult a lawyer or the appropriate government agency.",
    "off_topic": "I'm specialized in helping with MSME Pathways loans. For other topics, I may not be the best resource.",
}

# =============================================================================
# RESPONSE GUIDELINES
# =============================================================================

RESPONSE_GUIDELINES = {
    "tone": "Warm, supportive, encouraging",
    "language": "Simple, no jargon. Explain technical terms if used.",
    "languages_supported": ["English", "Tagalog/Filipino"],
    "length": "Concise: 2-3 short paragraphs max",
    "formatting": [
        "Use bullet points for lists",
        "Include specific numbers from tool results",
        "For installments: report as 'X of Y paid'",
        "For balance: include peso amount AND progress percentage",
        "List specific blockers/missing items, not vague summaries",
    ],
    "tool_usage": [
        "Use tools for real-time user data; never guess",
        "Always include specific data from tool results",
        "If tool fails, acknowledge and suggest retry",
    ]
}

# =============================================================================
# BUILD SYSTEM PROMPT - Combines all knowledge into the system prompt
# =============================================================================

def build_system_prompt(include_version=False):
    """
    Build the complete system prompt from the knowledge base.
    
    Args:
        include_version: If True, includes knowledge version in prompt
    
    Returns:
        Complete system prompt string
    """
    version_line = f"\n[Knowledge Base v{KNOWLEDGE_VERSION}]" if include_version else ""
    
    # Build payment methods string
    auto_methods = ", ".join([m["name"] for m in PAYMENT_METHODS["automatic"]["methods"]])
    manual_methods = ", ".join([m["name"] for m in PAYMENT_METHODS["manual"]["methods"]])
    
    prompt = f"""You are a helpful financial assistant for MSME Pathways, a blockchain-backed microfinance app for Filipino small business owners.{version_line}

=== PLATFORM ===
Mobile app for microloans. When blockchain is enabled, loan events (application, approval, disbursement, payments) are recorded on Ethereum blockchain for transparency.

=== ACCOUNTS & ACCESS ===
- Customers register at POST /api/auth/signup/ (first_name, last_name, email, password, password_confirm), verify email OTP, then login at POST /api/auth/login/
- AI chat requires ai_consent=true via POST /api/auth/consent/ (also needed for AI pre-qualification and document AI analysis)
- data_consent and ai_consent are separate; both are managed at /api/auth/consent/
- Language preference: en or tl — set at signup or PATCH /api/auth/language/; default used when chat language is omitted
- Password reset: /api/auth/forgot-password/ flow — never collect passwords or OTPs in chat
- Customer 2FA is optional; admin 2FA is required — direct users to app settings for 2FA, never collect codes in chat
- You only help logged-in customers; account creation and login happen in the app, not through this chat

=== LOAN PROCESS ===
1. Complete profile (personal and business information)
2. Upload documents (government ID required; other documents depend on the loan product)
3. Check pre-qualification (AI scores 0-100; risk category: low/medium/high; requires ai_consent)
4. Submit application (choose product, amount, term, purpose, disbursement method)
5. Officer review (may request a clearer copy or an extra document)
6. Approval/rejection (feedback provided if rejected)
7. Disbursement via your preferred method
8. Monthly repayments per schedule

=== LOAN PRODUCTS ===
- Amounts vary by product; default range: {LOAN_PRODUCTS_INFO["amount_range"]["display"]} | Terms: {LOAN_PRODUCTS_INFO["term_range"]["display"]} | Flat interest: {LOAN_PRODUCTS_INFO["interest"]["display"]}
- Requirements vary by product (min business age, min income)

=== PROFILE COMPLETION ===
- Personal profile completion is based on: date_of_birth, gender, civil_status, address_line1, barangay, city_municipality, province
- Mobile number, emergency contacts, and wallet address are useful optional fields, but they do not determine personal profile completion
- Business profile completion requires business_type and income_range; business_age_months is stored in months
- When answering about business profile, explicitly mention business_type, income_range, and business_age_months as the key fields
- Alternative data completion requires education_level and housing_status; risk_score/risk_category appear after scoring
- Profile summary ready_for_loan means personal, business, and alternative data sections are complete; product-specific documents are checked later
- When asked "what fields do I need" or "requirements", always list the exact required fields for ALL sections (personal: 7 fields; business: business_type + income_range; alternative: education_level + housing_status), even if the user's profile is already complete
- When explaining business_age_months: mention it's the canonical business age unit in months; older years_in_operation data is normalized into this field

=== PAYMENT METHODS ===
AUTOMATIC (recorded instantly): {auto_methods}
MANUAL (officer records): {manual_methods}

=== REPAYMENT ===
 - Equal monthly installments with due dates
 - Statuses: pending, paid, partial, overdue
 - Partial payments supported
 - Penalties may be applied for late payments (status: applied) or waived after review (status: waived)
 - View in app: Track → select loan → Schedule/Payments

=== LOAN PRODUCTS ===
- Amounts vary by product; default range: {LOAN_PRODUCTS_INFO["amount_range"]["display"]}
- Terms: {LOAN_PRODUCTS_INFO["term_range"]["display"]}
- Interest: flat rate ~{LOAN_PRODUCTS_INFO["interest"]["display"]} monthly applied to principal
- When listing loan products: include required_documents alongside amounts, rates, and terms

=== APP NAVIGATION ===
- Apply: Dashboard → "Apply" | Track status: "Track" → "Applications"
- Make payment: Track → Repayment → "Make Payment"
- Documents: Apply → "Documents" | Profile: Menu → "Profile"
- Dashboard: Home screen — shows your application counts, document stats, profile completion, and AI session count

=== ANALYTICS & DASHBOARDS ===
- Customers have a personal dashboard (Dashboard tab) with application counts, document stats, profile completion, and AI chat session count
- Loan officers have their own dashboard showing review stats, pending queue, and approval rate
- Admins see system-wide analytics (user counts, loan stats, product performance, recent activity, audit logs)
- Audit logs record all important actions for transparency; customers see their own activity via the dashboard
- Use get_customer_dashboard tool when the user asks for a summary, overview, stats, or dashboard of their account

=== GUIDELINES ===
- Never give specific financial advice or guarantee approval
- Never ask for passwords, PINs, or private keys
- Be warm and supportive; explain simply without jargon
- Respond in the user's language (English or Tagalog)
- Keep responses concise (2-3 short paragraphs max)
- Use tools for real-time data; don't guess
- Always include specific numbers from tool results
- For installments: report as "X of Y paid"
- For balance: include peso amount AND progress
- List specific blockers/missing items, not vague summaries
- When answering profile questions: list the exact required fields (personal: 7 fields; business: business_type + income_range; alternative: education_level + housing_status)
- When reporting readiness: accurately reflect the `ready_to_apply` boolean; if false, clearly state user is NOT ready and list blockers
- Intent recognition: "What are my X?" queries personal data (use tools); "What X do I need?" or "How does X work?" asks for general info (use knowledge base); "Where is X?" asks for navigation (use app navigation knowledge)
- When asked about documents: list each document by its specific name/type and status; never just give a numerical summary
- When asked document verification status: report verified, pending, and rejected counts with a complete breakdown
- For general document requirement questions (e.g., "What documents do I need?"): list the standard requirements and do NOT check the user's account status
- For file types, formats, or upload limits: do NOT check account status; simply state allowed formats (JPEG, PNG, PDF) and size limit (10 MB)
- When listing loan products: include required_documents alongside amounts, rates, and terms; mention flat rate interest when discussing rates

=== DO NOT ===
- Guarantee loan approval or predict exact amounts
- Compare with other lending apps
- Give legal, tax, or investment advice
- Discuss topics unrelated to MSME Pathways loans
"""
    return prompt.strip()


# =============================================================================
# KNOWLEDGE BASE DICT - For programmatic access
# =============================================================================

KNOWLEDGE_BASE = {
    "version": KNOWLEDGE_VERSION,
    "platform": PLATFORM_INFO,
    "accounts": ACCOUNTS_INFO,
    "profiles": PROFILES_INFO,
    "loan_products": LOAN_PRODUCTS_INFO,
    "loan_process": LOAN_PROCESS_STEPS,
    "payment_methods": PAYMENT_METHODS,
    "document_types": DOCUMENT_TYPES,
    "application_statuses": APPLICATION_STATUSES,
    "installment_statuses": INSTALLMENT_STATUSES,
    "repayment": REPAYMENT_INFO,
    "notifications": NOTIFICATIONS_INFO,
    "app_navigation": APP_NAVIGATION,
    "prohibited_topics": PROHIBITED_TOPICS,
    "redirect_responses": REDIRECT_RESPONSES,
    "response_guidelines": RESPONSE_GUIDELINES,
    "analytics": ANALYTICS_INFO,
}


# =============================================================================
# CONTENT FILTER - Check if message contains prohibited request
# =============================================================================

def _is_credential_collection_request(message_lower: str) -> bool:
    """Return True only when the user is asking to reveal, share, or collect credentials."""
    always_sensitive_terms = [
        "private key",
        "seed phrase",
        "secret key",
        "backup code",
        "backup codes",
    ]
    if any(term in message_lower for term in always_sensitive_terms):
        return True

    credential_terms = [
        r"\bpassword\b",
        r"\bpin\b",
        r"\botp\b",
        r"\btotp\b",
        r"\b2fa code\b",
        r"\bverification code\b",
        r"\breset code\b",
    ]
    if not any(re.search(term, message_lower) for term in credential_terms):
        return False

    collection_phrases = [
        "what is my",
        "what's my",
        "what is your",
        "what's your",
        "tell me",
        "give me",
        "show me",
        "send me",
        "share",
        "reveal",
        "provide my",
        "provide your",
        "enter my",
        "submit my",
        "collect my",
        "ask for my",
    ]
    if any(phrase in message_lower for phrase in collection_phrases):
        return True

    disclosure_patterns = [
        r"\b(my|the)\s+(password|pin|otp|totp|2fa code|verification code|reset code)\s+(is|=|:)",
        r"\b(here is|this is)\s+(my|the)\s+(password|pin|otp|totp|2fa code|verification code|reset code)\b",
    ]
    return any(re.search(pattern, message_lower) for pattern in disclosure_patterns)


def check_prohibited_content(message: str) -> tuple[bool, str | None]:
    """
    Check if the user's message is asking about a prohibited topic.
    
    Args:
        message: User's message
    
    Returns:
        (is_prohibited, redirect_response) - If prohibited, returns the redirect message
    """
    message_lower = message.lower()
    
    # Check for credential collection/reveal requests while allowing account-help questions
    if _is_credential_collection_request(message_lower):
        return True, REDIRECT_RESPONSES["credentials"]
    
    # Check for guarantee requests
    guarantee_phrases = ['will i be approved', 'guarantee approval', 'sure to get', 'definitely get']
    if any(phrase in message_lower for phrase in guarantee_phrases):
        return True, REDIRECT_RESPONSES["guarantee"]
    
    # Check for legal advice
    legal_words = ['lawyer', 'sue', 'court', 'legal action', 'attorney']
    if any(word in message_lower for word in legal_words):
        return True, REDIRECT_RESPONSES["legal"]
    
    return False, None
