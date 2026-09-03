"""
AI Qualification Service - Uses Groq LLM to analyze customer eligibility.
"""

import json
import logging
import re
from django.conf import settings
from ai_assistant.services import get_llm_service
from accounts.models import Consent
from accounts.utils.validation_utils import sanitize_multiline_text, sanitize_text
from profiles.models import CustomerProfile, BusinessProfile, AlternativeData
from documents.models import Document, DOCUMENT_TYPES

logger = logging.getLogger("loans")


def _ai_qualification_enabled():
    return getattr(settings, "LOANS_AI_QUALIFICATION_ENABLED", True)

BASELINE_REQUIRED_DOCUMENTS = ["valid_id"]
DOCUMENT_TYPE_ALIASES = {
    "proof_of_income": "income_proof",
    "business_registration": "business_permit",
}
DOCUMENT_TYPE_LABELS = {
    "valid_id": "Valid Government ID",
    "selfie_with_id": "Selfie with ID",
    "proof_of_address": "Proof of Address",
    "business_permit": "Business Permit",
    "business_photo": "Business Photo",
    "income_proof": "Proof of Income",
    "other": "Other",
}


def _normalize_scope(requirements_scope):
    """Normalize scope to supported values."""
    normalized = str(requirements_scope or "product").strip().lower()
    if normalized not in {"baseline", "product"}:
        return "product"
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
    return DOCUMENT_TYPE_LABELS.get(canonical, canonical.replace("_", " "))


def resolve_required_document_types(product=None, requirements_scope="product"):
    """
    Resolve required documents with normalization and sane fallback.
    - baseline scope: always baseline required docs
    - product scope:
        * explicit [] means no product documents required
        * missing/None falls back to baseline defaults
    """
    scope = _normalize_scope(requirements_scope)
    explicit_product_docs = False
    if scope == "baseline":
        source = BASELINE_REQUIRED_DOCUMENTS
    else:
        product_required_documents = getattr(product, "required_documents", None)
        explicit_product_docs = product_required_documents is not None
        source = (
            product_required_documents
            if explicit_product_docs
            else BASELINE_REQUIRED_DOCUMENTS
        )

    resolved = []
    for raw_type in source:
        canonical = canonicalize_document_type(raw_type)
        if canonical and canonical not in resolved:
            resolved.append(canonical)

    if not resolved:
        if scope == "baseline" or not explicit_product_docs:
            resolved = list(BASELINE_REQUIRED_DOCUMENTS)
        else:
            # Explicit empty product config means no required documents.
            resolved = []

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

REQUIREMENT STATUS (pre-computed, authoritative — do NOT override):
{requirement_status}

