"""
AI Qualification Service - Uses Groq LLM to analyze customer eligibility.
"""
import json
import logging
import re
from ai_assistant.services import get_llm_service
from accounts.models import Consent
from profiles.models import CustomerProfile, BusinessProfile, AlternativeData
from documents.models import Document, DOCUMENT_TYPES

logger = logging.getLogger('loans')

BASELINE_REQUIRED_DOCUMENTS = ['valid_id']
DOCUMENT_TYPE_ALIASES = {
    'proof_of_income': 'income_proof',
    'business_registration': 'business_permit',
}
DOCUMENT_TYPE_LABELS = {
    'valid_id': 'valid_id',
    'selfie_with_id': 'selfie_with_id',
    'proof_of_address': 'proof_of_address',
    'business_permit': 'business_permit',
    'business_photo': 'business_photo',
    'income_proof': 'proof_of_income',
    'other': 'other',
}


def _normalize_scope(requirements_scope):
    """Normalize scope to supported values."""
    normalized = str(requirements_scope or 'product').strip().lower()
    if normalized not in {'baseline', 'product'}:
        return 'product'
    return normalized


def canonicalize_document_type(document_type):
    """Return canonical document type key or None if unknown."""
    if not document_type:
        return None

    normalized = str(document_type).strip().lower()
    normalized = DOCUMENT_TYPE_ALIASES.get(normalized, normalized)
    if normalized in DOCUMENT_TYPES:
        return normalized
    return None


def document_type_label(document_type):
    """Return display label used by requirements messages."""
    canonical = canonicalize_document_type(document_type) or str(document_type)
    return DOCUMENT_TYPE_LABELS.get(canonical, canonical.replace('_', ' '))


def resolve_required_document_types(product=None, requirements_scope='product'):
    """
    Resolve required documents with normalization and sane fallback.
    - baseline scope: always baseline required docs
    - product scope: product.required_documents when available; falls back to baseline
    """
    scope = _normalize_scope(requirements_scope)
    if scope == 'baseline':
        source = BASELINE_REQUIRED_DOCUMENTS
    else:
        source = getattr(product, 'required_documents', None) or BASELINE_REQUIRED_DOCUMENTS

    resolved = []
    for raw_type in source:
        canonical = canonicalize_document_type(raw_type)
        if canonical and canonical not in resolved:
            resolved.append(canonical)

    if not resolved:
        resolved = list(BASELINE_REQUIRED_DOCUMENTS)

    return resolved


QUALIFICATION_SYSTEM_PROMPT = """You are a strict loan pre-qualification engine.

Return ONLY a valid JSON object, with no markdown, no code fences, and no extra text.
Use exactly this schema:
{
  "eligible": boolean,
  "eligibility_score": number,      // 0-100
  "risk_category": "low|medium|high",
  "recommended_amount": number,     // PHP
  "reasoning": string,
  "strengths": [string],
  "concerns": [string],
  "missing_requirements": [string]
}
"""

QUALIFICATION_USER_PROMPT = """Analyze this MSME loan request and return your result in the required JSON schema.

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
"""

QUALIFICATION_REQUIRED_FIELDS = {
    'eligible',
    'eligibility_score',
    'risk_category',
    'recommended_amount',
    'reasoning',
    'strengths',
    'concerns',
    'missing_requirements',
}
QUALIFICATION_RISK_LEVELS = {'low', 'medium', 'high'}


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


def has_ai_consent(customer_id):
    """Check if customer granted AI consent."""
    consent = Consent.find_by_user(customer_id, 'customer')
    return bool(consent and consent.ai_consent)


def _extract_first_json_object(text):
    """Extract the first JSON object from model output."""
    raw = str(text or '').strip()
    if not raw:
        return None

    # Fast path: response is already raw JSON.
    try:
        candidate = json.loads(raw)
        if isinstance(candidate, dict):
            return candidate
    except json.JSONDecodeError:
        pass

    # Common path: response wrapped in a markdown json code fence.
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    if fenced_match:
        try:
            candidate = json.loads(fenced_match.group(1))
            if isinstance(candidate, dict):
                return candidate
        except json.JSONDecodeError:
            pass

    # Fallback: scan for first decodable JSON object.
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != '{':
            continue
        try:
            candidate, _ = decoder.raw_decode(raw[index:])
            if isinstance(candidate, dict):
                return candidate
        except json.JSONDecodeError:
            continue

    return None


