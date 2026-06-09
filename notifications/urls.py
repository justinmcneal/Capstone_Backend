"""
Notification URL Routes.

Customer-facing notification inbox API.
"""
from django.urls import path
from notifications.views import (
    NotificationListView,
    NotificationMarkReadView,
    NotificationMarkAllReadView,
    NotificationUnreadCountView,
    NotificationDeleteView,
    NotificationClearAllView,
    RegisterDeviceTokenView,
)

app_name = 'notifications'

urlpatterns = [
    # List notifications with pagination
    path('', NotificationListView.as_view(), name='notification-list'),
    
    # Get unread count (for badge)
    path('unread-count/', NotificationUnreadCountView.as_view(), name='notification-unread-count'),
    
    # Mark all notifications as read
    path('mark-all-read/', NotificationMarkAllReadView.as_view(), name='notification-mark-all-read'),
    
    # Mark single notification as read
    path('<str:notification_id>/read/', NotificationMarkReadView.as_view(), name='notification-mark-read'),
    
    # Delete all notifications
    path('clear-all/', NotificationClearAllView.as_view(), name='notification-clear-all'),

    # Delete single notification
    path('<str:notification_id>/', NotificationDeleteView.as_view(), name='notification-delete'),

    # Register FCM token
    path('register-token/', RegisterDeviceTokenView.as_view(), name='notification-register-token'),
]
