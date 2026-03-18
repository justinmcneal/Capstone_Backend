"""
=============================================================================
AI KNOWLEDGE BASE - Single Source of Truth for MSME Pathways AI Assistant
=============================================================================

This module centralizes all platform knowledge used by the AI chatbot.
Update this file when platform features, policies, or details change.

VERSION HISTORY:
- v1.0 (2026-03-18): Initial centralized knowledge base

USAGE:
- Import KNOWLEDGE_BASE dict for structured access
- Import build_system_prompt() for the full system prompt
- Import PROHIBITED_TOPICS for content filtering
=============================================================================
"""

# Knowledge base version - increment when making significant changes
KNOWLEDGE_VERSION = "1.0"

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
# LOAN PRODUCTS - Canonical ranges and defaults
# =============================================================================

LOAN_PRODUCTS_INFO = {
    "amount_range": {
        "min": 5000,
        "max": 500000,
        "currency": "PHP",
        "display": "₱5,000 – ₱500,000"
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
        "description": "Fill in personal info (name, contact, address) and business info (type, income, years operating)",
        "app_location": "Menu → Profile"
    },
    {
        "step": 2,
        "title": "Upload Documents",
        "description": "Government ID is always required. Some products need: proof of address, business permit, business photo, income proof",
        "app_location": "Apply → Documents"
    },
    {
        "step": 3,
        "title": "Check Pre-qualification",
        "description": "AI scores your profile 0-100 with risk category (Excellent/Good/Fair/Poor). This is NOT a guarantee of approval.",
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
        "description": "A loan officer reviews your application. They may request additional documents.",
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
# PAYMENT METHODS
# =============================================================================

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
    "rejected": "Not approved (feedback provided)",
    "disbursed": "Loan money has been sent to you",
    "completed": "Fully repaid",
    "defaulted": "Significantly overdue (contact support)",
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
Mobile app for microloans. All loan events (application, approval, disbursement, payments) are recorded on Ethereum blockchain for transparency.

=== LOAN PROCESS ===
1. Complete profile (personal + business info)
2. Upload documents (government ID required; some products need proof of address, business permit, or photo)
3. Check pre-qualification (AI scores 0-100 with risk category)
4. Submit application (choose product, amount, term, purpose, disbursement method)
5. Officer review (may request additional documents)
6. Approval/rejection (feedback provided if rejected)
7. Disbursement via your preferred method
8. Monthly repayments per schedule

=== LOAN PRODUCTS ===
- Amounts: {LOAN_PRODUCTS_INFO["amount_range"]["display"]} | Terms: {LOAN_PRODUCTS_INFO["term_range"]["display"]} | Flat interest: {LOAN_PRODUCTS_INFO["interest"]["display"]}
- Requirements vary by product (min business age, min income)

=== PAYMENT METHODS ===
AUTOMATIC (recorded instantly): {auto_methods}
MANUAL (officer records): {manual_methods}

=== REPAYMENT ===
- Equal monthly installments with due dates
- Statuses: pending, paid, partial, overdue
- Partial payments supported
- View in app: Track → select loan → Schedule/Payments

=== APP NAVIGATION ===
- Apply: Dashboard → "Apply" | Track status: "Track" → "Applications"
- Make payment: Track → Repayment → "Make Payment"
- Documents: Apply → "Documents" | Profile: Menu → "Profile"

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
    "loan_products": LOAN_PRODUCTS_INFO,
    "loan_process": LOAN_PROCESS_STEPS,
    "payment_methods": PAYMENT_METHODS,
    "document_types": DOCUMENT_TYPES,
    "application_statuses": APPLICATION_STATUSES,
    "installment_statuses": INSTALLMENT_STATUSES,
    "app_navigation": APP_NAVIGATION,
    "prohibited_topics": PROHIBITED_TOPICS,
    "redirect_responses": REDIRECT_RESPONSES,
    "response_guidelines": RESPONSE_GUIDELINES,
}


# =============================================================================
# CONTENT FILTER - Check if message contains prohibited request
# =============================================================================

def check_prohibited_content(message: str) -> tuple[bool, str | None]:
    """
    Check if the user's message is asking about a prohibited topic.
    
    Args:
        message: User's message
    
    Returns:
        (is_prohibited, redirect_response) - If prohibited, returns the redirect message
    """
    message_lower = message.lower()
    
    # Check for credential requests (scam detection)
    credential_words = ['password', 'pin', 'otp', 'private key', 'seed phrase', 'secret key']
    if any(word in message_lower for word in credential_words):
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
