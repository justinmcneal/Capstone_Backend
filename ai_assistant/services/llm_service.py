"""
=============================================================================
GROQ LLM SERVICE - AI Chat for MSME Pathways
=============================================================================

This service connects to Groq Cloud to power the AI chatbot.
Groq provides FREE access to LLM models (14,400 requests/day).

SETUP:
1. Go to https://console.groq.com
2. Create account and get API key
3. Add to .env: GROQ_API_KEY=gsk_your_key_here

MODEL USED:
- llama-3.1-8b-instant (default) - Fast responses, supports Tagalog

HOW IT WORKS:
1. User sends message to /api/ai/chat/
2. This service sends message to Groq API
3. Groq returns AI response
4. Response is saved and sent back to user
=============================================================================
"""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from django.conf import settings

from ai_assistant.services.exception_types import NON_FATAL_EXCEPTIONS

# Import from centralized knowledge base
from ai_assistant.services.knowledge_base import (
    build_system_prompt,
    check_prohibited_content,
)
from ai_assistant.services.provider_boundary import (
    ProviderCircuitOpen,
    ProviderConcurrencyExceeded,
    provider_session,
)
from ai_assistant.services.officer_policy import (
    OFFICER_UNSUPPORTED_RESPONSE,
    officer_policy_response,
    validate_officer_response,
)
from ai_assistant.services.officer_privacy import officer_provider_input_violations
from ai_assistant.services.officer_review_brief import (
    InvalidReviewBrief,
    validate_narration,
    validate_review_brief,
)
from ai_assistant.services.response_controls import (
    controlled_guidance_response,
    validate_provider_response,
)
from ai_assistant.services.request_limits import bounded_conversation_history
from ai_assistant.metrics import AI_STREAM_LIMIT_CANCELLATIONS, increment

logger = logging.getLogger('ai_assistant')


# =============================================================================
# CONFIGURATION - Read lazily from Django settings at call time
# =============================================================================

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

_session = provider_session
PUBLIC_PROVIDER_ERROR = "AI service is temporarily unavailable. Please try again later."
INVALID_TOOL_ARGUMENTS = {"__invalid_tool_arguments__": True}


def _officer_stream_buffer_limit():
    """Return a finite response buffer bound derived from the output policy."""
    return max(1, int(settings.AI_ASSISTANT_MAX_OUTPUT_TOKENS)) * 8


def _policy_result(message, *, model, provider, request_id=None):
    """Apply the deterministic safety boundary before any provider or tool call."""
    prohibited, response = check_prohibited_content(str(message or ""))
    if not prohibited:
        return None
    result = {
        'success': True,
        'response': response,
        'model': model,
        'provider': provider,
        'response_time_ms': 0,
        'tokens_used': 0,
        'tools_called': [],
        'policy_intercepted': True,
    }
    if request_id:
        result['request_id'] = request_id
    return result


def _controlled_result(message, *, language, model, provider, request_id=None):
    response = controlled_guidance_response(message, language=language)
    if not response:
        return None
    result = {
        'success': True,
        'response': response,
        'model': model,
        'provider': provider,
        'response_time_ms': 0,
        'tokens_used': 0,
        'tools_called': [],
        'controlled_response': True,
    }
    if request_id:
        result['request_id'] = request_id
    return result


def _officer_policy_result(message, *, model, provider, request_id=None):
    response = officer_policy_response(message)
    if not response:
        return None
    result = {
        'success': True,
        'response': response,
        'model': model,
        'provider': provider,
        'response_time_ms': 0,
        'tokens_used': 0,
        'tools_called': [],
        'policy_intercepted': True,
    }
    if request_id:
        result['request_id'] = request_id
    return result


def _officer_privacy_result(
    message,
    *,
    conversation_history=None,
    model,
    provider,
    request_id=None,
):
    violations = officer_provider_input_violations(message, conversation_history)
    if not violations:
        return None
    result = {
        'success': True,
        'response': OFFICER_UNSUPPORTED_RESPONSE,
        'model': model,
        'provider': provider,
        'response_time_ms': 0,
        'tokens_used': 0,
        'tools_called': [],
        'policy_intercepted': True,
        'privacy_blocked': True,
        'privacy_violations': list(violations),
    }
    if request_id:
        result['request_id'] = request_id
    return result


def _parse_tool_arguments(arguments, *, injected_executor):
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        if injected_executor:
            return dict(INVALID_TOOL_ARGUMENTS)
        return {}


def _get_config():
    """Read LLM config from Django settings (which reads .env via load_dotenv)."""
    return {
        'provider': getattr(settings, 'LLM_PROVIDER', 'groq'),
        'groq_api_key': getattr(settings, 'GROQ_API_KEY', ''),
        'groq_model': getattr(settings, 'GROQ_MODEL', 'llama-3.1-8b-instant'),
        'groq_chat_model': getattr(settings, 'GROQ_CHAT_MODEL', getattr(settings, 'GROQ_MODEL', 'llama-3.1-8b-instant')),
        'groq_qualification_model': getattr(settings, 'GROQ_QUALIFICATION_MODEL', getattr(settings, 'GROQ_MODEL', 'llama-3.1-8b-instant')),
        'ollama_base_url': getattr(settings, 'OLLAMA_BASE_URL', 'http://localhost:11434'),
        'ollama_model': getattr(settings, 'OLLAMA_MODEL', 'llama3.1'),
        'max_output_tokens': settings.AI_ASSISTANT_MAX_OUTPUT_TOKENS,
        'max_tool_rounds': settings.AI_ASSISTANT_MAX_TOOL_ROUNDS,
        'max_tool_calls': settings.AI_ASSISTANT_MAX_TOOL_CALLS_PER_REQUEST,
    }


