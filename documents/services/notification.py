"""
Document notification service.

Handles reviewer notifications for pending documents.
"""

import logging

from bson import ObjectId
from django.conf import settings

from accounts.models import Admin, Customer, LoanOfficer
from notifications.services import get_email_sender

logger = logging.getLogger("documents")


def get_customer_by_identifier(customer_id):
    """Resolve customer record from ObjectId/string IDs across legacy data shapes."""
    if not customer_id:
        return None

    from bson import ObjectId

    candidate_queries = []
    if isinstance(customer_id, ObjectId):
        candidate_queries.append({"_id": customer_id})
        customer_id = str(customer_id)
    else:
        try:
            candidate_queries.append({"_id": ObjectId(customer_id)})
        except Exception:
            pass

    candidate_queries.append({"_id": customer_id})
    candidate_queries.append({"customer_id": customer_id})

    for query in candidate_queries:
        customer = Customer.find_one(query)
        if customer:
            return customer
    return None


def get_display_name(user, fallback="User"):
    """Build a readable display name from common account model fields."""
    if not user:
        return fallback

    first_name = (getattr(user, "first_name", "") or "").strip()
    last_name = (getattr(user, "last_name", "") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name

    username = (getattr(user, "username", "") or "").strip()
    if username:
        return username

    email = (getattr(user, "email", "") or "").strip()
    if email:
        return email
    return fallback


def notify_reviewers_document_pending(document):
    """Notify active officers/admins that a document needs review."""
    sender = get_email_sender()
    customer = get_customer_by_identifier(document.customer_id)
    customer_name = get_display_name(customer, fallback="Customer")

    recipients = []
    seen_emails = set()

    customer_value = str(document.customer_id or "")
    customer_variants = [customer_value]
    if ObjectId.is_valid(customer_value):
        customer_variants.insert(0, ObjectId(customer_value))
    assigned_officer_ids = {
        str(row.get("assigned_officer"))
        for row in settings.MONGODB["loan_applications"].find(
            {
                "customer_id": {"$in": customer_variants},
                "assigned_officer": {"$nin": [None, ""]},
            },
            {"assigned_officer": 1},
        )
        if row.get("assigned_officer")
    }

    for officer in LoanOfficer.find({"active": True}):
        if not officer.has_permission("review_documents"):
            continue
        if assigned_officer_ids and str(officer.id) not in assigned_officer_ids:
            continue
        email = (officer.email or "").strip()
        if not email:
            continue
        email_key = email.lower()
        if email_key in seen_emails:
            continue
        seen_emails.add(email_key)
        recipients.append(
            {
                "email": email,
                "name": get_display_name(officer, fallback="Loan Officer"),
                "user_id": officer.id,
                "user_type": "loan_officer",
            }
        )

    for admin in Admin.find({"active": True}):
        if not admin.has_permission("review_documents"):
            continue
        email = (admin.email or "").strip()
        if not email:
            continue
        email_key = email.lower()
        if email_key in seen_emails:
            continue
        seen_emails.add(email_key)
        recipients.append(
            {
                "email": email,
                "name": get_display_name(admin, fallback="Admin"),
                "user_id": admin.id,
                "user_type": "admin",
            }
        )

    if not recipients:
        logger.warning(
            "No active reviewers found to notify for pending document %s",
            document.id,
        )
        return

    for recipient in recipients:
        try:
            sender.send_document_pending_review(
                reviewer_email=recipient["email"],
                reviewer_name=recipient["name"],
                customer_name=customer_name,
                document_type=document.document_type,
                document_id=document.id,
                reviewer_user_id=recipient["user_id"],
                reviewer_user_type=recipient["user_type"],
            )
        except Exception as e:
            logger.warning(
                "Failed pending-review email to %s for document %s: %s",
                recipient["email"],
                document.id,
                e,
            )
