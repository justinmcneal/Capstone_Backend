"""Focused unit and Mongo-backed integration coverage for the officer portal."""

from bson import ObjectId
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Customer, LoanOfficer
from loans.models import LoanApplication, LoanProduct
from loans.serializers import LoanReviewSerializer, MissingDocumentsRequestSerializer
from loans.views.officer_views import OfficerApplicationListView
from profiles.serializers import RiskReviewResolutionSerializer


def _auth(account, role):
    return AuthenticatedUser(
        customer_id=str(account.id),
        email=account.email,
        verified=True,
        role=role,
    )


def _officer(label):
    return LoanOfficer(
        employee_id=f"PORTAL-{label}-{ObjectId()}",
        first_name=label,
        last_name="Officer",
        email=f"portal-{label.lower()}-{ObjectId()}@example.com",
        password="hashed",
        department="Loans",
        active=True,
    ).save()


def _customer(label):
    return Customer(
        first_name=label,
        last_name="Customer",
        email=f"portal-{label.lower()}-{ObjectId()}@example.com",
        password="hashed",
        verified=True,
        active=True,
    ).save()


def test_review_serializer_requires_decision_specific_fields():
    approve = LoanReviewSerializer(data={"action": "approve"})
    reject = LoanReviewSerializer(
        data={"action": "reject", "rejection_reason": "   "}
    )

    assert not approve.is_valid()
    assert "approved_amount" in approve.errors
    assert not reject.is_valid()
    assert "rejection_reason" in reject.errors


def test_missing_document_serializer_deduplicates_without_reordering():
    serializer = MissingDocumentsRequestSerializer(
        data={
            "missing_documents": ["valid_id", "business_permit", "valid_id"],
            "reason": "Complete the application package.",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["missing_documents"] == [
        "valid_id",
        "business_permit",
    ]


def test_risk_resolution_serializer_rejects_terminal_state_without_note():
    serializer = RiskReviewResolutionSerializer(
        data={
            "status": "resolved",
            "resolution_note": "   ",
            "review_revision": 3,
        }
    )

    assert not serializer.is_valid()
    assert "resolution_note" in serializer.errors


def test_application_list_is_mongo_backed_role_and_assignment_scoped(monkeypatch):
    assigned_officer = _officer("Assigned")
    other_officer = _officer("Other")
    assigned_customer = _customer("Assigned")
    other_customer = _customer("Other")
    product = LoanProduct(
        name="Portal Harness Product",
        code=f"PHP-{ObjectId()}",
        min_amount=1000,
        max_amount=50000,
        interest_rate=0.01,
        min_term_months=1,
        max_term_months=12,
        active=True,
    ).save()
    assigned_application = LoanApplication(
        customer_id=str(assigned_customer.id),
        product_id=product.id,
        requested_amount=10000,
        term_months=6,
        purpose="Inventory",
        status="under_review",
        assigned_officer=str(assigned_officer.id),
    ).save()
    LoanApplication(
        customer_id=str(other_customer.id),
        product_id=product.id,
        requested_amount=12000,
        term_months=6,
        purpose="Equipment",
        status="under_review",
        assigned_officer=str(other_officer.id),
    ).save()

    factory = APIRequestFactory()
    request = factory.get(
        "/api/loans/officer/applications/", {"status": "all"}, format="json"
    )
    force_authenticate(request, user=_auth(assigned_officer, "loan_officer"))
    monkeypatch.setattr(
        OfficerApplicationListView, "authentication_classes", [], raising=False
    )
    monkeypatch.setattr(
        OfficerApplicationListView, "permission_classes", [], raising=False
    )

    response = OfficerApplicationListView.as_view()(request)

    assert response.status_code == 200
    assert response.data["data"]["total"] == 1
    assert [
        item["id"] for item in response.data["data"]["applications"]
    ] == [assigned_application.id]

    customer_request = factory.get(
        "/api/loans/officer/applications/", {"status": "all"}, format="json"
    )
    force_authenticate(
        customer_request, user=_auth(assigned_customer, "customer")
    )
    denied = OfficerApplicationListView.as_view()(customer_request)

    assert denied.status_code == 403
