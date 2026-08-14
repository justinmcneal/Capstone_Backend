import logging
import uuid

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.services.consent_service import ConsentService
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.throttles import ChatRateThrottle
from accounts.utils.validation_utils import (
    escape_llm_output,
    sanitize_multiline_text,
    sanitize_text,
)
from ai_assistant.models import AIInteraction
from ai_assistant.services import get_llm_service
from ai_assistant.services.context_builder import (
    get_context_for_intent,
)
from ai_assistant.services.exception_types import NON_FATAL_EXCEPTIONS
from ai_assistant.services.idempotency import (
    claim,
    mark_complete,
    mark_failed,
    request_fingerprint,
)
from ai_assistant.services.knowledge_base import check_prohibited_content
from ai_assistant.services.llm_service import SYSTEM_PROMPT, needs_user_context
from ai_assistant.services.request_limits import (
    resolve_request_id,
    validate_chat_message,
)
from ai_assistant.services.tools import TOOL_SCHEMAS

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
                message="Current data and AI consent are required to use this feature",
                code="CONSENT_REQUIRED",
                errors={
                    'action_required': {
                        'endpoint': '/api/auth/consent/',
                        'method': 'POST',
                        'required_fields': [
                            'data_consent',
                            'ai_consent',
                            'consent_version',
                        ],
                        'current_policy': ConsentService.current_policy(),
                    }
                },
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        return True, None


class ChatView(ConsentRequiredMixin, APIView):
    """
    Main chat endpoint for AI assistant.
    
    POST /api/ai/chat/
    """
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (ChatRateThrottle,)
    
    def post(self, request):
        """Send a message to the AI assistant"""
        try:
            has_consent, result = self.check_ai_consent(request)
            if not has_consent:
                return result
            
            user = request.user
            customer_id = user.customer_id
            request_id, validation_error = resolve_request_id(request)
            if validation_error:
                return validation_error
            
            message, validation_error = validate_chat_message(request.data.get('message'), request)
            if validation_error:
                return validation_error
            
            raw_conversation_id = request.data.get('conversation_id')
            if raw_conversation_id:
                try:
                    conversation_id = str(uuid.UUID(str(raw_conversation_id)))
                except (ValueError, TypeError):
                    return error_response(
                        message="conversation_id must be a valid UUID",
                        errors={'conversation_id': 'Invalid format'},
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
            else:
                conversation_id = str(uuid.uuid4())
            requested_language = sanitize_text(
                request.data.get('language', user.language if hasattr(user, 'language') else 'en')
            ).lower()
            if requested_language not in ALLOWED_LANGUAGES:
                return error_response(
                    message="Invalid language value",
                    errors={'language': f"language must be one of: {', '.join(sorted(ALLOWED_LANGUAGES))}"},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            language = requested_language

            request_claim = claim(
                customer_id,
                request_id,
                fingerprint=request_fingerprint(message, raw_conversation_id or '', language),
            )
            if request_claim['state'] == 'conflict':
                return error_response(
                    message='Idempotency-Key was already used for a different request',
                    code='AI_IDEMPOTENCY_KEY_REUSED',
                    status_code=status.HTTP_409_CONFLICT,
                )
            if request_claim['state'] == 'in_progress':
                return error_response(
                    message='An identical AI request is already processing',
                    code='AI_REQUEST_IN_PROGRESS',
                    status_code=status.HTTP_409_CONFLICT,
                )
            if request_claim['state'] == 'replay':
                assistant = request_claim['interactions'][-1]
                return success_response(
                    data={
                        'response': assistant.response,
                        'conversation_id': assistant.conversation_id,
                        'model': assistant.model_used,
                        'response_time_ms': assistant.response_time_ms,
                        'request_id': request_id,
                        'replayed': True,
                    },
                    message='Response replayed successfully',
                )
            
            history = AIInteraction.find_by_conversation(
                conversation_id=conversation_id,
                customer_id=customer_id,
            )
            conversation_history = [
                {'role': h.role, 'content': h.message if h.role == 'user' else h.response}
                for h in history[-10:]
            ]
            
            is_prohibited, redirect_response = check_prohibited_content(message)
            if is_prohibited:
                user_interaction = AIInteraction(
                    customer_id=customer_id,
                    message=message,
                    response='',
                    conversation_id=conversation_id,
                    role='user',
                    request_id=request_id,
                )
                ai_interaction = AIInteraction(
                    customer_id=customer_id,
                    message='',
                    response=escape_llm_output(redirect_response),
                    conversation_id=conversation_id,
                    role='assistant',
                    model_used='content_filter',
                    response_time_ms=0,
                    request_id=request_id,
                )
                AIInteraction.save_exchange(user_interaction, ai_interaction)
                mark_complete(customer_id, request_id)
                
                return success_response(
                    data={
                        'message': escape_llm_output(redirect_response),
                        'conversation_id': conversation_id,
                        'filtered': True,
                        'request_id': request_id,
                    },
                    message="Response generated"
                )
            
            llm = get_llm_service(use_case='chat')
            
            if not llm.is_available():
                mark_failed(customer_id, request_id)
                return error_response(
                    message="AI service is currently unavailable",
                    code='AI_PROVIDER_UNAVAILABLE',
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            if needs_user_context(message):
                user_context = get_context_for_intent(message, customer_id)
                contextualized_prompt = SYSTEM_PROMPT + user_context
            else:
                contextualized_prompt = SYSTEM_PROMPT

            result = llm.chat_with_tools(
                message=message,
                customer_id=customer_id,
                conversation_history=conversation_history,
                language=language,
                system_prompt=contextualized_prompt,
                tools=TOOL_SCHEMAS,
            )
            
            if not result['success']:
                mark_failed(customer_id, request_id)
                return error_response(
                    message='AI service is temporarily unavailable',
                    code=result.get('code', 'AI_PROVIDER_ERROR'),
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE
                )

            ai_response = escape_llm_output(sanitize_multiline_text(result.get('response', '')))
            if not ai_response:
                mark_failed(customer_id, request_id)
                return error_response(
                    message="AI returned an empty response",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            user_interaction = AIInteraction(
                customer_id=customer_id,
                message=message,
                response='',
                language=language,
                conversation_id=conversation_id,
                role='user',
                request_id=request_id,
            )
            ai_interaction = AIInteraction(
                customer_id=customer_id,
                message='',
                response=ai_response,
                language=language,
                conversation_id=conversation_id,
                role='assistant',
                model_used=result.get('model', ''),
                response_time_ms=result.get('response_time_ms'),
                tokens_used=result.get('tokens_used'),
                request_id=request_id,
            )
            AIInteraction.save_exchange(user_interaction, ai_interaction)
            mark_complete(customer_id, request_id)
            
            logger.info(f"AI chat: customer {customer_id}, {result.get('response_time_ms')}ms")
            
            return success_response(
                data={
                    'response': ai_response,
                    'conversation_id': conversation_id,
                    'model': result.get('model'),
                    'response_time_ms': result.get('response_time_ms'),
                    'request_id': request_id,
                },
                message="Response generated successfully"
            )
            
        except NON_FATAL_EXCEPTIONS as e:
            if 'request_id' in locals() and 'customer_id' in locals():
                mark_failed(customer_id, request_id)
            logger.error(f"Chat error: {e!s}")
            return error_response(
                message="Failed to process chat message",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
