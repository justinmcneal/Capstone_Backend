import json
import logging
import time
import uuid

from django.conf import settings
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
    AI_STREAM_LIMIT_CANCELLATIONS,
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
    AI_ASSISTANT_HISTORY_MAX_MESSAGES,
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
        if not getattr(settings, 'AI_ASSISTANT_ENABLED', True):
            return error_response(
                message="AI assistant is temporarily disabled",
                code="AI_ASSISTANT_DISABLED",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
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
            limit=AI_ASSISTANT_HISTORY_MAX_MESSAGES,
        )
        conversation_history = [
            {'role': h.role, 'content': h.message if h.role == 'user' else h.response}
            for h in history
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
            start_time = time.monotonic()
            full_response = []
            full_response_chars = 0
            full_response_bytes = 0
            max_stream_chars = max(1, int(settings.AI_ASSISTANT_STREAM_MAX_CHARS))
            max_stream_bytes = max(1, int(settings.AI_ASSISTANT_STREAM_MAX_BYTES))
            max_stream_duration = max(
                0.1,
                float(settings.AI_ASSISTANT_STREAM_MAX_DURATION_SECONDS),
            )
            model_used = ''
            tokens_used = 0
            tools_called = []
            terminal_emitted = False
            provider_stream = None

            def stream_limit_event(limit):
                code = (
                    'AI_PROVIDER_STREAM_DURATION_LIMIT'
                    if limit == 'duration'
                    else 'AI_PROVIDER_STREAM_OUTPUT_LIMIT'
                )
                mark_failed(customer_id, request_id)
                increment(
                    AI_STREAM_LIMIT_CANCELLATIONS,
                    provider=str(getattr(llm, 'provider', 'unknown')),
                    limit=limit,
                )
                increment(
                    AI_PROVIDER_REQUESTS,
                    provider=str(getattr(llm, 'provider', 'unknown')),
                    outcome='limit',
                )
                increment(
                    AI_REQUESTS,
                    endpoint='chat_stream_completion',
                    outcome='limit',
                )
                return f"event: error\ndata: {json.dumps({'content': escape_llm_output('AI service is temporarily unavailable'), 'code': code, 'request_id': request_id})}\n\n"
            
            try:
                provider_stream = llm.chat_with_tools_stream(
                    message=message,
                    customer_id=customer_id,
                    conversation_history=conversation_history,
                    language=language,
                    system_prompt=contextualized_prompt,
                    tools=TOOL_SCHEMAS,
                    request_id=request_id,
                )
                for chunk in provider_stream:
                    if time.monotonic() - start_time >= max_stream_duration:
                        terminal_emitted = True
                        yield stream_limit_event('duration')
                        return
                    chunk_type = chunk.get('type')
                    
                    if chunk_type == 'tool_call':
                        yield f"event: tool_call\ndata: {json.dumps({'name': chunk.get('name')})}\n\n"
                    
                    elif chunk_type == 'tool_result':
                        tools_called.append(chunk.get('name'))
                        yield f"event: tool_result\ndata: {json.dumps({'name': chunk.get('name'), 'success': chunk.get('success', True)})}\n\n"
                    
                    elif chunk_type == 'token':
                        raw_content = str(chunk.get('content', '') or '')
                        next_chars = full_response_chars + len(raw_content)
                        next_bytes = full_response_bytes + len(
                            raw_content.encode('utf-8')
                        )
                        if next_chars > max_stream_chars:
                            terminal_emitted = True
                            yield stream_limit_event('characters')
                            return
                        if next_bytes > max_stream_bytes:
                            terminal_emitted = True
                            yield stream_limit_event('bytes')
                            return
                        full_response_chars = next_chars
                        full_response_bytes = next_bytes
                        full_response.append(raw_content)
                        safe_content = escape_llm_output(raw_content)
                        yield f"event: token\ndata: {json.dumps({'content': safe_content})}\n\n"
                    
                    elif chunk_type == 'done':
                        model_used = chunk.get('model', '')
                        tokens_used = chunk.get('tokens_used', 0)
                        elapsed_ms = int((time.monotonic() - start_time) * 1000)
                        
                        ai_response = escape_llm_output(
                            sanitize_multiline_text(''.join(full_response))
                        )
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
                            terminal_emitted = True
                            yield f"event: done\ndata: {json.dumps({'model': model_used, 'tokens_used': tokens_used, 'response_time_ms': elapsed_ms, 'conversation_id': conversation_id, 'tools_called': tools_called, 'request_id': request_id})}\n\n"
                        else:
                            mark_failed(customer_id, request_id)
                            increment(
                                AI_PERSISTENCE_FAILURES,
                                operation='empty_stream',
                            )
                            terminal_emitted = True
                            yield f"event: error\ndata: {json.dumps({'content': escape_llm_output('AI returned an empty response'), 'code': 'AI_EMPTY_RESPONSE', 'request_id': request_id})}\n\n"
                        break
                    
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
                            'request_id': request_id,
                        }
                        terminal_emitted = True
                        yield f"event: error\ndata: {json.dumps(error_data)}\n\n"
                        break

                if not terminal_emitted:
                    mark_failed(customer_id, request_id)
                    increment(
                        AI_REQUESTS,
                        endpoint='chat_stream_completion',
                        outcome='incomplete',
                    )
                    terminal_emitted = True
                    yield f"event: error\ndata: {json.dumps({'content': escape_llm_output('AI stream ended unexpectedly'), 'code': 'AI_STREAM_INCOMPLETE', 'request_id': request_id})}\n\n"
            except GeneratorExit:
                if not terminal_emitted:
                    mark_failed(customer_id, request_id)
                    increment(
                        AI_REQUESTS,
                        endpoint='chat_stream_completion',
                        outcome='disconnect',
                    )
                    logger.info(
                        'AI stream disconnected before completion',
                        extra={'request_id': request_id},
                    )
                raise
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
                yield f"event: error\ndata: {json.dumps({'content': escape_llm_output('Stream error occurred'), 'code': 'AI_STREAM_ERROR', 'request_id': request_id})}\n\n"
            finally:
                close_stream = getattr(provider_stream, 'close', None)
                if callable(close_stream):
                    close_stream()
        
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
