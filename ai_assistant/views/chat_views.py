from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
import uuid
import math
import os
import json
import re

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.throttles import ChatRateThrottle
from accounts.utils.validation_utils import sanitize_text, sanitize_multiline_text
from accounts.models import Consent
from ai_assistant.models import AIInteraction
from ai_assistant.services import get_llm_service
from documents.models import Document
from loans.models import LoanProduct
from loans.services import check_basic_eligibility, qualify_customer, resolve_required_document_types
import logging

logger = logging.getLogger('ai_assistant')
ALLOWED_LANGUAGES = {'en', 'tl'}
AI_CHAT_MAX_TOKENS = int(os.getenv('AI_CHAT_MAX_TOKENS', '400'))
AI_CHAT_CONTEXT_MESSAGES = int(os.getenv('AI_CHAT_CONTEXT_MESSAGES', '6'))
LOAN_READINESS_MODE = 'loan_readiness'
LOAN_READINESS_KEYWORDS = {
    'loan readiness',
    'readiness',
    'ready to apply',
    'eligible',
    'eligibility',
    'qualify',
    'requirements',
    'approval chance',
    'handa',
}
DOCUMENT_TYPE_ALIASES = {
    'proof_of_income': 'income_proof',
    'business_registration': 'business_permit',
}
DOCUMENT_TYPE_LABELS = {
    'valid_id': 'Valid Government ID',
    'selfie_with_id': 'Selfie with ID',
    'proof_of_address': 'Proof of Address',
    'business_permit': 'Business Permit',
    'business_photo': 'Business Photo',
    'income_proof': 'Proof of Income',
    'other': 'Other',
}

LOAN_READINESS_SYSTEM_PROMPT = """You are Loan Readiness Coach for MSME Pathways.

Use ONLY the provided backend readiness data. Do not invent facts.

Return a concise response with these exact sections in order:
1) Readiness Summary
2) Missing Requirements
3) Risk Flags
4) Next 3 Actions

Rules:
- If a section has no items, say "None".
- Keep actions specific and prioritized.
- Never guarantee approval.
- Readiness Summary must match readiness.ready_to_apply.
  If readiness.ready_to_apply is false, clearly say not ready yet.
- Use eligibility_check.missing_requirements exactly; do not duplicate items.
"""


def _safe_float(value, default=None):
    try:
        parsed = float(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=None):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _extract_requested_amount(message):
    if not message:
        return None

    pattern = r'(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kK])?'
    for match in re.finditer(pattern, str(message)):
        raw_value = match.group(1).replace(',', '')
        amount = _safe_float(raw_value)
        if amount is None:
            continue
        if match.group(2):
            amount *= 1000
        if amount >= 1000:
            return round(amount, 2)
    return None


def _is_loan_readiness_request(message, mode):
    requested_mode = sanitize_text(mode or '').lower()
    if requested_mode == LOAN_READINESS_MODE:
        return True

    lowered = sanitize_text(message or '').lower()
    return any(keyword in lowered for keyword in LOAN_READINESS_KEYWORDS)


def _normalize_requirements_scope(raw_scope):
    normalized = sanitize_text(raw_scope or '').lower()
    if normalized not in {'baseline', 'product'}:
        return 'product'
    return normalized


def _normalize_missing_requirement_item(item):
    text = sanitize_text(item or '')
    if not text:
        return ''

    normalized = re.sub(r'^(document required|missing)\s*:\s*', '', text, flags=re.IGNORECASE).strip()
    return normalized or text


def _canonical_document_type(document_type):
    normalized = sanitize_text(document_type or '').lower()
    return DOCUMENT_TYPE_ALIASES.get(normalized, normalized)


def _document_type_label(document_type):
    canonical = _canonical_document_type(document_type)
    return DOCUMENT_TYPE_LABELS.get(canonical, canonical.replace('_', ' ').title())


