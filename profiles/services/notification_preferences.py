"""
Notification preferences service.

Reads and writes notification_preferences on the customer document.
"""

import logging
from datetime import datetime, timezone

from django.conf import settings
from pymongo import ReturnDocument

logger = logging.getLogger("profiles")


class UnknownPreferenceKeysError(ValueError):
    def __init__(self, message, unknown_keys):
        super().__init__(message)
        self.unknown_keys = unknown_keys


VALID_PREFERENCE_KEYS = {
    "email_loan_updates",
    "email_payment_reminders",
    "email_promotions",
}

DEFAULT_PREFERENCES = {
    "email_loan_updates": True,
    "email_payment_reminders": True,
    "email_promotions": False,
}


def get_preferences(customer):
    stored = getattr(customer, "notification_preferences", None)
    merged = dict(DEFAULT_PREFERENCES)
    if isinstance(stored, dict):
        for key in VALID_PREFERENCE_KEYS:
            value = stored.get(key)
            if type(value) is bool:
                merged[key] = value
    return merged


def update_preferences(customer, prefs):
    if not isinstance(prefs, dict):
        raise TypeError("preferences must be an object")

    unknown_keys = sorted([key for key in prefs if key not in VALID_PREFERENCE_KEYS])
    if unknown_keys:
        raise UnknownPreferenceKeysError(
            f"Unsupported keys: {', '.join(unknown_keys)}",
            unknown_keys=unknown_keys,
        )

    invalid_keys = sorted(key for key, value in prefs.items() if type(value) is not bool)
    if invalid_keys:
        raise TypeError(
            "Notification preference values must be JSON booleans: "
            + ", ".join(invalid_keys)
        )

    customer_id = getattr(customer, "_id", None)
    if customer_id is None:
        raise ValueError("Customer must be persisted before updating preferences")

    collection = settings.MONGODB[customer.collection_name]
    if prefs:
        updates = {
            f"notification_preferences.{key}": value for key, value in prefs.items()
        }
        updates["updated_at"] = datetime.now(timezone.utc)
        document = collection.find_one_and_update(
            {"_id": customer_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
    else:
        document = collection.find_one({"_id": customer_id})

    if document is None:
        raise ValueError("Customer not found while updating preferences")

    customer.notification_preferences = document.get("notification_preferences", {})
    current_prefs = get_preferences(customer)
    customer.notification_preferences = current_prefs

    logger.info("Notification preferences updated for customer %s", customer.id)

    return current_prefs
