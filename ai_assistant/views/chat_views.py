from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from django.http import StreamingHttpResponse
from django.core.cache import cache
from django.conf import settings
import uuid
import math
import time

from accounts.authentication import CustomJWTAuthentication
from accounts.services.auth_service import AuthService
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.throttles import ChatRateThrottle
from accounts.utils.validation_utils import sanitize_text, sanitize_multiline_text
from accounts.models import Consent
from ai_assistant.models import AIInteraction
from ai_assistant.services import get_llm_service
from ai_assistant.services.llm_service import SYSTEM_PROMPT, needs_user_context
from ai_assistant.services.knowledge_base import check_prohibited_content
from ai_assistant.services.context_builder import (
    build_user_context,
    get_context_for_intent,
    build_minimal_context,
)
from ai_assistant.services.tools import TOOL_SCHEMAS
import logging

logger = logging.getLogger('ai_assistant')
ALLOWED_LANGUAGES = {'en', 'tl'}


class EventStreamRenderer(BaseRenderer):
    """Custom renderer for Server-Sent Events"""
    media_type = 'text/event-stream'
    format = 'txt'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


# Cache TTL defaults (fallback if not in settings)
CACHE_TTL = getattr(settings, 'CACHE_TTL', {
    'faqs': 86400,
    'education': 86400,
    'suggestions': 43200,
    'loan_products': 1800,
    'ai_status': 60,
})

# Note: build_user_context and related functions are now in context_builder.py