IMPORTANT RULES:
- Use the REQUIREMENT STATUS above as the ground truth for whether each requirement is met.
- If a requirement is marked as MEETS, do NOT list it as a concern or missing requirement.
- Only list a requirement as missing/concern if the status says DOES NOT MEET.
- The "missing_requirements" array must ONLY contain items the customer genuinely fails.
- Always quote the exact product threshold (e.g. "{min_months} months") — never invent different numbers.
"""

QUALIFICATION_REQUIRED_FIELDS = {
    "eligible",
    "eligibility_score",
    "risk_category",
    "recommended_amount",
    "reasoning",
    "strengths",
    "concerns",
    "missing_requirements",
}
QUALIFICATION_RISK_LEVELS = {"low", "medium", "high"}


def get_customer_data(customer_id):
    """Gather all customer data for qualification"""
    # Get profiles
    personal = CustomerProfile.find_by_customer(customer_id)
    business = BusinessProfile.find_by_customer(customer_id)
    alternative = AlternativeData.find_by_customer(customer_id)

    # Get documents
    documents = Document.find_by_customer(customer_id)

    # Debug logging
    if business:
        logger.info(
            f"[QUALIFICATION DATA] Customer {customer_id} - business_age_months: {business.business_age_months}, is_registered: {business.is_registered}, income: {business.estimated_monthly_income}"
        )
    else:
        logger.warning(
            f"[QUALIFICATION DATA] Customer {customer_id} - no business profile found"
        )

    return {
        "personal": personal,
        "business": business,
        "alternative": alternative,
        "documents": documents,
    }


def has_ai_consent(customer_id):
    """Check if customer granted AI consent."""
    consent = Consent.find_by_user(customer_id, "customer")
    return bool(consent and consent.ai_consent)


def _extract_first_json_object(text):
    """Extract the first JSON object from model output."""
    raw = str(text or "").strip()
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
    fenced_match = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.IGNORECASE | re.DOTALL
    )
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
        if char != "{":
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
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
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
        text = sanitize_text(item)
        if text:
            normalized.append(text)
    return normalized


def _derive_risk_category(score):
    if score >= 75:
        return "low"
    if score >= 50:
        return "medium"
    return "high"


def _normalize_recommended_amount(raw_amount, eligible, product, requested_amount):
    if not eligible:
        return 0.0

    requested = max(0.0, _coerce_number(requested_amount, "requested_amount"))
    model_amount = max(0.0, _coerce_number(raw_amount, "recommended_amount"))

    lower_bound = float(product.min_amount or 0.0)
    upper_bound = min(float(product.max_amount or 0.0), requested)
    if upper_bound < lower_bound:
        upper_bound = lower_bound

    bounded = max(lower_bound, min(model_amount, upper_bound))
    return round(bounded, 2)


def _check_hard_product_requirements(data, product):
    """
    Deterministic hard-fail checks for product minimums.

    These requirements cannot be overridden by AI output,
    score bonuses, or alternative data.  A non-empty return
    list means the customer is unconditionally ineligible.

    A zero-valued minimum is treated as "no minimum required"
    and skips the check.
    """
    hard_failures = []
    business = data.get("business")

    # Business age minimum
    biz_months = (business.business_age_months or 0) if business else 0
    min_months = product.min_business_months or 0
    if min_months > 0 and biz_months < min_months:
        hard_failures.append(
            f"Insufficient business operation: {biz_months} months "
            f"(minimum {min_months} months required)"
        )

    # Monthly income minimum
    income = (business.estimated_monthly_income or 0) if business else 0
    min_income = product.min_monthly_income or 0
    if min_income > 0 and income < min_income:
        hard_failures.append(
            f"Insufficient monthly income: \u20b1{income:,.2f} "
            f"(minimum \u20b1{min_income:,.2f} required)"
        )

    return hard_failures


def _make_hard_fail_result(
    hard_failures, required_doc_types, scope, ai_used=False
):
    """Build a deterministic ineligible result from hard-fail entries."""
    return {
        "eligible": False,
        "eligibility_score": 0,
        "risk_category": "high",
        "recommended_amount": 0.0,
        "reasoning": "Does not meet mandatory product requirements",
        "strengths": [],
        "concerns": [],
        "missing_requirements": list(hard_failures),
        "can_apply": False,
        "ai_used": ai_used,
        "required_documents_resolved": required_doc_types,
        "requirements_scope": scope,
    }


def _validate_and_normalize_ai_qualification(
    payload, product, requested_amount, required_doc_types, scope, data=None
):
    """Strict schema validation + deterministic normalization for AI output."""
    if not isinstance(payload, dict):
        raise ValueError("Qualification response must be a JSON object")

    missing_fields = [
        field for field in QUALIFICATION_REQUIRED_FIELDS if field not in payload
    ]
    if missing_fields:
        raise ValueError(
            f"Missing required fields: {', '.join(sorted(missing_fields))}"
        )

    eligible = _coerce_bool(payload.get("eligible"), "eligible")
    score = _coerce_number(payload.get("eligibility_score"), "eligibility_score")
    score = round(max(0.0, min(100.0, score)), 2)

    risk_category = str(payload.get("risk_category", "")).strip().lower()
    if risk_category not in QUALIFICATION_RISK_LEVELS:
        risk_category = _derive_risk_category(score)

    recommended_amount = _normalize_recommended_amount(
        payload.get("recommended_amount"),
        eligible,
        product,
        requested_amount,
    )

    reasoning = sanitize_multiline_text(payload.get("reasoning", ""))
    if not reasoning:
        raise ValueError("reasoning must be a non-empty string")

    strengths = _normalize_string_list(payload.get("strengths"), "strengths")
    concerns = _normalize_string_list(payload.get("concerns"), "concerns")
    missing_requirements = _normalize_string_list(
        payload.get("missing_requirements"),
        "missing_requirements",
    )

    # Defense-in-depth: enforce hard product requirements even if the AI
    # returned eligible.  The primary gate in qualify_customer should
    # already prevent reaching here with hard failures, but this protects
    # against future refactors that might skip the pre-AI gate.
    if data is not None:
        hard_failures = _check_hard_product_requirements(data, product)
        if hard_failures:
            for hf in hard_failures:
                if hf not in missing_requirements:
                    missing_requirements.append(hf)
            eligible = False
            logger.info(
                "[AI ENFORCEMENT] Overriding AI eligibility to False "
                "due to hard product requirement failures: %s",
                hard_failures,
            )

    can_apply = eligible and len(missing_requirements) == 0
    if not can_apply:
        recommended_amount = 0.0

    return {
        "eligible": eligible,
        "eligibility_score": score,
        "risk_category": risk_category,
        "recommended_amount": recommended_amount,
        "reasoning": reasoning,
        "strengths": strengths,
        "concerns": concerns,
        "missing_requirements": missing_requirements,
        "can_apply": can_apply,
        "ai_used": True,
        "required_documents_resolved": required_doc_types,
        "requirements_scope": scope,
    }


def format_profile_for_ai(data):
    """Format customer data for AI prompt"""
    personal = data.get("personal")
    business = data.get("business")
    alternative = data.get("alternative")
    docs = data.get("documents", [])

    profile_str = "None provided"
    if personal:
        profile_str = f"""
