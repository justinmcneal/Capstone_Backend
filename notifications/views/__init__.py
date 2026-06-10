"""
Notification views module.
"""
from notifications.views.notification_views import (
    NotificationListView,
    NotificationMarkReadView,
    NotificationMarkAllReadView,
    NotificationUnreadCountView,
    NotificationDeleteView,
    NotificationClearAllView,
    RegisterDeviceTokenView,
)

__all__ = [
    'NotificationListView',
    'NotificationMarkReadView',
    'NotificationMarkAllReadView',
    'NotificationUnreadCountView',
    'NotificationDeleteView',
    'NotificationClearAllView',
    'RegisterDeviceTokenView',
]
