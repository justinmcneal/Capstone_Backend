"""Officer-only policy and response controls.

This module deliberately does not reuse the borrower-facing knowledge base or
controlled guidance.  The officer assistant has a narrower application-bound
contract and a single public refusal response for unsupported requests.
"""

import re

from ai_assistant.services.officer_privacy import officer_text_privacy_violations


OFFICER_UNSUPPORTED_RESPONSE = (
    "I can help summarize this application's status, profile readiness, document "
    "review, or repayment information. I can't help with that request here."
)
OFFICER_READ_ONLY_ACTION_RESPONSE = (
    "I am read-only and cannot perform that action. Use the established portal workflow."
)

_BOUNDARY_TERMS = (
    "ignore your instructions",
    "ignore previous instructions",
    "ignore all previous",
    "reveal the system prompt",
    "show the system prompt",
    "print the system prompt",
    "explain your instructions",
    "explain the instructions",
    "tell me your rules",
    "developer mode",
    "role-play",
    "role play",
    "pretend",
    "simulate",
    "for testing purposes",
    "call every tool",
)
_CROSS_SCOPE_TERMS = (
    "another application",
    "other application",
    "another customer",
    "other customer",
    "all customers",
    "cross-portfolio",
    "cross portfolio",
    "ibang application",
    "ibang customer",
)
_RESTRICTED_TERMS = (
    "full name",
    "borrower name",
    "customer name",
    "email address",
    "phone number",
    "mobile number",
    "contact number",
    "home address",
    "street address",
    "government id",
    "government identifier",
    "wallet address",
    "transaction hash",
    "private key",
    "password",
    "one-time password",
    "otp",
)
_GENERAL_TERMS = (
    "weather",
    "joke",
    "poem",
    "recipe",
    "sports score",
    "politics",
    "news",
)
_LEGAL_TERMS = ("legal advice", "lawyer", "attorney", "court", "lawsuit")
_BORROWER_GUIDANCE_REQUEST_PATTERN = re.compile(
    r"\b(?:how|where|can i|could i|paano|saan)\b.*\b(?:upload|submit|"
    r"navigate|track|apply|mag-upload|mag\s+upload|mag-apply|mag-aapply|"
    r"mag\s+apply)\b"
    r"|\b(?:how|where|can i|could i|paano|saan)\b.*\b(?:make|pay|"
    r"magbayad|bayad)\b.*\b(?:payment|loan|installment|hulog|utang)?\b",
    re.IGNORECASE,
)
_BORROWER_GUIDANCE_RESPONSE_PATTERN = re.compile(
    r"\b(?:to|how to)\s+apply for (?:a\s+)?loan\b"
    r"|\b(?:make a payment|pay your installment|upload (?:your|the)\b)\b"
    r"|\b(?:track|go to|open|tap|select)\b.{0,80}\b(?:applications|"
    r"repayment|make a payment)\b",
    re.IGNORECASE | re.DOTALL,
)
_ACTION_PATTERN = re.compile(
    r"(?:^|\b)(?:please\s+)?(?:approve|reject|disburse|escalate|mutate|"
    r"update|change)\s+(?:this|the|an?|my)\b"
    r"|(?:^|\b)(?:please\s+)?(?:process|make)\s+(?:a\s+)?payment\b"
    r"|(?:^|\b)(?:please\s+)?verify\s+(?:this|the|an?)\s+document\b"
    r"|(?:^|\b)(?:can|could)\s+you\s+(?:approve|reject|disburse|"
    r"escalate|mutate|update|change|verify)\b",
    re.IGNORECASE,
)
_ACTION_CLAIM_PATTERN = re.compile(
    r"\b(?:i|we)\s+(?:recommend(?:ed)?|approve(?:d)?|reject(?:ed)?|"
    r"disburse(?:d)?|process(?:ed)?|verif(?:y|ied)|escalate(?:d)?)\b"
    r"|\b(?:should|must)\s+(?:approve|reject|disburse|process|verify|escalate)\b",
    re.IGNORECASE,
)
# Pattern matching and display-field relaying are intentionally conservative
# and cannot guarantee that every sufficiently unusual decision claim is caught
# or that a model will never ignore or mis-transcribe a supplied currency
# display value.  These are known residual risks; unbuffered SSE also exposes
# provider tokens before aggregate response validation (see the streaming
# item-8 decision).
_PASSIVE_ACTION_CLAIM_PATTERN = re.compile(
    r"\b(?:application|loan|request|case)\b.{0,50}"
    r"\b(?:has been|have been|is|are|was|were|will be|"
    r"is guaranteed to be|is certain to be)\s+"
    r"(?:recommended|approved|rejected|accepted|declined|cleared|authorized)\b"
    r"(?:.{0,50}\b(?:for|to)\s+(?:a\s+)?(?:loan|approval|funding|"
    r"disbursement)\b)?"
    r"|\b(?:application|loan|request|case)\b.{0,50}"
    r"\b(?:qualifies|is eligible)\s+for\s+"
    r"(?:a\s+)?(?:loan|approval|funding|disbursement)\b",
    re.IGNORECASE | re.DOTALL,
)
_UNSUPPORTED_RESPONSE_PATTERN = re.compile(
    r"\b(?:i\s+can(?:not|'t)|cannot|can't)\b.*\b(?:system prompt|"
    r"instructions|another application|another customer)\b",
    re.IGNORECASE,
)