- Civil Status: {personal.civil_status or 'Not provided'}
- Address: {personal.city_municipality or 'Not provided'}, {personal.province or ''}
- Emergency Contact: {'Provided' if personal.emergency_contact_name else 'Not provided'}
"""

    business_str = "None provided"
    if business:
        months = business.business_age_months or 0
        years = months / 12 if months else 0
        logger.info(
            f"[AI QUALIFICATION] Business Age - months: {months}, years: {years:.1f}, raw value: {business.business_age_months}"
        )
        business_str = f"""
- Business Name: {business.business_name or 'Not provided'}
- Business Type: {business.business_type or 'Not provided'}
- Business Age: {months} months ({years:.1f} years)
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


def _build_requirement_status(
    data, product, required_doc_types, require_approved_documents
):
    """
    Pre-compute authoritative requirement status lines for the AI prompt.
    These act as ground truth so the AI cannot hallucinate different thresholds.
    """
    lines = []
    business = data.get("business")
    docs = data.get("documents", [])

    # Business age check
    biz_months = (business.business_age_months or 0) if business else 0
    min_months = product.min_business_months
    if biz_months >= min_months:
        lines.append(
            f"- Business operation: MEETS requirement ({biz_months} months >= {min_months} months minimum)"
        )
    else:
        lines.append(
            f"- Business operation: DOES NOT MEET requirement ({biz_months} months < {min_months} months minimum)"
        )

    # Income check
    income = (business.estimated_monthly_income or 0) if business else 0
    min_income = product.min_monthly_income
    if income >= min_income:
        lines.append(
            f"- Monthly income: MEETS requirement (₱{income:,.2f} >= ₱{min_income:,.2f} minimum)"
        )
    else:
        lines.append(
            f"- Monthly income: DOES NOT MEET requirement (₱{income:,.2f} < ₱{min_income:,.2f} minimum)"
        )

    # Document check
    if require_approved_documents and required_doc_types:
        doc_types_uploaded = set()
        for doc in docs:
            canonical = canonicalize_document_type(doc.document_type)
            if canonical:
                doc_types_uploaded.add(canonical)
        for req_doc in required_doc_types:
            label = document_type_label(req_doc)
            if req_doc in doc_types_uploaded:
                lines.append(f"- Document '{label}': UPLOADED")
            else:
                lines.append(f"- Document '{label}': MISSING")

    return "\n".join(lines) if lines else "No pre-computed status available."


_BUSINESS_AGE_PATTERNS = re.compile(
    r"business\s+(age|operation|history|experience|months)"
    r"|insufficient.*business"
    r"|limited.*business.*histor"
    r"|minimum.*\d+\s*months?\s*(of\s+)?business"
    r"|business.*less\s+than",
    re.IGNORECASE,
)


