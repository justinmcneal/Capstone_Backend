from django.urls import path

from profiles.views import OfficerCustomerProfilesListView, OfficerProfileView

app_name = "officer_profiles"

urlpatterns = [
    path("profiles/", OfficerCustomerProfilesListView.as_view(), name="list"),
    path(
        "profiles/<str:customer_id>/",
        OfficerProfileView.as_view(),
        name="detail",
    ),
]
