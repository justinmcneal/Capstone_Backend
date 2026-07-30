"""
Notification preferences service.

Reads and writes notification_preferences on the customer document.
"""

import logging

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
    return getattr(customer, "notification_preferences", dict(DEFAULT_PREFERENCES))


def update_preferences(customer, prefs):
    if not isinstance(prefs, dict):
        raise TypeError("preferences must be an object")

    unknown_keys = sorted([key for key in prefs if key not in VALID_PREFERENCE_KEYS])
    if unknown_keys:
        raise UnknownPreferenceKeysError(
            f"Unsupported keys: {', '.join(unknown_keys)}",
            unknown_keys=unknown_keys,
        )

    current_prefs = dict(get_preferences(customer))
    for key in VALID_PREFERENCE_KEYS:
        if key in prefs:
            current_prefs[key] = bool(prefs[key])

    customer.notification_preferences = current_prefs
    customer.save()

    logger.info("Notification preferences updated for customer %s", customer.id)

    return current_prefs
