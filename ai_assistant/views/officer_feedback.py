"""Loan-officer-only AI brief feedback HTTP boundary."""

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import error_response, success_response
from ai_assistant.models.officer_feedback import OfficerAIFeedback
from ai_assistant.serializers.officer import (
    OFFICER_FEEDBACK_INVALID_CODE,
    OFFICER_PRIVACY_BLOCKED_CODE,
    OfficerFeedbackSerializer,
)
from ai_assistant.services.officer_audit import record_officer_ai_feedback
from ai_assistant.services.officer_scope import (
    revalidate_officer_scope,
    resolve_officer_scope,
)

logger = logging.getLogger("ai_assistant")

OFFICER_FEEDBACK_UNKNOWN_CODE = "AI_FEEDBACK_REQUEST_UNKNOWN"


def _contains_validation_code(errors, code):
    if isinstance(errors, dict):
        return any(_contains_validation_code(value, code) for value in errors.values())
    if isinstance(errors, (list, tuple)):
        return any(_contains_validation_code(value, code) for value in errors)
    return getattr(errors, "code", None) == code


class OfficerFeedbackView(APIView):
    """Record one officer rating per generated review brief."""

    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = OfficerFeedbackSerializer(data=request.data)
        if not serializer.is_valid():
            if _contains_validation_code(
                serializer.errors, OFFICER_PRIVACY_BLOCKED_CODE
            ):
                return error_response(
                    message="Protected information cannot be processed by the officer assistant.",
                    code=OFFICER_PRIVACY_BLOCKED_CODE,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            return error_response(
                message="Invalid officer feedback request",
                code=OFFICER_FEEDBACK_INVALID_CODE,
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data

        scope, response = resolve_officer_scope(request, data["application_id"])
        if response is not None:
            return response

        # Feedback anchors to a completed assistant response so phantom
        # briefs cannot be rated.
        lease = settings.MONGODB['ai_chat_requests'].find_one(
            {
                'customer_id': str(scope.customer_id),
                'request_id': data["request_id"],
                'status': 'complete',
            }
        )
        if not lease:
            return error_response(
                message="No completed assistant response found for this request",
                code=OFFICER_FEEDBACK_UNKNOWN_CODE,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not revalidate_officer_scope(scope):
            return error_response(
                message="Officer access to this application is no longer available.",
                code="AI_OFFICER_SCOPE_CHANGED",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        try:
            stored = OfficerAIFeedback.record_feedback(
                officer_id=scope.officer_id,
                application_id=scope.application_id,
                customer_id=scope.customer_id,
                request_id=data["request_id"],
                conversation_id=data.get("conversation_id"),
                language=data["language"],
                rating=data["rating"],
                comment=data.get("comment", ""),
            )
        except ValueError:
            return error_response(
                message="Invalid officer feedback request",
                code=OFFICER_FEEDBACK_INVALID_CODE,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.error(
                "Officer AI feedback write failed",
                extra={"request_id": data["request_id"]},
            )
            return error_response(
                message="Failed to record officer AI feedback",
                code="AI_PROVIDER_ERROR",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        record_officer_ai_feedback(
            scope, data["request_id"], data["language"], rating=data["rating"]
        )
        return success_response(
            data={
                "rating": data["rating"],
                "request_id": data["request_id"],
                "updated": stored["updated"],
            },
            message="Officer AI feedback recorded",
        )
