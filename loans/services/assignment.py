"""
Officer Assignment Service - Auto and manual assignment of loan applications.
"""
from accounts.models import LoanOfficer
from loans.models import LoanApplication
import logging

logger = logging.getLogger('loans')


def auto_assign_application(application):
    """
    Auto-assign application to officer with least workload.
    
    Returns:
        LoanOfficer or None if no active officers
    """
    officer = LoanOfficer.find_with_least_workload()
    
    if officer:
        application.assign_officer(officer.id)
        logger.info(f"Auto-assigned application {application.id} to officer {officer.id}")
        
        # Send notification to officer
        try:
            from notifications.services import get_email_sender
            sender = get_email_sender()
            sender.send_new_application_alert(
                officer_email=officer.email,
                officer_name=officer.full_name,
                customer_name="New Customer",  # Can be enhanced to get actual name
                loan_id=application.id,
                amount=application.requested_amount
            )
        except Exception as e:
            logger.warning(f"Failed to send assignment email: {e}")
        
        return officer
    
    logger.warning(f"No active officers to assign application {application.id}")
    return None


def manual_assign_application(application, officer_id):
    """
    Manually assign application to specific officer.
    
    Returns:
        LoanOfficer or None if officer not found
    """
    from bson import ObjectId
    
    try:
        officer = LoanOfficer.find_one({'_id': ObjectId(officer_id)})
    except:
        officer = LoanOfficer.find_one({'employee_id': officer_id})
    
    if not officer:
        return None
    
    if not officer.active:
        raise ValueError("Cannot assign to inactive officer")
    
    application.assign_officer(officer.id)
    logger.info(f"Manually assigned application {application.id} to officer {officer.id}")
    
    # Send notification to officer
    try:
        from notifications.services import get_email_sender
        sender = get_email_sender()
        sender.send_new_application_alert(
            officer_email=officer.email,
            officer_name=officer.full_name,
            customer_name="New Customer",
            loan_id=application.id,
            amount=application.requested_amount
        )
    except Exception as e:
        logger.warning(f"Failed to send assignment email: {e}")
    
    return officer


def get_officers_workload():
    """
    Get workload for all active officers.
    
    Returns:
        list of dicts with officer info and pending count
    """
    officers = LoanOfficer.find_active()
    
    return [{
        'id': officer.id,
        'employee_id': officer.employee_id,
        'name': officer.full_name,
        'email': officer.email,
        'pending_count': officer.get_pending_count(),
        'active': officer.active
    } for officer in officers]