MODEL_USE_CASE_KEYS = {
    'default': 'groq_model',
    'chat': 'groq_chat_model',
    'qualification': 'groq_qualification_model',
}


# =============================================================================
# SYSTEM PROMPT - Built from centralized knowledge base
# =============================================================================
# The AI reads this before every conversation.
# To update AI knowledge, modify knowledge_base.py (single source of truth)

SYSTEM_PROMPT = build_system_prompt()


# Keywords that indicate user is asking about their personal data
CONTEXT_REQUIRED_KEYWORDS = [
    'my', 'mine', 'i have', 'do i', 'am i', 'can i',
    'profile', 'document', 'loan', 'payment', 'balance',
    'status', 'application', 'schedule', 'installment',
    'overdue', 'due', 'remaining', 'paid', 'approved',
    'rejected', 'pending', 'upload', 'complete', 'missing',
    'akin', 'ko', 'aking', 'bayad', 'utang', 'aplikasyon',
]


def needs_user_context(message: str) -> bool:
    """
    Determine if the user's message requires fetching their personal data.
    Returns False for general questions about the platform, loans, etc.
    """
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in CONTEXT_REQUIRED_KEYWORDS)


# =============================================================================
# LLM SERVICE CLASS - Supports Groq (cloud) and Ollama (local)
# =============================================================================

