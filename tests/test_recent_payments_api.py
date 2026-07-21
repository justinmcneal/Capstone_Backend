from datetime import datetime, timezone

from bson import ObjectId
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from loans.views import RecentPaymentsView


def test_recent_payments_returns_newest_payment_with_customer_name(settings, monkeypatch):
    assert reverse("loans:officer-recent-payments") == "/api/loans/officer/payments/recent/"

    customer_id = ObjectId()
    older_payment_id = ObjectId()
    latest_payment_id = ObjectId()
    settings.MONGODB["customer"].insert_one(
        {"_id": customer_id, "first_name": "Ana", "last_name": "Santos"}
    )
    settings.MONGODB["loan_payments"].insert_many(
        [
            {
                "_id": older_payment_id,
                "customer_id": str(customer_id),
                "loan_id": "loan-1",
                "amount": 500,
                "reference": "PAY-OLD",
                "recorded_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "_id": latest_payment_id,
                "customer_id": str(customer_id),
                "loan_id": "loan-2",
                "amount": 750,
                "reference": "PAY-LATEST",
                "recorded_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            },
        ]
    )
    monkeypatch.setattr(
        RecentPaymentsView,
        "check_officer_permission",
        lambda self, request: (True, request.user),
    )

    request = APIRequestFactory().get("/api/loans/officer/payments/recent/?limit=1")
    force_authenticate(
        request,
        user=AuthenticatedUser(
            customer_id="admin-1",
            email="admin@example.com",
            verified=True,
            role="admin",
        ),
    )
    response = RecentPaymentsView.as_view()(request)

    assert response.status_code == 200
    assert response.data["data"]["payments"] == [
        {
            "id": str(latest_payment_id),
            "customer_name": "Ana Santos",
            "reference": "PAY-LATEST",
            "amount": 750,
            "recorded_at": "2026-01-02T00:00:00",
        }
    ]
