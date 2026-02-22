"""
Core views for health check and system status.
"""
from rest_framework.views import APIView
from rest_framework import status
from django.conf import settings

from accounts.utils.response_helpers import success_response, error_response
import logging

logger = logging.getLogger('config')


class HealthCheckView(APIView):
    """
    API Health Check endpoint.
    
    GET /api/health/
    """
    authentication_classes = []
    permission_classes = []
    
    def get(self, request):
        """Check system health"""
        health = {
            'status': 'healthy',
            'services': {},
            'security': {
                'field_encryption': 'enabled' if bool(getattr(settings, 'FIELD_ENCRYPTION_KEY', '')) else 'disabled',
                'tde': 'verify_in_mongodb_atlas_cluster_settings',
            },
        }
        
        # Check MongoDB
        try:
            db = settings.MONGODB
            db.command('ping')
            health['services']['mongodb'] = 'connected'
        except Exception as e:
            health['services']['mongodb'] = 'disconnected'
            health['status'] = 'degraded'
        
        # Check AI service (optional)
        try:
            from ai_assistant.services import get_llm_service
            llm = get_llm_service()
            health['services']['ai'] = 'available' if llm.is_available() else 'unavailable'
        except Exception:
            health['services']['ai'] = 'unavailable'
        
        status_code = status.HTTP_200_OK if health['status'] == 'healthy' else status.HTTP_503_SERVICE_UNAVAILABLE
        
        return success_response(
            data=health,
            message=f"System is {health['status']}",
            status_code=status_code
        )