class ConsentRequiredMixin(AccessControlMixin):
    """Mixin to enforce AI consent before allowing AI features"""
    
    def check_ai_consent(self, request):
        """Check if user has given AI consent"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return False, result

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
            
            # Check for prohibited content (credentials, guarantees, etc.)
            is_prohibited, redirect_response = check_prohibited_content(message)
            if is_prohibited:
                # Save the interaction but return the redirect response
                user_interaction = AIInteraction(
                    customer_id=customer_id,
                    message=message,
                    response='',
                    conversation_id=conversation_id,
                    role='user'
                )
                user_interaction.save()
                
                ai_interaction = AIInteraction(
                    customer_id=customer_id,
                    message=message,
                    response=redirect_response,
                    conversation_id=conversation_id,
                    role='assistant',
                    model='content_filter',
                    response_time_ms=0,
                )
                ai_interaction.save()
                
                return success_response(
                    data={
                        'message': redirect_response,
                        'conversation_id': conversation_id,
                        'filtered': True,
                    },
                    message="Response generated"
                )
            
            # Get LLM response
            llm = get_llm_service(use_case='chat')
            
            # Check if Groq API is available
            if not llm.is_available():
                return error_response(
                    message="AI service is currently unavailable. Please configure GROQ_API_KEY.",
                    errors={'hint': 'Get free API key at https://console.groq.com'},
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            # Build context-aware system prompt based on intent
            if needs_user_context(message):
                # Use intent-based context selection for optimized token usage
                user_context = get_context_for_intent(message, customer_id)
                contextualized_prompt = SYSTEM_PROMPT + user_context
            else:
                contextualized_prompt = SYSTEM_PROMPT

            result = llm.chat_with_tools(
                message=message,
                customer_id=customer_id,
                conversation_history=conversation_history,
                language=language,
                system_prompt=contextualized_prompt,
                tools=TOOL_SCHEMAS,
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


class StreamingChatView(ConsentRequiredMixin, APIView):
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
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ChatRateThrottle]
    renderer_classes = [EventStreamRenderer]

    def post(self, request):
        """Stream AI response as Server-Sent Events"""
        import json
        
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
        
        # Check for prohibited content before processing
        is_prohibited, redirect_response = check_prohibited_content(message)
        if is_prohibited:
            # Return redirect response as a simple SSE stream
            def filtered_stream():
                yield f"event: token\ndata: {json.dumps({'content': redirect_response})}\n\n"
                yield f"event: done\ndata: {json.dumps({'filtered': True})}\n\n"
            
            response = StreamingHttpResponse(
                filtered_stream(),
                content_type='text/event-stream'
            )
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
        
        # Get conversation history
        history = AIInteraction.find_by_conversation(
            conversation_id=conversation_id,
            customer_id=customer_id,
        )
        conversation_history = [
            {'role': h.role, 'content': h.message if h.role == 'user' else h.response}
            for h in history[-10:]
        ]
        
        # Get LLM service
        llm = get_llm_service(use_case='chat')
        
        if not llm.is_available():
            return error_response(
                message="AI service is currently unavailable",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        # Build context-aware system prompt based on intent
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
                ):
                    chunk_type = chunk.get('type')
                    
                    if chunk_type == 'tool_call':
                        yield f"event: tool_call\ndata: {json.dumps({'name': chunk.get('name')})}\n\n"
                    
                    elif chunk_type == 'tool_result':
                        tools_called.append(chunk.get('name'))
                        yield f"event: tool_result\ndata: {json.dumps({'name': chunk.get('name'), 'success': chunk.get('success', True)})}\n\n"
                    
                    elif chunk_type == 'token':
                        content = chunk.get('content', '')
                        full_response.append(content)
                        yield f"event: token\ndata: {json.dumps({'content': content})}\n\n"
                    
                    elif chunk_type == 'done':
                        model_used = chunk.get('model', '')
                        tokens_used = chunk.get('tokens_used', 0)
                        elapsed_ms = int((time.time() - start_time) * 1000)
                        
                        # Save interactions to database
                        ai_response = sanitize_multiline_text(''.join(full_response))
                        if ai_response:
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
                                model_used=model_used,
                                response_time_ms=elapsed_ms,
                                tokens_used=tokens_used
                            )
                            ai_interaction.save()
                        
                        yield f"event: done\ndata: {json.dumps({'model': model_used, 'tokens_used': tokens_used, 'response_time_ms': elapsed_ms, 'conversation_id': conversation_id, 'tools_called': tools_called})}\n\n"
                    
                    elif chunk_type == 'error':
                        yield f"event: error\ndata: {json.dumps({'content': chunk.get('content', 'Unknown error')})}\n\n"
                        break
                        
            except Exception as e:
                logger.error(f"Stream error: {str(e)}")
                yield f"event: error\ndata: {json.dumps({'content': 'Stream error occurred'})}\n\n"
        
        response = StreamingHttpResponse(
            event_stream(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response


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
    
    Responses are cached per language for performance.
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get conversation starters"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result

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
        
        # Check cache first
        cache_key = f'ai_suggestions_{language}'
        cached_data = cache.get(cache_key)
        if cached_data:
            return success_response(
                data={'suggestions': cached_data, 'language': language, 'cached': True},
                message="Suggestions retrieved successfully"
            )
        
        if language == 'tl':
            suggestions = [
                "Ano ang loan at paano ito gumagana?",
                "Paano mag-apply ng loan para sa maliit na negosyo?",
                "Ano-ano ang mga requirements para sa loan?",
                "Magkano ang pwede kong i-loan?",
                "Paano malalaman kung approved ang loan ko?",
                "Paano magbayad ng loan?",
                "Ano-ano ang mga paraan ng pagbabayad?",
                "Paano gumagana ang blockchain verification?",
            ]
        else:
            suggestions = [
                "What is a loan and how does it work?",
                "How do I apply for a small business loan?",
                "What documents do I need for a loan?",
                "How much can I borrow?",
                "How will I know if my loan is approved?",
                "How do I make a payment?",
                "What payment methods are available?",
                "How does blockchain verification work?",
            ]
        
        # Cache for future requests
        cache.set(cache_key, suggestions, CACHE_TTL.get('suggestions', 43200))
        
        return success_response(
            data={'suggestions': suggestions, 'language': language, 'cached': False},
            message="Suggestions retrieved successfully"
        )


class AIStatusView(AccessControlMixin, APIView):
    """
    Check AI service status.
    
    GET /api/ai/status/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Check if AI service is available"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result

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


