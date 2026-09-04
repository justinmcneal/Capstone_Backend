"""Durable customer notification outbox for loan lifecycle events."""

import logging

from django.conf import settings

from loans.models import LoanNotificationDelivery
from loans.metrics import LOAN_NOTIFICATION_OUTCOMES, increment
from notifications.services import get_email_sender

logger = logging.getLogger("loans.notifications")


def _options():
    return {
        "max_attempts": max(
            1, int(getattr(settings, "LOAN_NOTIFICATION_MAX_ATTEMPTS", 5))
        ),
        "backoff_seconds": max(
            1, int(getattr(settings, "LOAN_NOTIFICATION_RETRY_BACKOFF_SECONDS", 60))
        ),
        "lease_seconds": max(
            30, int(getattr(settings, "LOAN_NOTIFICATION_LEASE_SECONDS", 300))
        ),
    }


def queue_customer_loan_notification(
    *, loan_id, event_type, event_key, customer, payload
):
    """Persist before broker publication so enqueue failures remain recoverable."""
    email = str(getattr(customer, "email", "") or "").strip()
    if not customer or not email:
        return {"created": False, "queued": False}
    delivery = LoanNotificationDelivery.ensure(
        loan_id=loan_id,
        event_type=event_type,
        event_key=event_key,
        recipient={
            "id": customer.id,
            "user_type": "customer",
            "email": email,
            "name": getattr(customer, "full_name", "") or email,
        },
        payload=payload,
    )
    from loans.tasks import deliver_loan_notification_task

    try:
        deliver_loan_notification_task.delay(delivery.id)
        queued = True
    except Exception:
        queued = False
        logger.exception(
            "Loan notification remains pending after enqueue failure: %s", delivery.id
        )
    return {"created": True, "queued": queued, "delivery_id": delivery.id}


def deliver_loan_notification(delivery_id):
    options = _options()
    delivery = LoanNotificationDelivery.claim(
        delivery_id, lease_seconds=options["lease_seconds"]
    )
    if not delivery:
        return "not_due"
    sender = get_email_sender()
    payload = dict(delivery.payload or {})
    common = {
        "customer_email": delivery.recipient_email,
        "customer_name": delivery.recipient_name,
        "loan_id": delivery.loan_id,
        "customer_id": delivery.recipient_user_id,
        "delivery_key": delivery.id,
    }
    try:
        if delivery.event_type == "submitted":
            sent = sender.send_loan_submitted(
                **common, product_name=payload["product_name"], amount=payload["amount"]
            )
        elif delivery.event_type == "approved":
            sent = sender.send_loan_approved(
                **common, approved_amount=payload["approved_amount"]
            )
        elif delivery.event_type == "rejected":
            sent = sender.send_loan_rejected(**common, reason=payload["reason"])
        elif delivery.event_type == "missing_documents":
            sent = sender.send_missing_documents_requested(
                **common,
                missing_documents=payload["missing_documents"],
                reason=payload.get("reason", "")
            )
        elif delivery.event_type == "disbursed":
            sent = sender.send_loan_disbursed(
                **common,
                amount=payload["amount"],
                method=payload["method"],
                reference=payload.get("reference", "")
            )
        elif delivery.event_type == "payment_received":
            sent = sender.send_payment_received(
                **common,
                amount=payload["amount"],
                installment=payload["installment"],
                remaining=payload["remaining"]
            )
        else:
            sent = False
        if sent is False:
            raise RuntimeError("delivery_rejected")
        delivery.mark_delivered()
        increment(
            LOAN_NOTIFICATION_OUTCOMES, event=delivery.event_type, outcome="delivered"
        )
        return "delivered"
    except Exception:  # noqa: BLE001 - persist a stable non-sensitive code
        logger.exception("Loan notification delivery failed: %s", delivery.id)
        delivery.defer(
            "delivery_failed",
            max_attempts=options["max_attempts"],
            backoff_seconds=options["backoff_seconds"],
        )
        outcome = (
            "failed"
            if delivery.attempt_count >= options["max_attempts"]
            else "retry_wait"
        )
        increment(
            LOAN_NOTIFICATION_OUTCOMES, event=delivery.event_type, outcome=outcome
        )
        return outcome


def reconcile_loan_notifications(limit=100):
    outcomes = {"delivered": 0, "retry_wait": 0, "failed": 0, "not_due": 0}
    for delivery_id in LoanNotificationDelivery.due_ids(limit=limit):
        outcome = deliver_loan_notification(delivery_id)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return outcomes
