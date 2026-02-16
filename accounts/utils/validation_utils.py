import re


# Unicode-aware: allows letters with optional separators between words.
_PERSON_NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:[ .'-][^\W\d_]+)*$", re.UNICODE)


def normalize_text(value):
    """Normalize user input by trimming and collapsing repeated whitespace."""
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def validate_person_name(value, field_name="Name", allow_blank=False):
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
