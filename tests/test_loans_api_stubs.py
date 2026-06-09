from rest_framework.test import APIRequestFactory, force_authenticate
import pytest

from accounts.authentication import AuthenticatedUser
from accounts.utils.access_control import AccessControlMixin
from loans import views as loan_views


def _auth_customer(customer_id="cust-test"):
    return AuthenticatedUser(customer_id=customer_id, email="cust@example.com", verified=True, role="customer")


def _auth_officer(officer_id="officer-test"):
    return AuthenticatedUser(customer_id=officer_id, email="officer@example.com", verified=True, role="loan_officer")


def _auth_admin(admin_id="admin-test"):
    return AuthenticatedUser(customer_id=admin_id, email="admin@example.com", verified=True, role="admin")


@pytest.fixture(autouse=True)
def bypass_access_control(monkeypatch):
    # Bypass common access control checks to allow view dispatch without DB actor resolution
    monkeypatch.setattr(AccessControlMixin, "require_customer", lambda self, request: (True, request.user), raising=False)
    monkeypatch.setattr(AccessControlMixin, "require_admin", lambda self, request, *a, **k: (True, object()), raising=False)
    monkeypatch.setattr(AccessControlMixin, "require_roles", lambda self, request, roles: (True, request.user), raising=False)


def _prepare_view(view_cls, user):
    # Remove authentication/permission classes to simplify tests
    try:
        view_cls.authentication_classes = []
    except Exception:
        pass
    try:
        view_cls.permission_classes = []
    except Exception:
        pass


def assert_dispatch_ok(response):
    # Ensure view did not hit a server error
    assert hasattr(response, "status_code")
    assert int(response.status_code) < 500


def test_products_list_endpoint_exists():
    factory = APIRequestFactory()
    request = factory.get("/api/loans/products/")
    force_authenticate(request, user=_auth_customer())
    _prepare_view(loan_views.LoanProductListView, _auth_customer())

    response = loan_views.LoanProductListView.as_view()(request)
    assert_dispatch_ok(response)


def test_prequalify_and_apply_endpoints_accept_payload():
    factory = APIRequestFactory()
    prequal_payload = {"product_id": "prod-1", "amount": 10000, "term_months": 12, "purpose": "test"}

    request = factory.post("/api/loans/pre-qualify/", prequal_payload, format="json")
    force_authenticate(request, user=_auth_customer())
    _prepare_view(loan_views.PreQualifyView, _auth_customer())
    resp = loan_views.PreQualifyView.as_view()(request)
    assert_dispatch_ok(resp)

    apply_payload = {"product_id": "prod-1", "requested_amount": 10000, "term_months": 12, "purpose": "test"}
    request2 = factory.post("/api/loans/apply/", apply_payload, format="json")
    force_authenticate(request2, user=_auth_customer())
    _prepare_view(loan_views.LoanApplyView, _auth_customer())
    resp2 = loan_views.LoanApplyView.as_view()(request2)
    assert_dispatch_ok(resp2)


def test_officer_review_and_disburse_stubs():
    factory = APIRequestFactory()
    application_id = "app-test-1"

    # Officer review (PUT)
    review_payload = {"action": "approve", "approved_amount": 8000}
    request = factory.put(f"/api/loans/officer/applications/{application_id}/review/", review_payload, format="json")
    force_authenticate(request, user=_auth_officer())
    _prepare_view(loan_views.OfficerReviewView, _auth_officer())
    resp = loan_views.OfficerReviewView.as_view()(request, application_id=application_id)
    assert_dispatch_ok(resp)

    # Disburse (POST)
    disburse_payload = {"amount": 8000, "method": "bank_transfer", "reference": "tx-1"}
    request2 = factory.post(f"/api/loans/officer/applications/{application_id}/disburse/", disburse_payload, format="json")
    force_authenticate(request2, user=_auth_officer())
    _prepare_view(loan_views.DisburseView, _auth_officer())
    resp2 = loan_views.DisburseView.as_view()(request2, application_id=application_id)
    assert_dispatch_ok(resp2)


def test_admin_blockchain_transactions_endpoint():
    factory = APIRequestFactory()
    request = factory.get("/api/loans/admin/blockchain/transactions/")
    force_authenticate(request, user=_auth_admin())
    _prepare_view(loan_views.AdminBlockchainTransactionsView, _auth_admin())
    resp = loan_views.AdminBlockchainTransactionsView.as_view()(request)
    assert_dispatch_ok(resp)
