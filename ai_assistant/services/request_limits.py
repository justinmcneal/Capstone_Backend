"""Shared request validation for normal and streaming AI endpoints."""

import uuid

from django.conf import settings
from rest_framework import status

from accounts.utils.response_helpers import error_response
from accounts.utils.validation_utils import sanitize_text

AI_ASSISTANT_HISTORY_MAX_MESSAGES = 12


def bounded_conversation_history(history):
    """Keep the last six complete user/assistant turns for provider context."""
    return list(history or [])[-AI_ASSISTANT_HISTORY_MAX_MESSAGES:]


def validate_chat_message(raw_message, request=None):
    content_length = 0
    if request is not None:
        try:
            content_length = int(getattr(request, 'META', {}).get('CONTENT_LENGTH') or 0)
        except (TypeError, ValueError):
            content_length = 0
    if content_length > settings.AI_ASSISTANT_REQUEST_MAX_BYTES:
        return None, error_response(
            message='Request payload is too large',
            code='AI_REQUEST_BYTES_EXCEEDED',
            errors={'request': f'Must not exceed {settings.AI_ASSISTANT_REQUEST_MAX_BYTES} bytes'},
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    raw_text = '' if raw_message is None else str(raw_message)
    byte_count = len(raw_text.encode('utf-8'))
    if byte_count > settings.AI_ASSISTANT_MESSAGE_MAX_BYTES:
        return None, error_response(
            message='Message payload is too large',
            code='AI_MESSAGE_BYTES_EXCEEDED',
            errors={'message': f'Must not exceed {settings.AI_ASSISTANT_MESSAGE_MAX_BYTES} bytes'},
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    message = sanitize_text(raw_text)
    if not message:
        return None, error_response(
            message='Message is required',
            code='AI_MESSAGE_REQUIRED',
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if len(message) > settings.AI_ASSISTANT_MESSAGE_MAX_CHARS:
        return None, error_response(
            message='Message is too long',
            code='AI_MESSAGE_CHARS_EXCEEDED',
            errors={'message': f'Must not exceed {settings.AI_ASSISTANT_MESSAGE_MAX_CHARS} characters'},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return message, None


def resolve_request_id(request):
    """Validate an optional UUID idempotency key or generate one."""
    headers = getattr(request, 'headers', {})
    raw_value = headers.get('Idempotency-Key') if headers else None
    if not raw_value:
        raw_value = getattr(request, 'META', {}).get('HTTP_IDEMPOTENCY_KEY')
    if not raw_value:
        return str(uuid.uuid4()), None
    try:
        return str(uuid.UUID(str(raw_value))), None
    except (TypeError, ValueError):
        return None, error_response(
            message='Idempotency-Key must be a valid UUID',
            code='AI_IDEMPOTENCY_KEY_INVALID',
            errors={'Idempotency-Key': 'Invalid UUID format'},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
