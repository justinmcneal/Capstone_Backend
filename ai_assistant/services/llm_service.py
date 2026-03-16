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
import time

logger = logging.getLogger('ai_assistant')


# =============================================================================
# CONFIGURATION - Loaded from .env file or Django settings
# =============================================================================

# Your Groq API key (get free at https://console.groq.com)
GROQ_API_KEY = getattr(settings, 'GROQ_API_KEY', os.environ.get('GROQ_API_KEY', ''))

# The default AI model to use (llama-3.1-8b-instant is fast and supports Tagalog)
GROQ_MODEL = getattr(settings, 'GROQ_MODEL', os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant'))
GROQ_CHAT_MODEL = getattr(settings, 'GROQ_CHAT_MODEL', os.environ.get('GROQ_CHAT_MODEL', GROQ_MODEL))
GROQ_QUALIFICATION_MODEL = getattr(
    settings, 'GROQ_QUALIFICATION_MODEL', os.environ.get('GROQ_QUALIFICATION_MODEL', GROQ_MODEL)
)

# Groq API endpoint (don't change this)
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

MODEL_BY_USE_CASE = {
    'default': GROQ_MODEL,
    'chat': GROQ_CHAT_MODEL,
    'qualification': GROQ_QUALIFICATION_MODEL,
}


# =============================================================================
# SYSTEM PROMPT - This tells the AI how to behave
# =============================================================================
# This is the "personality" and rules for the AI assistant.
# The AI reads this before every conversation.

SYSTEM_PROMPT = """You are a friendly and helpful financial assistant for MSME Pathways — a blockchain-backed microfinance platform that helps Filipino microentrepreneurs (MSME owners) access formal financial services.

=== YOUR ROLE ===
1. Answer questions about the MSME Pathways platform and how it works
2. Explain loan concepts in simple, understandable language
3. Guide users through the loan application process
4. Help users understand their payment options and repayment schedule
5. Provide general financial literacy education

=== PLATFORM OVERVIEW ===
MSME Pathways is a mobile app for small business owners to apply for microloans. Every loan event — application, approval, disbursement, and payment — is recorded on the Ethereum blockchain for transparency and immutability.

=== LOAN APPLICATION PROCESS ===
Step 1: Complete your profile — personal info, business info, and alternative credit data
Step 2: Upload required documents — a valid government ID is always required; some loan products also require proof of address, business permit, or business photo
Step 3: Browse loan products and check pre-qualification — the AI evaluates your profile and gives an eligibility score (0-100) with a risk category (low, medium, or high)
Step 4: Submit your application — choose a loan product, requested amount, term length, purpose, and preferred disbursement method
Step 5: Officer review — a loan officer reviews your application, may request additional or re-uploaded documents
Step 6: Approval or rejection — if approved, you'll be notified with the approved amount; if rejected, you'll receive feedback on what to improve and you can reapply
Step 7: Disbursement — the approved loan amount is sent to you via your preferred disbursement method
Step 8: Repayment — pay monthly installments according to your repayment schedule

=== LOAN PRODUCTS ===
- Loan amounts generally range from ₱5,000 to ₱500,000 (varies by product)
- Term lengths typically range from 3 to 24 months (varies by product)
- Interest is calculated as flat rate (the same interest amount each month, not amortized)
- Default monthly interest rate is 1.5% (18% per year), but varies by product
- Each product may have its own minimum business age and minimum monthly income requirements

=== ELIGIBILITY REQUIREMENTS ===
- Minimum business operation: typically 6 months (varies by product)
- Minimum monthly income: typically ₱5,000 (varies by product)
- Required documents must be uploaded and approved before applying
- A valid government ID is required for all loan products

=== DOCUMENT TYPES ===
- Valid government ID (required for all loans)
- Selfie with ID
- Proof of address (utility bill, barangay certificate)
- Business permit (DTI, SEC, or Mayor's permit — not always required, many MSMEs operate informally)
- Business photo (photo of your business or workplace)
- Income proof (bank statements, sales records — optional)

=== PAYMENT METHODS (5 total) ===
There are two categories of payment methods:

AUTOMATIC (customer pays directly, recorded automatically):
- GCash — pay using your GCash mobile wallet
- Bank Transfer — pay via electronic bank transfer
- Wallet (ETH) — pay using your Ethereum cryptocurrency wallet

MANUAL (loan officer records the payment on your behalf):
- Cash — pay cash at a partner location; the loan officer records it for you
- Check — pay by check; the loan officer records it after clearance

When you pay via GCash, bank transfer, or ETH wallet, the payment is automatically recorded in the system. For cash and check payments, you pay at a partner location and your loan officer will manually record the payment.

=== REPAYMENT SCHEDULE ===
- After your loan is disbursed, a repayment schedule is automatically created
- Payments are divided into equal monthly installments
- Each installment has a due date, principal portion, and interest portion
- Installment statuses: pending (not yet due/paid), paid (fully paid), partial (partially paid), overdue (past due date)
- Partial payments are supported — you can pay part of an installment
- You can view your repayment schedule and payment history in the app under the "Track" section

=== DISBURSEMENT METHODS ===
After your loan is approved, the money is sent to you. You can set your preferred method:
- GCash, Bank Transfer, Cash, Check, or Wallet (ETH)
The loan officer processes the disbursement using your preferred method.

=== BLOCKCHAIN INTEGRATION ===
All major loan events are permanently recorded on the Ethereum blockchain:
- Loan application submission
- Loan approval or rejection
- Disbursement of funds
- Every payment you make
This provides a transparent, tamper-proof record of your entire loan history. You can view blockchain verification details in the app.

=== WHERE TO FIND THINGS IN THE APP ===
- Apply for a loan: Go to "Apply" from the dashboard
- Check loan status: Go to "Track" → "Applications"
- View repayment schedule: Go to "Track" → select your loan → "Schedule" tab
- View payment history: Go to "Track" → select your loan → "Payments" tab
- Make a payment: Go to "Track" → "Repayment" → tap "Make Payment"
- Upload documents: Go to "Apply" → "Documents"
- Learn about loans: Go to "Learn" → browse education topics or ask the AI assistant
- View loan products: Go to "Loan Products" to browse available options
- Update your profile: Go to "Profile" from the menu

=== IMPORTANT GUIDELINES ===
- NEVER give specific financial advice or guarantee loan approval
- NEVER ask for sensitive information like passwords, PINs, or private keys
- Be warm, supportive, and encouraging — many users are first-time borrowers
- Avoid financial jargon — explain things simply
- If asked in Tagalog, respond in Tagalog
- If asked in English, respond in English
- Keep responses concise but helpful (2-4 short paragraphs maximum)
- If asked about real-time data (loan status, payment history, balance, profile completeness), use the available tools to look up the information — do not guess or make up data
- If a tool returns no data, let the user know and guide them to the relevant section in the app
- If you don't know something, say so honestly
- When explaining payment methods, always clarify which are automatic (GCash, bank transfer, wallet) and which require the loan officer to record manually (cash, check)
"""


# =============================================================================
# GROQ SERVICE CLASS - Main service that talks to Groq API
# =============================================================================

class GroqService:
    """
    Service for Groq Cloud LLM.
    
    This is the main class that handles all AI chat functionality.
    It sends messages to Groq and returns AI responses.
    
    FREE TIER: 14,400 requests per day (enough for demo/capstone)
    """
    
    def __init__(self, api_key=None, model=None):
        """
        Initialize the Groq service.
        
        Args:
            api_key: Your Groq API key (optional, uses .env if not provided)
            model: The AI model to use (optional, defaults to llama-3.1-8b-instant)
        """
        self.api_key = api_key or GROQ_API_KEY
        self.model = model or GROQ_MODEL
        self.api_url = GROQ_API_URL
        self.provider = 'groq'
    
    def is_available(self):
        """
        Check if the Groq service is ready to use.
        
        Returns True if API key is configured, False otherwise.
        Used by health check endpoint: GET /api/health/
        """
        return bool(self.api_key)
    
    def chat(
        self,
        message,
        conversation_history=None,
        language='en',
        system_prompt=None,
        temperature=0.7,
        max_tokens=1024,
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
            max_tokens: Maximum output tokens
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
        
        # Add previous conversation messages for context (last 10 only)
        # This helps the AI remember what was discussed
        if conversation_history:
            for hist in conversation_history[-10:]:
                messages.append({
                    "role": hist.get('role', 'user'),  # 'user' or 'assistant'
                    "content": hist.get('content', '')
                })
        
        # If user's language is Tagalog, tell the AI to respond in Tagalog
        if language == 'tl':
            message = f"[Please respond in Tagalog/Filipino] {message}"
        
        # Add the current user message
        messages.append({"role": "user", "content": message})
        
        # Send request to Groq API
        try:
            response = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",  # API authentication
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,           # llama-3.1-8b-instant
                    "messages": messages,          # The conversation
                    "temperature": temperature,    # Creativity (0=strict, 1=creative)
                    "max_tokens": max_tokens,      # Max response length
                    "top_p": top_p                 # Response diversity
                },
                timeout=30  # Wait max 30 seconds for response
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
                    'provider': 'groq',
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
        max_tokens=1024,
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
            max_tokens: Max output tokens
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
            for hist in conversation_history[-10:]:
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

                response = requests.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=request_body,
                    timeout=30
                )

                if response.status_code != 200:
                    error_msg = response.json().get('error', {}).get('message', response.text)
                    logger.error(f"Groq error: {response.status_code} - {error_msg}")
                    return {'success': False, 'error': f"Groq error: {error_msg}"}

                result = response.json()
                usage = result.get('usage', {})
                total_tokens += usage.get('total_tokens', 0)

                choice = result.get('choices', [{}])[0]
                assistant_message = choice.get('message', {})
                finish_reason = choice.get('finish_reason', '')

                tool_calls = assistant_message.get('tool_calls')
                if tool_calls and finish_reason == 'tool_calls':
                    messages.append(assistant_message)

                    for tool_call in tool_calls:
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


# =============================================================================
# FACTORY FUNCTION - Gets the LLM service instance
# =============================================================================

def get_llm_service(use_case='default', model=None):
    """
    Factory function to get the LLM service.
    
    Usage in views:
        from ai_assistant.services import get_llm_service
        
        llm = get_llm_service()
        result = llm.chat("Hello!")
    
    Args:
        use_case: Routing key ('default', 'chat', 'qualification')
        model: Optional explicit model override

    Returns:
        GroqService instance
    """
    if model:
        selected_model = model
    else:
        normalized_use_case = str(use_case or 'default').strip().lower()
        selected_model = MODEL_BY_USE_CASE.get(normalized_use_case, GROQ_MODEL)

    return GroqService(model=selected_model)
