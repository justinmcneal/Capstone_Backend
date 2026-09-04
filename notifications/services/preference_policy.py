"""Versioned notification-channel preference policy."""

from datetime import datetime, timezone

from bson import ObjectId
from django.conf import settings

from accounts.models import Customer
from notifications.ownership import normalize_notification_user_type
from profiles.services.notification_preferences import get_preferences

EMAIL_PREFERENCE_BY_EVENT = {
    "loan_submitted": "email_loan_updates",
    "loan_approved": "email_loan_updates",
    "loan_rejected": "email_loan_updates",
    "loan_disbursed": "email_loan_updates",
    "missing_documents_requested": "email_loan_updates",
    "document_flagged": "email_loan_updates",
    "document_verified": "email_loan_updates",
    "payment_reminder": "email_payment_reminders",
    "promotion": "email_promotions",
}


def _find_customer(user_id):
    value = str(user_id or "").strip()
    if not value:
        return None
    if ObjectId.is_valid(value):
        customer = Customer.find_one({"_id": ObjectId(value)})
        if customer:
            return customer
    return Customer.find_one({"_id": value})


def evaluate_email_policy(*, user_id, user_type, event_type):
    """Return a stored-safe decision; mandatory/security email is never opted out."""
    normalized_type = normalize_notification_user_type(user_type)
    preference_key = EMAIL_PREFERENCE_BY_EVENT.get(str(event_type))
    decision = {
        "policy_version": settings.NOTIFICATIONS_PREFERENCE_POLICY_VERSION,
        "preference_key": preference_key,
        "allowed": True,
        "reason": "mandatory_or_operational",
        "decided_at": datetime.now(timezone.utc),
    }
    if normalized_type != "customer" or preference_key is None:
        return decision

    customer = _find_customer(user_id)
    if customer is None:
        return {
            **decision,
            "allowed": False,
            "reason": "customer_unavailable_fail_closed",
        }
    allowed = bool(get_preferences(customer)[preference_key])
    return {
        **decision,
        "allowed": allowed,
        "reason": "preference_allowed" if allowed else "preference_denied",
    }
