"""
Email Sender Service - Sends email notifications.
"""
import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from notifications.models.notification import Notification

logger = logging.getLogger('notifications')


class EmailSender:
    """
    Service for sending email notifications.
    """
    
    def __init__(self):
        self.from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com')
    
    def send(self, to_email, subject, template_name, context, notification=None):
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
        try:
            # Render templates
            html_content = render_to_string(f'email/{template_name}.html', context)
            text_content = render_to_string(f'email/{template_name}.txt', context)
            
            # Create email
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=self.from_email,
                to=[to_email]
            )
            email.attach_alternative(html_content, 'text/html')
            
            # Send
            email.send(fail_silently=False)
            
            logger.info(f"Email sent: {subject} to {to_email}")
            
            if notification:
                notification.mark_sent()
            
            return True
            
        except Exception as e:
            logger.error(f"Email send failed: {str(e)}")
            
            if notification:
                notification.mark_failed(str(e))
            
            return False
    
    def send_loan_submitted(self, customer_email, customer_name, loan_id, product_name, amount):
        """Send loan submission confirmation"""
        notification = Notification(
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
    
    def send_loan_approved(self, customer_email, customer_name, loan_id, approved_amount):
        """Send loan approval notification"""
        notification = Notification(
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
    
    def send_loan_rejected(self, customer_email, customer_name, loan_id, reason):
        """Send loan rejection notification"""
        notification = Notification(
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
    
    def send_document_flagged(self, customer_email, customer_name, document_type, issues):
        """Send document quality issue notification"""
        notification = Notification(
            recipient_email=customer_email,
            recipient_name=customer_name,
            notification_type='document_flagged',
            subject='Document Needs Attention',
            related_type='document'
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
    
    def send_missing_documents_requested(
        self,
        customer_email,
        customer_name,
        loan_id,
        missing_documents,
        reason='',
    ):
        """Send missing documents request notification"""
        notification = Notification(
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
    
    def send_new_application_alert(self, officer_email, officer_name, customer_name, loan_id, amount):
        """Send new application alert to loan officer"""
        notification = Notification(
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
    
    def send_loan_disbursed(self, customer_email, customer_name, loan_id, amount, method, reference):
        """Send loan disbursement notification"""
        notification = Notification(
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
    
    def send_payment_received(self, customer_email, customer_name, loan_id, amount, installment, remaining):
        """Send payment received notification"""
        notification = Notification(
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
