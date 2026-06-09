"""
Officer Assignment Service - Auto and manual assignment of loan applications.
"""

from accounts.models import LoanOfficer
import logging

logger = logging.getLogger("loans")


def auto_assign_application(application):
    """
    Auto-assign application to officer with least workload.

    Returns:
        LoanOfficer or None if no active officers
    """
    officer = LoanOfficer.find_with_least_workload()

    if officer:
        application.assign_officer(officer.id)
        logger.info(
            f"Auto-assigned application {application.id} to officer {officer.id}"
        )

        # Send notification to officer
        try:
            from notifications.services import get_email_sender

            sender = get_email_sender()
            sender.send_new_application_alert(
                officer_email=officer.email,
                officer_name=officer.full_name,
                customer_name="New Customer",  # Can be enhanced to get actual name
                loan_id=application.id,
                amount=application.requested_amount,
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
        officer = LoanOfficer.find_one({"_id": ObjectId(officer_id)})
    except:
        officer = LoanOfficer.find_one({"employee_id": officer_id})

    if not officer:
        return None

    if not officer.active:
        raise ValueError("Cannot assign to inactive officer")

    application.assign_officer(officer.id)
    logger.info(
        f"Manually assigned application {application.id} to officer {officer.id}"
    )

    # Send notification to officer
    try:
        from notifications.services import get_email_sender

        sender = get_email_sender()
        sender.send_new_application_alert(
            officer_email=officer.email,
            officer_name=officer.full_name,
            customer_name="New Customer",
            loan_id=application.id,
            amount=application.requested_amount,
        )
    except Exception as e:
        logger.warning(f"Failed to send assignment email: {e}")

    return officer


def reassign_application(application, new_officer_id):
    """
    Reassign application from current officer to a new officer.

    Args:
        application: LoanApplication instance
        new_officer_id: ID of the new officer to assign to

    Returns:
        LoanOfficer (new officer) or None if officer not found

    Raises:
        ValueError: If application is not assigned or new officer is inactive
    """
    from bson import ObjectId

    if not application.assigned_officer:
        raise ValueError("Application is not currently assigned to any officer")

    # Get the current officer for logging
    try:
        current_officer = LoanOfficer.find_one(
            {"_id": ObjectId(application.assigned_officer)}
        )
    except:
        current_officer = None

    # Find and validate new officer
    try:
        new_officer = LoanOfficer.find_one({"_id": ObjectId(new_officer_id)})
    except:
        new_officer = LoanOfficer.find_one({"employee_id": new_officer_id})

    if not new_officer:
        return None

    if not new_officer.active:
        raise ValueError("Cannot reassign to inactive officer")

    # Use the reassign method on the application
    application.reassign(new_officer.id)

    logger.info(
        f"Reassigned application {application.id} from officer "
        f"{current_officer.id if current_officer else 'Unknown'} to officer {new_officer.id}"
    )

    # Send notification to new officer
    try:
        from notifications.services import get_email_sender

        sender = get_email_sender()
        sender.send_new_application_alert(
            officer_email=new_officer.email,
            officer_name=new_officer.full_name,
            customer_name="Customer",
            loan_id=application.id,
            amount=application.requested_amount,
        )
    except Exception as e:
        logger.warning(f"Failed to send reassignment email: {e}")

    return new_officer


def get_officers_workload(page=1, page_size=20, search=None):
    """
    Get workload for all active officers with pagination.

    Args:
        page: Page number (default 1)
        page_size: Items per page (default 20)
        search: Optional search term for officer name/email

    Returns:
        dict with officers list, pagination info
    """
    import re

    # Base query for active officers
    officers = LoanOfficer.find_active()

    # Apply search filter
    if search:
        search_regex = re.compile(re.escape(search), re.IGNORECASE)
        officers = [
            o
            for o in officers
            if search_regex.search(o.full_name) or search_regex.search(o.email)
        ]

    total = len(officers)

    # Apply pagination
    start = (page - 1) * page_size
    end = start + page_size
    paginated_officers = officers[start:end]

    return {
        "officers": [
            {
                "id": officer.id,
                "employee_id": officer.employee_id,
                "name": officer.full_name,
                "email": officer.email,
                "pending_count": officer.get_pending_count(),
                "active": officer.active,
            }
            for officer in paginated_officers
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,  # Ceiling division
    }
