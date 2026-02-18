from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
import uuid
import math

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.throttles import ChatRateThrottle
from accounts.utils.validation_utils import sanitize_text, sanitize_multiline_text
from accounts.models import Consent
from ai_assistant.models import AIInteraction
from ai_assistant.services import get_llm_service
import logging

logger = logging.getLogger('ai_assistant')
ALLOWED_LANGUAGES = {'en', 'tl'}


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
    throttle_classes = [ChatRateThrottle]
    
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
            message = sanitize_text(request.data.get('message', ''))
            if not message:
                return error_response(
                    message="Message is required",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Get optional parameters
            raw_conversation_id = request.data.get('conversation_id')
            if raw_conversation_id:
                try:
                    # Normalize client-provided conversation IDs to canonical UUID format
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
            
            # Get conversation history for context
            history = AIInteraction.find_by_conversation(
                conversation_id=conversation_id,
                customer_id=customer_id,
            )
            conversation_history = [
                {'role': h.role, 'content': h.message if h.role == 'user' else h.response}
                for h in history[-10:]  # Last 10 messages
            ]
            
            # Get LLM response
            llm = get_llm_service(use_case='chat')
            
            # Check if Groq API is available
            if not llm.is_available():
                return error_response(
                    message="AI service is currently unavailable. Please configure GROQ_API_KEY.",
                    errors={'hint': 'Get free API key at https://console.groq.com'},
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

            ai_response = sanitize_multiline_text(result.get('response', ''))
            if not ai_response:
                return error_response(
                    message="AI returned an empty response",
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
                response=ai_response,
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
                    'response': ai_response,
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

    def _parse_positive_int(self, value, default=None):
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except (TypeError, ValueError):
            return default
    
    def get(self, request):
        """Get chat history"""
        try:
            has_consent, result = self.check_ai_consent(request)
            if not has_consent:
                return result
            
            user = request.user
            customer_id = user.customer_id
            
            # Query params
            page = self._parse_positive_int(request.query_params.get('page', 1))
            if page is None:
                return error_response(
                    message="Invalid page parameter",
                    errors={'page': 'page must be a positive integer'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            limit = self._parse_positive_int(request.query_params.get('limit', 50))
            if limit is None:
                return error_response(
                    message="Invalid limit parameter",
                    errors={'limit': 'limit must be a positive integer'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            limit = min(limit, 100)
            search_query = sanitize_text(request.query_params.get('search', ''))

            interactions, total_messages = AIInteraction.find_by_customer_paginated(
                customer_id=customer_id,
                page=page,
                limit=limit,
                search_query=search_query or None,
            )
            
            # Group by conversation
            history = [{
                'id': i.id,
                'role': i.role,
                'content': i.message if i.role == 'user' else i.response,
                'conversation_id': i.conversation_id,
                'timestamp': i.timestamp.isoformat(),
                'language': i.language
            } for i in reversed(interactions)]  # Oldest first
            total_pages = max(1, math.ceil(total_messages / limit)) if total_messages else 1
            has_more = page < total_pages
            
            return success_response(
                data={
                    'history': history,
                    'total': len(history),  # Backward-compatible key
                    'page': page,
                    'limit': limit,
                    'total_messages': total_messages,
                    'total_pages': total_pages,
                    'has_more': has_more,
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
        requested_language = sanitize_text(
            request.query_params.get('language', user.language if hasattr(user, 'language') else 'en')
        ).lower()
        if requested_language not in ALLOWED_LANGUAGES:
            return error_response(
                message="Invalid language value",
                errors={'language': f"language must be one of: {', '.join(sorted(ALLOWED_LANGUAGES))}"},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        language = requested_language
        
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
        llm = get_llm_service(use_case='chat')
        
        is_available = llm.is_available()
        
        return success_response(
            data={
                'available': is_available,
                'provider': llm.provider,
                'current_model': llm.model if is_available else None,
                'api_configured': bool(llm.api_key)
            },
            message="AI status retrieved"
        )


class EducationView(APIView):
    """
    Get loan education content.
    
    GET /api/ai/education/
    GET /api/ai/education/<topic>/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, topic=None):
        """Get education content on loan topics"""
        
        topics = {
            'what_is_a_loan': {
                'title': 'What is a Loan?',
                'content': 'A loan is money you borrow and agree to pay back with interest. Think of it as a tool to help your business grow when you need funds.',
                'key_points': [
                    'You receive money upfront',
                    'You pay it back in installments',
                    'Interest is the cost of borrowing'
                ]
            },
            'interest_rates': {
                'title': 'Understanding Interest Rates',
                'content': 'Interest is what you pay for borrowing money. Lower rates mean lower total cost.',
                'key_points': [
                    'Monthly rate: Applied each month',
                    'Annual rate: Total yearly percentage',
                    'Compare rates before choosing a loan'
                ]
            },
            'loan_process': {
                'title': 'The Loan Process',
                'content': 'Applying for a loan is simple with our AI-assisted process.',
                'key_points': [
                    'Step 1: Complete your profile',
                    'Step 2: Upload required documents',
                    'Step 3: Get AI pre-qualification',
                    'Step 4: Submit application',
                    'Step 5: Wait for approval'
                ]
            },
            'documents_needed': {
                'title': 'Documents You Need',
                'content': 'We keep requirements simple for MSMEs.',
                'key_points': [
                    'Valid government ID (required)',
                    'Proof of address',
                    'Business permit (if available)',
                    'Photo of your business'
                ]
            },
            'improving_chances': {
                'title': 'Improving Your Approval Chances',
                'content': 'Tips to increase your likelihood of getting approved.',
                'key_points': [
                    'Complete your profile fully',
                    'Upload clear, valid documents',
                    'Start with a smaller loan amount',
                    'Show consistent business activity'
                ]
            }
        }
        
        if topic:
            if topic in topics:
                return success_response(data=topics[topic])
            else:
                return error_response(
                    message="Topic not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
        
        # Return list of available topics
        topic_list = [{'id': k, 'title': v['title']} for k, v in topics.items()]
        return success_response(
            data={'topics': topic_list},
            message="Education topics retrieved"
        )


class FAQsView(APIView):
    """
    Get frequently asked questions.
    
    GET /api/ai/faqs/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get FAQs"""
        
        faqs = [
            {
                'question': 'How much can I borrow?',
                'answer': 'Loan amounts range from ₱5,000 to ₱500,000 depending on your profile and business needs.'
            },
            {
                'question': 'How long does approval take?',
                'answer': 'Most applications are reviewed within 1-3 business days with our AI-assisted process.'
            },
            {
                'question': 'What if I get rejected?',
                'answer': 'You can reapply after improving your profile or try a smaller loan amount. Our AI will explain what to improve.'
            },
            {
                'question': 'Do I need a business permit?',
                'answer': 'Not necessarily! We understand many MSMEs operate informally. A valid ID is the main requirement.'
            },
            {
                'question': 'How do I make payments?',
                'answer': 'Payments can be made via bank transfer, GCash, Maya, or cash at partner locations.'
            },
            {
                'question': 'What happens if I miss a payment?',
                'answer': 'Contact us immediately. We offer flexible arrangements for genuine difficulties.'
            }
        ]
        
        return success_response(
            data={'faqs': faqs, 'total': len(faqs)},
            message="FAQs retrieved"
        )
