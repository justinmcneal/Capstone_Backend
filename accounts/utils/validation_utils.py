import re
from django.utils.html import strip_tags


# Unicode-aware: allows letters with optional separators between words.
_PERSON_NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:[ .'-][^\W\d_]+)*$", re.UNICODE)
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def normalize_text(value):
    """Normalize user input by trimming and collapsing repeated whitespace."""
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def sanitize_text(value):
    """
    Sanitize free-text input by stripping HTML tags, removing control chars,
    and normalizing whitespace.
    """
    if value is None:
        return ""

    cleaned = strip_tags(str(value))
    cleaned = _CONTROL_CHARS_PATTERN.sub("", cleaned)
    return normalize_text(cleaned)


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
