from django.urls import path

from profiles.views import (
    OfficerCustomerProfilesListView,
    OfficerProfileView,
    OfficerRiskReviewDetailView,
    OfficerRiskReviewListView,
)

app_name = "officer_profiles"

urlpatterns = [
    path("profiles/", OfficerCustomerProfilesListView.as_view(), name="list"),
    path(
        "profiles/<str:customer_id>/",
        OfficerProfileView.as_view(),
        name="detail",
    ),
    path("profile-risk-reviews/", OfficerRiskReviewListView.as_view(), name="reviews"),
    path(
        "profile-risk-reviews/<str:review_id>/",
        OfficerRiskReviewDetailView.as_view(),
        name="review-detail",
    ),
]
