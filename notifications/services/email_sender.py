"""Email Sender Service - Sends email notifications.

Improvements:
- Type hints for clarity and mypy
- Default ThreadPoolExecutor when `send_async=True` and no executor provided
- Reuse SMTP connections via `get_connection()` for better throughput
- Fail-fast template errors and clear logging
"""
import logging
from typing import Optional, Dict, Any
from concurrent.futures import Executor, ThreadPoolExecutor
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.template import TemplateDoesNotExist
from django.conf import settings
from notifications.models.notification import Notification

logger = logging.getLogger("notifications")

# Prometheus metrics (optional, increments are safe when client not scraped)
try:
    from prometheus_client import Counter 

    EMAIL_SEND_SUCCESS_COUNTER = Counter(
        "notifications_email_send_success_total", "Total successful email sends"
    )
    EMAIL_SEND_FAILURE_COUNTER = Counter(
        "notifications_email_send_failure_total", "Total failed email sends"
    )
except Exception:
    EMAIL_SEND_SUCCESS_COUNTER = None
    EMAIL_SEND_FAILURE_COUNTER = None


class EmailSender:
    """Service for sending email notifications.

    Parameters
    - send_async: if True, send via a thread pool
    - executor: optional Executor; if None and send_async True, a ThreadPoolExecutor is created
    - use_celery: if True, enqueue send to Celery task
    """

    def __init__(
        self,
        *,
        send_async: bool = False,
        executor: Optional[Executor] = None,
        use_celery: bool = False,
    ) -> None:
        self.from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")
        self.send_async = send_async
        # Lazy-create a ThreadPoolExecutor when needed
        self.executor: Optional[Executor] = executor
        self._owns_executor = False
        if self.send_async and self.executor is None:
            max_workers = getattr(settings, "EMAIL_SENDER_THREADPOOL_MAX_WORKERS", 4)
            self.executor = ThreadPoolExecutor(max_workers=max_workers)
            self._owns_executor = True
        self.use_celery = use_celery

    def _do_send(
        self,
        to_email: str,
        subject: str,
        template_name: str,
        context: Dict[str, Any],
        notification: Optional[Notification] = None,
    ) -> bool:
        """Internal synchronous send implementation.

        Uses a shared SMTP connection via `get_connection()` and validates templates.
        """
        try:
            # Validate templates (render_to_string will raise TemplateDoesNotExist if missing)
            try:
                html_content = render_to_string(f"email/{template_name}.html", context)
                text_content = render_to_string(f"email/{template_name}.txt", context)
            except TemplateDoesNotExist as e:
                logger.error("Email template missing: %s", e)
                if notification:
                    notification.mark_failed(f"template missing: {e}")
                return False

            connection = get_connection()

            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=self.from_email,
                to=[to_email],
                connection=connection,
            )
            email.attach_alternative(html_content, "text/html")

            # Use connection to send (allows reuse/pooling under the hood)
            email.send(fail_silently=False)

            logger.info("Email sent: %s to %s", subject, to_email)
            if EMAIL_SEND_SUCCESS_COUNTER is not None:
                try:
                    EMAIL_SEND_SUCCESS_COUNTER.inc()
                except Exception:
                    logger.exception("Failed to increment email success metric")
            if notification:
                try:
                    notification.mark_sent()
                except Exception:
                    logger.exception("Failed to mark notification sent")
            return True
        except Exception as e:
            logger.exception("Email send failed")
            if EMAIL_SEND_FAILURE_COUNTER is not None:
                try:
                    EMAIL_SEND_FAILURE_COUNTER.inc()
                except Exception:
                    logger.exception("Failed to increment email failure metric")
            if notification:
                try:
                    notification.mark_failed(str(e))
                except Exception:
                    logger.exception("Failed to mark notification failed")
            return False

    def send(
        self,
        to_email: str,
        subject: str,
        template_name: str,
        context: Dict[str, Any],
        notification: Optional[Notification] = None,
    ) -> bool:
        """Public send API. May queue sending if configured for async.

        When `use_celery` is True, enqueues the Celery task and returns immediately.
        """
        # Celery integration: submit task to configured Celery task if requested
        if self.use_celery:
            try:
                from notifications.services.email_tasks import send_email_task

                notif_id = None
                if notification and getattr(notification, "_id", None):
                    notif_id = str(notification._id)
                # Fire-and-forget
                send_email_task.delay(to_email, subject, template_name, context, notif_id)
                return True
            except Exception as e:
                logger.exception("Failed to enqueue Celery email task")
                if notification:
                    try:
                        notification.mark_failed(str(e))
                    except Exception:
                        logger.exception("Failed to mark notification failed after enqueue error")
                return False
        if self.send_async and self.executor:
            # Queue the task and return immediately (queued)
            try:
                self.executor.submit(self._do_send, to_email, subject, template_name, context, notification)
                return True
            except Exception as e:
                logger.exception("Failed to queue email send")
                if notification:
                    try:
                        notification.mark_failed(str(e))
                    except Exception:
                        logger.exception("Failed to mark notification failed after queue error")
                return False
        # Synchronous send
        return self._do_send(to_email, subject, template_name, context, notification)
    
    def send_loan_submitted(
        self,
        customer_email,
        customer_name,
        loan_id,
        product_name,
        amount,
        customer_id=None,
    ):
        """Send loan submission confirmation"""
        notification = Notification(
            user_id=str(customer_id) if customer_id else None,
            recipient_email=customer_email,
            recipient_name=customer_name,
            notification_type='loan_submitted',
            subject='Loan Application Received',
            related_type='loan',
            related_id=loan_id
        )
        notification.save()
        
        return self.send(
            to_email=customer_email,
            subject='Your Loan Application Has Been Received',
            template_name='loan_submitted',
            context={
                'name': customer_name,
                'product_name': product_name,
                'amount': amount,
                'loan_id': loan_id
            },
            notification=notification
        )
    
    def send_loan_approved(
        self,
        customer_email,
        customer_name,
        loan_id,
        approved_amount,
        customer_id=None,
    ):
        """Send loan approval notification"""
        notification = Notification(
            user_id=str(customer_id) if customer_id else None,
            recipient_email=customer_email,
            recipient_name=customer_name,
            notification_type='loan_approved',
            subject='Loan Approved!',
            related_type='loan',
            related_id=loan_id
        )
        notification.save()
        
        return self.send(
            to_email=customer_email,
            subject='Congratulations! Your Loan Has Been Approved',
            template_name='loan_approved',
            context={
                'name': customer_name,
                'approved_amount': approved_amount,
                'loan_id': loan_id
            },
            notification=notification
        )
    
    def send_loan_rejected(
        self,
        customer_email,
        customer_name,
        loan_id,
        reason,
        customer_id=None,
    ):
        """Send loan rejection notification"""
        notification = Notification(
            user_id=str(customer_id) if customer_id else None,
            recipient_email=customer_email,
            recipient_name=customer_name,
            notification_type='loan_rejected',
            subject='Loan Application Update',
            related_type='loan',
            related_id=loan_id
        )
        notification.save()
        
        return self.send(
            to_email=customer_email,
            subject='Update on Your Loan Application',
            template_name='loan_rejected',
            context={
                'name': customer_name,
                'reason': reason,
                'loan_id': loan_id
            },
            notification=notification
        )
    
    def send_document_flagged(
        self,
        customer_email,
        customer_name,
        document_type,
        issues,
        document_id=None,
        customer_id=None,
    ):
        """Send document quality issue notification"""
        notification = Notification(
            user_id=str(customer_id) if customer_id else None,
            recipient_email=customer_email,
            recipient_name=customer_name,
            notification_type='document_flagged',
            subject='Document Needs Attention',
            related_type='document',
            related_id=document_id,
        )
        notification.save()
        
        return self.send(
            to_email=customer_email,
            subject='Action Required: Document Quality Issue',
            template_name='document_flagged',
            context={
                'name': customer_name,
                'document_type': document_type,
                'issues': issues
            },
            notification=notification
        )

    def send_document_approved(
        self,
        customer_email,
        customer_name,
        document_type,
        document_id=None,
        customer_id=None,
        notes='',
    ):
        """Send document approval notification to customer."""
        notification = Notification(
            user_id=str(customer_id) if customer_id else None,
            recipient_email=customer_email,
            recipient_name=customer_name,
            notification_type='document_verified',
            subject='Document Approved',
            related_type='document',
            related_id=document_id,
        )
        notification.save()

        return self.send(
            to_email=customer_email,
            subject='Your Document Has Been Approved',
            template_name='document_approved',
            context={
                'name': customer_name,
                'document_type': document_type,
                'document_id': document_id,
                'notes': notes,
            },
            notification=notification
        )

    def send_document_pending_review(
        self,
        reviewer_email,
        reviewer_name,
        customer_name,
        document_type,
        document_id,
        reviewer_user_id=None,
        reviewer_user_type='loan_officer',
    ):
        """Notify reviewers that a new document needs review."""
        notification = Notification(
            user_id=str(reviewer_user_id) if reviewer_user_id else None,
            user_type=reviewer_user_type,
            recipient_email=reviewer_email,
            recipient_name=reviewer_name,
            notification_type='document_pending_review',
            subject='New Document Pending Review',
            related_type='document',
            related_id=document_id,
        )
        notification.save()

        return self.send(
            to_email=reviewer_email,
            subject='New Customer Document Pending Review',
            template_name='document_pending_review',
            context={
                'reviewer_name': reviewer_name,
                'customer_name': customer_name,
                'document_type': document_type,
                'document_id': document_id,
            },
            notification=notification
        )
    
    def send_missing_documents_requested(
        self,
        customer_email,
        customer_name,
        loan_id,
        missing_documents,
        reason='',
        customer_id=None,
    ):
        """Send missing documents request notification"""
        notification = Notification(
            user_id=str(customer_id) if customer_id else None,
            recipient_email=customer_email,
            recipient_name=customer_name,
            notification_type='missing_documents_requested',
            subject='Additional Documents Needed',
            related_type='loan',
            related_id=loan_id
        )
        notification.save()
        
        return self.send(
            to_email=customer_email,
            subject='Action Required: Additional Documents Needed',
            template_name='missing_documents_requested',
            context={
                'name': customer_name,
                'loan_id': loan_id,
                'missing_documents': missing_documents,
                'reason': reason,
            },
            notification=notification
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
        notification = Notification(
            user_id=str(officer_user_id) if officer_user_id else None,
            recipient_email=officer_email,
            recipient_name=officer_name,
            notification_type='new_application',
            subject='New Loan Application',
            related_type='loan',
            related_id=loan_id,
            user_type='loan_officer'
        )
        notification.save()
        
        return self.send(
            to_email=officer_email,
            subject='New Loan Application for Review',
            template_name='new_application',
            context={
                'officer_name': officer_name,
                'customer_name': customer_name,
                'amount': amount,
                'loan_id': loan_id
            },
            notification=notification
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
    ):
        """Send loan disbursement notification"""
        notification = Notification(
            user_id=str(customer_id) if customer_id else None,
            recipient_email=customer_email,
            recipient_name=customer_name,
            notification_type='loan_disbursed',
            subject='Loan Disbursed!',
            related_type='loan',
            related_id=loan_id
        )
        notification.save()
        
        return self.send(
            to_email=customer_email,
            subject='Your Loan Has Been Disbursed!',
            template_name='loan_disbursed',
            context={
                'name': customer_name,
                'amount': amount,
                'method': method,
                'reference': reference,
                'loan_id': loan_id
            },
            notification=notification
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
    ):
        """Send payment received notification"""
        notification = Notification(
            user_id=str(customer_id) if customer_id else None,
            recipient_email=customer_email,
            recipient_name=customer_name,
            notification_type='payment_received',
            subject='Payment Received',
            related_type='loan',
            related_id=loan_id
        )
        notification.save()
        
        return self.send(
            to_email=customer_email,
            subject='Payment Received - Thank You!',
            template_name='payment_received',
            context={
                'name': customer_name,
                'amount': amount,
                'installment': installment,
                'remaining': remaining,
                'loan_id': loan_id
            },
            notification=notification
        )


# Singleton
_sender = None

def get_email_sender():
    global _sender
    if _sender is None:
        _sender = EmailSender()
    return _sender
