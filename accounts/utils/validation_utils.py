import os
import re
from django.utils.html import strip_tags


# Unicode-aware: allows letters with optional separators between words.
_PERSON_NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:[ .'-][^\W\d_]+)*$", re.UNICODE)
_EMPLOYEE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_MULTI_NEWLINE_PATTERN = re.compile(r"\n{3,}")
_DANGEROUS_BLOCK_TAG_PATTERN = re.compile(
    r"(?is)<\s*(script|style|iframe|object|embed|svg|math)\b[^>]*>.*?<\s*/\s*\1\s*>"
)
_DANGEROUS_UNCLOSED_TAG_PATTERN = re.compile(
    r"(?is)<\s*(script|style|iframe|object|embed|svg|math)\b[^>]*>.*$"
)
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def normalize_text(value):
    """Normalize user input by trimming and collapsing repeated whitespace."""
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _remove_dangerous_html_blocks(value):
    """
    Remove dangerous HTML blocks together with their inner content.
    """
    cleaned = str(value)
    cleaned = _DANGEROUS_BLOCK_TAG_PATTERN.sub(" ", cleaned)
    cleaned = _DANGEROUS_UNCLOSED_TAG_PATTERN.sub(" ", cleaned)
    return cleaned


def sanitize_text(value):
    """
    Sanitize free-text input by stripping HTML tags, removing control chars,
    and normalizing whitespace.
    """
    if value is None:
        return ""

    cleaned = _remove_dangerous_html_blocks(value)
    cleaned = strip_tags(cleaned)
    cleaned = _CONTROL_CHARS_PATTERN.sub("", cleaned)
    return normalize_text(cleaned)


def sanitize_multiline_text(value):
    """
    Sanitize text while preserving line breaks for multi-line content.
    """
    if value is None:
        return ""

    cleaned = _remove_dangerous_html_blocks(value)
    cleaned = strip_tags(cleaned)
    cleaned = _CONTROL_CHARS_PATTERN.sub("", cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "\n".join(" ".join(line.split()) for line in cleaned.split("\n"))
    cleaned = _MULTI_NEWLINE_PATTERN.sub("\n\n", cleaned)
    return cleaned.strip()


def sanitize_filename(value, fallback="uploaded_file"):
    """
    Sanitize a user-provided filename for metadata/display use.
    """
    basename = os.path.basename(str(value or ""))
    cleaned = sanitize_text(basename).replace("/", "_").replace("\\", "_").strip(" .")
    return cleaned or fallback


def parse_bool(value, field_name="value"):
    """
    Strictly parse a boolean-like value.

    Returns:
        tuple[bool, bool|None, str|None]: (is_valid, parsed_value, error_message)
    """
    if isinstance(value, bool):
        return True, value, None

    normalized = normalize_text(value).lower()
    if normalized in _TRUE_VALUES:
        return True, True, None
    if normalized in _FALSE_VALUES:
        return True, False, None

    return False, None, f"{field_name} must be a boolean (true/false)"


def parse_optional_bool(value, field_name="value"):
    """
    Parse optional booleans from query/body values.

    Returns:
        tuple[bool, bool|None, str|None]: (is_valid, parsed_or_none, error_message)
    """
    if value is None:
        return True, None, None
    if isinstance(value, str) and not normalize_text(value):
        return True, None, None

    return parse_bool(value, field_name)


def validate_person_name(value, field_name="Name", allow_blank=False, max_length=None):
    """
    Validate a person-name input.

    Returns:
        tuple[bool, str|None, str]: (is_valid, error_message, normalized_value)
    """
    normalized = normalize_text(value)

    if not normalized:
        if allow_blank:
            return True, None, normalized
        return False, f"{field_name} is required", normalized

    if max_length is not None and len(normalized) > max_length:
        return False, f"{field_name} must be at most {max_length} characters", normalized

    if not _PERSON_NAME_PATTERN.fullmatch(normalized):
        return (
            False,
            (
                f"{field_name} can only contain letters, spaces, apostrophes, "
                "hyphens, and periods"
            ),
            normalized,
        )

    return True, None, normalized


def validate_employee_id(value, field_name="Employee ID", min_length=3, max_length=50):
    """
    Validate employee identifiers (alphanumeric + underscore/hyphen).
    """
    normalized = sanitize_text(value)

    if not normalized:
        return False, f"{field_name} is required", normalized

    if len(normalized) < min_length:
        return (
            False,
            f"{field_name} must be at least {min_length} characters",
            normalized,
        )

    if len(normalized) > max_length:
        return (
            False,
            f"{field_name} must be at most {max_length} characters",
            normalized,
        )

    if not _EMPLOYEE_ID_PATTERN.fullmatch(normalized):
        return (
            False,
            f"{field_name} can only contain letters, numbers, underscores, and hyphens",
            normalized,
        )

    return True, None, normalized


def validate_phone_number(
    value,
    field_name="Phone",
    required=False,
    min_digits=11,
    max_digits=11,
):
    """
    Validate phone number with numeric-only policy.
    Default enforces exactly 11 digits.
    """
    raw = "" if value is None else str(value).strip()

    if not raw:
        if required:
            return False, f"{field_name} is required", ""
        return True, None, ""

    if not re.fullmatch(r"[0-9\s-]+", raw):
        return (
            False,
            f"{field_name} must contain numbers only",
            raw,
        )

    digits_only = re.sub(r"\D", "", raw)
    digit_count = len(digits_only)

    if digit_count < min_digits or digit_count > max_digits:
        if min_digits == max_digits:
            return (
                False,
                f"{field_name} must be exactly {min_digits} digits",
                digits_only,
            )
        return (
            False,
            f"{field_name} must be between {min_digits} and {max_digits} digits",
            digits_only,
        )

    return True, None, digits_only
