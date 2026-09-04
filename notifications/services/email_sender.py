"""
Email Sender Service - Sends email notifications.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from notifications.services.notification_creator import (
    create_and_broadcast_notification,
)
from notifications.services.preference_policy import evaluate_email_policy

logger = logging.getLogger("notifications")


class EmailSender:
    """
    Service for sending email notifications.
    """

    def __init__(self):
        self.from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")

    def send(
        self,
        to_email,
        subject,
        template_name,
        context,
        notification=None,
        email_policy_decision=None,
    ):
        """
        Send an email using a template.

        Args:
            to_email: Recipient email
            subject: Email subject
            template_name: Name of template (without extension)
            context: Context dict for template
            notification: Optional Notification object to update status

        Returns:
            bool: Success status
        """
        if email_policy_decision and not email_policy_decision["allowed"]:
            logger.info(
                "Email suppressed by notification policy: preference=%s policy=%s",
                email_policy_decision.get("preference_key"),
                email_policy_decision.get("policy_version"),
            )
            return True

        try:
            # Render templates
            html_content = render_to_string(f"email/{template_name}.html", context)
            text_content = render_to_string(f"email/{template_name}.txt", context)

            # Create email
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=self.from_email,
                to=[to_email],
            )
            email.attach_alternative(html_content, "text/html")

            # Send
            email.send(fail_silently=False)

            logger.info(
                "Notification email accepted by backend: notification=%s",
                getattr(notification, "id", None),
            )

            if notification:
                notification.mark_sent()

            return True

        except Exception as exc:  # noqa: BLE001
            logger.error("Notification email failed: error_type=%s", type(exc).__name__)

            if notification:
                notification.mark_failed("email_delivery_failed")

            return False

    @staticmethod
    def _customer_email_decision(customer_id, event_type):
        return evaluate_email_policy(
            user_id=customer_id,
            user_type="customer",
            event_type=event_type,
        )

    @staticmethod
    def _policy_metadata(decision):
        return {
            "email_policy": {
                "policy_version": decision["policy_version"],
                "preference_key": decision["preference_key"],
                "allowed": decision["allowed"],
                "reason": decision["reason"],
                "decided_at": decision["decided_at"].isoformat(),
            }
        }

    def send_loan_submitted(
        self,
        customer_email,
        customer_name,
        loan_id,
        product_name,
        amount,
        customer_id=None,
        delivery_key=None,
    ):
        """Send loan submission confirmation"""
        decision = self._customer_email_decision(customer_id, "loan_submitted")
        notification = create_and_broadcast_notification(
            user_id=str(customer_id) if customer_id else None,
            user_type="customer",
            notification_type="loan_submitted",
            subject="Loan Application Received",
            message=f"Your loan application for {product_name} in the amount of {amount} has been received.",
            recipient_email=customer_email,
            recipient_name=customer_name,
            related_type="loan",
            related_id=loan_id,
            channel="in_app",
            idempotency_key=delivery_key,
            metadata=self._policy_metadata(decision),
        )

        return self.send(
            to_email=customer_email,
            subject="Your Loan Application Has Been Received",
            template_name="loan_submitted",
            context={
                "name": customer_name,
                "product_name": product_name,
                "amount": amount,
                "loan_id": loan_id,
            },
            notification=notification,
            email_policy_decision=decision,
        )

    def send_loan_approved(
        self,
        customer_email,
        customer_name,
        loan_id,
        approved_amount,
        customer_id=None,
        delivery_key=None,
    ):
        """Send loan approval notification"""
        decision = self._customer_email_decision(customer_id, "loan_approved")
        notification = create_and_broadcast_notification(
            user_id=str(customer_id) if customer_id else None,
            user_type="customer",
            notification_type="loan_approved",
            subject="Loan Approved!",
            message=f"Congratulations! Your loan has been approved for {approved_amount}.",
            recipient_email=customer_email,
            recipient_name=customer_name,
            related_type="loan",
            related_id=loan_id,
            channel="in_app",
            idempotency_key=delivery_key,
            metadata=self._policy_metadata(decision),
        )

        return self.send(
            to_email=customer_email,
            subject="Congratulations! Your Loan Has Been Approved",
            template_name="loan_approved",
            context={
                "name": customer_name,
                "approved_amount": approved_amount,
                "loan_id": loan_id,
            },
            notification=notification,
            email_policy_decision=decision,
        )

    def send_loan_rejected(
        self,
        customer_email,
        customer_name,
        loan_id,
        reason,
        customer_id=None,
        delivery_key=None,
    ):
        """Send loan rejection notification"""
        decision = self._customer_email_decision(customer_id, "loan_rejected")
        notification = create_and_broadcast_notification(
            user_id=str(customer_id) if customer_id else None,
            user_type="customer",
            notification_type="loan_rejected",
            subject="Loan Application Update",
            message=f"Your loan application was unsuccessful. Reason: {reason}",
            recipient_email=customer_email,
            recipient_name=customer_name,
            related_type="loan",
            related_id=loan_id,
            channel="in_app",
            idempotency_key=delivery_key,
            metadata=self._policy_metadata(decision),
        )

        return self.send(
            to_email=customer_email,
            subject="Update on Your Loan Application",
            template_name="loan_rejected",
            context={"name": customer_name, "reason": reason, "loan_id": loan_id},
            notification=notification,
            email_policy_decision=decision,
        )

    def send_document_flagged(
        self,
        customer_email,
        customer_name,
        document_type,
        issues,
        document_id=None,
        customer_id=None,
        delivery_key=None,
    ):
        """Send document quality issue notification"""
        decision = self._customer_email_decision(customer_id, "document_flagged")
        notification = create_and_broadcast_notification(
            user_id=str(customer_id) if customer_id else None,
            user_type="customer",
            notification_type="document_flagged",
            subject="Document Needs Attention",
            message=f"There are issues with your {document_type} document.",
            recipient_email=customer_email,
            recipient_name=customer_name,
            related_type="document",
            related_id=document_id,
            channel="in_app",
            idempotency_key=delivery_key,
            metadata=self._policy_metadata(decision),
        )

        return self.send(
            to_email=customer_email,
            subject="Action Required: Document Quality Issue",
            template_name="document_flagged",
            context={
                "name": customer_name,
                "document_type": document_type,
                "issues": issues,
            },
            notification=notification,
            email_policy_decision=decision,
        )

    def send_document_approved(
        self,
        customer_email,
        customer_name,
        document_type,
        document_id=None,
        customer_id=None,
        notes="",
        delivery_key=None,
    ):
        """Send document approval notification to customer."""
        decision = self._customer_email_decision(customer_id, "document_verified")
        notification = create_and_broadcast_notification(
            user_id=str(customer_id) if customer_id else None,
            user_type="customer",
            notification_type="document_verified",
            subject="Document Approved",
            message=f"Your {document_type} document has been successfully verified.",
            recipient_email=customer_email,
            recipient_name=customer_name,
            related_type="document",
            related_id=document_id,
            channel="in_app",
            idempotency_key=delivery_key,
            metadata=self._policy_metadata(decision),
        )

        return self.send(
            to_email=customer_email,
            subject="Your Document Has Been Approved",
            template_name="document_approved",
            context={
                "name": customer_name,
                "document_type": document_type,
                "document_id": document_id,
                "notes": notes,
            },
            notification=notification,
            email_policy_decision=decision,
        )

    def send_document_pending_review(
        self,
        reviewer_email,
        reviewer_name,
        customer_name,
        document_type,
        document_id,
        reviewer_user_id=None,
        reviewer_user_type="loan_officer",
        delivery_key=None,
    ):
        """Notify reviewers that a new document needs review."""
        notification = create_and_broadcast_notification(
            user_id=str(reviewer_user_id) if reviewer_user_id else None,
            user_type=reviewer_user_type,
            notification_type="document_pending_review",
            subject="New Document Pending Review",
            message=f"A new {document_type} document for {customer_name} requires your review.",
            recipient_email=reviewer_email,
            recipient_name=reviewer_name,
            related_type="document",
            related_id=document_id,
            channel="in_app",
            idempotency_key=delivery_key,
        )

        return self.send(
            to_email=reviewer_email,
            subject="New Customer Document Pending Review",
            template_name="document_pending_review",
            context={
                "reviewer_name": reviewer_name,
                "customer_name": customer_name,
                "document_type": document_type,
                "document_id": document_id,
            },
            notification=notification,
        )

    def send_missing_documents_requested(
        self,
        customer_email,
        customer_name,
        loan_id,
        missing_documents,
        reason="",
        customer_id=None,
        delivery_key=None,
    ):
        """Send missing documents request notification"""
        decision = self._customer_email_decision(
            customer_id, "missing_documents_requested"
        )
        notification = create_and_broadcast_notification(
            user_id=str(customer_id) if customer_id else None,
            user_type="customer",
            notification_type="missing_documents_requested",
            subject="Additional Documents Needed",
            message="We need some additional documents from you to process your loan application.",
            recipient_email=customer_email,
            recipient_name=customer_name,
            related_type="loan",
            related_id=loan_id,
            channel="in_app",
            idempotency_key=delivery_key,
            metadata=self._policy_metadata(decision),
        )

        return self.send(
            to_email=customer_email,
            subject="Action Required: Additional Documents Needed",
            template_name="missing_documents_requested",
            context={
                "name": customer_name,
                "loan_id": loan_id,
                "missing_documents": missing_documents,
                "reason": reason,
            },
            notification=notification,
            email_policy_decision=decision,
        )

    def send_new_application_alert(
        self,
        officer_email,
        officer_name,
        customer_name,
        loan_id,
        amount,
        officer_user_id=None,
    ):
        """Send new application alert to loan officer"""
        notification = create_and_broadcast_notification(
            user_id=str(officer_user_id) if officer_user_id else None,
            user_type="loan_officer",
            notification_type="new_application",
            subject="New Loan Application",
            message=f"A new loan application from {customer_name} for {amount} has been assigned to you.",
            recipient_email=officer_email,
            recipient_name=officer_name,
            related_type="loan",
            related_id=loan_id,
            channel="in_app",
        )

        return self.send(
            to_email=officer_email,
            subject="New Loan Application for Review",
            template_name="new_application",
            context={
                "officer_name": officer_name,
                "customer_name": customer_name,
                "amount": amount,
                "loan_id": loan_id,
            },
            notification=notification,
        )

    def send_loan_disbursed(
        self,
        customer_email,
        customer_name,
        loan_id,
        amount,
        method,
        reference,
        customer_id=None,
        delivery_key=None,
    ):
        """Send loan disbursement notification"""
        decision = self._customer_email_decision(customer_id, "loan_disbursed")
        notification = create_and_broadcast_notification(
            user_id=str(customer_id) if customer_id else None,
            user_type="customer",
            notification_type="loan_disbursed",
            subject="Loan Disbursed!",
            message=f"Your loan of {amount} has been successfully disbursed.",
            recipient_email=customer_email,
            recipient_name=customer_name,
            related_type="loan",
            related_id=loan_id,
            channel="in_app",
            idempotency_key=delivery_key,
            metadata=self._policy_metadata(decision),
        )

        return self.send(
            to_email=customer_email,
            subject="Your Loan Has Been Disbursed!",
            template_name="loan_disbursed",
            context={
                "name": customer_name,
                "amount": amount,
                "method": method,
                "reference": reference,
                "loan_id": loan_id,
            },
            notification=notification,
            email_policy_decision=decision,
        )

    def send_payment_received(
        self,
        customer_email,
        customer_name,
        loan_id,
        amount,
        installment,
        remaining,
        customer_id=None,
        delivery_key=None,
    ):
        """Send payment received notification"""
        decision = self._customer_email_decision(customer_id, "payment_received")
        notification = create_and_broadcast_notification(
            user_id=str(customer_id) if customer_id else None,
            user_type="customer",
            notification_type="payment_received",
            subject="Payment Received",
            message=f"We have received your payment of {amount} for installment {installment}.",
            recipient_email=customer_email,
            recipient_name=customer_name,
            related_type="loan",
            related_id=loan_id,
            channel="in_app",
            idempotency_key=delivery_key,
            metadata=self._policy_metadata(decision),
        )

        return self.send(
            to_email=customer_email,
            subject="Payment Received - Thank You!",
            template_name="payment_received",
            context={
                "name": customer_name,
                "amount": amount,
                "installment": installment,
                "remaining": remaining,
                "loan_id": loan_id,
            },
            notification=notification,
            email_policy_decision=decision,
        )


# Singleton
_sender = None


def get_email_sender():
    global _sender
    if _sender is None:
        _sender = EmailSender()
    return _sender