class GroqService:
    """
    LLM Service supporting multiple providers.

    Providers:
    - 'groq': Groq Cloud API (free tier, 14,400 req/day)
    - 'ollama': Local Ollama instance (no limits, requires local setup)

    Switch via .env: LLM_PROVIDER=groq or LLM_PROVIDER=ollama
    """
    
    def __init__(self, api_key=None, model=None, provider=None):
        config = _get_config()
        self.provider = provider or config['provider']
        if self.provider not in {'groq', 'ollama'}:
            raise ValueError('provider must be groq or ollama')
        logger.info(f"LLM init: provider={self.provider}")

        if self.provider == 'ollama':
            self.model = model or config['ollama_model']
            self.api_url = f"{config['ollama_base_url']}/v1/chat/completions"
            self.api_key = 'ollama'
            self._ollama_base_url = config['ollama_base_url']
        else:
            self.api_key = api_key or config['groq_api_key']
            self.model = model or config['groq_model']
            self.api_url = GROQ_API_URL
            self.provider = 'groq'
            self._ollama_base_url = None
    
    def readiness(self):
        """Return configured/reachable/authenticated provider readiness."""
        configured = bool(self.api_key) if self.provider == 'groq' else bool(self._ollama_base_url)
        result = {
            'provider': self.provider,
            'model': self.model,
            'configured': configured,
            'reachable': False,
            'authenticated': False,
            'model_available': False,
            'available': False,
            'state': 'unavailable',
            'circuit': _session.circuit_state(),
        }
        if not configured or result['circuit'] == 'open':
            result['state'] = 'not_configured' if not configured else 'degraded'
            return result

        url = (
            f"{self._ollama_base_url}/api/tags"
            if self.provider == 'ollama'
            else "https://api.groq.com/openai/v1/models"
        )
        try:
            response = _session.get(
                url,
                headers={'Authorization': f'Bearer {self.api_key}'},
            )
            result['reachable'] = True
            result['authenticated'] = response.status_code not in {401, 403}
            if response.status_code == 200:
                payload = response.json()
                if self.provider == 'ollama':
                    model_names = {
                        str(item.get('name') or item.get('model') or '')
                        for item in payload.get('models', [])
                    }
                    result['model_available'] = any(
                        name == self.model or name.startswith(f'{self.model}:')
                        for name in model_names
                    )
                else:
                    model_names = {
                        str(item.get('id') or '')
                        for item in payload.get('data', [])
                    }
                    result['model_available'] = self.model in model_names
            result['available'] = response.status_code == 200 and result['model_available']
            if result['available']:
                result['state'] = 'available'
            elif not result['authenticated']:
                result['state'] = 'authentication_failed'
            elif response.status_code == 200 and not result['model_available']:
                result['state'] = 'model_unavailable'
            else:
                result['state'] = 'degraded'
        except (requests.RequestException, TypeError, ValueError, AttributeError) as exc:
            logger.warning('AI provider readiness failed: %s', type(exc).__name__)
            result['state'] = 'degraded'
        return result

    def is_available(self):
        """Check whether the provider is reachable and authenticated."""
        return self.readiness()['available']

    @staticmethod
    def _bounded_limits(max_tokens, max_tool_rounds=None):
        max_tokens = min(max(1, int(max_tokens)), settings.AI_ASSISTANT_MAX_OUTPUT_TOKENS)
        if max_tool_rounds is None:
            return max_tokens
        rounds = min(max(0, int(max_tool_rounds)), settings.AI_ASSISTANT_MAX_TOOL_ROUNDS)
        return max_tokens, rounds

    @staticmethod
    def _provider_failure(exc=None, request_id=None):
        if exc is not None:
            logger.warning(
                'AI provider request failed: %s',
                type(exc).__name__,
                extra={'request_id': request_id},
            )
        if isinstance(exc, ProviderConcurrencyExceeded):
            code = 'AI_PROVIDER_BUSY'
        elif isinstance(exc, ProviderCircuitOpen):
            code = 'AI_PROVIDER_CIRCUIT_OPEN'
        elif isinstance(exc, requests.Timeout):
            code = 'AI_PROVIDER_TIMEOUT'
        else:
            code = 'AI_PROVIDER_ERROR'
        return {'success': False, 'error': PUBLIC_PROVIDER_ERROR, 'code': code}

    def _provider_stream_chunks(self, response, request_id=None):
        """Parse one provider SSE response and close it on every exit path."""
        total_tokens = 0
        saw_done = False
        output_chars = 0
        output_bytes = 0
        started = time.monotonic()
        max_chars = max(1, int(settings.AI_ASSISTANT_STREAM_MAX_CHARS))
        max_bytes = max(1, int(settings.AI_ASSISTANT_STREAM_MAX_BYTES))
        max_duration = max(
            0.1,
            float(settings.AI_ASSISTANT_STREAM_MAX_DURATION_SECONDS),
        )

        def limit_error(limit):
            code = (
                'AI_PROVIDER_STREAM_DURATION_LIMIT'
                if limit == 'duration'
                else 'AI_PROVIDER_STREAM_OUTPUT_LIMIT'
            )
            increment(
                AI_STREAM_LIMIT_CANCELLATIONS,
                provider=str(self.provider),
                limit=limit,
            )
            logger.warning(
                'AI provider stream cancelled by %s limit',
                limit,
                extra={'request_id': request_id},
            )
            return {
                'type': 'error',
                'content': PUBLIC_PROVIDER_ERROR,
                'code': code,
            }

        try:
            for line in response.iter_lines():
                if time.monotonic() - started >= max_duration:
                    yield limit_error('duration')
                    return
                if not line:
                    continue
                try:
                    line_text = (
                        line.decode('utf-8')
                        if isinstance(line, bytes)
                        else str(line)
                    )
                except UnicodeDecodeError:
                    logger.warning(
                        'AI provider stream contained invalid UTF-8',
                        extra={'request_id': request_id},
                    )
                    yield {
                        'type': 'error',
                        'content': PUBLIC_PROVIDER_ERROR,
                        'code': 'AI_PROVIDER_STREAM_MALFORMED',
                    }
                    return

                if not line_text.startswith('data:'):
                    continue
                data_text = line_text[5:].lstrip()
                if data_text.strip() == '[DONE]':
                    saw_done = True
                    break
                try:
                    payload = json.loads(data_text)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        'AI provider stream contained malformed JSON',
                        extra={'request_id': request_id},
                    )
                    yield {
                        'type': 'error',
                        'content': PUBLIC_PROVIDER_ERROR,
                        'code': 'AI_PROVIDER_STREAM_MALFORMED',
                    }
                    return
                if not isinstance(payload, dict):
                    yield {
                        'type': 'error',
                        'content': PUBLIC_PROVIDER_ERROR,
                        'code': 'AI_PROVIDER_STREAM_MALFORMED',
                    }
                    return

                usage = payload.get('usage')
                if isinstance(usage, dict):
                    try:
                        total_tokens = max(
                            0,
                            int(usage.get('total_tokens') or total_tokens),
                        )
                    except (TypeError, ValueError):
                        total_tokens = 0

                choices = payload.get('choices', [])
                if not isinstance(choices, list):
                    yield {
                        'type': 'error',
                        'content': PUBLIC_PROVIDER_ERROR,
                        'code': 'AI_PROVIDER_STREAM_MALFORMED',
                    }
                    return
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get('delta', {}) if isinstance(choice, dict) else None
                if not isinstance(delta, dict):
                    yield {
                        'type': 'error',
                        'content': PUBLIC_PROVIDER_ERROR,
                        'code': 'AI_PROVIDER_STREAM_MALFORMED',
                    }
                    return
                content = delta.get('content', '')
                if content:
                    content = str(content)
                    next_chars = output_chars + len(content)
                    next_bytes = output_bytes + len(content.encode('utf-8'))
                    if next_chars > max_chars:
                        yield limit_error('characters')
                        return
                    if next_bytes > max_bytes:
                        yield limit_error('bytes')
                        return
                    output_chars = next_chars
                    output_bytes = next_bytes
                    yield {'type': 'token', 'content': content}

            if time.monotonic() - started >= max_duration:
                yield limit_error('duration')
                return
            if not saw_done:
                logger.warning(
                    'AI provider stream ended without a terminal marker',
                    extra={'request_id': request_id},
                )
                yield {
                    'type': 'error',
                    'content': PUBLIC_PROVIDER_ERROR,
                    'code': 'AI_PROVIDER_STREAM_TRUNCATED',
                }
                return

            yield {
                'type': 'done',
                'model': self.model,
                'provider': self.provider,
                'tokens_used': total_tokens,
            }
        except requests.Timeout:
            if time.monotonic() - started >= max_duration:
                yield limit_error('duration')
                return
            raise
        finally:
            response.close()

    @staticmethod
    def _tool_budget_exceeded(count):
        return count > settings.AI_ASSISTANT_MAX_TOOL_CALLS_PER_REQUEST
    
    def chat(
        self,
        message,
        conversation_history=None,
        language='en',
        system_prompt=None,
        temperature=0.2,
        max_tokens=256,
        top_p=0.9,
    ):
        """
        Send a message to the AI and get a response.
        
        This is the main method used by the chat endpoint.
        
        Args:
            message: The user's message (string)
            conversation_history: Previous messages for context (list, optional)
            language: 'en' for English, 'tl' for Tagalog
            system_prompt: Optional custom system prompt override
            temperature: Sampling temperature
            max_tokens: Maximum output tokens (default 256 for concise responses)
            top_p: Nucleus sampling parameter
        
        Returns:
            dict with:
            - success: True/False
            - response: The AI's reply (if success)
            - error: Error message (if failed)
            - model: Which AI model was used
            - response_time_ms: How long it took
            - tokens_used: API usage count
        
        Example:
            result = groq.chat("Paano mag-apply ng loan?", language='tl')
            print(result['response'])  # AI reply in Tagalog
        """
        max_tokens = self._bounded_limits(max_tokens)
        policy_result = _policy_result(
            message, model=self.model, provider=self.provider
        )
        if policy_result:
            return policy_result
        controlled_result = _controlled_result(
            message,
            language=language,
            model=self.model,
            provider=self.provider,
        )
        if controlled_result:
            return controlled_result
        # Check if API key is configured
        if not self.api_key:
            return self._provider_failure()
        
        # Start timing the request
        start_time = time.time()
        
        # Build the messages array for the API
        # First message is always the system prompt (AI's instructions)
        active_system_prompt = system_prompt or SYSTEM_PROMPT
        messages = [{"role": "system", "content": active_system_prompt}]
        
        # Add previous conversation messages for context (last 6 for efficiency)
        if conversation_history:
            for hist in bounded_conversation_history(conversation_history):
                messages.append({
                    "role": hist.get('role', 'user'),
                    "content": hist.get('content', '')
                })
        
        # If user's language is Tagalog, tell the AI to respond in Tagalog
        if language == 'tl':
            message = f"[Please respond in Tagalog/Filipino] {message}"
        
        # Add the current user message
        messages.append({"role": "user", "content": message})
        
        # Send request to LLM API
        timeout = 120 if self.provider == 'ollama' else 180
        try:
            response = _session.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": top_p
                },
                timeout=timeout
            )
            
            # Check if request was successful
            if response.status_code == 200:
                result = response.json()
                elapsed_ms = int((time.time() - start_time) * 1000)
                
                # Extract the AI's response from the API result
                choice = result.get('choices', [{}])[0]
                usage = result.get('usage', {})
                
                provider_text, violations = validate_provider_response(
                    choice.get('message', {}).get('content', ''),
                    message=message,
                    language=language,
                )
                return {
                    'success': True,
                    'response': provider_text,
                    'model': self.model,
                    'provider': self.provider,
                    'response_time_ms': elapsed_ms,
                    'tokens_used': usage.get('total_tokens', 0),
                    'response_validation_violations': violations,
                }
            else:
                # API returned an error
                logger.error("AI provider returned HTTP %s", response.status_code)
                return self._provider_failure()
                
        except requests.Timeout as exc:
            return self._provider_failure(exc)
        except requests.RequestException as e:
            return self._provider_failure(e)
    
    def _execute_tools_parallel(
        self,
        tool_calls,
        customer_id,
        request_id=None,
        max_workers=4,
        tool_executor=None,
    ):
        """
        Execute multiple tool calls concurrently using ThreadPoolExecutor.
        Includes rate limiting and safety checks.
        
        Args:
            tool_calls: List of tool call objects from the LLM
            customer_id: Customer ID for scoping queries
            max_workers: Max concurrent threads (default 4)
        
        Returns:
            List of (tool_call_id, tool_name, result_json) tuples in original order
        """
        from ai_assistant.services.tools import execute_tool_result

        tool_executor_fn = tool_executor or execute_tool_result
        
        def run_tool(tool_call):
            func = tool_call.get('function', {})
            tool_name = func.get('name', '')
            tool_call_id = tool_call.get('id', '')
            try:
                tool_args = _parse_tool_arguments(
                    func.get('arguments', '{}'),
                    injected_executor=tool_executor is not None,
                )
            except TypeError:
                tool_args = (
                    dict(INVALID_TOOL_ARGUMENTS) if tool_executor is not None else {}
                )
            
            logger.info(
                "AI parallel tool call started",
                extra={'request_id': request_id, 'tool': tool_name},
            )
            
            result = tool_executor_fn(
                tool_name,
                tool_args,
                customer_id,
                request_id=request_id,
            )
            
            if result['success']:
                return (tool_call_id, tool_name, result['result'], True)
            elif result.get('rate_limited'):
                # Return rate limit error as tool result
                return (tool_call_id, tool_name, json.dumps({
                    "error": result['error'],
                    "rate_limited": True,
                    "retry_after_seconds": result.get('retry_after_seconds', 60)
                }), False)
            else:
                return (
                    tool_call_id,
                    tool_name,
                    json.dumps({"error": result['error']}),
                    False,
                )
        
        results = []
        # Use ThreadPoolExecutor for I/O-bound MongoDB queries
        with ThreadPoolExecutor(
            max_workers=min(max_workers, len(tool_calls))
        ) as thread_pool:
            # Submit all tasks and maintain order
            future_to_idx = {
                thread_pool.submit(run_tool, tool_call): index
                for index, tool_call in enumerate(tool_calls)
            }
            results = [None] * len(tool_calls)
            
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except NON_FATAL_EXCEPTIONS:
                    # Handle individual tool failure
                    tool_call = tool_calls[idx]
                    tool_name = tool_call.get('function', {}).get('name', 'unknown')
                    logger.error(
                        "AI parallel tool execution failed",
                        extra={'request_id': request_id, 'tool': tool_name},
                    )
                    results[idx] = (
                        tool_call.get('id', ''),
                        tool_name,
                        json.dumps({"error": "Failed to retrieve data"}),
                        False,
                    )
        
        logger.info(
            "AI parallel tools completed",
            extra={'request_id': request_id, 'tool_count': len(tool_calls)},
        )
        return results
    
    def generate(self, prompt):
        """
        Simple text generation without conversation history.
        
        Used for one-off generations like rejection feedback.
        
        Args:
            prompt: The text prompt
        
        Returns:
            The generated text (string) or empty string on error
        """
        result = self.chat(prompt)
        return result.get('response', '') if result.get('success') else ''

    def chat_with_tools(
        self,
        message,
        customer_id,
        conversation_history=None,
        language='en',
        system_prompt=None,
        tools=None,
        temperature=0.2,
        max_tokens=256,
        top_p=0.9,
        max_tool_rounds=3,
        request_id=None,
        tool_executor=None,
        officer_mode=False,
    ):
        """
        Send a message with function calling support.
        The LLM can request tool calls; we execute them and feed results back.

        Args:
            message: The user's message
            customer_id: Authenticated customer ID (for scoping tool queries)
            conversation_history: Previous messages for context
            language: 'en' or 'tl'
            system_prompt: Optional system prompt override
            tools: List of tool schemas (OpenAI format)
            temperature: Sampling temperature
            max_tokens: Max output tokens (default 256 for concise responses)
            top_p: Nucleus sampling
            max_tool_rounds: Max tool call iterations to prevent infinite loops

        Returns:
            dict with success, response, model, response_time_ms, tokens_used, tools_called
        """
        from ai_assistant.services.tools import execute_tool_result

        executor = tool_executor or execute_tool_result

        max_tokens, max_tool_rounds = self._bounded_limits(max_tokens, max_tool_rounds)
        if officer_mode:
            privacy_result = _officer_privacy_result(
                message,
                conversation_history=conversation_history,
                model=self.model,
                provider=self.provider,
                request_id=request_id,
            )
            if privacy_result:
                return privacy_result
            policy_result = _officer_policy_result(
                message,
                model=self.model,
                provider=self.provider,
                request_id=request_id,
            )
            if policy_result:
                return policy_result
        else:
            policy_result = _policy_result(
                message,
                model=self.model,
                provider=self.provider,
                request_id=request_id,
            )
            if policy_result:
                return policy_result
            controlled_result = _controlled_result(
                message,
                language=language,
                model=self.model,
                provider=self.provider,
                request_id=request_id,
            )
            if controlled_result:
                return controlled_result
        if not self.api_key:
            return self._provider_failure(request_id=request_id)

        start_time = time.time()
        total_tokens = 0
        tools_called = []

        active_system_prompt = system_prompt or SYSTEM_PROMPT
        messages = [{"role": "system", "content": active_system_prompt}]

        if conversation_history:
            for hist in bounded_conversation_history(conversation_history):
                messages.append({
                    "role": hist.get('role', 'user'),
                    "content": hist.get('content', '')
                })

        if language == 'tl':
            message = f"[Please respond in Tagalog/Filipino] {message}"

        messages.append({"role": "user", "content": message})

        for round_num in range(max_tool_rounds + 1):
            try:
                request_body = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": top_p,
                }

                if tools and round_num < max_tool_rounds:
                    request_body["tools"] = tools
                    request_body["tool_choice"] = "auto"

                timeout = 120 if self.provider == 'ollama' else 180
                response = _session.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=request_body,
                    timeout=timeout
                )

                if response.status_code != 200:
                    logger.error(
                        "AI provider returned HTTP %s",
                        response.status_code,
                        extra={'request_id': request_id},
                    )
                    return self._provider_failure(request_id=request_id)

                result = response.json()
                usage = result.get('usage', {})
                total_tokens += usage.get('total_tokens', 0)

                choice = result.get('choices', [{}])[0]
                assistant_message = choice.get('message', {})
                finish_reason = choice.get('finish_reason', '')

                tool_calls = assistant_message.get('tool_calls')
                if tool_calls and finish_reason == 'tool_calls':
                    if self._tool_budget_exceeded(len(tools_called) + len(tool_calls)):
                        logger.warning(
                            'AI tool-call budget exceeded',
                            extra={'request_id': request_id},
                        )
                        return {
                            'success': False,
                            'error': PUBLIC_PROVIDER_ERROR,
                            'code': 'AI_TOOL_BUDGET_EXCEEDED',
                        }
                    messages.append(assistant_message)

                    # Execute tools in parallel for better performance
                    if len(tool_calls) > 1:
                        # Multiple tools - run concurrently
                        tool_results = self._execute_tools_parallel(
                            tool_calls,
                            customer_id,
                            request_id=request_id,
                            tool_executor=tool_executor,
                        )
                        for tool_call_id, tool_name, tool_result, _success in tool_results:
                            tools_called.append(tool_name)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": tool_result,
                            })
                    else:
                        # Single tool - run directly (no thread overhead)
                        tool_call = tool_calls[0]
                        func = tool_call.get('function', {})
                        tool_name = func.get('name', '')
                        try:
                            tool_args = _parse_tool_arguments(
                                func.get('arguments', '{}'),
                                injected_executor=tool_executor is not None,
                            )
                        except TypeError:
                            tool_args = (
                                dict(INVALID_TOOL_ARGUMENTS)
                                if tool_executor is not None
                                else {}
                            )

                        logger.info(
                            "AI tool call started",
                            extra={'request_id': request_id, 'tool': tool_name},
                        )
                        execution = executor(
                            tool_name,
                            tool_args,
                            customer_id,
                            request_id=request_id,
                        )
                        if execution.get('success'):
                            tool_result = execution['result']
                        elif execution.get('rate_limited'):
                            tool_result = json.dumps({
                                'error': execution['error'],
                                'rate_limited': True,
                                'retry_after_seconds': execution.get(
                                    'retry_after_seconds', 60
                                ),
                            })
                        else:
                            tool_result = json.dumps({'error': execution['error']})
                        tools_called.append(tool_name)

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.get('id', ''),
                            "content": tool_result,
                        })

                    continue
                else:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    validator = (
                        validate_officer_response
                        if officer_mode
                        else validate_provider_response
                    )
                    provider_text, violations = validator(
                        assistant_message.get('content', ''),
                        message=message,
                        language=language,
                        tools_called=tools_called,
                    )
                    return {
                        'success': True,
                        'response': provider_text,
                        'model': self.model,
                        'provider': self.provider,
                        'response_time_ms': elapsed_ms,
                        'tokens_used': total_tokens,
                        'tools_called': tools_called,
                        'response_validation_violations': violations,
                    }

            except requests.Timeout as exc:
                return self._provider_failure(exc, request_id=request_id)
            except requests.RequestException as e:
                return self._provider_failure(e, request_id=request_id)
            except json.JSONDecodeError:
                return self._provider_failure(request_id=request_id)

        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            'success': False,
            'error': PUBLIC_PROVIDER_ERROR,
            'code': 'AI_TOOL_ROUND_LIMIT',
            'response_time_ms': elapsed_ms,
            'tools_called': tools_called,
        }

    def narrate_review_brief(
        self,
        review_brief,
        *,
        system_prompt,
        request_id=None,
    ):
        """Narrate one already-localized public brief without tool access."""
        try:
            validated_brief = validate_review_brief(review_brief)
        except InvalidReviewBrief:
            result = {
                "success": False,
                "error": PUBLIC_PROVIDER_ERROR,
                "code": "AI_OFFICER_REVIEW_BRIEF_INVALID",
            }
            if request_id:
                result["request_id"] = request_id
            return result

        if not self.api_key:
            return self._provider_failure(request_id=request_id)

        started = time.time()
        payload = json.dumps(
            {"review_brief": validated_brief},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            response = _session.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": payload},
                    ],
                    "temperature": 0,
                    "max_tokens": min(
                        512, int(settings.AI_ASSISTANT_MAX_OUTPUT_TOKENS)
                    ),
                    "top_p": 1,
                },
                timeout=120 if self.provider == "ollama" else 180,
            )
            if response.status_code != 200:
                return self._provider_failure(request_id=request_id)
            provider_payload = response.json()
            choice = provider_payload.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
            narration = validate_narration(content, validated_brief)
            if narration is None:
                result = {
                    "success": False,
                    "error": PUBLIC_PROVIDER_ERROR,
                    "code": "AI_OFFICER_NARRATION_INVALID",
                }
                if request_id:
                    result["request_id"] = request_id
                return result
            usage = provider_payload.get("usage", {})
            return {
                "success": True,
                "response": narration,
                "model": self.model,
                "provider": self.provider,
                "response_time_ms": int((time.time() - started) * 1000),
                "tokens_used": usage.get("total_tokens", 0),
            }
        except requests.Timeout as exc:
            return self._provider_failure(exc, request_id=request_id)
        except requests.RequestException as exc:
            return self._provider_failure(exc, request_id=request_id)
        except (json.JSONDecodeError, TypeError, AttributeError, IndexError):
            return self._provider_failure(request_id=request_id)

    def chat_stream(
        self,
        message,
        conversation_history=None,
        language='en',
        system_prompt=None,
        temperature=0.2,
        max_tokens=256,
        top_p=0.9,
    ):
        """
        Stream chat response token by token.
        
        Yields chunks as they arrive from the LLM.
        Each chunk is a dict with 'type' and 'content' keys.
        
        Yields:
            {'type': 'token', 'content': '...'} - A token chunk
            {'type': 'done', 'model': '...', 'tokens_used': N} - Stream complete
            {'type': 'error', 'content': '...'} - Error occurred
        """
        max_tokens = self._bounded_limits(max_tokens)
        policy_result = _policy_result(
            message, model=self.model, provider=self.provider
        )
        if policy_result:
            yield {'type': 'token', 'content': policy_result['response']}
            yield {
                'type': 'done',
                'model': self.model,
                'provider': self.provider,
                'tokens_used': 0,
                'policy_intercepted': True,
            }
            return
        controlled_result = _controlled_result(
            message,
            language=language,
            model=self.model,
            provider=self.provider,
        )
        if controlled_result:
            yield {'type': 'token', 'content': controlled_result['response']}
            yield {
                'type': 'done',
                'model': self.model,
                'provider': self.provider,
                'tokens_used': 0,
                'controlled_response': True,
            }
            return
        if not self.api_key:
            yield {'type': 'error', 'content': PUBLIC_PROVIDER_ERROR, 'code': 'AI_PROVIDER_ERROR'}
            return

        active_system_prompt = system_prompt or SYSTEM_PROMPT
        messages = [{"role": "system", "content": active_system_prompt}]

        if conversation_history:
            for hist in bounded_conversation_history(conversation_history):
                messages.append({
                    "role": hist.get('role', 'user'),
                    "content": hist.get('content', '')
                })

        if language == 'tl':
            message = f"[Please respond in Tagalog/Filipino] {message}"

        messages.append({"role": "user", "content": message})

        try:
            response = _session.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": top_p,
                    "stream": True,
                },
                timeout=120,
                stream=True,
            )

            if response.status_code != 200:
                logger.error("AI provider stream returned HTTP %s", response.status_code)
                response.close()
                yield {'type': 'error', 'content': PUBLIC_PROVIDER_ERROR, 'code': 'AI_PROVIDER_ERROR'}
                return

            yield from self._provider_stream_chunks(response)

        except requests.Timeout:
            yield {'type': 'error', 'content': PUBLIC_PROVIDER_ERROR, 'code': 'AI_PROVIDER_TIMEOUT'}
        except requests.RequestException as e:
            failure = self._provider_failure(e)
            yield {'type': 'error', 'content': failure['error'], 'code': failure['code']}

    def chat_with_tools_stream(
        self,
        message,
        customer_id,
        conversation_history=None,
        language='en',
        system_prompt=None,
        tools=None,
        temperature=0.2,
        max_tokens=256,
        top_p=0.9,
        max_tool_rounds=3,
        request_id=None,
        tool_executor=None,
        officer_mode=False,
    ):
        """
        Stream chat with function calling support.
        
        First executes any tool calls (non-streaming), then streams the final response.
        This hybrid approach ensures tools complete before streaming the answer.
        
        Yields:
            {'type': 'tool_call', 'name': '...'} - Tool being called
            {'type': 'tool_result', 'name': '...', 'success': bool} - Tool completed
            {'type': 'token', 'content': '...'} - Response token
            {'type': 'done', ...} - Stream complete
            {'type': 'error', 'content': '...'} - Error
        """
        from ai_assistant.services.tools import execute_tool_result

        executor = tool_executor or execute_tool_result

        max_tokens, max_tool_rounds = self._bounded_limits(max_tokens, max_tool_rounds)
        if officer_mode:
            privacy_result = _officer_privacy_result(
                message,
                conversation_history=conversation_history,
                model=self.model,
                provider=self.provider,
                request_id=request_id,
            )
            if privacy_result:
                yield {
                    'type': 'done',
                    'model': self.model,
                    'provider': self.provider,
                    'tokens_used': 0,
                    'tools_called': [],
                    'policy_intercepted': True,
                    'privacy_blocked': True,
                    'response': privacy_result['response'],
                }
                return
            policy_result = _officer_policy_result(
                message,
                model=self.model,
                provider=self.provider,
                request_id=request_id,
            )
            if policy_result:
                yield {
                    'type': 'done',
                    'model': self.model,
                    'provider': self.provider,
                    'tokens_used': 0,
                    'tools_called': [],
                    'policy_intercepted': True,
                    'response': policy_result['response'],
                }
                return
        else:
            policy_result = _policy_result(
                message,
                model=self.model,
                provider=self.provider,
                request_id=request_id,
            )
            if policy_result:
                yield {'type': 'token', 'content': policy_result['response']}
                yield {
                    'type': 'done',
                    'model': self.model,
                    'provider': self.provider,
                    'tokens_used': 0,
                    'tools_called': [],
                    'policy_intercepted': True,
                }
                return
            controlled_result = _controlled_result(
                message,
                language=language,
                model=self.model,
                provider=self.provider,
                request_id=request_id,
            )
            if controlled_result:
                yield {'type': 'token', 'content': controlled_result['response']}
                yield {
                    'type': 'done',
                    'model': self.model,
                    'provider': self.provider,
                    'tokens_used': 0,
                    'tools_called': [],
                    'controlled_response': True,
                }
                return
        if not self.api_key:
            yield {'type': 'error', 'content': PUBLIC_PROVIDER_ERROR, 'code': 'AI_PROVIDER_ERROR'}
            return

        tools_called = []
        active_system_prompt = system_prompt or SYSTEM_PROMPT
        messages = [{"role": "system", "content": active_system_prompt}]

        if conversation_history:
            for hist in bounded_conversation_history(conversation_history):
                messages.append({
                    "role": hist.get('role', 'user'),
                    "content": hist.get('content', '')
                })

        if language == 'tl':
            message = f"[Please respond in Tagalog/Filipino] {message}"

        messages.append({"role": "user", "content": message})

        # Phase 1: Execute tool calls (non-streaming)
        for round_num in range(max_tool_rounds):
            try:
                request_body = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": top_p,
                }

                if tools:
                    request_body["tools"] = tools
                    request_body["tool_choice"] = "auto"

                timeout = 120
                response = _session.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=request_body,
                    timeout=timeout,
                )

                if response.status_code != 200:
                    logger.error(
                        "AI provider returned HTTP %s",
                        response.status_code,
                        extra={'request_id': request_id},
                    )
                    yield {'type': 'error', 'content': PUBLIC_PROVIDER_ERROR, 'code': 'AI_PROVIDER_ERROR'}
                    return

                result = response.json()
                choice = result.get('choices', [{}])[0]
                assistant_message = choice.get('message', {})
                finish_reason = choice.get('finish_reason', '')
                tool_calls = assistant_message.get('tool_calls')

                if tool_calls and finish_reason == 'tool_calls':
                    if self._tool_budget_exceeded(len(tools_called) + len(tool_calls)):
                        logger.warning(
                            'AI streaming tool-call budget exceeded',
                            extra={'request_id': request_id},
                        )
                        yield {
                            'type': 'error',
                            'content': PUBLIC_PROVIDER_ERROR,
                            'code': 'AI_TOOL_BUDGET_EXCEEDED',
                        }
                        return
                    messages.append(assistant_message)

                    # Execute tools in parallel for better performance
                    if len(tool_calls) > 1:
                        # Yield all tool_call events first
                        for tool_call in tool_calls:
                            func = tool_call.get('function', {})
                            tool_name = func.get('name', '')
                            yield {'type': 'tool_call', 'name': tool_name}
                        
                        # Execute all tools concurrently
                        tool_results = self._execute_tools_parallel(
                            tool_calls,
                            customer_id,
                            request_id=request_id,
                            tool_executor=tool_executor,
                        )
                        
                        # Yield results and add to messages
                        for tool_call_id, tool_name, tool_result, success in tool_results:
                            tools_called.append(tool_name)
                            yield {
                                'type': 'tool_result',
                                'name': tool_name,
                                'success': success,
                            }
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": tool_result,
                            })
                    else:
                        # Single tool - run directly
                        tool_call = tool_calls[0]
                        func = tool_call.get('function', {})
                        tool_name = func.get('name', '')
                        try:
                            tool_args = _parse_tool_arguments(
                                func.get('arguments', '{}'),
                                injected_executor=tool_executor is not None,
                            )
                        except TypeError:
                            tool_args = (
                                dict(INVALID_TOOL_ARGUMENTS)
                                if tool_executor is not None
                                else {}
                            )

                        yield {'type': 'tool_call', 'name': tool_name}
                        
                        execution = executor(
                            tool_name,
                            tool_args,
                            customer_id,
                            request_id=request_id,
                        )
                        if execution.get('success'):
                            tool_result = execution['result']
                        elif execution.get('rate_limited'):
                            tool_result = json.dumps({
                                'error': execution['error'],
                                'rate_limited': True,
                                'retry_after_seconds': execution.get(
                                    'retry_after_seconds', 60
                                ),
                            })
                        else:
                            tool_result = json.dumps({'error': execution['error']})
                        tools_called.append(tool_name)

                        yield {
                            'type': 'tool_result',
                            'name': tool_name,
                            'success': bool(execution.get('success')),
                        }

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.get('id', ''),
                            "content": tool_result,
                        })
                    continue
                else:
                    # No more tool calls, break to streaming phase
                    break

            except requests.Timeout:
                yield {'type': 'error', 'content': PUBLIC_PROVIDER_ERROR, 'code': 'AI_PROVIDER_TIMEOUT'}
                return
            except requests.RequestException as exc:
                failure = self._provider_failure(exc, request_id=request_id)
                yield {'type': 'error', 'content': failure['error'], 'code': failure['code']}
                return

        # Phase 2: Stream the final response
        try:
            response = _session.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": top_p,
                    "stream": True,
                },
                timeout=120,
                stream=True,
            )

            if response.status_code != 200:
                response.close()
                yield {'type': 'error', 'content': PUBLIC_PROVIDER_ERROR, 'code': 'AI_PROVIDER_ERROR'}
                return

            if officer_mode:
                buffered_parts = []
                buffered_chars = 0
                buffer_limit = _officer_stream_buffer_limit()
                for chunk in self._provider_stream_chunks(
                    response,
                    request_id=request_id,
                ):
                    chunk_type = chunk.get('type')
                    if chunk_type == 'token':
                        content = str(chunk.get('content') or '')
                        buffered_chars += len(content)
                        if buffered_chars > buffer_limit:
                            yield {
                                'type': 'error',
                                'content': PUBLIC_PROVIDER_ERROR,
                                'code': 'AI_PROVIDER_STREAM_OUTPUT_LIMIT',
                            }
                            return
                        buffered_parts.append(content)
                        continue
                    if chunk_type == 'done':
                        safe_response, violations = validate_officer_response(
                            ''.join(buffered_parts),
                            message=message,
                            language=language,
                            tools_called=tools_called,
                        )
                        chunk['tools_called'] = tools_called
                        chunk['response_validation_violations'] = violations
                        chunk['response'] = safe_response
                        yield chunk
                        continue
                    yield chunk
            else:
                for chunk in self._provider_stream_chunks(
                    response,
                    request_id=request_id,
                ):
                    if chunk.get('type') == 'done':
                        chunk['tools_called'] = tools_called
                    yield chunk

        except requests.Timeout:
            yield {'type': 'error', 'content': PUBLIC_PROVIDER_ERROR, 'code': 'AI_PROVIDER_TIMEOUT'}
        except requests.RequestException as exc:
            failure = self._provider_failure(exc, request_id=request_id)
            yield {'type': 'error', 'content': failure['error'], 'code': failure['code']}


# =============================================================================
# FACTORY FUNCTION - Gets the LLM service instance
# =============================================================================

def get_llm_service(use_case='default', model=None):
    """
    Factory function to get the LLM service.
    
    Reads LLM_PROVIDER from Django settings at call time.
    """
    config = _get_config()
    provider = config['provider']

    if provider == 'ollama':
        selected_model = model or config['ollama_model']
    elif model:
        selected_model = model
    else:
        normalized_use_case = str(use_case or 'default').strip().lower()
        use_case_key = MODEL_USE_CASE_KEYS.get(normalized_use_case, 'groq_model')
        selected_model = config[use_case_key]

    return GroqService(model=selected_model, provider=provider)