def _strip_false_business_age_failures(result, business, product):
    """
    Post-AI guard: if the customer actually meets the business-age threshold
    but the AI wrongly flagged it, remove those entries from concerns and
    missing_requirements so the user isn't shown incorrect reasons.
    """
    if not business:
        return result

    biz_months = business.business_age_months or 0
    if biz_months < product.min_business_months:
        # Customer genuinely does not meet the requirement — keep AI output.
        return result

    # Customer meets the requirement — strip any erroneous AI flags.
    changed = False
    for key in ("concerns", "missing_requirements"):
        original = result.get(key, [])
        filtered = [
            item for item in original if not _BUSINESS_AGE_PATTERNS.search(item)
        ]
        if len(filtered) != len(original):
            result[key] = filtered
            changed = True
            logger.info(
                f"[AI VALIDATION] Stripped false business-age failure from {key}: "
                f"customer has {biz_months} months >= {product.min_business_months} required"
            )

    # If we removed all missing_requirements but AI said not eligible,
    # re-evaluate eligibility based on remaining missing_requirements.
    if (
        changed
        and not result.get("eligible")
        and len(result.get("missing_requirements", [])) == 0
    ):
        result["eligible"] = True
        result["can_apply"] = True
        logger.info(
            "[AI VALIDATION] Overriding eligibility to True after stripping false failures"
        )

    return result


def qualify_customer(
    customer_id,
    product,
    requested_amount,
    term_months,
    purpose,
    requirements_scope="product",
    require_approved_documents=True,
):
    """
    Use AI to assess customer loan eligibility.

    Returns dict with eligibility info.
    """
    scope = _normalize_scope(requirements_scope)
    required_doc_types = resolve_required_document_types(product, scope)

    if not _ai_qualification_enabled():
        logger.info("AI qualification disabled; using rule-based assessment")
        data = get_customer_data(customer_id)
        return rule_based_qualification(
            data,
            product,
            requested_amount,
            requirements_scope=scope,
            require_approved_documents=require_approved_documents,
            reason="Rule-based assessment (AI disabled)",
        )

    # Get customer data
    data = get_customer_data(customer_id)

    # Hard-fail gate: deterministic product requirements must pass before
    # any AI call.  This avoids wasting LLM tokens and guarantees the AI
    # cannot override business-age or income minimums.
    hard_failures = _check_hard_product_requirements(data, product)
    if hard_failures:
        logger.info(
            "Customer %s fails hard product requirements before AI: %s",
            customer_id,
            hard_failures,
        )
        return _make_hard_fail_result(
            hard_failures, required_doc_types, scope, ai_used=False
        )

    # Format for AI
    profile_str, business_str, alt_str, docs_str = format_profile_for_ai(data)

    # Never send profile data to external AI if consent is not granted.
    if not has_ai_consent(customer_id):
        logger.info(
            f"AI consent not granted for customer {customer_id}; using rule-based qualification"
        )
        return rule_based_qualification(
            data,
            product,
            requested_amount,
            requirements_scope=scope,
            require_approved_documents=require_approved_documents,
            reason="Rule-based assessment (AI consent not granted)",
        )

    # Build pre-computed requirement status so the AI has authoritative ground truth
    requirement_status = _build_requirement_status(
        data,
        product,
        required_doc_types,
        require_approved_documents,
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
        purpose=purpose or "Not specified",
        min_income=product.min_monthly_income,
        min_months=product.min_business_months,
        required_docs=(
            ", ".join(document_type_label(doc) for doc in required_doc_types)
            if require_approved_documents
            else "Not required at pre-qualification stage (enforced during loan application)"
        ),
        requirement_status=requirement_status,
    )

    # Get AI response
    llm = get_llm_service(use_case="qualification")

    if not llm.is_available():
        # Fallback to rule-based if AI unavailable
        return rule_based_qualification(
            data,
            product,
            requested_amount,
            requirements_scope=scope,
            require_approved_documents=require_approved_documents,
            reason="Rule-based assessment (AI unavailable)",
        )

    result = llm.chat(
        message=prompt,
        language="en",
        system_prompt=QUALIFICATION_SYSTEM_PROMPT,
        temperature=0.1,
        max_tokens=600,
        top_p=0.9,
    )

    if not result["success"]:
        logger.error(f"AI qualification failed: {result.get('error')}")
        return rule_based_qualification(
            data,
            product,
            requested_amount,
            requirements_scope=scope,
            require_approved_documents=require_approved_documents,
            reason="Rule-based assessment (AI request failed)",
        )

    payload = _extract_first_json_object(result.get("response"))
    if payload is None:
        logger.error("AI qualification response did not contain a valid JSON object")
        return rule_based_qualification(
            data,
            product,
            requested_amount,
            requirements_scope=scope,
            require_approved_documents=require_approved_documents,
            reason="Rule-based assessment (AI response parsing failed)",
        )

    try:
        ai_result = _validate_and_normalize_ai_qualification(
            payload=payload,
            product=product,
            requested_amount=requested_amount,
            required_doc_types=required_doc_types,
            scope=scope,
            data=data,
        )
        # Post-AI guard: strip false business-age failures the AI may hallucinate
        business = data.get("business")
        ai_result = _strip_false_business_age_failures(ai_result, business, product)
        return ai_result
    except ValueError as e:
        logger.error(f"AI qualification schema validation failed: {e}")

    return rule_based_qualification(
        data,
        product,
        requested_amount,
        requirements_scope=scope,
        require_approved_documents=require_approved_documents,
        reason="Rule-based assessment (AI response parsing failed)",
    )


