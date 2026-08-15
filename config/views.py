"""
Core views for health check and system status.
"""

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView

from accounts.utils.response_helpers import error_response as _error_response
from accounts.utils.response_helpers import success_response

logger = logging.getLogger("config")
error_response = _error_response


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
            "status": "healthy",
            "services": {},
            "security": {
                "field_encryption": (
                    "enabled"
                    if bool(getattr(settings, "FIELD_ENCRYPTION_KEY", ""))
                    else "disabled"
                ),
                "tde": "verify_in_mongodb_atlas_cluster_settings",
            },
        }

        # Check MongoDB
        try:
            db = settings.MONGODB
            db.command("ping")
            health["services"]["mongodb"] = "connected"
        except Exception:
            health["services"]["mongodb"] = "disconnected"
            health["status"] = "degraded"

        if health["services"].get("mongodb") == "connected":
            try:
                from analytics.services.operations import analytics_health_summary

                analytics_health = analytics_health_summary(settings.MONGODB)
                health["services"]["analytics"] = analytics_health
                if not getattr(settings, "DEBUG", False) and not analytics_health["ready"]:
                    health["status"] = "degraded"
            except Exception:
                health["services"]["analytics"] = {
                    "ready": False,
                    "status": "unavailable",
                }
                if not getattr(settings, "DEBUG", False):
                    health["status"] = "degraded"

        # Check AI service (optional)
        try:
            from ai_assistant.services import get_llm_service

            llm = get_llm_service()
            health["services"]["ai"] = (
                "available" if llm.is_available() else "unavailable"
            )
        except Exception:
            health["services"]["ai"] = "unavailable"

        # The document classifier has its own approved-artifact boundary. In
        # development it can be unavailable while quality-only checks remain
        # usable; deployments may require an approved artifact explicitly.
        try:
            from documents.services.analyzer import get_document_model_health

            document_ai = get_document_model_health()
            health["services"]["document_ai"] = document_ai
            if (
                getattr(settings, "DOCUMENT_UPLOAD_AI_ANALYSIS", True)
                and not document_ai.get("ready", False)
            ):
                health["status"] = "degraded"
        except Exception:
            health["services"]["document_ai"] = {"status": "unavailable"}
            if getattr(settings, "DOCUMENT_UPLOAD_AI_ANALYSIS", True):
                health["status"] = "degraded"

        # Malware scanning is fail-closed when required. Keep the scanner on a
        # private network and expose only this readiness verdict, never scan
        # responses or uploaded content.
        try:
            from documents.services.malware import get_malware_scanner_health

            malware_scanner = get_malware_scanner_health()
            health["services"]["document_malware_scanner"] = malware_scanner
            if malware_scanner.get("required") and not malware_scanner.get("ready"):
                health["status"] = "degraded"
        except Exception:
            health["services"]["document_malware_scanner"] = {
                "ready": False,
                "status": "unavailable",
                "required": bool(
                    getattr(settings, "DOCUMENT_MALWARE_SCAN_REQUIRED", False)
                ),
            }
            if getattr(settings, "DOCUMENT_MALWARE_SCAN_REQUIRED", False):
                health["status"] = "degraded"

        status_code = (
            status.HTTP_200_OK
            if health["status"] == "healthy"
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )

        return success_response(
            data=health,
            message=f"System is {health['status']}",
            status_code=status_code,
        )
