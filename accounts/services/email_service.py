import logging
from email.message import MIMEPart
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from accounts.utils.exception_types import NON_FATAL_EXCEPTIONS

logger = logging.getLogger(__name__)


class CentralizedEmailService:
    def __init__(self):
        self.from_email = getattr(
            settings, "DEFAULT_FROM_EMAIL", "noreply@capstone.com"
        )
        self.email_backend = getattr(
            settings,
            "EMAIL_BACKEND",
            "django.core.mail.backends.smtp.EmailBackend",
        )
        self.email_enabled = self._is_email_configured()

    def _is_email_configured(self) -> bool:
        if self.email_backend == "django.core.mail.backends.console.EmailBackend":
            return True

        placeholder_values = {
            "",
            "your-email@gmail.com",
            "your-16-character-app-password",
            "your-app-password",
        }

        host_user = str(getattr(settings, "EMAIL_HOST_USER", "")).strip().lower()
        host_password = (
            str(getattr(settings, "EMAIL_HOST_PASSWORD", "")).strip().lower()
        )
        if host_user in placeholder_values or host_password in placeholder_values:
            return False

        return bool(
            getattr(settings, "EMAIL_HOST_USER", None)
            and getattr(settings, "EMAIL_HOST_PASSWORD", None)
        )

    def send_email(
        self,
        to_emails: list[str],
        subject: str,
        message: str,
        html_message: str | None = None,
        inline_images: dict[str, Path] | None = None,
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

            for content_id, image_path in (inline_images or {}).items():
                try:
                    with image_path.open("rb") as image_file:
                        image = MIMEPart()
                        image.set_content(
                            image_file.read(),
                            maintype="image",
                            subtype="png",
                            disposition="inline",
                            filename=image_path.name,
                        )
                    image.add_header("Content-ID", f"<{content_id}>")
                    email.attach(image)
                except NON_FATAL_EXCEPTIONS as image_error:
                    logger.warning(
                        "Failed to attach inline email image %s: %s",
                        image_path,
                        image_error,
                    )

            email.send(fail_silently=False)
            logger.info(f"Email sent successfully to {to_emails}")
            return True

        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Failed to send email: {e!s}")
            if settings.DEBUG:
                print(f"Email error: {e!s}")
            return False

    def send_template_email(
        self, to_emails: list[str], subject: str, template_name: str, context: dict
    ) -> bool:
        try:
            context = {
                **context,
                "brand_logo_cid": "msme-pathways-logo",
            }
            logo_path = (
                settings.BASE_DIR / "accounts" / "static" / "email" / "msmeLogo.png"
            )
            inline_images = {}
            if logo_path.exists():
                inline_images["msme-pathways-logo"] = logo_path

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
                inline_images=inline_images,
            )

        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Failed to send template email: {e!s}")
            if settings.DEBUG:
                print(f"Template email error: {e!s}")
                import traceback

                traceback.print_exc()
            return False


# Global instance
email_service = CentralizedEmailService()
