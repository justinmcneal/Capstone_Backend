from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from accounts.serializers.contact_serializers import ContactSupportSerializer
from accounts.services.email_service import email_service
from accounts.utils.response_helpers import APIResponseHelper
import logging
import re

logger = logging.getLogger("support")


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


class ContactSupportView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        serializer = ContactSupportSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponseHelper.validation_error_response(serializer.errors)

        data = serializer.validated_data
        recipient = "sorianoeligabriel@gmail.com"

        subject = (
            f"[Support] {data['concern_type']} - {data['full_name']}"
        )
        body = (
            f"Name: {data['full_name']}\n"
            f"Email: {data['contact_email']}\n"
            f"Concern Type: {data['concern_type']}\n"
            f"Message:\n{data['message']}"
        )

        sent = email_service.send_email(
            to_emails=[recipient],
            subject=subject,
            message=body,
        )

        if not sent:
            logger.error(
                "Support request email failed for %s <%s>",
                data["full_name"],
                data["contact_email"],
            )
            return APIResponseHelper.server_error_response(
                "Failed to send support request. Please try again later."
            )

        logger.info(
            "Support request submitted by %s <%s> | type=%s",
            data["full_name"],
            data["contact_email"],
            data["concern_type"],
        )

        return APIResponseHelper.success_response(
            message="Your support request has been submitted. Our administrator will respond within 2 business hours.",
            status_code=201,
        )
