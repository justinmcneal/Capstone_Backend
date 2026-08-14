import logging
import math

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.validation_utils import sanitize_text
from ai_assistant.models import AIInteraction
from ai_assistant.services.exception_types import NON_FATAL_EXCEPTIONS
from ai_assistant.views.chat_views import ConsentRequiredMixin

logger = logging.getLogger('ai_assistant')


class ChatHistoryView(ConsentRequiredMixin, APIView):
    """
    Get and clear chat history.
    
    GET /api/ai/history/
    DELETE /api/ai/history/
    """
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

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
            
            page = self._parse_positive_int(request.query_params.get('page', 1))
            if page is None:
                return error_response(
                    message="Invalid page parameter",
                    errors={'page': 'page must be a positive integer'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if page > settings.AI_ASSISTANT_HISTORY_MAX_PAGE:
                return error_response(
                    message="Requested history page is too large",
                    code='AI_HISTORY_PAGE_EXCEEDED',
                    errors={'page': f'Must not exceed {settings.AI_ASSISTANT_HISTORY_MAX_PAGE}'},
                    status_code=status.HTTP_400_BAD_REQUEST,
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
            if len(search_query) > settings.AI_ASSISTANT_HISTORY_SEARCH_MAX_CHARS:
                return error_response(
                    message="History search is too long",
                    code='AI_HISTORY_SEARCH_EXCEEDED',
                    errors={
                        'search': (
                            'Must not exceed '
                            f'{settings.AI_ASSISTANT_HISTORY_SEARCH_MAX_CHARS} characters'
                        )
                    },
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            interactions, total_messages = AIInteraction.find_by_customer_paginated(
                customer_id=customer_id,
                page=page,
                limit=limit,
                search_query=search_query or None,
            )
            
            history = [{
                'id': i.id,
                'role': i.role,
                'content': i.message if i.role == 'user' else i.response,
                'conversation_id': i.conversation_id,
                'timestamp': i.timestamp.isoformat(),
                'language': i.language
            } for i in reversed(interactions)]
            total_pages = max(1, math.ceil(total_messages / limit)) if total_messages else 1
            has_more = page < total_pages
            
            return success_response(
                data={
                    'history': history,
                    'total': len(history),
                    'page': page,
                    'limit': limit,
                    'total_messages': total_messages,
                    'total_pages': total_pages,
                    'has_more': has_more,
                },
                message="Chat history retrieved successfully"
            )
            
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Get history error: {e!s}")
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
            
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Clear history error: {e!s}")
            return error_response(
                message="Failed to clear chat history",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