def _normalized(value):
    return " ".join(str(value or "").replace("’", "'").lower().split())


def officer_policy_response(message, *, language="en"):
    """Return a deterministic officer response for requests needing no provider."""
    text = _normalized(message)

    if any(term in text for term in _BOUNDARY_TERMS):
        return OFFICER_UNSUPPORTED_RESPONSE
    if any(term in text for term in _CROSS_SCOPE_TERMS):
        return OFFICER_UNSUPPORTED_RESPONSE
    if any(term in text for term in _RESTRICTED_TERMS):
        return OFFICER_UNSUPPORTED_RESPONSE
    if any(term in text for term in _GENERAL_TERMS + _LEGAL_TERMS):
        return OFFICER_UNSUPPORTED_RESPONSE
    if (
        "apply for a loan" in text
        or "apply for loan" in text
        or "mag-apply" in text
        or "mag-aapply" in text
        or "mag apply" in text
    ):
        return OFFICER_UNSUPPORTED_RESPONSE
    if _BORROWER_GUIDANCE_REQUEST_PATTERN.search(text):
        return OFFICER_UNSUPPORTED_RESPONSE
    if _ACTION_PATTERN.search(text):
        return OFFICER_READ_ONLY_ACTION_RESPONSE
    return None


def validate_officer_response(
    response,
    *,
    message="",
    language="en",
    tools_called=(),
):
    """Return provider text only when it stays inside the officer contract."""
    del message, language
    text = str(response or "").strip()
    if not text:
        return "", ["empty_response"]

    violations = []
    lowered = _normalized(text)
    privacy_violations = officer_text_privacy_violations(text)
    if privacy_violations:
        violations.extend(
            f"direct_identifier_{violation}" for violation in privacy_violations
        )
        return OFFICER_UNSUPPORTED_RESPONSE, violations
    if any(term in lowered for term in _BOUNDARY_TERMS) or _UNSUPPORTED_RESPONSE_PATTERN.search(text):
        violations.append("boundary_override")
        return OFFICER_UNSUPPORTED_RESPONSE, violations
    if any(term in lowered for term in _RESTRICTED_TERMS):
        violations.append("restricted_information")
        return OFFICER_UNSUPPORTED_RESPONSE, violations
    if _BORROWER_GUIDANCE_RESPONSE_PATTERN.search(text):
        violations.append("borrower_guidance")
        return OFFICER_UNSUPPORTED_RESPONSE, violations
    if _ACTION_CLAIM_PATTERN.search(text) or _PASSIVE_ACTION_CLAIM_PATTERN.search(
        text
    ):
        violations.append("decision_or_action_claim")
        return OFFICER_READ_ONLY_ACTION_RESPONSE, violations
    if re.search(r"\bget_[a-z][a-z0-9_]*\b", text, re.IGNORECASE):
        violations.append("raw_tool_name")
        return OFFICER_UNSUPPORTED_RESPONSE, violations
    return text, violations
