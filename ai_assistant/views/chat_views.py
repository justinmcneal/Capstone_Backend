from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from django.http import StreamingHttpResponse
from django.core.cache import cache
from django.conf import settings
import uuid
import math
import time

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.throttles import ChatRateThrottle
from accounts.utils.validation_utils import sanitize_text, sanitize_multiline_text, escape_llm_output
from accounts.services.consent_service import ConsentService
from ai_assistant.models import AIInteraction
from ai_assistant.services import get_llm_service
from ai_assistant.services.llm_service import SYSTEM_PROMPT, needs_user_context
from ai_assistant.services.knowledge_base import check_prohibited_content
from ai_assistant.services.context_builder import (
    build_user_context,
    get_context_for_intent,
    build_minimal_context,
)
from ai_assistant.services.tools import TOOL_SCHEMAS
import logging

logger = logging.getLogger('ai_assistant')
ALLOWED_LANGUAGES = {'en', 'tl'}


class EventStreamRenderer(BaseRenderer):
    """Custom renderer for Server-Sent Events"""
    media_type = 'text/event-stream'
    format = 'txt'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


CACHE_TTL = getattr(settings, 'CACHE_TTL', {
    'faqs': 86400,
    'education': 86400,
    'suggestions': 43200,
    'loan_products': 1800,
    'ai_status': 60,
})


class ConsentRequiredMixin(AccessControlMixin):
    """Mixin to enforce AI consent before allowing AI features"""
    
    def check_ai_consent(self, request):
        """Check if user has given AI consent"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return False, result

        user = request.user
        customer_id = user.customer_id
        
        if not ConsentService.check_ai_consent(customer_id, 'customer'):
            return False, error_response(
                message="AI consent is required to use this feature",
                code="CONSENT_REQUIRED",
                errors={
                    'action_required': {
                        'endpoint': '/api/auth/consent/',
                        'method': 'POST',
                        'required_fields': ['ai_consent']
                    }
                },
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        return True, None
