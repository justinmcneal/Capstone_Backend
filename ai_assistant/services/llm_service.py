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
)
from ai_assistant.services.provider_boundary import (
    ProviderCircuitOpen,
    ProviderConcurrencyExceeded,
    provider_session,
)

logger = logging.getLogger('ai_assistant')


# =============================================================================
# CONFIGURATION - Read lazily from Django settings at call time
# =============================================================================

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

_session = provider_session
PUBLIC_PROVIDER_ERROR = "AI service is temporarily unavailable. Please try again later."

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
        try:
            for line in response.iter_lines():
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
                    yield {'type': 'token', 'content': str(content)}

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
        temperature=0.7,
        max_tokens=512,
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
            max_tokens: Maximum output tokens (default 512 for concise responses)
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
            for hist in conversation_history[-6:]:
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
                
                return {
                    'success': True,
                    'response': choice.get('message', {}).get('content', ''),
                    'model': self.model,
                    'provider': self.provider,
                    'response_time_ms': elapsed_ms,
                    'tokens_used': usage.get('total_tokens', 0)
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
        from ai_assistant.services.tool_safety import safe_execute_tool
        
        def run_tool(tool_call):
            func = tool_call.get('function', {})
            tool_name = func.get('name', '')
            tool_call_id = tool_call.get('id', '')
            try:
                tool_args = json.loads(func.get('arguments', '{}'))
            except json.JSONDecodeError:
                tool_args = {}
            
            logger.info(
                "AI parallel tool call started",
                extra={'request_id': request_id, 'tool': tool_name},
            )
            
            # Use safe executor with rate limiting and validation
            result = safe_execute_tool(
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
        with ThreadPoolExecutor(max_workers=min(max_workers, len(tool_calls))) as executor:
            # Submit all tasks and maintain order
            future_to_idx = {executor.submit(run_tool, tc): idx for idx, tc in enumerate(tool_calls)}
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
        temperature=0.7,
        max_tokens=512,
        top_p=0.9,
        max_tool_rounds=3,
        request_id=None,
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
            max_tokens: Max output tokens (default 512 for concise responses)
            top_p: Nucleus sampling
            max_tool_rounds: Max tool call iterations to prevent infinite loops

        Returns:
            dict with success, response, model, response_time_ms, tokens_used, tools_called
        """
        from ai_assistant.services.tools import execute_tool_result

        max_tokens, max_tool_rounds = self._bounded_limits(max_tokens, max_tool_rounds)
        if not self.api_key:
            return self._provider_failure(request_id=request_id)

        start_time = time.time()
        total_tokens = 0
        tools_called = []

        active_system_prompt = system_prompt or SYSTEM_PROMPT
        messages = [{"role": "system", "content": active_system_prompt}]

        if conversation_history:
            for hist in conversation_history[-6:]:
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
                            tool_args = json.loads(func.get('arguments', '{}'))
                        except json.JSONDecodeError:
                            tool_args = {}

                        logger.info(
                            "AI tool call started",
                            extra={'request_id': request_id, 'tool': tool_name},
                        )
                        execution = execute_tool_result(
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
                    return {
                        'success': True,
                        'response': assistant_message.get('content', ''),
                        'model': self.model,
                        'provider': self.provider,
                        'response_time_ms': elapsed_ms,
                        'tokens_used': total_tokens,
                        'tools_called': tools_called,
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

    def chat_stream(
        self,
        message,
        conversation_history=None,
        language='en',
        system_prompt=None,
        temperature=0.7,
        max_tokens=512,
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
        if not self.api_key:
            yield {'type': 'error', 'content': PUBLIC_PROVIDER_ERROR, 'code': 'AI_PROVIDER_ERROR'}
            return

        active_system_prompt = system_prompt or SYSTEM_PROMPT
        messages = [{"role": "system", "content": active_system_prompt}]

        if conversation_history:
            for hist in conversation_history[-6:]:
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
        temperature=0.7,
        max_tokens=512,
        top_p=0.9,
        max_tool_rounds=3,
        request_id=None,
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

        max_tokens, max_tool_rounds = self._bounded_limits(max_tokens, max_tool_rounds)
        if not self.api_key:
            yield {'type': 'error', 'content': PUBLIC_PROVIDER_ERROR, 'code': 'AI_PROVIDER_ERROR'}
            return

        tools_called = []
        active_system_prompt = system_prompt or SYSTEM_PROMPT
        messages = [{"role": "system", "content": active_system_prompt}]

        if conversation_history:
            for hist in conversation_history[-6:]:
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
                            tool_args = json.loads(func.get('arguments', '{}'))
                        except json.JSONDecodeError:
                            tool_args = {}

                        yield {'type': 'tool_call', 'name': tool_name}
                        
                        execution = execute_tool_result(
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
