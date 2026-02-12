from __future__ import annotations

import re
from rest_framework import serializers

from config.security_events import log_security_event


XSS_PATTERNS = [
    r"<\s*script\b",
    r"javascript:",
    r"on\w+\s*=",
    r"<\s*iframe\b",
    r"<\s*img\b",
    r"%3cscript",
]

NOSQL_INJECTION_PATTERNS = [
    r"\$ne\b",
    r"\$gt\b",
    r"\$gte\b",
    r"\$lt\b",
    r"\$lte\b",
    r"\$or\b",
    r"\$where\b",
    r"db\.",
    r"\{\s*\"\$",
]


def _contains_pattern(value: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        if re.search(pattern, value, flags=re.IGNORECASE):
            return pattern
    return None


def sanitize_text_input(
    value: str,
    field_name: str,
    request=None,
    allow_blank: bool = False,
    max_length: int | None = None,
) -> str:
    """
    Validate user input and block common XSS/NoSQL injection payloads.
    """
    if value is None:
        return value

    if not isinstance(value, str):
        log_security_event(
            event="input_sanitization_blocked",
            outcome="blocked",
            request=request,
            details={
                "field": field_name,
                "reason": "non_string_input",
                "input_type": type(value).__name__,
            },
        )
        raise serializers.ValidationError("Invalid input format")

    cleaned = value.strip()

    if max_length and len(cleaned) > max_length:
        raise serializers.ValidationError(f"{field_name} exceeds allowed length")

    if not cleaned and not allow_blank:
        raise serializers.ValidationError(f"{field_name} cannot be blank")

    xss_match = _contains_pattern(cleaned, XSS_PATTERNS)
    if xss_match:
        log_security_event(
            event="input_sanitization_blocked",
            outcome="blocked",
            request=request,
            details={
                "field": field_name,
                "threat_type": "xss",
                "pattern": xss_match,
            },
        )
        raise serializers.ValidationError("Potentially malicious input detected")

    nosql_match = _contains_pattern(cleaned, NOSQL_INJECTION_PATTERNS)
    if nosql_match:
        log_security_event(
            event="input_sanitization_blocked",
            outcome="blocked",
            request=request,
            details={
                "field": field_name,
                "threat_type": "nosql_injection",
                "pattern": nosql_match,
            },
        )
        raise serializers.ValidationError("Potentially malicious input detected")

    return re.sub(r"\s+", " ", cleaned)
