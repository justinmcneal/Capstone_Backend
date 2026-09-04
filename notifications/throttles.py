"""Authenticated rate limits for notification inbox operations."""

from django.conf import settings

from accounts.utils.throttles import SafeUserRateThrottle


class NotificationReadRateThrottle(SafeUserRateThrottle):
    scope = "notifications_read"

    def get_rate(self):
        return getattr(settings, "NOTIFICATIONS_READ_RATE", "600/hour")


class NotificationWriteRateThrottle(SafeUserRateThrottle):
    scope = "notifications_write"

    def get_rate(self):
        return getattr(settings, "NOTIFICATIONS_WRITE_RATE", "300/hour")


class NotificationDeviceTokenRateThrottle(SafeUserRateThrottle):
    scope = "notifications_device_token"

    def get_rate(self):
        return getattr(settings, "NOTIFICATIONS_DEVICE_TOKEN_RATE", "60/hour")
