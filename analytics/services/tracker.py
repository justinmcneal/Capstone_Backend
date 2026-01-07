"""
Audit Tracker Service - Log actions throughout the system.
"""
import logging
from analytics.models.audit_log import AuditLog

logger = logging.getLogger('analytics')


def log_action(user_id, user_type, action, description='', resource_type=None, 
               resource_id=None, details=None, ip_address='', user_email=''):
    """
    Log an action to the audit log.
    
    Args:
        user_id: ID of user performing action
        user_type: customer/loan_officer/admin
        action: Action name (from AUDIT_ACTIONS)
        description: Human-readable description
        resource_type: Type of resource affected (loan, document, etc.)
        resource_id: ID of affected resource
        details: Additional details dict
        ip_address: User's IP address
        user_email: User's email
    """
    try:
        log = AuditLog(
            user_id=str(user_id) if user_id else None,
            user_type=user_type,
            user_email=user_email,
            action=action,
            description=description,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            details=details or {},
            ip_address=ip_address
        )
        log.save()
        logger.info(f"Audit: {action} by {user_type} {user_id}")
        return log
    except Exception as e:
        logger.error(f"Failed to log audit: {e}")
        return None


def log_login(user_id, user_type, user_email, ip_address=''):
    """Log user login"""
    return log_action(
        user_id=user_id,
        user_type=user_type,
        action='user_login',
        description='User logged in',
        user_email=user_email,
        ip_address=ip_address
    )


def log_loan_submitted(user_id, loan_id, product_name, amount):
    """Log loan application submission"""
    return log_action(
        user_id=user_id,
        user_type='customer',
        action='loan_submitted',
        description=f'Submitted loan application for {product_name}',
        resource_type='loan',
        resource_id=loan_id,
        details={'product': product_name, 'amount': amount}
    )


def log_loan_approved(officer_id, loan_id, customer_id, amount):
    """Log loan approval"""
    return log_action(
        user_id=officer_id,
        user_type='loan_officer',
        action='loan_approved',
        description=f'Approved loan for ₱{amount:,.2f}',
        resource_type='loan',
        resource_id=loan_id,
        details={'customer_id': customer_id, 'amount': amount}
    )


def log_loan_rejected(officer_id, loan_id, customer_id, reason):
    """Log loan rejection"""
    return log_action(
        user_id=officer_id,
        user_type='loan_officer',
        action='loan_rejected',
        description='Rejected loan application',
        resource_type='loan',
        resource_id=loan_id,
        details={'customer_id': customer_id, 'reason': reason}
    )


def log_document_uploaded(user_id, document_id, document_type):
    """Log document upload"""
    return log_action(
        user_id=user_id,
        user_type='customer',
        action='document_uploaded',
        description=f'Uploaded {document_type}',
        resource_type='document',
        resource_id=document_id,
        details={'document_type': document_type}
    )


def log_profile_updated(user_id, profile_type):
    """Log profile update"""
    return log_action(
        user_id=user_id,
        user_type='customer',
        action='profile_updated',
        description=f'Updated {profile_type} profile',
        resource_type='profile',
        details={'profile_type': profile_type}
    )
