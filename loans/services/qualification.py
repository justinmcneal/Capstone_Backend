"""
AI Qualification Service - Uses Ollama to analyze customer eligibility.
"""
import logging
from ai_assistant.services import get_llm_service
from profiles.models import CustomerProfile, BusinessProfile, AlternativeData
from documents.models import Document

logger = logging.getLogger('loans')


QUALIFICATION_PROMPT = """You are a loan qualification assistant for MSME (Micro, Small, Medium Enterprise) customers.

Analyze the following customer profile and provide a loan qualification assessment.

CUSTOMER PROFILE:
{profile_data}

BUSINESS PROFILE:
{business_data}

ALTERNATIVE DATA:
{alternative_data}

UPLOADED DOCUMENTS:
{documents}

REQUESTED LOAN:
- Product: {product_name}
- Amount: ₱{requested_amount:,.2f}
- Term: {term_months} months
- Purpose: {purpose}

PRODUCT REQUIREMENTS:
- Minimum monthly income: ₱{min_income:,.2f}
- Minimum business operation: {min_months} months
- Required documents: {required_docs}

Provide your assessment in the following JSON format:
{{
    "eligible": true/false,
    "eligibility_score": 0-100,
    "risk_category": "low/medium/high",
    "recommended_amount": <amount in PHP>,
    "reasoning": "<brief explanation>",
    "strengths": ["<strength1>", "<strength2>"],
    "concerns": ["<concern1>", "<concern2>"],
    "missing_requirements": ["<missing1>", "<missing2>"]
}}

Be realistic but supportive. Consider the informal nature of MSME businesses.
"""


def get_customer_data(customer_id):
    """Gather all customer data for qualification"""
    # Get profiles
    personal = CustomerProfile.find_by_customer(customer_id)
    business = BusinessProfile.find_by_customer(customer_id)
    alternative = AlternativeData.find_by_customer(customer_id)
    
    # Get documents
    documents = Document.find_by_customer(customer_id)
    
    return {
        'personal': personal,
        'business': business,
        'alternative': alternative,
        'documents': documents
    }


def format_profile_for_ai(data):
    """Format customer data for AI prompt"""
    personal = data.get('personal')
    business = data.get('business')
    alternative = data.get('alternative')
    docs = data.get('documents', [])
    
    profile_str = "None provided"
    if personal:
        profile_str = f"""
- Civil Status: {personal.civil_status or 'Not provided'}
- Address: {personal.city_municipality or 'Not provided'}, {personal.province or ''}
- Emergency Contact: {'Provided' if personal.emergency_contact_name else 'Not provided'}
"""
    
    business_str = "None provided"
    if business:
        business_str = f"""
- Business Name: {business.business_name or 'Not provided'}
- Business Type: {business.business_type or 'Not provided'}
- Years in Operation: {business.years_in_operation or 0}
- Registered: {'Yes' if business.is_registered else 'No'}
- Monthly Income Range: {business.income_range or 'Not provided'}
- Estimated Monthly Income: ₱{business.estimated_monthly_income or 0:,.2f}
"""
    
    alt_str = "None provided"
    if alternative:
        alt_str = f"""
- Education: {alternative.education_level or 'Not provided'}
- Employment: {alternative.employment_status or 'Not provided'}
- Housing: {alternative.housing_status or 'Not provided'}
- Bank Account: {'Yes' if alternative.has_bank_account else 'No'}
- E-wallet: {'Yes' if alternative.has_ewallet else 'No'} ({alternative.ewallet_usage or ''})
- Existing Loans: {'Yes' if alternative.has_existing_loans else 'No'}
- Utility Payment: {alternative.utility_payment_history or 'Not tracked'}
"""
    
    docs_str = "None uploaded"
    if docs:
        doc_list = [f"- {d.document_type}: {d.status}" for d in docs]
        docs_str = "\n".join(doc_list)
    
    return profile_str, business_str, alt_str, docs_str


