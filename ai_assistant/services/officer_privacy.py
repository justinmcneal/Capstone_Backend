"""Provider-boundary privacy checks for the loan-officer assistant."""

import re
import unicodedata


_SAFE_PROMPTS = frozenset(
    {
        "summarize this application's review readiness",
        "summarize review readiness",
        "review summary",
        "review this application",
        "review missing documents and repayment status",
        "what documents are present",
        "what profile information is still incomplete",
        "summarize the required document review statuses",
        "explain the current repayment summary",
        "summarize what is still needed before review",
        "review missing documents",
        "ibuod ang kahandaan ng aplikasyon para sa pagsusuri",
        "ano pa ang kulang sa profile bago ang pagsusuri",
        "ibuod ang katayuan ng mga kinakailangang dokumento",
        "ipaliwanag ang kasalukuyang buod ng pagbabayad",
    }
)
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\w)\+?[\d][\d\s()./-]*[\d](?!\w)")
_DATE_PATTERN = re.compile(
    r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{8})\b"
)
_REFERENCE_PATTERN = re.compile(
    r"\b(?:0x[0-9a-f]{8,}|(?:pay|txn|ref)[-_][A-Za-z0-9]{4,})\b",
    re.IGNORECASE,
)
_CONTEXTUAL_NAME_PATTERN = re.compile(
    r"\b(?:customer|borrower|applicant|client)\b.{0,24}?"
    r"(?:\bis\b|\bwas\b|\bnamed\b|[:=-])\s*"
    r"(?:mr|mrs|ms|miss)?\.?\s*"
    r"(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30}"
    r"(?:[ -][A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30})?)",
    re.IGNORECASE,
)
_CONTEXTUAL_NAME_AFTER_ACTION_PATTERN = re.compile(
    r"\b(?:review|about|contact|call)\b\s+"
    r"(?:mr|mrs|ms|miss)?\.?\s*"
    r"(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30}"
    r"(?:[ -][A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30})?)",
    re.IGNORECASE,
)
_CAPITALIZED_NAME_PAIR_PATTERN = re.compile(
    r"(?<!\w)([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30})"
    r"(?:[ -]([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30}))(?!\w)"
)
_BARE_NAME_PATTERN = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30}"
    r"\s+[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30}",
    re.IGNORECASE,
)
_NON_LATIN_LETTER = re.compile(r"[^\W\d_]")
_NAME_STOP_WORDS = frozenset(
    {
        "a", "an", "and", "application", "are", "before", "can", "complete",
        "current", "customer", "decision", "documents", "earlier", "explain",
        "for", "has", "have", "in", "information", "is", "it", "loan", "making",
        "missing", "my", "next", "not", "of", "please", "profile", "qualified",
        "ready", "repayment", "required", "review", "should", "status", "still",
        "summary", "summarize", "tell", "the", "this", "to", "what", "with", "you",
    }
)


def _canonical_text(value):
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Cf"
    )


def officer_text_privacy_violations(value):
    """Return privacy violation codes without returning the sensitive text."""
    text = _canonical_text(value)
    normalized = " ".join(text.casefold().strip(" .!?;:").split())
    if normalized in _SAFE_PROMPTS:
        return ()

    violations = []
    if _EMAIL_PATTERN.search(text):
        violations.append("email")
    if _DATE_PATTERN.search(text):
        violations.append("date")
    if _REFERENCE_PATTERN.search(text):
        violations.append("reference")

    for match in _PHONE_PATTERN.finditer(text):
        if sum(character.isdigit() for character in match.group()) >= 7:
            violations.append("identifier_like_number")
            break

    contextual_match = _CONTEXTUAL_NAME_PATTERN.search(text)
    contextual_name = bool(
        contextual_match
        and all(
            part.casefold() not in _NAME_STOP_WORDS
            for part in contextual_match.group("name").split()
        )
    )
    contextual_action_match = _CONTEXTUAL_NAME_AFTER_ACTION_PATTERN.search(text)
    contextual_action_name = bool(
        contextual_action_match
        and all(
            part.casefold() not in _NAME_STOP_WORDS
            for part in contextual_action_match.group("name").split()
        )
    )
    capitalized_name = any(
        first.casefold() not in _NAME_STOP_WORDS
        and second.casefold() not in _NAME_STOP_WORDS
        for first, second in _CAPITALIZED_NAME_PAIR_PATTERN.findall(text)
    )
    bare_name_parts = _BARE_NAME_PATTERN.fullmatch(text)
    bare_name = bool(
        bare_name_parts
        and all(
            part.casefold() not in _NAME_STOP_WORDS
            for part in text.split()
        )
    )
    if contextual_name or contextual_action_name or capitalized_name or bare_name:
        violations.append("name")

    if any(
        _NON_LATIN_LETTER.fullmatch(character)
        and "LATIN" not in unicodedata.name(character, "")
        for character in text
    ):
        violations.append("non_latin_identifier")

    return tuple(dict.fromkeys(violations))


def officer_provider_input_violations(message, conversation_history=()):
    """Inspect the current message and all replayed history before provider use."""
    violations = list(officer_text_privacy_violations(message))
    for entry in conversation_history or ():
        if isinstance(entry, dict):
            violations.extend(officer_text_privacy_violations(entry.get("content", "")))
    return tuple(dict.fromkeys(violations))
