from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.http import StreamingHttpResponse
import uuid
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
from ai_assistant.services.context_builder import get_context_for_intent
from ai_assistant.services.tools import TOOL_SCHEMAS
from ai_assistant.views.chat_views import (
    ConsentRequiredMixin,
    EventStreamRenderer,
    ALLOWED_LANGUAGES,
)
import json
import logging

logger = logging.getLogger('ai_assistant')


class StreamingChatView(ConsentRequiredMixin, APIView):
    """
    Streaming chat endpoint using Server-Sent Events (SSE).
    
    POST /api/ai/chat/stream/
    
    Returns a stream of events:
    - event: tool_call, data: {"name": "get_profile_status"}
    - event: tool_result, data: {"name": "get_profile_status", "success": true}
    - event: token, data: {"content": "Hello"}
    - event: done, data: {"model": "llama3.1", "tokens_used": 150}
    - event: error, data: {"content": "Error message"}
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ChatRateThrottle]
    renderer_classes = [EventStreamRenderer]

    def post(self, request):
        """Stream AI response as Server-Sent Events"""
        has_consent, result = self.check_ai_consent(request)
        if not has_consent:
            return result
        
        user = request.user
        customer_id = user.customer_id
        
        message = sanitize_text(request.data.get('message', ''))
        if not message:
            return error_response(
                message="Message is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
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
        
        is_prohibited, redirect_response = check_prohibited_content(message)
        if is_prohibited:
            def filtered_stream():
                yield f"event: token\ndata: {json.dumps({'content': escape_llm_output(redirect_response)})}\n\n"
                yield f"event: done\ndata: {json.dumps({'filtered': True})}\n\n"
            
            response = StreamingHttpResponse(
                filtered_stream(),
                content_type='text/event-stream'
            )
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
        
        history = AIInteraction.find_by_conversation(
            conversation_id=conversation_id,
            customer_id=customer_id,
        )
        conversation_history = [
            {'role': h.role, 'content': h.message if h.role == 'user' else h.response}
            for h in history[-10:]
        ]
        
        llm = get_llm_service(use_case='chat')
        
        if not llm.is_available():
            return error_response(
                message="AI service is currently unavailable",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        if needs_user_context(message):
            user_context = get_context_for_intent(message, customer_id)
            contextualized_prompt = SYSTEM_PROMPT + user_context
        else:
            contextualized_prompt = SYSTEM_PROMPT

        def event_stream():
            """Generator that yields SSE formatted events"""
            start_time = time.time()
            full_response = []
            model_used = ''
            tokens_used = 0
            tools_called = []
            
            try:
                for chunk in llm.chat_with_tools_stream(
                    message=message,
                    customer_id=customer_id,
                    conversation_history=conversation_history,
                    language=language,
                    system_prompt=contextualized_prompt,
                    tools=TOOL_SCHEMAS,
                ):
                    chunk_type = chunk.get('type')
                    
                    if chunk_type == 'tool_call':
                        yield f"event: tool_call\ndata: {json.dumps({'name': chunk.get('name')})}\n\n"
                    
                    elif chunk_type == 'tool_result':
                        tools_called.append(chunk.get('name'))
                        yield f"event: tool_result\ndata: {json.dumps({'name': chunk.get('name'), 'success': chunk.get('success', True)})}\n\n"
                    
                    elif chunk_type == 'token':
                        content = escape_llm_output(chunk.get('content', ''))
                        full_response.append(content)
                        yield f"event: token\ndata: {json.dumps({'content': content})}\n\n"
                    
                    elif chunk_type == 'done':
                        model_used = chunk.get('model', '')
                        tokens_used = chunk.get('tokens_used', 0)
                        elapsed_ms = int((time.time() - start_time) * 1000)
                        
                        ai_response = escape_llm_output(sanitize_multiline_text(''.join(full_response)))
                        if ai_response:
                            user_interaction = AIInteraction(
                                customer_id=customer_id,
                                message=message,
                                response='',
                                language=language,
                                conversation_id=conversation_id,
                                role='user'
                            )
                            user_interaction.save()
                            
                            ai_interaction = AIInteraction(
                                customer_id=customer_id,
                                message='',
                                response=ai_response,
                                language=language,
                                conversation_id=conversation_id,
                                role='assistant',
                                model_used=model_used,
                                response_time_ms=elapsed_ms,
                                tokens_used=tokens_used
                            )
                            ai_interaction.save()
                        
                        yield f"event: done\ndata: {json.dumps({'model': model_used, 'tokens_used': tokens_used, 'response_time_ms': elapsed_ms, 'conversation_id': conversation_id, 'tools_called': tools_called})}\n\n"
                    
                    elif chunk_type == 'error':
                        yield f"event: error\ndata: {json.dumps({'content': escape_llm_output(chunk.get('content', 'Unknown error'))})}\n\n"
                        break
                        
            except Exception as e:
                logger.error(f"Stream error: {str(e)}")
                yield f"event: error\ndata: {json.dumps({'content': escape_llm_output('Stream error occurred')})}\n\n"
        
        response = StreamingHttpResponse(
            event_stream(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response
