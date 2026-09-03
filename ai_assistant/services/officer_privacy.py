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
_BARE_NAME_PATTERN = re.compile(
    r"(?<!\w)([^\W\d_][^\W\d_'’-]{1,30})\s+"
    r"([^\W\d_][^\W\d_'’-]{1,30})(?!\w)",
    re.IGNORECASE,
)
_SEPARATED_NAME_PATTERN = re.compile(
    r"(?<!\w)([A-Za-zÀ-ÖØ-öø-ÿ]{2,30})[.\-]"
    r"([A-Za-zÀ-ÖØ-öø-ÿ]{2,30})(?!\w)",
    re.IGNORECASE,
)
_NON_LATIN_LETTER = re.compile(r"[^\W\d_]")
_PROVIDER_NAME_PATTERN = re.compile(
    r"(?<!\w)([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30})"
    r"(?:[ -]([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30}))(?!\w)"
)
_NAME_STOP_WORDS = frozenset(
    {
        "a", "an", "and", "application", "are", "before", "can", "complete",
        "current", "customer", "decision", "documents", "earlier", "explain",
        "for", "has", "have", "in", "information", "is", "it", "loan", "making",
        "fix", "function", "homework", "javascript", "missing", "my", "next",
        "not", "of", "please", "profile", "python", "qualified", "solve",
        "ready", "repayment", "required", "review", "should", "status", "still",
        "summary", "summarize", "tell", "the", "this", "to", "what", "with", "you",
    }
)
_HIGH_CONFIDENCE_RESTRICTED_PATTERN = re.compile(
    r"\b(?:phone|mobile|address|government\s+id|national\s+id|passport|"
    r"id\s+number|date\s+of\s+birth|dob|wallet|transaction\s+hash|"
    r"payment\s+reference|reference\s+number|internal\s+note|password|"
    r"secret|api\s+key|token|credential|private\s+key)\b"
    r"|\b(?:customer|borrower|applicant|client)\s+(?:name|email|phone|"
    r"mobile|address)\b"
    r"|\b(?:document|file)\s+(?:filename|name|content|path|url|storage)\b"
    r"|[\\/]\S+|\b[\w.-]+\.(?:pdf|png|jpe?g|docx?|csv)\b"
    r"|\b\d{1,6}\s+[^\W\d_][^\W\d_'’-]{1,30}"
    r"(?:\s+[^\W\d_][^\W\d_'’-]{1,30}){0,3}\s*,"
    r"|\b\d{1,6}\s+[^\W\d_][^\W\d_'’-]{1,30}"
    r"(?:\s+[^\W\d_][^\W\d_'’-]{1,30}){0,3}\s+"
    r"(?:city|municipality|barangay)\b"
    r"|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+)\d{4}\b",
    re.IGNORECASE,
)


def _canonical_text(value):
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    canonical = []
    for character in normalized:
        if unicodedata.category(character) == "Cf":
            continue
        if character in {"⁄", "∕", "／", "⧸"}:
            canonical.append("/")
        elif character in {"．", "。", "｡"}:
            canonical.append(".")
        elif unicodedata.category(character) == "Pd":
            canonical.append("-")
        elif character in {",", "،"}:
            canonical.append(",")
        elif unicodedata.category(character).startswith("P") and character not in {
            "'",
            "’",
            ".",
            "+",
            "@",
            "-",
            "/",
        }:
            canonical.append(" ")
        else:
            canonical.append(character)
    return "".join(canonical)


def officer_text_privacy_violations(value, *, include_bare_name=True):
    """Return privacy violation codes without returning the sensitive text."""
    text = " ".join(_canonical_text(value).split())
    normalized = text.casefold().strip(" .!?;:")
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
    bare_name_match = _BARE_NAME_PATTERN.fullmatch(text)
    bare_name = bool(
        bare_name_match
        and all(
            part.casefold() not in _NAME_STOP_WORDS
            for part in bare_name_match.groups()
        )
    )
    separated_name = any(
        first.casefold() not in _NAME_STOP_WORDS
        and second.casefold() not in _NAME_STOP_WORDS
        for first, second in _SEPARATED_NAME_PATTERN.findall(text)
    )
    if contextual_name or contextual_action_name or separated_name or (
        include_bare_name and bare_name
    ):
        violations.append("name")

    if _HIGH_CONFIDENCE_RESTRICTED_PATTERN.search(text):
        violations.append("restricted_information")

    if any(
        _NON_LATIN_LETTER.fullmatch(character)
        and "LATIN" not in unicodedata.name(character, "")
        for character in text
    ):
        violations.append("non_latin_identifier")

    return tuple(dict.fromkeys(violations))


def normalize_officer_text(value):
    """Return the detector's canonical text form without returning evidence."""
    return " ".join(_canonical_text(value).casefold().split())


def officer_provider_output_violations(value):
    """Add conservative output-only checks without treating names as input proof."""
    violations = list(
        officer_text_privacy_violations(value, include_bare_name=False)
    )
    text = _canonical_text(value)
    if _PROVIDER_NAME_PATTERN.search(text):
        violations.append("name")
    return tuple(dict.fromkeys(violations))


def officer_provider_input_violations(message, conversation_history=()):
    """Inspect the current message and all replayed history before provider use."""
    violations = list(officer_text_privacy_violations(message))
    for entry in conversation_history or ():
        if isinstance(entry, dict):
            violations.extend(officer_text_privacy_violations(entry.get("content", "")))
    return tuple(dict.fromkeys(violations))
