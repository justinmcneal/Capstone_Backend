"""
Document notification service.

Handles reviewer notifications for pending documents.
"""

import logging

from bson import ObjectId
from django.conf import settings

from accounts.models import Admin, Customer, LoanOfficer
from documents.models import DocumentNotificationDelivery
from documents.services.recipients import resolve_review_recipients
from notifications.services import get_email_sender

logger = logging.getLogger("documents")


def _delivery_settings():
    return {
        "max_attempts": max(
            1, int(getattr(settings, "DOCUMENT_NOTIFICATION_MAX_ATTEMPTS", 5))
        ),
        "backoff_seconds": max(
            1,
            int(getattr(settings, "DOCUMENT_NOTIFICATION_RETRY_BACKOFF_SECONDS", 60)),
        ),
        "lease_seconds": max(
            30,
            int(getattr(settings, "DOCUMENT_NOTIFICATION_LEASE_SECONDS", 300)),
        ),
    }


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


def prepare_reviewer_notification_deliveries(document):
    """Persist one idempotent outbox record for each currently scoped reviewer.

    D-014: assigned customers notify only their currently assigned officer(s);
    unassigned customers fall back to permitted admins.
    """
    customer = get_customer_by_identifier(document.customer_id)
    customer_name = get_display_name(customer, fallback="Customer")

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

    resolution = resolve_review_recipients(
        assigned_officer_ids=assigned_officer_ids,
        officers=list(LoanOfficer.find({"active": True})),
        admins=(
            list(Admin.find({"active": True}))
            if not assigned_officer_ids
            else []
        ),
        get_display_name=get_display_name,
    )
    recipients = resolution["officers"] + resolution["admins"]

    if not recipients:
        logger.warning(
            "No eligible reviewers for pending document %s reason=%s",
            document.id,
            resolution["reason"],
        )
        return []

    delivery_ids = []
    for recipient in recipients:
        if not recipient.get("user_id"):
            logger.warning(
                "Skipping reviewer delivery with missing user id document=%s email=%s",
                document.id,
                recipient.get("email", ""),
            )
            continue
        delivery = DocumentNotificationDelivery.ensure(
            document=document,
            recipient=recipient,
            customer_name=customer_name,
        )
        delivery_ids.append(delivery.id)
    logger.info(
        "Reviewer deliveries document=%s created=%d reason=%s",
        document.id,
        len(delivery_ids),
        resolution["reason"],
    )
    return delivery_ids


def notify_reviewers_document_pending(document):
    """Persist and synchronously attempt each pending-review notification."""
    outcomes = {"created": 0, "delivered": 0, "retryable": 0}
    delivery_ids = prepare_reviewer_notification_deliveries(document)
    outcomes["created"] = len(delivery_ids)
    for delivery_id in delivery_ids:
        outcome = deliver_reviewer_notification(delivery_id)
        outcomes["delivered"] += outcome == "delivered"
        outcomes["retryable"] += outcome == "retry_wait"
    return outcomes


def queue_reviewer_notifications(document):
    """Persist deliveries before publishing tasks to the Celery broker."""
    from documents.tasks import deliver_reviewer_notification_task

    delivery_ids = prepare_reviewer_notification_deliveries(document)
    queued = 0
    for delivery_id in delivery_ids:
        try:
            deliver_reviewer_notification_task.delay(delivery_id)
            queued += 1
        except Exception:
            logger.exception(
                "Reviewer notification remains pending after enqueue failure "
                "document=%s delivery=%s",
                getattr(document, "id", ""),
                delivery_id,
            )
    logger.info(
        "Reviewer notifications queued document=%s created=%d queued=%d",
        getattr(document, "id", ""),
        len(delivery_ids),
        queued,
    )
    return {"created": len(delivery_ids), "queued": queued}


def deliver_document_notification(delivery_id):
    """Claim and deliver one outbox record without duplicating completed work."""
    options = _delivery_settings()
    delivery = DocumentNotificationDelivery.claim(
        delivery_id, lease_seconds=options["lease_seconds"]
    )
    if not delivery:
        return "not_due"
    try:
        sender = get_email_sender()
        if delivery.delivery_type == "pending_review":
            sent = sender.send_document_pending_review(
                reviewer_email=delivery.recipient_email,
                reviewer_name=delivery.recipient_name,
                customer_name=delivery.customer_name,
                document_type=delivery.document_type,
                document_id=delivery.document_id,
                reviewer_user_id=delivery.recipient_user_id,
                reviewer_user_type=delivery.recipient_user_type,
                delivery_key=delivery.id,
            )
        elif delivery.delivery_type == "approved":
            sent = sender.send_document_approved(
                customer_email=delivery.recipient_email,
                customer_name=delivery.recipient_name,
                document_type=delivery.document_type,
                document_id=delivery.document_id,
                customer_id=delivery.recipient_user_id,
                notes=delivery.notes,
                delivery_key=delivery.id,
            )
        elif delivery.delivery_type in {"rejected", "reupload_requested"}:
            sent = sender.send_document_flagged(
                customer_email=delivery.recipient_email,
                customer_name=delivery.recipient_name,
                document_type=delivery.document_type,
                issues=delivery.issues,
                document_id=delivery.document_id,
                customer_id=delivery.recipient_user_id,
                delivery_key=delivery.id,
            )
        else:
            delivery.defer("delivery_type_invalid", max_attempts=1)
            return "failed"
        if sent is False:
            raise RuntimeError("delivery_rejected")
        delivery.mark_delivered()
        return "delivered"
    except Exception:  # noqa: BLE001 - persisted as a non-sensitive error code
        logger.exception(
            "Pending-review notification delivery failed document=%s delivery=%s "
            "recipient=%s/%s attempt=%d",
            delivery.document_id,
            delivery_id,
            delivery.recipient_user_type,
            delivery.recipient_user_id,
            delivery.attempt_count,
        )
        delivery.defer(
            "delivery_failed",
            max_attempts=options["max_attempts"],
            backoff_seconds=options["backoff_seconds"],
        )
        return (
            "failed"
            if delivery.attempt_count >= options["max_attempts"]
            else "retry_wait"
        )


def reconcile_reviewer_notifications(limit=100):
    """Retry a bounded batch of due document-notification outbox records."""
    outcomes = {"delivered": 0, "retry_wait": 0, "failed": 0, "not_due": 0}
    for delivery_id in DocumentNotificationDelivery.due_ids(limit=limit):
        outcome = deliver_reviewer_notification(delivery_id)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return outcomes


def deliver_reviewer_notification(delivery_id):
    """Backward-compatible name for the generic document outbox delivery."""
    return deliver_document_notification(delivery_id)


def queue_customer_document_notification(
    document, customer, *, delivery_type, issues=None, notes=""
):
    """Persist a customer outcome before publishing its delivery task."""
    from documents.tasks import deliver_reviewer_notification_task

    delivery = DocumentNotificationDelivery.ensure_customer_outcome(
        document=document,
        customer=customer,
        delivery_type=delivery_type,
        issues=issues,
        notes=notes,
    )
    try:
        deliver_reviewer_notification_task.delay(delivery.id)
        return True
    except Exception:
        logger.exception(
            "Customer document notification remains pending after enqueue failure: %s",
            delivery.id,
        )
        return False