class EducationView(AccessControlMixin, APIView):
    """
    Get loan education content.
    
    GET /api/ai/education/
    GET /api/ai/education/<topic>/
    
    Responses are cached for performance (content rarely changes).
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    ENABLE_MODULE_SEQUENCING = bool(
        getattr(settings, 'ENABLE_LEARN_MODULE_SEQUENCING', False)
    )
    
    # Education content is static, define once
    TOPICS = {
        'what_is_a_loan': {
            'title_fil': 'Ano ang Loan?',
            'title_en': 'What is a Loan?',
            'title': 'What is a Loan?',
            'description': 'Praktikal na paliwanag kung paano gamitin ang loan sa negosyo.',
            'weak_area_tag': 'loan_basics',
            'order': 3,
            'duration_minutes': 6,
            'content': 'A loan is money you borrow and agree to pay back with interest. Think of it as a tool to help your business grow when you need funds.',
            'key_points': [
                'You receive money upfront',
                'You pay it back in installments',
                'Interest is the cost of borrowing'
            ]
        },
        'interest_rates': {
            'title_fil': 'Paano Gumagana ang Interes',
            'title_en': 'Understanding Interest Rates',
            'title': 'Understanding Interest Rates',
            'description': 'Gabayan sa interes para makapagplano ng hulog nang tama.',
            'weak_area_tag': 'loan_basics',
            'order': 6,
            'duration_minutes': 5,
            'content': 'Interest is what you pay for borrowing money. MSME Pathways uses a flat interest rate, meaning you pay the same interest amount each month. Lower rates mean lower total cost.',
            'key_points': [
                'Flat rate: Same interest amount every month (not compounding)',
                'Default rate: 1.5% per month (18% per year), varies by product',
                'Compare rates before choosing a loan product'
            ]
        },
        'loan_process': {
            'title_fil': 'Hakbang sa Pag-apply',
            'title_en': 'Loan Process',
            'title': 'The Loan Process',
            'description': 'Sunod-sunod na hakbang mula profile hanggang paglabas ng pondo.',
            'weak_area_tag': 'loan_basics',
            'order': 7,
            'duration_minutes': 7,
            'content': 'Applying for a loan is simple with our AI-assisted process. Every step is tracked and recorded on the blockchain for transparency.',
            'key_points': [
                'Step 1: Complete your profile (personal, business, and alternative credit data)',
                'Step 2: Upload required documents (valid ID is always required)',
                'Step 3: Browse loan products and get AI pre-qualification',
                'Step 4: Submit your application with your preferred amount and term',
                'Step 5: A loan officer reviews your application',
                'Step 6: Get approved or receive feedback on what to improve',
                'Step 7: Loan is disbursed via your preferred method',
                'Step 8: Repay in monthly installments'
            ]
        },
        'documents_needed': {
            'title_fil': 'Mga Dokumentong Kailangan',
            'title_en': 'Documents You Need',
            'title': 'Documents You Need',
            'description': 'Checklist ng pangunahing dokumento para mabilis ang proseso.',
            'weak_area_tag': 'loan_basics',
            'order': 8,
            'duration_minutes': 4,
            'content': 'We keep requirements simple for MSMEs. Many small businesses operate informally, so we don\'t always require a business permit.',
            'key_points': [
                'Valid government ID (required for all loans)',
                'Selfie with your ID',
                'Proof of address (utility bill, barangay certificate)',
                'Business permit (DTI/SEC/Mayor\'s permit — if available)',
                'Business photo (photo of your business or workplace)',
                'Income proof (bank statements, sales records — optional)'
            ]
        },
        'improving_chances': {
            'title_fil': 'Paano Lumakas ang Iyong Application',
            'title_en': 'Improving Approval Chances',
            'title': 'Improving Your Approval Chances',
            'description': 'Mga praktikal na gawin para mas handa sa susunod na hakbang.',
            'weak_area_tag': 'loan_basics',
            'order': 9,
            'duration_minutes': 5,
            'content': 'Tips to increase your likelihood of getting approved.',
            'key_points': [
                'Complete your profile fully',
                'Upload clear, valid documents',
                'Start with a smaller loan amount',
                'Show consistent business activity'
            ]
        },
        'budgeting_basics': {
            'title_fil': 'Badyet ng Tindahan',
            'title_en': 'Store Budgeting Basics',
            'title': 'Badyet ng Tindahan',
            'description': 'Ayusin ang kita at gastos para laging may pondo sa negosyo.',
            'weak_area_tag': 'budgeting',
            'order': 1,
            'duration_minutes': 6,
            'content': 'Ang badyet ay simpleng plano ng papasok na kita at lalabas na gastos. Kapag maayos ang badyet, mas kontrolado ang puhunan at hulog.',
            'key_points': [
                'Ilista araw-araw ang benta at gastos',
                'Ihiwalay ang puhunan sa personal na gastos',
                'Maglaan ng emergency buffer kada linggo'
            ]
        },
        'debt_credit': {
            'title_fil': 'Utang at Kredito',
            'title_en': 'Debt and Credit',
            'title': 'Utang at Kredito',
            'description': 'Unawain kung kailan tama ang pangungutang at paano umiwas sa penalty.',
            'weak_area_tag': 'debt_credit',
            'order': 2,
            'duration_minutes': 7,
            'content': 'Ang utang ay pwedeng makatulong sa paglago kung may malinaw na plano ng bayad. Ang kredito ay dapat gamitin ayon sa cash flow ng negosyo.',
            'key_points': [
                'Pumili ng hulog na kaya ng lingguhang benta',
                'Unahin bayaran ang may mas mataas na interes',
                'Iwasan ang sabay-sabay na utang na walang plano'
            ]
        },
        'savings_fund': {
            'title_fil': 'Ipon at Pondo',
            'title_en': 'Savings and Fund Building',
            'title': 'Ipon at Pondo',
            'description': 'Gumawa ng maliit pero tuloy-tuloy na ipon para sa negosyo.',
            'weak_area_tag': 'savings',
            'order': 4,
            'duration_minutes': 5,
            'content': 'Ang regular na ipon ay proteksyon ng negosyo laban sa biglaang gastos at bagal ng benta.',
            'key_points': [
                'Magtabi ng porsyento ng kita kada araw',
                'Magkaroon ng pondo para sa 1-2 buwang gastos',
                'Gamitin lang ang ipon para sa mahalagang pangangailangan'
            ]
        },
        'payment_methods': {
            'title_fil': 'Paraan ng Bayad',
            'title_en': 'Payment Methods',
            'title': 'Payment Methods',
            'description': 'Piliin ang pinaka-angkop na paraan ng bayad para sa iyo.',
            'weak_area_tag': 'debt_credit',
            'order': 10,
            'duration_minutes': 6,
            'content': 'MSME Pathways supports 5 payment methods in two categories: automatic and manual.',
            'key_points': [
                'AUTOMATIC — recorded instantly when you pay:',
                '  • GCash — pay using your GCash mobile wallet',
                '  • Bank Transfer — pay via electronic bank transfer',
                '  • Wallet (ETH) — pay using your Ethereum cryptocurrency wallet',
                'MANUAL — your loan officer records the payment for you:',
                '  • Cash — pay at a partner location',
                '  • Check — pay by check; recorded after clearance',
                'For cash and check, visit a partner location and your loan officer will record it in the system'
            ]
        },
        'repayment_schedule': {
            'title_fil': 'Pag-unawa sa Iskedyul ng Bayad',
            'title_en': 'Repayment Schedule',
            'title': 'Understanding Your Repayment Schedule',
            'description': 'Alamin ang due dates at status ng bawat hulog.',
            'weak_area_tag': 'debt_credit',
            'order': 5,
            'duration_minutes': 6,
            'content': 'After your loan is disbursed, a repayment schedule is automatically created with equal monthly installments.',
            'key_points': [
                'Each installment has a due date, principal portion, and interest portion',
                'Installment statuses: Pending, Paid, Partial, or Overdue',
                'Partial payments are supported — pay what you can',
                'View your schedule in the app: Track → select your loan → Schedule tab',
                'View payment history: Track → select your loan → Payments tab'
            ]
        },
        'blockchain_basics': {
            'title_fil': 'Blockchain Verification',
            'title_en': 'Blockchain Verification',
            'title': 'Blockchain Verification',
            'description': 'Paano nakakatulong ang blockchain sa malinaw na records.',
            'weak_area_tag': 'loan_basics',
            'order': 11,
            'duration_minutes': 5,
            'content': 'MSME Pathways records all major loan events on the Ethereum blockchain, providing a transparent and tamper-proof record of your loan history.',
            'key_points': [
                'Every loan application, approval, disbursement, and payment is recorded on-chain',
                'Blockchain records cannot be altered or deleted — ensuring transparency',
                'You can view blockchain verification details in the app',
                'This protects both borrowers and lenders with an immutable audit trail'
            ]
        },
        'after_approval': {
            'title_fil': 'Pagkatapos Maaprubahan',
            'title_en': 'After Approval',
            'title': 'After Your Loan is Approved',
            'description': 'Ano ang susunod na hakbang pagkatapos ng approval.',
            'weak_area_tag': 'loan_basics',
            'order': 12,
            'duration_minutes': 5,
            'content': 'Once approved, here\'s what happens next and what you need to know about managing your loan.',
            'key_points': [
                'You\'ll receive a notification with your approved loan amount',
                'Set your preferred disbursement method (GCash, bank transfer, cash, check, or wallet)',
                'The loan officer processes the disbursement',
                'A repayment schedule is automatically created after disbursement',
                'Make monthly payments on time to maintain good standing',
                'Track everything in the app under the "Track" section'
            ]
        },
        'wallet_setup': {
            'title_fil': 'Gamitin ang ETH Wallet',
            'title_en': 'Using the ETH Wallet',
            'title': 'Using the ETH Wallet',
            'description': 'Gabay sa paggamit ng wallet para sa bayad at paglabas ng pondo.',
            'weak_area_tag': 'loan_basics',
            'order': 13,
            'duration_minutes': 5,
            'content': 'MSME Pathways supports Ethereum (ETH) wallet payments for both disbursement and repayment. This is a cryptocurrency-based payment option.',
            'key_points': [
                'Wallet (ETH) is one of the 5 accepted payment methods',
                'Payments via ETH wallet are automatically recorded in the system',
                'You can also choose to receive your loan disbursement via ETH wallet',
                'All wallet transactions are verified on the Ethereum blockchain'
            ]
        }
    }
    
    def get(self, request, topic=None):
        """Get education content on loan topics"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result
        
        if topic:
            # Check cache for specific topic
            cache_key = f'ai_education_{topic}'
            cached_data = cache.get(cache_key)
            if cached_data:
                return success_response(data={**cached_data, 'cached': True})
            
            if topic in self.TOPICS:
                topic_data = self.TOPICS[topic]
                cache.set(cache_key, topic_data, CACHE_TTL.get('education', 86400))
                return success_response(data={**topic_data, 'cached': False})
            else:
                return error_response(
                    message="Topic not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
        
        # Return list of available topics (cached)
        customer = AuthService.get_customer_by_id(request.user.customer_id)
        weak_areas = []
        progress_map = {}
        if customer:
            if isinstance(getattr(customer, 'pretest_weak_areas', None), list):
                weak_areas = [str(item) for item in customer.pretest_weak_areas if item]
            if isinstance(getattr(customer, 'learn_module_progress', None), dict):
                progress_map = customer.learn_module_progress

        cache_key = f'ai_education_topics_list_v2_{request.user.customer_id}'
        cached_list = cache.get(cache_key)
        if cached_list:
            return success_response(
                data={'topics': cached_list, 'cached': True},
                message="Education topics retrieved"
            )

        topic_list = []
        for topic_id, topic_data in self.TOPICS.items():
            status_value = str(progress_map.get(topic_id, '')).strip().lower()
            if self.ENABLE_MODULE_SEQUENCING:
                if status_value not in {'locked', 'in_progress', 'completed'}:
                    status_value = 'locked'
            else:
                # Default behavior: unlock all modules unless explicitly completed.
                if status_value not in {'in_progress', 'completed'}:
                    status_value = 'in_progress'
            topic_list.append({
                'id': topic_id,
                'title': topic_data.get('title_en') or topic_data['title'],
                'title_fil': topic_data.get('title_fil') or topic_data['title'],
                'title_en': topic_data.get('title_en') or topic_data['title'],
                'description': topic_data.get('description', ''),
                'weak_area_tag': topic_data.get('weak_area_tag'),
                'order': int(topic_data.get('order', 999)),
                'duration_minutes': int(topic_data.get('duration_minutes', 5)),
                'status': status_value,
                'recommended': topic_data.get('weak_area_tag') in weak_areas,
            })

        if self.ENABLE_MODULE_SEQUENCING:
            has_accessible = any(t['status'] != 'locked' for t in topic_list)
            if not has_accessible and topic_list:
                prioritized = sorted(
                    topic_list,
                    key=lambda t: (
                        0 if t['recommended'] else 1,
                        t['order'],
                    ),
                )
                prioritized[0]['status'] = 'in_progress'

        topic_list.sort(
            key=lambda t: (
                1 if t['status'] == 'completed' else 0,
                0 if t['recommended'] and t['status'] != 'completed' else 1,
                t['order'],
            )
        )

        cache.set(cache_key, topic_list, CACHE_TTL.get('education', 86400))
        return success_response(
            data={
                'topics': topic_list,
                'cached': False,
                'module_sequencing_enabled': self.ENABLE_MODULE_SEQUENCING,
            },
            message="Education topics retrieved"
        )


class ModuleProgressView(AccessControlMixin, APIView):
    """Update progress state for a learning module."""

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    ALLOWED_STATUSES = {'in_progress', 'completed'}

    def post(self, request):
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result

        topic_id = str(request.data.get('topic_id') or '').strip()
        status_value = str(request.data.get('status') or '').strip().lower()

        if not topic_id:
            return error_response(
                message='topic_id is required',
                errors={'topic_id': 'This field is required'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if status_value not in self.ALLOWED_STATUSES:
            return error_response(
                message='Invalid status',
                errors={
                    'status': (
                        'Status must be one of: '
                        + ', '.join(sorted(self.ALLOWED_STATUSES))
                    )
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        customer = AuthService.get_customer_by_id(request.user.customer_id)
        if not customer:
            return error_response(
                message='Customer not found',
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not isinstance(getattr(customer, 'learn_module_progress', None), dict):
            customer.learn_module_progress = {}

        customer.learn_module_progress[topic_id] = status_value
        customer.save()

        cache.delete(f'ai_education_topics_list_v2_{request.user.customer_id}')

        return success_response(
            data={
                'topic_id': topic_id,
                'status': status_value,
            },
            message='Module progress updated',
        )


class FAQsView(AccessControlMixin, APIView):
    """
    Get frequently asked questions.
    
    GET /api/ai/faqs/
    
    Responses are cached for performance (FAQs rarely change).
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    # FAQs are static, define once
    FAQS = [
        {
            'question': 'How much can I borrow?',
            'answer': 'Loan amounts range from ₱5,000 to ₱500,000 depending on the loan product, your profile, and business needs.'
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
            'answer': 'Not necessarily! We understand many MSMEs operate informally. A valid government ID is the main requirement.'
        },
        {
            'question': 'How do I make payments?',
            'answer': 'There are 5 payment methods in two categories. Automatic (recorded instantly): GCash, Bank Transfer, and Wallet (ETH) — you pay directly and it\'s automatically recorded. Manual (recorded by your loan officer): Cash and Check — you pay at a partner location and the loan officer records it for you.'
        },
        {
            'question': 'What happens if I miss a payment?',
            'answer': 'Your installment will be marked as overdue. Contact us immediately — we offer flexible arrangements for genuine difficulties.'
        },
        {
            'question': 'How do I check my loan status?',
            'answer': 'Open the app and go to Track → Applications. You\'ll see the current status of all your loan applications (draft, submitted, under review, approved, rejected, or disbursed).'
        },
        {
            'question': 'What is blockchain verification?',
            'answer': 'Every major event in your loan — application, approval, disbursement, and each payment — is permanently recorded on the Ethereum blockchain. This creates a transparent, tamper-proof audit trail that protects both you and the lender.'
        },
        {
            'question': 'How does the repayment schedule work?',
            'answer': 'After your loan is disbursed, a repayment schedule is automatically created with equal monthly installments. Each installment includes a principal and interest portion. You can view it in the app under Track → select your loan → Schedule tab.'
        },
        {
            'question': 'What happens after my loan is disbursed?',
            'answer': 'Once disbursed, your repayment schedule is automatically created. You\'ll need to make monthly payments according to the schedule. You can track your payments and remaining balance in the app under the Track section.'
        },
        {
            'question': 'What is the ETH Wallet payment method?',
            'answer': 'Wallet (ETH) lets you make payments using an Ethereum cryptocurrency wallet. Payments via ETH wallet are automatically recorded in the system and verified on the blockchain. You can also receive your loan disbursement via ETH wallet.'
        }
    ]
    
    def get(self, request):
        """Get FAQs"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result
        
        # Check cache first
        cache_key = 'ai_faqs'
        cached_data = cache.get(cache_key)
        if cached_data:
            return success_response(
                data={'faqs': cached_data, 'total': len(cached_data), 'cached': True},
                message="FAQs retrieved"
            )
        
        # Cache for future requests
        cache.set(cache_key, self.FAQS, CACHE_TTL.get('faqs', 86400))
        
        return success_response(
            data={'faqs': self.FAQS, 'total': len(self.FAQS), 'cached': False},
            message="FAQs retrieved"
        )