def rule_based_qualification(
    data,
    product,
    requested_amount,
    requirements_scope="product",
    require_approved_documents=True,
    reason="Rule-based assessment (AI unavailable)",
):
    """
    Fallback rule-based qualification when AI is unavailable.
    """
    scope = _normalize_scope(requirements_scope)
    score = 50  # Base score
    concerns = []
    strengths = []
    missing = []

    business = data.get("business")
    alternative = data.get("alternative")
    docs = data.get("documents", [])

    # Hard product requirements — these are deterministic gates,
    # not score-based.  They go into `missing` so that `eligible`
    # is forced False regardless of the accumulated score.
    hard_failures = _check_hard_product_requirements(
        {"business": business}, product
    )
    missing.extend(hard_failures)

    # Check business profile (score adjustments are informational only;
    # eligibility is governed by hard_failures above)
    if business:
        logger.info(
            f"[RULE-BASED QUALIFICATION] Checking business age - months: {business.business_age_months}, required: {product.min_business_months}"
        )
        if (
            business.business_age_months
            and business.business_age_months >= product.min_business_months
        ):
            score += 15
            strengths.append("Sufficient business experience")
        else:
            score -= 10
            concerns.append("Limited business history")
            logger.warning(
                f"[RULE-BASED QUALIFICATION] Insufficient business age: {business.business_age_months} < {product.min_business_months}"
            )

        if (
            business.estimated_monthly_income
            and business.estimated_monthly_income >= product.min_monthly_income
        ):
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
    doc_status = {}
    for doc in docs:
        canonical_type = canonicalize_document_type(doc.document_type)
        if canonical_type:
            doc_types.add(canonical_type)
            doc_status[canonical_type] = getattr(doc, "status", "pending")
    required_doc_types = resolve_required_document_types(product, scope)
    if require_approved_documents:
        for req_doc in required_doc_types:
            label = document_type_label(req_doc)
            if req_doc not in doc_types:
                score -= 5
                missing.append(f"Missing: {label}")
            elif doc_status.get(req_doc) != "approved":
                score -= 3
                missing.append(f"Document not approved: {label}")
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
        if alternative.utility_payment_history == "on_time":
            score += 5
            strengths.append("Good payment history")

    # Determine eligibility
    score = max(0, min(100, score))
    eligible = score >= 50 and len(missing) == 0

    # Risk category
    if score >= 75:
        risk = "low"
    elif score >= 50:
        risk = "medium"
    else:
        risk = "high"

    # Recommended amount
    if eligible:
        # Recommend based on income (3x monthly income or requested, whichever is lower)
        income = business.estimated_monthly_income if business else 0
        max_recommend = min(income * 3, product.max_amount, requested_amount)
        # Profile money fields are loaded as Decimal values. Qualification is
        # embedded in LoanApplication.ai_recommendation, and PyMongo cannot
        # encode a native Decimal. Keep this API/ML payload consistently numeric
        # and BSON-safe, matching the normalized AI qualification path.
        recommended = float(max(product.min_amount, max_recommend))
    else:
        recommended = 0.0

    return {
        "eligible": eligible,
        "eligibility_score": score,
        "risk_category": risk,
        "recommended_amount": recommended,
        "reasoning": reason,
        "strengths": strengths,
        "concerns": concerns,
        "missing_requirements": missing,
        "can_apply": eligible,
        "ai_used": False,
        "required_documents_resolved": required_doc_types,
        "requirements_scope": scope,
    }


