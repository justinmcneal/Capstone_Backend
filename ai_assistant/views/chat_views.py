import logging

from django.conf import settings
from rest_framework import status
from rest_framework.renderers import BaseRenderer

from accounts.services.consent_service import ConsentService
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import error_response

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
