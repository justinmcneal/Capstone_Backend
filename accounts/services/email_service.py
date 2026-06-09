from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


class CentralizedEmailService:
    def __init__(self):
        self.from_email = getattr(
            settings, "DEFAULT_FROM_EMAIL", "noreply@capstone.com"
        )
        self.email_enabled = self._is_email_configured()

    def _is_email_configured(self) -> bool:
        return bool(
            getattr(settings, "EMAIL_HOST_USER", None)
            and getattr(settings, "EMAIL_HOST_PASSWORD", None)
        )

    def send_email(
        self,
        to_emails: List[str],
        subject: str,
        message: str,
        html_message: Optional[str] = None,
    ) -> bool:
        """
        Send email with both plain text and HTML versions

        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            message: Plain text message
            html_message: Optional HTML version of the message

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        if not self.email_enabled:
            if settings.DEBUG:
                logger.warning(
                    f"Email not configured. Would send: {subject} to {to_emails}"
                )
                print(f"\n{'='*50}")
                print(f"EMAIL (DEBUG MODE): {subject}")
                print(f"To: {', '.join(to_emails)}")
                print(f"Message: {message}")
                print(f"{'='*50}\n")
            return False

        try:
            email = EmailMultiAlternatives(
                subject=subject, body=message, from_email=self.from_email, to=to_emails
            )

            if html_message:
                email.attach_alternative(html_message, "text/html")

            email.send(fail_silently=False)
            logger.info(f"Email sent successfully to {to_emails}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            if settings.DEBUG:
                print(f"Email error: {str(e)}")
            return False

    def send_template_email(
        self, to_emails: List[str], subject: str, template_name: str, context: dict
    ) -> bool:
        try:
            # Render HTML template
            html_message = render_to_string(f"email/{template_name}.html", context)

            # Create plain text version by stripping HTML tags
            import re

            plain_message = re.sub(r"<[^>]+>", "", html_message)
            plain_message = re.sub(r"\s+", " ", plain_message).strip()

            return self.send_email(
                to_emails=to_emails,
                subject=subject,
                message=plain_message,
                html_message=html_message,
            )

        except Exception as e:
            logger.error(f"Failed to send template email: {str(e)}")
            if settings.DEBUG:
                print(f"Template email error: {str(e)}")
                import traceback

                traceback.print_exc()
            return False


# Global instance
email_service = CentralizedEmailService()
