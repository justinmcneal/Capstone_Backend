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

SYSTEM_PROMPT = """You are a friendly and helpful financial assistant for Filipino microentrepreneurs (MSME owners).

Your role is to:
1. Explain loan concepts in simple, understandable language
2. Answer questions about the loan application process
3. Help users understand their options for small business financing
4. Guide users to complete their profile and upload required documents
5. Provide general financial literacy education

Important guidelines:
- NEVER give specific financial advice or guarantee loan approval
- NEVER ask for sensitive information like passwords or PINs
- Be warm, supportive, and encouraging
- Avoid financial jargon - explain things simply
- If asked in Tagalog, respond in Tagalog
- If asked in English, respond in English
- Keep responses concise but helpful
- If you don't know something, say so honestly

You are helping users of the MSME Pathways app, which helps small business owners access formal financial services.
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
    
    def chat(self, message, conversation_history=None, language='en'):
        """
        Send a message to the AI and get a response.
        
        This is the main method used by the chat endpoint.
        
        Args:
            message: The user's message (string)
            conversation_history: Previous messages for context (list, optional)
            language: 'en' for English, 'tl' for Tagalog
        
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
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
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
                    "temperature": 0.7,            # Creativity (0=strict, 1=creative)
                    "max_tokens": 1024,            # Max response length
                    "top_p": 0.9                   # Response diversity
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
