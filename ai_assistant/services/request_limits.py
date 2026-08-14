"""Shared request validation for normal and streaming AI endpoints."""

from django.conf import settings
from rest_framework import status

from accounts.utils.response_helpers import error_response
from accounts.utils.validation_utils import sanitize_text


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
