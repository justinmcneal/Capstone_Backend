from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from bson import ObjectId
import uuid

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.models import Consent
from ai_assistant.models import AIInteraction
from ai_assistant.services import get_llm_service
import logging

logger = logging.getLogger('ai_assistant')


class ConsentRequiredMixin:
    """Mixin to enforce AI consent before allowing AI features"""
    
    def check_ai_consent(self, request):
        """Check if user has given AI consent"""
        user = request.user
        customer_id = user.customer_id
        
        consent = Consent.find_by_user(customer_id, 'customer')
        
        if not consent or not consent.ai_consent:
            return False, error_response(
                message="AI consent is required to use this feature",
                errors={
                    'code': 'CONSENT_REQUIRED',
                    'action_required': {
                        'endpoint': '/api/auth/consent/',
                        'method': 'POST',
                        'required_fields': ['ai_consent']
                    }
                },
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        return True, consent


class ChatView(ConsentRequiredMixin, APIView):
    """
    Main chat endpoint for AI assistant.
    
    POST /api/ai/chat/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Send a message to the AI assistant"""
        try:
            # Check AI consent
            has_consent, result = self.check_ai_consent(request)
            if not has_consent:
                return result
            
            user = request.user
            customer_id = user.customer_id
            
            # Get message from request
            message = request.data.get('message', '').strip()
            if not message:
                return error_response(
                    message="Message is required",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Get optional parameters
            conversation_id = request.data.get('conversation_id') or str(uuid.uuid4())
            language = request.data.get('language', user.language if hasattr(user, 'language') else 'en')
            
            # Get conversation history for context
            history = AIInteraction.find_by_conversation(conversation_id)
            conversation_history = [
                {'role': h.role, 'content': h.message if h.role == 'user' else h.response}
                for h in history[-10:]  # Last 10 messages
            ]
            
            # Get LLM response
            llm = get_llm_service()
            
            # Check if Ollama is available
            if not llm.is_available():
                return error_response(
                    message="AI service is currently unavailable. Please ensure Ollama is running.",
                    errors={'hint': 'Run: ollama run llama3.2'},
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            result = llm.chat(
                message=message,
                conversation_history=conversation_history,
                language=language
            )
            
            if not result['success']:
                return error_response(
                    message=result.get('error', 'Failed to get AI response'),
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Save user message
            user_interaction = AIInteraction(
                customer_id=customer_id,
                message=message,
                response='',
                language=language,
                conversation_id=conversation_id,
                role='user'
            )
            user_interaction.save()
            
            # Save AI response
            ai_interaction = AIInteraction(
                customer_id=customer_id,
                message='',
                response=result['response'],
                language=language,
                conversation_id=conversation_id,
                role='assistant',
                model_used=result.get('model', ''),
                response_time_ms=result.get('response_time_ms'),
                tokens_used=result.get('tokens_used')
            )
            ai_interaction.save()
            
            logger.info(f"AI chat: customer {customer_id}, {result.get('response_time_ms')}ms")
            
            return success_response(
                data={
                    'response': result['response'],
                    'conversation_id': conversation_id,
                    'model': result.get('model'),
                    'response_time_ms': result.get('response_time_ms')
                },
                message="Response generated successfully"
            )
            
        except Exception as e:
            logger.error(f"Chat error: {str(e)}")
            return error_response(
                message="Failed to process chat message",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ChatHistoryView(ConsentRequiredMixin, APIView):
    """
    Get and clear chat history.
    
    GET /api/ai/history/
    DELETE /api/ai/history/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get chat history"""
        try:
            has_consent, result = self.check_ai_consent(request)
            if not has_consent:
                return result
            
            user = request.user
            customer_id = user.customer_id
            
            # Get optional limit
            limit = min(int(request.query_params.get('limit', 50)), 100)
            
            interactions = AIInteraction.find_by_customer(customer_id, limit=limit)
            
            # Group by conversation
            history = [{
                'id': i.id,
                'role': i.role,
                'content': i.message if i.role == 'user' else i.response,
                'conversation_id': i.conversation_id,
                'timestamp': i.timestamp.isoformat(),
                'language': i.language
            } for i in reversed(interactions)]  # Oldest first
            
            return success_response(
                data={
                    'history': history,
                    'total': len(history)
                },
                message="Chat history retrieved successfully"
            )
            
        except Exception as e:
            logger.error(f"Get history error: {str(e)}")
            return error_response(
                message="Failed to retrieve chat history",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request):
        """Clear chat history"""
        try:
            has_consent, result = self.check_ai_consent(request)
            if not has_consent:
                return result
            
            user = request.user
            customer_id = user.customer_id
            
            deleted_count = AIInteraction.delete_by_customer(customer_id)
            
            logger.info(f"Chat history cleared: customer {customer_id}, {deleted_count} messages")
            
            return success_response(
                data={'deleted_count': deleted_count},
                message="Chat history cleared successfully"
            )
            
        except Exception as e:
            logger.error(f"Clear history error: {str(e)}")
            return error_response(
                message="Failed to clear chat history",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SuggestionsView(ConsentRequiredMixin, APIView):
    """
    Get conversation starters/suggestions.
    
    GET /api/ai/suggestions/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get conversation starters"""
        user = request.user
        language = request.query_params.get('language', 
            user.language if hasattr(user, 'language') else 'en')
        
        if language == 'tl':
            suggestions = [
                "Ano ang loan at paano ito gumagana?",
                "Paano mag-apply ng loan para sa maliit na negosyo?",
                "Ano-ano ang mga requirements para sa loan?",
                "Magkano ang pwede kong i-loan?",
                "Paano malalaman kung approved ang loan ko?"
            ]
        else:
            suggestions = [
                "What is a loan and how does it work?",
                "How do I apply for a small business loan?",
                "What documents do I need for a loan?",
                "How much can I borrow?",
                "How will I know if my loan is approved?"
            ]
        
        return success_response(
            data={'suggestions': suggestions, 'language': language},
            message="Suggestions retrieved successfully"
        )


class AIStatusView(APIView):
    """
    Check AI service status.
    
    GET /api/ai/status/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Check if AI service is available"""
        llm = get_llm_service()
        
        is_available = llm.is_available()
        available_models = llm.get_available_models() if is_available else []
        
        return success_response(
            data={
                'available': is_available,
                'current_model': llm.model,
                'available_models': available_models,
                'host': llm.host
            },
            message="AI status retrieved"
        )
