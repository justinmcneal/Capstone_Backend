"""Auto and manual loan-application assignment services."""

import logging

from bson import ObjectId
from django.conf import settings

from accounts.models import Customer, LoanOfficer
from loans.models import LoanApplication

logger = logging.getLogger("loans")


def _find_by_id(model, raw_id):
    if not raw_id:
        return None

    if isinstance(raw_id, ObjectId):
        account = model.find_one({"_id": raw_id})
        return account or model.find_one({"_id": str(raw_id)})

    text_id = str(raw_id)
    if ObjectId.is_valid(text_id):
        account = model.find_one({"_id": ObjectId(text_id)})
        if account:
            return account
    return model.find_one({"_id": text_id})


def _find_officer(officer_id):
    if not officer_id:
        return None
    officer = _find_by_id(LoanOfficer, officer_id)
    if officer:
        return officer
    return LoanOfficer.find_one({"employee_id": str(officer_id)})


def _assignment_party(account, user_type=None):
    if not account:
        return None
    return {
        "id": account.id,
        "user_type": user_type or getattr(account, "role", "loan_officer"),
        "name": account.full_name or account.email,
        "email": account.email,
    }


def _actor_identity(account):
    if not account:
        return None, "system"
    actor_id = getattr(account, "id", None) or getattr(account, "_id", None)
    actor_type = getattr(account, "role", None) or "admin"
    return str(actor_id) if actor_id else None, str(actor_type)


def _notify_assignment_change(
    application,
    *,
    assigned_by,
    assigned_to=None,
    previous_assignee=None,
    transition_id=None,
):
    """Publish assignment notifications without affecting assignment success."""
    try:
        from notifications.services import publish_assignment_notifications

        customer = _find_by_id(Customer, application.customer_id)
        entity_name = (
            f"{customer.full_name}'s loan application"
            if customer and customer.full_name
            else f"Loan application {application.id}"
        )

        publish_assignment_notifications(
            entity_name=entity_name,
            assigned_by=_assignment_party(assigned_by, "admin"),
            assigned_to=_assignment_party(assigned_to),
            previous_assignee=_assignment_party(previous_assignee),
            related_type="loan",
            related_id=application.id,
            transition_id=transition_id,
        )
    except Exception:
        logger.exception(
            "Failed to publish assignment notifications for application %s",
            application.id,
        )


def auto_assign_application(application):
    """
    Auto-assign application to officer with least workload.

    Returns:
        LoanOfficer or None if no active officers
    """
    officer = LoanOfficer.find_with_least_workload()

    if officer:
        previous_officer = _find_officer(application.assigned_officer)
        if previous_officer and previous_officer.id == officer.id:
            return officer

        application.assign_officer(officer.id, actor_id=None, actor_type="system")
        logger.info(
            "Auto-assigned application %s to officer %s",
            application.id,
            officer.id,
        )

        _notify_assignment_change(
            application,
            assigned_by=None,
            assigned_to=officer,
            previous_assignee=previous_officer,
            transition_id=getattr(application, "last_transition_id", None),
        )

        return officer

    logger.warning(f"No active officers to assign application {application.id}")
    return None


def manual_assign_application(application, officer_id, assigned_by=None):
    """
    Manually assign application to specific officer.

    Returns:
        LoanOfficer or None if officer not found
    """
    officer = _find_officer(officer_id)

    if not officer:
        return None

    if not officer.active:
        raise ValueError("Cannot assign to inactive officer")

    previous_officer = _find_officer(application.assigned_officer)
    if previous_officer and previous_officer.id == officer.id:
        return officer

    actor_id, actor_type = _actor_identity(assigned_by)
    application.assign_officer(
        officer.id, actor_id=actor_id, actor_type=actor_type
    )
    logger.info(
        "Manually assigned application %s to officer %s",
        application.id,
        officer.id,
    )

    _notify_assignment_change(
        application,
        assigned_by=assigned_by,
        assigned_to=officer,
        previous_assignee=previous_officer,
        transition_id=getattr(application, "last_transition_id", None),
    )

    return officer


def reassign_application(application, new_officer_id, assigned_by=None):
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
    if not application.assigned_officer:
        raise ValueError("Application is not currently assigned to any officer")

    # Get the current officer for logging
    current_officer = _find_officer(application.assigned_officer)

    # Find and validate new officer
    new_officer = _find_officer(new_officer_id)

    if not new_officer:
        return None

    if not new_officer.active:
        raise ValueError("Cannot reassign to inactive officer")

    if current_officer and current_officer.id == new_officer.id:
        return new_officer

    # Use the reassign method on the application
    actor_id, actor_type = _actor_identity(assigned_by)
    application.reassign(
        new_officer.id, actor_id=actor_id, actor_type=actor_type
    )

    logger.info(
        "Reassigned application %s from officer %s to officer %s",
        application.id,
        current_officer.id if current_officer else "Unknown",
        new_officer.id,
    )

    _notify_assignment_change(
        application,
        assigned_by=assigned_by,
        assigned_to=new_officer,
        previous_assignee=current_officer,
        transition_id=getattr(application, "last_transition_id", None),
    )

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

    query = {"active": True}
    if search:
        search_regex = re.compile(re.escape(search), re.IGNORECASE)
        query["$or"] = [
            {"first_name": search_regex},
            {"last_name": search_regex},
            {"email": search_regex},
            {"employee_id": search_regex},
        ]

    db = settings.MONGODB
    officer_collection = db[LoanOfficer.collection_name]
    total = officer_collection.count_documents(query)
    cursor = (
        officer_collection.find(query)
        .sort([("last_name", 1), ("first_name", 1), ("_id", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    paginated_officers = [LoanOfficer.from_dict(document) for document in cursor]
    officer_ids = [officer.id for officer in paginated_officers if officer]
    workload = {
        row["_id"]: {
            "assigned": int(row.get("assigned", 0)),
            "pending": int(row.get("pending", 0)),
        }
        for row in db[LoanApplication.collection_name].aggregate(
            [
                {"$match": {"assigned_officer": {"$in": officer_ids}}},
                {
                    "$group": {
                        "_id": "$assigned_officer",
                        "assigned": {
                            "$sum": {
                                "$cond": [
                                    {
                                        "$in": [
                                            "$status",
                                            [
                                                "submitted",
                                                "under_review",
                                                "approved",
                                                "disbursed",
                                            ],
                                        ]
                                    },
                                    1,
                                    0,
                                ]
                            }
                        },
                        "pending": {
                            "$sum": {
                                "$cond": [
                                    {"$in": ["$status", ["submitted", "under_review"]]},
                                    1,
                                    0,
                                ]
                            }
                        },
                    }
                },
            ]
        )
    }

    return {
        "officers": [
            {
                "id": officer.id,
                "employee_id": officer.employee_id,
                "name": officer.full_name,
                "email": officer.email,
                "assigned_count": workload.get(officer.id, {}).get("assigned", 0),
                "pending_count": workload.get(officer.id, {}).get("pending", 0),
                "active": officer.active,
            }
            for officer in paginated_officers
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,  # Ceiling division
    }
