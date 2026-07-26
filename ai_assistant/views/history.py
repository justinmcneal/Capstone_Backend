from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.throttles import ChatRateThrottle
from accounts.utils.validation_utils import sanitize_text
from accounts.services.consent_service import ConsentService
from ai_assistant.models import AIInteraction
from ai_assistant.views.chat_views import ConsentRequiredMixin
import math
import logging

logger = logging.getLogger('ai_assistant')


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