def _required_document_result(
    documents,
    required_doc_types,
    *,
    require_approved_documents,
    requirements_scope,
):
    missing = []

    latest_documents_by_type = {}
    for document in documents:
        canonical_type = canonicalize_document_type(document.document_type)
        if canonical_type and canonical_type not in latest_documents_by_type:
            latest_documents_by_type[canonical_type] = document

    submission_statuses = {"pending", "needs_review", "approved"}
    for required_type in required_doc_types:
        label = document_type_label(required_type)
        document = latest_documents_by_type.get(required_type)
        if not document:
            missing.append(f"Document required: {label}")
        elif getattr(document, "reupload_requested", False):
            missing.append(f"Document re-upload requested: {label}")
        elif require_approved_documents and document.status != "approved":
            if document.status in {"pending", "needs_review"}:
                missing.append(f"Document pending verification: {label}")
            elif document.status == "rejected":
                missing.append(f"Document rejected, please re-upload: {label}")
            else:
                missing.append(f"Document not yet approved: {label}")
        elif (
            not require_approved_documents
            and document.status not in submission_statuses
        ):
            if document.status == "rejected":
                missing.append(f"Document rejected, please re-upload: {label}")
            else:
                missing.append(f"Document unavailable, please re-upload: {label}")

    return {
        "requirements_met": len(missing) == 0,
        "missing_requirements": missing,
        "required_documents_resolved": required_doc_types,
        "requirements_scope": requirements_scope,
    }


def check_required_documents(
    customer_id,
    product,
    requirements_scope="product",
    require_approved_documents=True,
):
    """Check product-required documents for submission or final approval."""
    scope = _normalize_scope(requirements_scope)
    required_doc_types = resolve_required_document_types(product, scope)
    documents = get_customer_data(customer_id).get("documents", [])
    return _required_document_result(
        documents,
        required_doc_types,
        require_approved_documents=require_approved_documents,
        requirements_scope=scope,
    )


def check_basic_eligibility(
    customer_id,
    product,
    requirements_scope="product",
    require_approved_documents=True,
):
    """
    Quick check for basic eligibility before full qualification.

    Requirements:
    1. Personal profile must exist
    2. Business profile must exist
    3. Alternative data must exist
    4. Required documents must be uploaded/approved when require_approved_documents=True
    """
    scope = _normalize_scope(requirements_scope)
    data = get_customer_data(customer_id)
    missing = []

    # Check all 3 profiles exist
    personal = data.get("personal")
    business = data.get("business")
    alternative = data.get("alternative")

    if not personal:
        missing.append("Personal profile required")
    elif not personal.profile_completed:
        missing.append("Personal profile incomplete")

    if not business:
        missing.append("Business profile required")
    elif not getattr(
        business,
        "profile_completed",
        bool(business.business_type and business.income_range),
    ):
        missing.append("Business profile incomplete")

    # Alternative data is required
    if not alternative:
        missing.append("Alternative data required")
    elif not getattr(
        alternative,
        "profile_completed",
        bool(alternative.education_level and alternative.housing_status),
    ):
        missing.append("Alternative data incomplete")

    required_doc_types = resolve_required_document_types(product, scope)

    if require_approved_documents:
        document_result = _required_document_result(
            data.get("documents", []),
            required_doc_types,
            require_approved_documents=True,
            requirements_scope=scope,
        )
        missing.extend(document_result["missing_requirements"])

    return {
        "can_apply": len(missing) == 0,
        "missing_requirements": missing,
        "required_documents_resolved": required_doc_types,
        "requirements_scope": scope,
        "required_documents_labels": {
            doc: document_type_label(doc) for doc in required_doc_types
        },
    }