def _build_loan_readiness_context(customer_id, message, payload):
    product_id = sanitize_text(payload.get('product_id', ''))
    if product_id:
        product = LoanProduct.find_by_id(product_id)
        if not product or not product.active:
            return None, "Selected loan product was not found or is inactive."
    else:
        products = LoanProduct.find(active_only=True)
        if len(products) > 1:
            return None, "Please provide product_id to compute readiness for a specific loan product."
        product = products[0] if products else None
        if not product:
            return None, "No active loan products are available for readiness coaching."

    requested_amount = _safe_float(payload.get('amount'))
    if requested_amount is None:
        requested_amount = _safe_float(payload.get('requested_amount'))
    if requested_amount is None:
        requested_amount = _extract_requested_amount(message)
    if requested_amount is None:
        requested_amount = float(product.min_amount or 1000)

    term_months = _safe_int(payload.get('term_months'), default=12)
    term_months = max(product.min_term_months, min(term_months, product.max_term_months))
    purpose = sanitize_text(payload.get('purpose', '')) or 'General business funding'
    requirements_scope = _normalize_requirements_scope(payload.get('requirements_scope'))

    basic = check_basic_eligibility(
        customer_id=customer_id,
        product=product,
        requirements_scope=requirements_scope,
        require_approved_documents=False,
    )

    qualification = qualify_customer(
        customer_id=customer_id,
        product=product,
        requested_amount=requested_amount,
        term_months=term_months,
        purpose=purpose,
        requirements_scope=requirements_scope,
        require_approved_documents=False,
    )

    required_doc_types = resolve_required_document_types(product, requirements_scope)
    uploaded_doc_types = {
        _canonical_document_type(doc.document_type)
        for doc in Document.find_by_customer(customer_id)
        if _canonical_document_type(doc.document_type)
    }
    missing_document_uploads = [
        _document_type_label(doc_type)
        for doc_type in required_doc_types
        if doc_type not in uploaded_doc_types
    ]

    merged_missing = []
    seen_missing = set()
    for item in (basic.get('missing_requirements', []) + qualification.get('missing_requirements', [])):
        normalized_item = _normalize_missing_requirement_item(item)
        if not normalized_item:
            continue
        marker = normalized_item.lower()
        if marker in seen_missing:
            continue
        seen_missing.add(marker)
        merged_missing.append(normalized_item)
    for label in missing_document_uploads:
        marker = f"upload required: {label}".lower()
        if marker in seen_missing:
            continue
        seen_missing.add(marker)
        merged_missing.append(f"Upload required: {label}")

    amount_in_range = product.min_amount <= requested_amount <= product.max_amount
    can_apply_profiles = bool(basic.get('can_apply'))
    can_apply_documents = len(missing_document_uploads) == 0
    can_apply = can_apply_profiles and can_apply_documents
    ready_to_apply = bool(
        amount_in_range
        and can_apply
        and qualification.get('can_apply')
        and qualification.get('eligible')
    )
    risk_flags = []
    if not amount_in_range:
        risk_flags.append(
            f"Requested amount is outside product range (₱{product.min_amount:,.0f}-₱{product.max_amount:,.0f})"
        )
    if qualification.get('risk_category') == 'high':
        risk_flags.append("High risk category from qualification result")
    if not qualification.get('eligible'):
        risk_flags.append("Current profile is not yet eligible for recommended approval flow")
    if not can_apply_profiles:
        risk_flags.append("Basic profile requirements are incomplete")
    if not can_apply_documents:
        risk_flags.append("Required documents for selected product are not yet uploaded")

    context = {
        'readiness': {
            'ready_to_apply': ready_to_apply,
            'status': 'ready' if ready_to_apply else 'not_ready',
        },
        'product': {
            'id': product.id,
            'name': product.name,
            'code': product.code,
            'min_amount': product.min_amount,
            'max_amount': product.max_amount,
            'min_term_months': product.min_term_months,
            'max_term_months': product.max_term_months,
        },
        'requested': {
            'amount': requested_amount,
            'term_months': term_months,
            'purpose': purpose,
            'requirements_scope': requirements_scope,
            'amount_in_range': amount_in_range,
        },
        'eligibility_check': {
            'can_apply': can_apply,
            'can_apply_profiles': can_apply_profiles,
            'can_apply_documents': can_apply_documents,
            'missing_requirements': merged_missing,
            'required_documents': [_document_type_label(doc_type) for doc_type in required_doc_types],
            'missing_document_uploads': missing_document_uploads,
            'uploaded_documents': sorted(_document_type_label(doc_type) for doc_type in uploaded_doc_types),
        },
        'qualification': {
            'eligible': qualification.get('eligible', False),
            'eligibility_score': qualification.get('eligibility_score'),
            'risk_category': qualification.get('risk_category'),
            'recommended_amount': qualification.get('recommended_amount'),
            'strengths': qualification.get('strengths', []),
            'concerns': qualification.get('concerns', []),
        },
        'risk_flags': risk_flags,
    }
    return context, None


