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
import os
import json
import requests
import logging
from django.conf import settings
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

logger = logging.getLogger('ai_assistant')


# =============================================================================
# CONFIGURATION - Read lazily from Django settings at call time
# =============================================================================

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


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
    }


MODEL_USE_CASE_KEYS = {
    'default': 'groq_model',
    'chat': 'groq_chat_model',
    'qualification': 'groq_qualification_model',
}


# =============================================================================
# SYSTEM PROMPT - This tells the AI how to behave
# =============================================================================
# This is the "personality" and rules for the AI assistant.
# The AI reads this before every conversation.

SYSTEM_PROMPT = """You are a helpful financial assistant for MSME Pathways, a blockchain-backed microfinance app for Filipino small business owners.

=== PLATFORM ===
Mobile app for microloans. All loan events (application, approval, disbursement, payments) are recorded on Ethereum blockchain for transparency.

=== LOAN PROCESS ===
1. Complete profile (personal + business info)
2. Upload documents (government ID required; some products need proof of address, business permit, or photo)
3. Check pre-qualification (AI scores 0-100 with risk category)
4. Submit application (choose product, amount, term, purpose, disbursement method)
5. Officer review (may request additional documents)
6. Approval/rejection (feedback provided if rejected)
7. Disbursement via your preferred method
8. Monthly repayments per schedule

=== LOAN PRODUCTS ===
- Amounts: ₱5,000–₱500,000 | Terms: 3–24 months | Flat interest: ~1.5%/month
- Requirements vary by product (min business age, min income)

=== PAYMENT METHODS ===
AUTOMATIC (recorded instantly): GCash, Bank Transfer, ETH Wallet
MANUAL (officer records): Cash, Check at partner locations

=== REPAYMENT ===
- Equal monthly installments with due dates
- Statuses: pending, paid, partial, overdue
- Partial payments supported
- View in app: Track → select loan → Schedule/Payments

=== APP NAVIGATION ===
- Apply: Dashboard → "Apply" | Track status: "Track" → "Applications"
- Make payment: Track → Repayment → "Make Payment"
- Documents: Apply → "Documents" | Profile: Menu → "Profile"

=== GUIDELINES ===
- Never give specific financial advice or guarantee approval
- Never ask for passwords, PINs, or private keys
- Be warm and supportive; explain simply without jargon
- Respond in the user's language (English or Tagalog)
- Keep responses concise (2-3 short paragraphs max)
- Use tools for real-time data; don't guess
- Always include specific numbers from tool results
- For installments: report as "X of Y paid"
- For balance: include peso amount AND progress
- List specific blockers/missing items, not vague summaries
"""


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
    
    def is_available(self):
        """Check if the LLM service is ready to use."""
        if self.provider == 'ollama':
            try:
                resp = requests.get(f"{self._ollama_base_url}/api/tags", timeout=3)
                return resp.status_code == 200
            except Exception:
                return False
        return bool(self.api_key)
    
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
        # Check if API key is configured
        if not self.api_key:
            return {
                'success': False, 
                'error': "Groq API key not configured. Add GROQ_API_KEY to .env file."
            }
        
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
        timeout = 120 if self.provider == 'ollama' else 30
        try:
            response = requests.post(
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
                error_msg = response.json().get('error', {}).get('message', response.text)
                logger.error(f"Groq error: {response.status_code} - {error_msg}")
                return {'success': False, 'error': f"Groq error: {error_msg}"}
                
        except requests.Timeout:
            # Request took too long
            return {'success': False, 'error': "Request timed out. Please try again."}
        except requests.RequestException as e:
            # Network or connection error
            logger.error(f"Groq error: {str(e)}")
            return {'success': False, 'error': "Could not connect to Groq API."}
    
    def _execute_tools_parallel(self, tool_calls, customer_id, max_workers=4):
        """
        Execute multiple tool calls concurrently using ThreadPoolExecutor.
        
        Args:
            tool_calls: List of tool call objects from the LLM
            customer_id: Customer ID for scoping queries
            max_workers: Max concurrent threads (default 4)
        
        Returns:
            List of (tool_call_id, tool_name, result_json) tuples in original order
        """
        from ai_assistant.services.tools import execute_tool
        
        def run_tool(tool_call):
            func = tool_call.get('function', {})
            tool_name = func.get('name', '')
            tool_call_id = tool_call.get('id', '')
            try:
                tool_args = json.loads(func.get('arguments', '{}'))
            except json.JSONDecodeError:
                tool_args = {}
            
            logger.info(f"[Parallel] Tool call: {tool_name}({tool_args}) for customer {customer_id}")
            result = execute_tool(tool_name, tool_args, customer_id)
            return (tool_call_id, tool_name, result)
        
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
                except Exception as e:
                    # Handle individual tool failure
                    tool_call = tool_calls[idx]
                    tool_name = tool_call.get('function', {}).get('name', 'unknown')
                    logger.error(f"Parallel tool error ({tool_name}): {e}")
                    results[idx] = (
                        tool_call.get('id', ''),
                        tool_name,
                        json.dumps({"error": "Failed to retrieve data"})
                    )
        
        logger.info(f"[Parallel] Executed {len(tool_calls)} tools concurrently")
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
        from ai_assistant.services.tools import execute_tool

        if not self.api_key:
            return {
                'success': False,
                'error': "Groq API key not configured. Add GROQ_API_KEY to .env file."
            }

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

                timeout = 120 if self.provider == 'ollama' else 30
                response = requests.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=request_body,
                    timeout=timeout
                )

                if response.status_code != 200:
                    error_msg = response.json().get('error', {}).get('message', response.text)
                    logger.error(f"LLM error ({self.provider}): {response.status_code} - {error_msg}")
                    return {'success': False, 'error': f"LLM error: {error_msg}"}

                result = response.json()
                usage = result.get('usage', {})
                total_tokens += usage.get('total_tokens', 0)

                choice = result.get('choices', [{}])[0]
                assistant_message = choice.get('message', {})
                finish_reason = choice.get('finish_reason', '')

                tool_calls = assistant_message.get('tool_calls')
                if tool_calls and finish_reason == 'tool_calls':
                    messages.append(assistant_message)

                    # Execute tools in parallel for better performance
                    if len(tool_calls) > 1:
                        # Multiple tools - run concurrently
                        tool_results = self._execute_tools_parallel(tool_calls, customer_id)
                        for tool_call_id, tool_name, tool_result in tool_results:
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

                        logger.info(f"Tool call: {tool_name}({tool_args}) for customer {customer_id}")
                        tool_result = execute_tool(tool_name, tool_args, customer_id)
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
                        'provider': 'groq',
                        'response_time_ms': elapsed_ms,
                        'tokens_used': total_tokens,
                        'tools_called': tools_called,
                    }

            except requests.Timeout:
                return {'success': False, 'error': "Request timed out. Please try again."}
            except requests.RequestException as e:
                logger.error(f"Groq error: {str(e)}")
                return {'success': False, 'error': "Could not connect to Groq API."}
            except json.JSONDecodeError:
                return {'success': False, 'error': "Invalid response from AI service."}

        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            'success': False,
            'error': "Too many tool call rounds. Please try a simpler question.",
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
        if not self.api_key:
            yield {'type': 'error', 'content': "API key not configured"}
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
            response = requests.post(
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
                error_msg = response.text
                try:
                    error_msg = response.json().get('error', {}).get('message', response.text)
                except Exception:
                    pass
                yield {'type': 'error', 'content': f"LLM error: {error_msg}"}
                return

            total_tokens = 0
            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        if data_str.strip() == '[DONE]':
                            break
                        try:
                            data = json.loads(data_str)
                            choice = data.get('choices', [{}])[0]
                            delta = choice.get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                yield {'type': 'token', 'content': content}
                            
                            usage = data.get('usage')
                            if usage:
                                total_tokens = usage.get('total_tokens', 0)
                        except json.JSONDecodeError:
                            continue

            yield {
                'type': 'done',
                'model': self.model,
                'provider': self.provider,
                'tokens_used': total_tokens,
            }

        except requests.Timeout:
            yield {'type': 'error', 'content': "Request timed out"}
        except requests.RequestException as e:
            logger.error(f"Stream error: {str(e)}")
            yield {'type': 'error', 'content': "Connection error"}

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
        from ai_assistant.services.tools import execute_tool

        if not self.api_key:
            yield {'type': 'error', 'content': "API key not configured"}
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

                timeout = 120 if self.provider == 'ollama' else 30
                response = requests.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=request_body,
                    timeout=timeout,
                )

                if response.status_code != 200:
                    error_msg = response.json().get('error', {}).get('message', response.text)
                    yield {'type': 'error', 'content': f"LLM error: {error_msg}"}
                    return

                result = response.json()
                choice = result.get('choices', [{}])[0]
                assistant_message = choice.get('message', {})
                finish_reason = choice.get('finish_reason', '')
                tool_calls = assistant_message.get('tool_calls')

                if tool_calls and finish_reason == 'tool_calls':
                    messages.append(assistant_message)

                    # Execute tools in parallel for better performance
                    if len(tool_calls) > 1:
                        # Yield all tool_call events first
                        for tool_call in tool_calls:
                            func = tool_call.get('function', {})
                            tool_name = func.get('name', '')
                            yield {'type': 'tool_call', 'name': tool_name}
                        
                        # Execute all tools concurrently
                        tool_results = self._execute_tools_parallel(tool_calls, customer_id)
                        
                        # Yield results and add to messages
                        for tool_call_id, tool_name, tool_result in tool_results:
                            tools_called.append(tool_name)
                            yield {'type': 'tool_result', 'name': tool_name, 'success': True}
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
                        
                        tool_result = execute_tool(tool_name, tool_args, customer_id)
                        tools_called.append(tool_name)

                        yield {'type': 'tool_result', 'name': tool_name, 'success': True}

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
                yield {'type': 'error', 'content': "Request timed out"}
                return
            except requests.RequestException as e:
                yield {'type': 'error', 'content': "Connection error"}
                return

        # Phase 2: Stream the final response
        try:
            response = requests.post(
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
                yield {'type': 'error', 'content': "Failed to stream response"}
                return

            total_tokens = 0
            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        if data_str.strip() == '[DONE]':
                            break
                        try:
                            data = json.loads(data_str)
                            choice = data.get('choices', [{}])[0]
                            delta = choice.get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                yield {'type': 'token', 'content': content}
                            
                            usage = data.get('usage')
                            if usage:
                                total_tokens = usage.get('total_tokens', 0)
                        except json.JSONDecodeError:
                            continue

            yield {
                'type': 'done',
                'model': self.model,
                'provider': self.provider,
                'tokens_used': total_tokens,
                'tools_called': tools_called,
            }

        except requests.Timeout:
            yield {'type': 'error', 'content': "Stream timed out"}
        except requests.RequestException as e:
            yield {'type': 'error', 'content': "Stream connection error"}


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