def qualify_customer(customer_id, product, requested_amount, term_months, purpose):
    """
    Use AI to assess customer loan eligibility.
    
    Returns dict with eligibility info.
    """
    # Get customer data
    data = get_customer_data(customer_id)
    
    # Format for AI
    profile_str, business_str, alt_str, docs_str = format_profile_for_ai(data)
    
    # Build prompt
    prompt = QUALIFICATION_PROMPT.format(
        profile_data=profile_str,
        business_data=business_str,
        alternative_data=alt_str,
        documents=docs_str,
        product_name=product.name,
        requested_amount=requested_amount,
        term_months=term_months,
        purpose=purpose or 'Not specified',
        min_income=product.min_monthly_income,
        min_months=product.min_business_months,
        required_docs=', '.join(product.required_documents)
    )
    
    # Get AI response
    llm = get_llm_service()
    
    if not llm.is_available():
        # Fallback to rule-based if AI unavailable
        return rule_based_qualification(data, product, requested_amount)
    
    result = llm.chat(message=prompt, language='en')
    
    if not result['success']:
        logger.error(f"AI qualification failed: {result.get('error')}")
        return rule_based_qualification(data, product, requested_amount)
    
    # Parse AI response (extract JSON)
    try:
        import json
        response_text = result['response']
        # Find JSON in response
        start = response_text.find('{')
        end = response_text.rfind('}') + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            return json.loads(json_str)
    except Exception as e:
        logger.error(f"Failed to parse AI response: {e}")
    
    return rule_based_qualification(data, product, requested_amount)


def rule_based_qualification(data, product, requested_amount):
    """
    Fallback rule-based qualification when AI is unavailable.
    """
    score = 50  # Base score
    concerns = []
    strengths = []
    missing = []
    
    business = data.get('business')
    alternative = data.get('alternative')
    docs = data.get('documents', [])
    
    # Check business profile
    if business:
        if business.years_in_operation and business.years_in_operation >= product.min_business_months / 12:
            score += 15
            strengths.append("Sufficient business experience")
        else:
            score -= 10
            concerns.append("Limited business history")
        
        if business.estimated_monthly_income and business.estimated_monthly_income >= product.min_monthly_income:
            score += 15
            strengths.append("Meets income requirement")
        else:
            score -= 10
            concerns.append("Income below requirement")
        
        if business.is_registered:
            score += 10
            strengths.append("Business is registered")
    else:
        score -= 20
        missing.append("Business profile not complete")
    
    # Check documents
    doc_types = [d.document_type for d in docs]
    for req_doc in product.required_documents:
        if req_doc not in doc_types:
            score -= 5
            missing.append(f"Missing: {req_doc}")
        else:
            score += 5
    
    # Check alternative data
    if alternative:
        if alternative.has_bank_account:
            score += 5
            strengths.append("Has bank account")
        if alternative.has_ewallet:
            score += 3
            strengths.append("Uses digital payments")
        if alternative.utility_payment_history == 'on_time':
            score += 5
            strengths.append("Good payment history")
    
    # Determine eligibility
    score = max(0, min(100, score))
    eligible = score >= 50 and len(missing) == 0
    
    # Risk category
    if score >= 75:
        risk = 'low'
    elif score >= 50:
        risk = 'medium'
    else:
        risk = 'high'
    
    # Recommended amount
    if eligible:
        # Recommend based on income (3x monthly income or requested, whichever is lower)
        income = business.estimated_monthly_income if business else 0
        max_recommend = min(income * 3, product.max_amount, requested_amount)
        recommended = max(product.min_amount, max_recommend)
    else:
        recommended = 0
    
    return {
        'eligible': eligible,
        'eligibility_score': score,
        'risk_category': risk,
        'recommended_amount': recommended,
        'reasoning': 'Rule-based assessment (AI unavailable)',
        'strengths': strengths,
        'concerns': concerns,
        'missing_requirements': missing
    }


def check_basic_eligibility(customer_id, product):
    """
    Quick check for basic eligibility before full qualification.
    """
    data = get_customer_data(customer_id)
    missing = []
    
    # Check profile exists
    if not data.get('personal'):
        missing.append('Personal profile required')
    if not data.get('business'):
        missing.append('Business profile required')
    
    # Check required documents
    doc_types = [d.document_type for d in data.get('documents', [])]
    for req_doc in product.required_documents:
        if req_doc not in doc_types:
            missing.append(f'Document required: {req_doc}')
    
    return {
        'can_apply': len(missing) == 0,
        'missing_requirements': missing
    }
