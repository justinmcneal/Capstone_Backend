from django.urls import path
from profiles.views import (
    CustomerProfileView,
    BusinessProfileView,
    AlternativeDataView,
    ProfileSummaryView,
    NotificationPreferencesView,
)

app_name = "profiles"

urlpatterns = [
    # Customer Personal Profile
    path("", CustomerProfileView.as_view(), name="customer-profile"),
    # Business/MSME Profile
    path("business/", BusinessProfileView.as_view(), name="business-profile"),
    # Alternative Credit Data
    path("alternative-data/", AlternativeDataView.as_view(), name="alternative-data"),
    # Profile Summary
    path("summary/", ProfileSummaryView.as_view(), name="profile-summary"),
    # Notification Preferences
    path("notifications/", NotificationPreferencesView.as_view(), name="notifications"),
]