def _coerce_bool(value, field_name):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes'}:
            return True
        if normalized in {'false', '0', 'no'}:
            return False
    raise ValueError(f"{field_name} must be boolean")


def _coerce_number(value, field_name):
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be numeric")


def _normalize_string_list(value, field_name):
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")

    normalized = []
    for item in value:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def _derive_risk_category(score):
    if score >= 75:
        return 'low'
    if score >= 50:
        return 'medium'
    return 'high'


def _normalize_recommended_amount(raw_amount, eligible, product, requested_amount):
    if not eligible:
        return 0.0

    requested = max(0.0, _coerce_number(requested_amount, 'requested_amount'))
    model_amount = max(0.0, _coerce_number(raw_amount, 'recommended_amount'))

    lower_bound = float(product.min_amount or 0.0)
    upper_bound = min(float(product.max_amount or 0.0), requested)
    if upper_bound < lower_bound:
        upper_bound = lower_bound

    bounded = max(lower_bound, min(model_amount, upper_bound))
    return round(bounded, 2)


def _validate_and_normalize_ai_qualification(payload, product, requested_amount, required_doc_types, scope):
    """Strict schema validation + deterministic normalization for AI output."""
    if not isinstance(payload, dict):
        raise ValueError("Qualification response must be a JSON object")

    missing_fields = [field for field in QUALIFICATION_REQUIRED_FIELDS if field not in payload]
    if missing_fields:
        raise ValueError(f"Missing required fields: {', '.join(sorted(missing_fields))}")

    eligible = _coerce_bool(payload.get('eligible'), 'eligible')
    score = _coerce_number(payload.get('eligibility_score'), 'eligibility_score')
    score = round(max(0.0, min(100.0, score)), 2)

    risk_category = str(payload.get('risk_category', '')).strip().lower()
    if risk_category not in QUALIFICATION_RISK_LEVELS:
        risk_category = _derive_risk_category(score)

    recommended_amount = _normalize_recommended_amount(
        payload.get('recommended_amount'),
        eligible,
        product,
        requested_amount,
    )

    reasoning = str(payload.get('reasoning', '')).strip()
    if not reasoning:
        raise ValueError("reasoning must be a non-empty string")

    strengths = _normalize_string_list(payload.get('strengths'), 'strengths')
    concerns = _normalize_string_list(payload.get('concerns'), 'concerns')
    missing_requirements = _normalize_string_list(
        payload.get('missing_requirements'),
        'missing_requirements',
    )

    can_apply = eligible and len(missing_requirements) == 0
    if not can_apply:
        recommended_amount = 0.0

    return {
        'eligible': eligible,
        'eligibility_score': score,
        'risk_category': risk_category,
        'recommended_amount': recommended_amount,
        'reasoning': reasoning,
        'strengths': strengths,
        'concerns': concerns,
        'missing_requirements': missing_requirements,
        'can_apply': can_apply,
        'ai_used': True,
        'required_documents_resolved': required_doc_types,
        'requirements_scope': scope,
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


def qualify_customer(
    customer_id,
    product,
    requested_amount,
    term_months,
    purpose,
    requirements_scope='product',
):
    """
    Use AI to assess customer loan eligibility.
    
    Returns dict with eligibility info.
    """
    scope = _normalize_scope(requirements_scope)
    required_doc_types = resolve_required_document_types(product, scope)

    # Get customer data
    data = get_customer_data(customer_id)
    
    # Format for AI
    profile_str, business_str, alt_str, docs_str = format_profile_for_ai(data)

    # Never send profile data to external AI if consent is not granted.
    if not has_ai_consent(customer_id):
        logger.info(f"AI consent not granted for customer {customer_id}; using rule-based qualification")
        return rule_based_qualification(
            data,
            product,
            requested_amount,
            requirements_scope=scope,
            reason='Rule-based assessment (AI consent not granted)',
        )
    
    # Build prompt
    prompt = QUALIFICATION_USER_PROMPT.format(
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
        required_docs=', '.join(document_type_label(doc) for doc in required_doc_types)
    )
    
    # Get AI response
    llm = get_llm_service(use_case='qualification')
    
    if not llm.is_available():
        # Fallback to rule-based if AI unavailable
        return rule_based_qualification(
            data,
            product,
            requested_amount,
            requirements_scope=scope,
            reason='Rule-based assessment (AI unavailable)',
        )
        
    result = llm.chat(
        message=prompt,
        language='en',
        system_prompt=QUALIFICATION_SYSTEM_PROMPT,
        temperature=0.1,
        max_tokens=600,
        top_p=0.9,
    )
    
    if not result['success']:
        logger.error(f"AI qualification failed: {result.get('error')}")
        return rule_based_qualification(
            data,
            product,
            requested_amount,
            requirements_scope=scope,
            reason='Rule-based assessment (AI request failed)',
        )
    
    payload = _extract_first_json_object(result.get('response'))
    if payload is None:
        logger.error("AI qualification response did not contain a valid JSON object")
        return rule_based_qualification(
            data,
            product,
            requested_amount,
            requirements_scope=scope,
            reason='Rule-based assessment (AI response parsing failed)',
        )

    try:
        return _validate_and_normalize_ai_qualification(
            payload=payload,
            product=product,
            requested_amount=requested_amount,
            required_doc_types=required_doc_types,
            scope=scope,
        )
    except ValueError as e:
        logger.error(f"AI qualification schema validation failed: {e}")

    return rule_based_qualification(
        data,
        product,
        requested_amount,
        requirements_scope=scope,
        reason='Rule-based assessment (AI response parsing failed)',
    )


def rule_based_qualification(
    data,
    product,
    requested_amount,
    requirements_scope='product',
    reason='Rule-based assessment (AI unavailable)',
):
    """
    Fallback rule-based qualification when AI is unavailable.
    """
    scope = _normalize_scope(requirements_scope)
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
    doc_types = set()
    for doc in docs:
        canonical_type = canonicalize_document_type(doc.document_type)
        if canonical_type:
            doc_types.add(canonical_type)
    required_doc_types = resolve_required_document_types(product, scope)
    for req_doc in required_doc_types:
        label = document_type_label(req_doc)
        if req_doc not in doc_types:
            score -= 5
            missing.append(f"Missing: {label}")
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
        'reasoning': reason,
        'strengths': strengths,
        'concerns': concerns,
        'missing_requirements': missing,
        'can_apply': eligible,
        'ai_used': False,
        'required_documents_resolved': required_doc_types,
        'requirements_scope': scope,
    }


