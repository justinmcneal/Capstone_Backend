from datetime import datetime, timezone

from bson import ObjectId
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Customer, LoanOfficer
from loans.models import LoanApplication, LoanPayment, LoanProduct
from loans.views.admin.workload import OfficerWorkloadView
from loans.views.customer_views import ApplicationDetailView
from loans.views.officer.payments import OfficerPaymentHistoryView, PaymentSearchView


def _authenticated_user(role, user_id):
    return AuthenticatedUser(
        customer_id=str(user_id),
        email=f"{role}@example.com",
        verified=True,
        role=role,
    )


def test_payment_search_default_path_paginates_and_summarizes_full_result(
    settings, monkeypatch
):
    customer_id = ObjectId()
    product_id = ObjectId()
    loan_id = ObjectId()
    settings.MONGODB["customer"].insert_one(
        {"_id": customer_id, "first_name": "Ana", "last_name": "Santos"}
    )
    settings.MONGODB["loan_products"].insert_one(
        {"_id": product_id, "name": "Micro Loan", "active": True}
    )
    settings.MONGODB["loan_applications"].insert_one(
        {
            "_id": loan_id,
            "customer_id": str(customer_id),
            "product_id": str(product_id),
            "status": "disbursed",
        }
    )
    settings.MONGODB["loan_payments"].insert_many(
        [
            {
                "loan_id": str(loan_id),
                "customer_id": str(customer_id),
                "amount": 100,
                "installment_number": 1,
                "payment_status": "posted",
                "loan_disbursed": True,
                "recorded_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "loan_id": str(loan_id),
                "customer_id": str(customer_id),
                "amount": 250,
                "installment_number": 2,
                "payment_status": "posted",
                "loan_disbursed": True,
                "recorded_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            },
        ]
    )
    monkeypatch.setattr(
        PaymentSearchView,
        "check_officer_permission",
        lambda self, request: (True, request.user),
    )

    request = APIRequestFactory().get(
        "/api/loans/officer/payments/search/?page=2&page_size=1"
    )
    force_authenticate(request, user=_authenticated_user("admin", ObjectId()))
    response = PaymentSearchView.as_view()(request)

    assert response.status_code == 200
    assert len(response.data["data"]["payments"]) == 1
    assert response.data["data"]["total"] == 2
    assert response.data["data"]["summary"] == {
        "total_amount": 350,
        "count": 2,
    }


def test_product_partial_validation_uses_stored_counterpart():
    from loans.serializers import LoanProductSerializer

    product = LoanProduct(
        min_amount=5_000,
        max_amount=50_000,
        min_term_months=3,
        max_term_months=24,
    )

    amount_serializer = LoanProductSerializer(
        instance=product, data={"min_amount": 60_000}, partial=True
    )
    term_serializer = LoanProductSerializer(
        instance=product, data={"max_term_months": 2}, partial=True
    )

    assert not amount_serializer.is_valid()
    assert "max_amount" in amount_serializer.errors
    assert not term_serializer.is_valid()
    assert "max_term_months" in term_serializer.errors


def test_draft_update_persists_preferred_disbursement_method(monkeypatch):
    customer_id = ObjectId()
    product_id = ObjectId()
    app = LoanApplication(
        _id=ObjectId(),
        customer_id=str(customer_id),
        product_id=str(product_id),
        status="draft",
    )
    product = LoanProduct(
        _id=product_id,
        name="Micro Loan",
        code="ML001",
        min_amount=5_000,
        max_amount=50_000,
        interest_rate=0.015,
        min_term_months=3,
        max_term_months=24,
    )
    monkeypatch.setattr(LoanApplication, "find_by_id", lambda app_id: app)
    monkeypatch.setattr(LoanProduct, "find_by_id", lambda product_id: product)
    monkeypatch.setattr(
        "loans.views.customer.applications.check_basic_eligibility",
        lambda *args, **kwargs: {"can_apply": True, "missing_requirements": []},
    )
    monkeypatch.setattr(
        "loans.views.customer.applications.qualify_customer",
        lambda **kwargs: {
            "can_apply": True,
            "eligible": True,
            "recommended_amount": 10_000,
        },
    )
    monkeypatch.setattr(app, "submit", lambda: setattr(app, "status", "submitted"))
    monkeypatch.setattr(
        "loans.views.customer.applications.AuditLog.log_action", lambda **kwargs: None
    )
    monkeypatch.setattr(
        ApplicationDetailView,
        "check_customer_permission",
        lambda self, request: (True, request.user),
    )

    request = APIRequestFactory().put(
        f"/api/loans/applications/{app.id}/",
        {
            "product_id": str(product_id),
            "requested_amount": 10_000,
            "term_months": 12,
            "preferred_disbursement_method": "cash",
        },
        format="json",
    )
    force_authenticate(request, user=_authenticated_user("customer", customer_id))
    response = ApplicationDetailView.as_view()(request, application_id=app.id)

    assert response.status_code == 200
    assert app.preferred_disbursement_method == "cash"
    assert response.data["data"]["preferred_disbursement_method"] == "cash"


def test_disbursed_application_blocks_product_mutation(settings):
    product_id = ObjectId()
    settings.MONGODB["loan_applications"].insert_one(
        {"product_id": str(product_id), "status": "disbursed"}
    )

    assert LoanApplication.count_by_product(product_id) == 1


def test_workload_resolves_customer_and_officer_names(settings, monkeypatch):
    customer = Customer(
        first_name="Ana",
        last_name="Santos",
        email="ana@example.com",
        password="hashed",
    ).save()
    officer = LoanOfficer(
        first_name="Omar",
        last_name="Reyes",
        email="omar@example.com",
        password="hashed",
    ).save()
    app = LoanApplication(
        _id=ObjectId(),
        customer_id=customer.id,
        assigned_officer=officer.id,
        status="under_review",
        internal_notes=[],
    )
    monkeypatch.setattr(
        "loans.views.admin.workload.get_officers_workload",
        lambda **kwargs: {
            "officers": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
            "total_pages": 0,
        },
    )
    monkeypatch.setattr(
        LoanApplication,
        "find_pending_paginated",
        lambda **kwargs: {
            "applications": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
            "total_pages": 0,
        },
    )
    monkeypatch.setattr(
        LoanApplication,
        "find_assigned_paginated",
        lambda **kwargs: {
            "applications": [app],
            "total": 1,
            "page": 1,
            "page_size": 20,
            "total_pages": 1,
        },
    )
    monkeypatch.setattr(
        OfficerWorkloadView,
        "check_admin_permission",
        lambda self, request: (True, request.user),
    )

    request = APIRequestFactory().get("/api/loans/admin/officers/workload/")
    force_authenticate(request, user=_authenticated_user("admin", ObjectId()))
    response = OfficerWorkloadView.as_view()(request)

    assigned = response.data["data"]["assigned_applications"][0]
    assert assigned["customer_name"] == "Ana Santos"
    assert assigned["assigned_officer_name"] == "Omar Reyes"


def test_officer_payment_history_total_excludes_unposted(monkeypatch):
    app = LoanApplication(_id=ObjectId(), assigned_officer=str(ObjectId()))
    payments = [
        LoanPayment(amount=100, payment_status="posted"),
        LoanPayment(amount=250, payment_status="pending_verification"),
    ]
    monkeypatch.setattr(LoanApplication, "find_by_id", lambda app_id: app)
    monkeypatch.setattr(
        "loans.views.officer.payments.payment_history_page",
        lambda loan_id, page, page_size: {
            "payments": payments,
            "total": 2,
            "page": page,
            "page_size": page_size,
            "total_pages": 1,
            "total_paid": 100,
        },
    )
    monkeypatch.setattr(
        OfficerPaymentHistoryView,
        "check_officer_permission",
        lambda self, request: (True, request.user),
    )
    monkeypatch.setattr(
        OfficerPaymentHistoryView,
        "check_application_scope",
        lambda self, request, application, **kwargs: (True, request.user),
    )

    request = APIRequestFactory().get(
        f"/api/loans/officer/applications/{app.id}/payments/"
    )
    force_authenticate(request, user=_authenticated_user("loan_officer", ObjectId()))
    response = OfficerPaymentHistoryView.as_view()(request, application_id=app.id)

    assert response.status_code == 200
    assert response.data["data"]["total_paid"] == 100
    assert response.data["data"]["payments"][1]["payment_status"] == (
        "pending_verification"
    )
