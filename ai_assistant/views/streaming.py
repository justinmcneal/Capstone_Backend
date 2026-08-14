import json
import logging
import time
import uuid

from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response
from accounts.utils.throttles import ChatRateThrottle
from accounts.utils.validation_utils import (
    escape_llm_output,
    sanitize_multiline_text,
    sanitize_text,
)
from ai_assistant.metrics import (
    AI_ACTIVE_STREAMS,
    AI_PERSISTENCE_FAILURES,
    AI_PROVIDER_LATENCY,
    AI_PROVIDER_REQUESTS,
    AI_REQUESTS,
    AI_TOKENS,
    decrement,
    increment,
    observe,
)
from ai_assistant.models import AIInteraction
from ai_assistant.services import get_llm_service
from ai_assistant.services.context_builder import get_context_for_intent
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
from ai_assistant.views.chat_views import (
    ALLOWED_LANGUAGES,
    AIRequestMetricsMixin,
    ConsentRequiredMixin,
    EventStreamRenderer,
)

logger = logging.getLogger('ai_assistant')


class StreamingChatView(AIRequestMetricsMixin, ConsentRequiredMixin, APIView):
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
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (ChatRateThrottle,)
    renderer_classes = (EventStreamRenderer,)
    metrics_endpoint = 'chat_stream'

    def post(self, request):
        """Stream AI response as Server-Sent Events"""
        request_id, validation_error = resolve_request_id(request)
        if validation_error:
            return validation_error
        logger.info("LLM stream start", extra={"request_id": request_id, "customer_id": request.user.customer_id})
        
        has_consent, result = self.check_ai_consent(request)
        if not has_consent:
            return result
        
        user = request.user
        customer_id = user.customer_id
        
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

            def replay_stream():
                yield f"event: token\ndata: {json.dumps({'content': assistant.response})}\n\n"
                yield f"event: done\ndata: {json.dumps({'model': assistant.model_used, 'tokens_used': assistant.tokens_used or 0, 'response_time_ms': assistant.response_time_ms, 'conversation_id': assistant.conversation_id, 'tools_called': [], 'request_id': request_id, 'replayed': True})}\n\n"

            return self._streaming_response(replay_stream())
        
        is_prohibited, redirect_response = check_prohibited_content(message)
        if is_prohibited:
            filtered_response = escape_llm_output(redirect_response)
            AIInteraction.save_exchange(
                AIInteraction(
                    customer_id=customer_id,
                    message=message,
                    response='',
                    language=language,
                    conversation_id=conversation_id,
                    role='user',
                    request_id=request_id,
                ),
                AIInteraction(
                    customer_id=customer_id,
                    message='',
                    response=filtered_response,
                    language=language,
                    conversation_id=conversation_id,
                    role='assistant',
                    model_used='content_filter',
                    response_time_ms=0,
                    request_id=request_id,
                ),
            )
            mark_complete(customer_id, request_id)

            def filtered_stream():
                yield f"event: token\ndata: {json.dumps({'content': filtered_response})}\n\n"
                yield f"event: done\ndata: {json.dumps({'filtered': True, 'request_id': request_id})}\n\n"
            
            return self._streaming_response(filtered_stream())
        
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
            mark_failed(customer_id, request_id)
            increment(
                AI_PROVIDER_REQUESTS,
                provider=str(getattr(llm, 'provider', 'unknown')),
                outcome='unavailable',
            )
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
                    request_id=request_id,
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
                                role='user',
                                request_id=request_id
                            )
                            ai_interaction = AIInteraction(
                                customer_id=customer_id,
                                message='',
                                response=ai_response,
                                language=language,
                                conversation_id=conversation_id,
                                role='assistant',
                                model_used=model_used,
                                response_time_ms=elapsed_ms,
                                tokens_used=tokens_used,
                                request_id=request_id
                            )
                            AIInteraction.save_exchange(user_interaction, ai_interaction)
                            mark_complete(customer_id, request_id)
                            increment(
                                AI_TOKENS,
                                amount=max(0, int(tokens_used or 0)),
                                provider=str(
                                    chunk.get('provider')
                                    or getattr(llm, 'provider', 'unknown')
                                ),
                            )
                            provider_name = str(
                                chunk.get('provider')
                                or getattr(llm, 'provider', 'unknown')
                            )
                            increment(
                                AI_PROVIDER_REQUESTS,
                                provider=provider_name,
                                outcome='success',
                            )
                            observe(
                                AI_PROVIDER_LATENCY,
                                elapsed_ms / 1000,
                                provider=provider_name,
                                operation='stream',
                            )
                            increment(
                                AI_REQUESTS,
                                endpoint='chat_stream_completion',
                                outcome='success',
                            )
                        else:
                            mark_failed(customer_id, request_id)
                            increment(
                                AI_PERSISTENCE_FAILURES,
                                operation='empty_stream',
                            )
                        
                        yield f"event: done\ndata: {json.dumps({'model': model_used, 'tokens_used': tokens_used, 'response_time_ms': elapsed_ms, 'conversation_id': conversation_id, 'tools_called': tools_called, 'request_id': request_id})}\n\n"
                    
                    elif chunk_type == 'error':
                        mark_failed(customer_id, request_id)
                        provider_outcome = {
                            'AI_PROVIDER_TIMEOUT': 'timeout',
                            'AI_PROVIDER_BUSY': 'busy',
                            'AI_PROVIDER_CIRCUIT_OPEN': 'circuit_open',
                        }.get(chunk.get('code'), 'error')
                        increment(
                            AI_PROVIDER_REQUESTS,
                            provider=str(getattr(llm, 'provider', 'unknown')),
                            outcome=provider_outcome,
                        )
                        increment(
                            AI_REQUESTS,
                            endpoint='chat_stream_completion',
                            outcome='error',
                        )
                        error_data = {
                            'content': escape_llm_output(chunk.get('content', 'Unknown error')),
                            'code': chunk.get('code', 'AI_PROVIDER_ERROR'),
                        }
                        yield f"event: error\ndata: {json.dumps(error_data)}\n\n"
                        break
                        
            except NON_FATAL_EXCEPTIONS:
                mark_failed(customer_id, request_id)
                increment(AI_PERSISTENCE_FAILURES, operation='stream_request')
                increment(
                    AI_REQUESTS,
                    endpoint='chat_stream_completion',
                    outcome='error',
                )
                logger.error(
                    "AI stream request failed",
                    extra={'request_id': request_id},
                )
                yield f"event: error\ndata: {json.dumps({'content': escape_llm_output('Stream error occurred')})}\n\n"
        
        return self._streaming_response(event_stream())

    @staticmethod
    def _streaming_response(stream):
        def observed_stream():
            increment(AI_ACTIVE_STREAMS)
            try:
                yield from stream
            finally:
                decrement(AI_ACTIVE_STREAMS)

        response = StreamingHttpResponse(
            observed_stream(),
            content_type='text/event-stream',
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response
