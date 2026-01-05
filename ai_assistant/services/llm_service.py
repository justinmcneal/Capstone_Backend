"""
Ollama LLM Service for AI Assistant.

Ollama runs locally - no API key required.
Install: https://ollama.ai
Run: ollama run llama3.2
"""
import requests
import logging
from django.conf import settings
import time

logger = logging.getLogger('ai_assistant')


# Default Ollama configuration
OLLAMA_HOST = getattr(settings, 'OLLAMA_HOST', 'http://localhost:11434')
OLLAMA_MODEL = getattr(settings, 'OLLAMA_MODEL', 'llama3.2')


# System prompt for the financial assistant
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


class OllamaService:
    """
    Service for interacting with local Ollama LLM.
    """
    
    def __init__(self, host=None, model=None):
        self.host = host or OLLAMA_HOST
        self.model = model or OLLAMA_MODEL
        self.api_url = f"{self.host}/api/chat"
    
    def is_available(self):
        """Check if Ollama is running and the model is available"""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            if response.status_code == 200:
                models = response.json().get('models', [])
                model_names = [m.get('name', '').split(':')[0] for m in models]
                return self.model in model_names or f"{self.model}:latest" in [m.get('name', '') for m in models]
            return False
        except requests.RequestException:
            return False
    
    def get_available_models(self):
        """Get list of available models"""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            if response.status_code == 200:
                return [m.get('name', '') for m in response.json().get('models', [])]
            return []
        except requests.RequestException:
            return []
    
    def chat(self, message, conversation_history=None, language='en'):
        """
        Send a message and get a response.
        
        Args:
            message: User's message
            conversation_history: List of previous messages for context
            language: 'en' or 'tl' for response language hint
        
        Returns:
            dict with response, model, and timing info
        """
        start_time = time.time()
        
        # Build messages array
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Add conversation history for context
        if conversation_history:
            for hist in conversation_history[-10:]:  # Last 10 messages for context
                messages.append({
                    "role": hist.get('role', 'user'),
                    "content": hist.get('content', '')
                })
        
        # Add language hint if Tagalog
        if language == 'tl':
            message = f"[Please respond in Tagalog/Filipino] {message}"
        
        # Add current message
        messages.append({"role": "user", "content": message})
        
        try:
            response = requests.post(
                self.api_url,
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                    }
                },
                timeout=60  # 60 second timeout for response
            )
            
            if response.status_code == 200:
                result = response.json()
                elapsed_ms = int((time.time() - start_time) * 1000)
                
                return {
                    'success': True,
                    'response': result.get('message', {}).get('content', ''),
                    'model': self.model,
                    'response_time_ms': elapsed_ms,
                    'tokens_used': result.get('eval_count', 0) + result.get('prompt_eval_count', 0)
                }
            else:
                logger.error(f"Ollama error: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'error': f"Ollama returned status {response.status_code}",
                    'response': None
                }
                
        except requests.Timeout:
            logger.error("Ollama request timed out")
            return {
                'success': False,
                'error': "Request timed out. Please try again.",
                'response': None
            }
        except requests.RequestException as e:
            logger.error(f"Ollama request error: {str(e)}")
            return {
                'success': False,
                'error': "Could not connect to AI service. Please ensure Ollama is running.",
                'response': None
            }


def get_llm_service():
    """Factory function to get the LLM service instance"""
    return OllamaService()
