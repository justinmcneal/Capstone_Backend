from datetime import datetime, timezone

from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Customer, LoanOfficer
from loans.models import LoanApplication, LoanProduct, RepaymentSchedule
from loans.views.officer.active_loans import ActiveLoansView
from loans.views.officer.schedule import OfficerScheduleView


def _authenticated_officer(officer):
    return AuthenticatedUser(
        customer_id=officer.id,
        email=officer.email,
        verified=True,
        role="loan_officer",
    )


def test_active_schedule_remains_readable_when_application_status_is_stale():
    officer = LoanOfficer(
        employee_id="LO-SCHEDULE-1",
        first_name="Lina",
        last_name="Torres",
        email="lina.torres@example.com",
        password="hashed",
    ).save()
    customer = Customer(
        first_name="Joshua",
        last_name="Co",
        email="joshua.co@example.com",
        password="hashed",
    ).save()
    product = LoanProduct(name="Sari-Sari Store Microloan", code="SSM-1").save()
    application = LoanApplication(
        customer_id=customer.id,
        product_id=product.id,
        assigned_officer=officer.id,
        status="approved",
        approved_amount=20_000,
        term_months=3,
    ).save()
    RepaymentSchedule(
        loan_id=application.id,
        customer_id=customer.id,
        principal=20_000,
        interest_rate=0.025,
        term_months=3,
        monthly_payment=7_166.67,
        total_amount=21_500.01,
        total_interest=1_500.01,
        status="active",
        installments=[
            {
                "number": 1,
                "due_date": datetime(2026, 3, 23, tzinfo=timezone.utc),
                "principal": 6_666.67,
                "interest": 500,
                "total_amount": 7_166.67,
                "status": "paid",
                "paid_amount": 7_166.67,
            },
            {
                "number": 2,
                "due_date": datetime(2026, 4, 23, tzinfo=timezone.utc),
                "principal": 6_666.67,
                "interest": 500,
                "total_amount": 7_166.67,
                "status": "pending",
                "paid_amount": 0,
            },
            {
                "number": 3,
                "due_date": datetime(2026, 5, 23, tzinfo=timezone.utc),
                "principal": 6_666.66,
                "interest": 500.01,
                "total_amount": 7_166.67,
                "status": "pending",
                "paid_amount": 0,
            },
        ],
    ).save()
    user = _authenticated_officer(officer)
    factory = APIRequestFactory()

    search_request = factory.get(
        "/api/loans/officer/active-loans/", {"search": "Joshua"}
    )
    force_authenticate(search_request, user=user)
    search_response = ActiveLoansView.as_view()(search_request)

    assert search_response.status_code == 200
    assert search_response.data["data"]["loans"][0]["loan_id"] == application.id

    schedule_request = factory.get(
        f"/api/loans/officer/applications/{application.id}/schedule/"
    )
    force_authenticate(schedule_request, user=user)
    schedule_response = OfficerScheduleView.as_view()(
        schedule_request, application_id=application.id
    )

    assert schedule_response.status_code == 200
    assert schedule_response.data["data"]["loan_id"] == application.id
    assert schedule_response.data["data"]["paid_count"] == 1