def _build_loan_readiness_message(message, context):
    readiness_payload = json.dumps(context, ensure_ascii=False)
    return (
        "User question:\n"
        f"{message}\n\n"
        "Authoritative rule: readiness.ready_to_apply is the final apply-ready status.\n\n"
        "Trusted backend readiness data:\n"
        f"{readiness_payload}\n\n"
        "Answer using the required 4-section format."
    )


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
            requested_mode = sanitize_text(request.data.get('mode', '')).lower()
            loan_readiness_requested = _is_loan_readiness_request(message, requested_mode)
            loan_readiness_context = None
            llm_message = message
            llm_system_prompt = None

            if loan_readiness_requested:
                loan_readiness_context, readiness_error = _build_loan_readiness_context(
                    customer_id=customer_id,
                    message=message,
                    payload=request.data,
                )
                if readiness_error:
                    return error_response(
                        message="Loan readiness coaching is unavailable",
                        errors={'loan_readiness': readiness_error},
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
                llm_message = _build_loan_readiness_message(message, loan_readiness_context)
                llm_system_prompt = LOAN_READINESS_SYSTEM_PROMPT
            
            # Get conversation history for context
            history = AIInteraction.find_by_conversation(
                conversation_id=conversation_id,
                customer_id=customer_id,
            )
            conversation_history = [
                {'role': h.role, 'content': h.message if h.role == 'user' else h.response}
                for h in history[-AI_CHAT_CONTEXT_MESSAGES:]
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
                message=llm_message,
                conversation_history=conversation_history,
                language=language,
                system_prompt=llm_system_prompt,
                max_tokens=AI_CHAT_MAX_TOKENS,
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

            response_payload = {
                'response': ai_response,
                'conversation_id': conversation_id,
                'model': result.get('model'),
                'response_time_ms': result.get('response_time_ms'),
            }
            if loan_readiness_context:
                response_payload['loan_readiness'] = {
                    'enabled': True,
                    'readiness': loan_readiness_context.get('readiness'),
                    'product': loan_readiness_context.get('product'),
                    'requested': loan_readiness_context.get('requested'),
                    'eligibility_check': loan_readiness_context.get('eligibility_check'),
                    'qualification': loan_readiness_context.get('qualification'),
                    'risk_flags': loan_readiness_context.get('risk_flags'),
                }
            
            return success_response(
                data=response_payload,
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
                projection={
                    '_id': 1,
                    'role': 1,
                    'message': 1,
                    'response': 1,
                    'conversation_id': 1,
                    'timestamp': 1,
                    'language': 1,
                },
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
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, topic=None):
        """Get education content on loan topics"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result
        
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


class FAQsView(AccessControlMixin, APIView):
    """
    Get frequently asked questions.
    
    GET /api/ai/faqs/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get FAQs"""
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result
        
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
