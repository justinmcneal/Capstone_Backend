from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger("security_events")


SENSITIVE_KEY_MARKERS = (
    "password",
    "otp",
    "token",
    "access",
    "refresh",
    "authorization",
    "file_bytes",
    "encryption_key",
    "secret",
    "raw_data",
)


def should_log_demo_hashes() -> bool:
    """
    Demo-only toggle. When enabled, bcrypt hashes can be logged for proof.
    Default is disabled.
    """
    value = os.getenv("SECURITY_DEMO_LOG_HASHES", "false").strip().lower()
    return value in ("1", "true", "yes", "on")


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, val in value.items():
            if any(marker in key.lower() for marker in SENSITIVE_KEY_MARKERS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_value(val)
        return redacted

    if isinstance(value, list):
        return [_redact_value(item) for item in value]

    if isinstance(value, str) and len(value) > 512:
        return f"{value[:512]}...[TRUNCATED]"

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    return str(value)


def _get_client_ip(request) -> str:
    if not request:
        return ""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def log_security_event(
    event: str,
    outcome: str = "success",
    request=None,
    user_id: str = "",
    user_role: str = "",
    details: dict | None = None,
) -> dict:
    """
    Write a JSON security event to the dedicated security log.

    This logger intentionally excludes sensitive values (passwords, tokens, keys, bytes).
    """
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "outcome": outcome,
        "user_id": str(user_id) if user_id else "",
        "user_role": user_role or "",
        "client_ip": _get_client_ip(request),
        "details": _redact_value(details or {}),
    }
    logger.info(json.dumps(payload, separators=(",", ":")))
    return payload