def check_basic_eligibility(customer_id, product, requirements_scope='product'):
    """
    Quick check for basic eligibility before full qualification.
    
    Requirements:
    1. Personal profile must exist
    2. Business profile must exist  
    3. Alternative data must exist
    4. All required documents must be uploaded AND APPROVED
    """
    scope = _normalize_scope(requirements_scope)
    data = get_customer_data(customer_id)
    missing = []
    
    # Check all 3 profiles exist
    personal = data.get('personal')
    business = data.get('business')
    alternative = data.get('alternative')
    
    if not personal:
        missing.append('Personal profile required')
    elif not personal.profile_completed:
        missing.append('Personal profile incomplete')
        
    if not business:
        missing.append('Business profile required')
    elif not (business.business_type and business.income_range):
        missing.append('Business profile incomplete (type and income required)')
    
    # Alternative data is required
    if not alternative:
        missing.append('Alternative data required')
    elif not (alternative.education_level and alternative.housing_status):
        missing.append('Alternative data incomplete (education and housing required)')
    
    # Check required documents - must be APPROVED, not just uploaded
    documents = data.get('documents', [])
    
    required_doc_types = resolve_required_document_types(product, scope)

    latest_documents_by_type = {}
    for doc in documents:
        canonical_type = canonicalize_document_type(doc.document_type)
        if not canonical_type:
            continue
        if canonical_type not in latest_documents_by_type:
            latest_documents_by_type[canonical_type] = doc
    
    for req_doc in required_doc_types:
        label = document_type_label(req_doc)
        # Find document of this type
        doc_found = latest_documents_by_type.get(req_doc)
        
        if not doc_found:
            missing.append(f'Document required: {label}')
        elif doc_found.status != 'approved':
            # Document exists but not approved
            if doc_found.reupload_requested:
                missing.append(f'Document re-upload requested: {label}')
            elif doc_found.status in ['pending', 'needs_review']:
                missing.append(f'Document pending verification: {label}')
            elif doc_found.status == 'rejected':
                missing.append(f'Document rejected, please re-upload: {label}')
            else:
                missing.append(f'Document not yet approved: {label}')
    
    return {
        'can_apply': len(missing) == 0,
        'missing_requirements': missing,
        'required_documents_resolved': required_doc_types,
        'requirements_scope': scope,
        'required_documents_labels': {
            doc: document_type_label(doc) for doc in required_doc_types
        },
    }
