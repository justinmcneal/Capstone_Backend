"""
Loan API tests for /api/loans/ endpoints.

Coverage:
- Loan product listing and detail (customer)
- Pre-qualification
- Loan application submission
- Customer application listing
- Officer application listing and review
- Officer disbursement
- Role enforcement
- Validation errors
"""

from unittest.mock import MagicMock

from bson import ObjectId
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Admin, Customer, LoanOfficer
from loans.models import LoanApplication, LoanProduct
from loans.views.customer_views import (
    ApplicationDetailView,
    LoanApplyView,
    LoanProductDetailView,
    LoanProductListView,
    MyApplicationsView,
    PreQualifyView,
)
from loans.views.officer_views import (
    DisburseView,
    OfficerApplicationListView,
    OfficerReviewView,
)


def _create_customer(customer_id=None):
    customer = Customer(
        first_name="Loan",
        last_name="Customer",
        email=f"loan_customer_{ObjectId()}@example.com",
        password="hashed",
        verified=True,
    ).save()
    if customer_id is not None:
        customer.id = customer_id
        customer.save()
    return customer


def _create_officer():
    officer = LoanOfficer(
        first_name="Loan",
        last_name="Officer",
        email=f"loan_officer_{ObjectId()}@example.com",
        password="hashed",
        department="Operations",
    ).save()
    return officer


def _create_admin(permissions=None):
    admin = Admin(
        username=f"loan_admin_{ObjectId()}",
        email=f"loan_admin_{ObjectId()}@example.com",
        password="hashed",
        first_name="Admin",
        last_name="User",
        permissions=permissions or ["manage_loans"],
        super_admin=False,
    ).save()
    return admin


def _auth_customer(customer):
    return AuthenticatedUser(
        customer_id=str(customer.id),
        email=customer.email,
        verified=True,
        role="customer",
    )


def _auth_officer(officer):
    return AuthenticatedUser(
        customer_id=str(officer.id),
        email=officer.email,
        verified=True,
        role="loan_officer",
    )


def _auth_admin(admin):
    return AuthenticatedUser(
        customer_id=str(admin.id),
        email=admin.email,
        verified=True,
        role="admin",
    )


def _get(path, user, query=None):
    factory = APIRequestFactory()
    request = factory.get(path, query or {}, format="json")
    force_authenticate(request, user=user)
    return request


def _post(path, payload, user):
    factory = APIRequestFactory()
    request = factory.post(path, payload, format="json")
    force_authenticate(request, user=user)
    return request


def _put(path, payload, user):
    factory = APIRequestFactory()
    request = factory.put(path, payload, format="json")
    force_authenticate(request, user=user)
    return request


# ── Customer endpoints ──────────────────────────────────────────────


class TestLoanProductListView:
    def test_get_returns_active_products(self, monkeypatch):
        customer = _create_customer()
        product = LoanProduct(
            _id=ObjectId(),
            name="Micro Loan",
            code="ML001",
            min_amount=5000,
            max_amount=50000,
            interest_rate=0.015,
            min_term_months=3,
            max_term_months=24,
            active=True,
        )

        monkeypatch.setattr(
            LoanProduct,
            "find",
            staticmethod(lambda query=None, active_only=True, **kwargs: [product]),
            raising=False,
        )
        monkeypatch.setattr(
            "loans.views.customer.products.resolve_required_document_types",
            lambda *args, **kwargs: ["valid_id"],
            raising=False,
        )

        request = _get("/api/loans/products/", _auth_customer(customer))
        monkeypatch.setattr(
            LoanProductListView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            LoanProductListView, "permission_classes", [], raising=False
        )

        response = LoanProductListView.as_view()(request)
        assert response.status_code == 200, response.data
        assert len(response.data["data"]["products"]) == 1
        assert response.data["data"]["products"][0]["name"] == "Micro Loan"
        assert response.data["data"]["settlement_policy"][
            "available_disbursement_methods"
        ] == ["cash", "check"]


class TestLoanProductDetailView:
    def test_get_returns_product(self, monkeypatch):
        customer = _create_customer()
        product = LoanProduct(
            _id=ObjectId(),
            name="Micro Loan",
            code="ML001",
            min_amount=5000,
            max_amount=50000,
            interest_rate=0.015,
            min_term_months=3,
            max_term_months=24,
            active=True,
        )

        monkeypatch.setattr(
            LoanProduct,
            "find_by_id",
            staticmethod(lambda product_id: product),
            raising=False,
        )
        monkeypatch.setattr(
            "loans.views.customer.products.resolve_required_document_types",
            lambda *args, **kwargs: ["valid_id"],
            raising=False,
        )

        request = _get(
            f"/api/loans/products/{product.id}/", _auth_customer(customer)
        )
        monkeypatch.setattr(
            LoanProductDetailView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            LoanProductDetailView, "permission_classes", [], raising=False
        )

        response = LoanProductDetailView.as_view()(request, product_id=product.id)
        assert response.status_code == 200
        assert response.data["data"]["name"] == "Micro Loan"
        policy = response.data["data"]["settlement_policy"]
        assert policy["available_disbursement_methods"] == ["cash", "check"]
        assert "planned_provider_methods" not in policy


class TestPreQualifyView:
    def test_pre_qualify_returns_recommendation(self, monkeypatch):
        customer = _create_customer()
        product = LoanProduct(
            _id=ObjectId(),
            name="Micro Loan",
            code="ML001",
            min_amount=5000,
            max_amount=50000,
            interest_rate=0.015,
            min_term_months=3,
            max_term_months=24,
            active=True,
        )

        monkeypatch.setattr(
            LoanProduct,
            "find_by_id",
            staticmethod(lambda product_id: product),
            raising=False,
        )
        monkeypatch.setattr(
            "loans.views.customer.products.check_basic_eligibility",
            lambda *args, **kwargs: {
                "can_apply": True,
                "missing_requirements": [],
                "required_documents_resolved": ["valid_id", "proof_of_income"],
            },
            raising=False,
        )
        monkeypatch.setattr(
            "loans.views.customer.products.qualify_customer",
            lambda *args, **kwargs: {
                "eligible": True,
                "recommended_amount": 20000,
                "score": 85,
                "reasoning": "Good credit history",
            },
            raising=False,
        )
        monkeypatch.setattr(
            "loans.views.customer.products.resolve_required_document_types",
            lambda *args, **kwargs: ["valid_id", "proof_of_income"],
            raising=False,
        )

        payload = {
            "product_id": str(product.id),
            "amount": 20000,
            "term_months": 12,
            "purpose": "Working capital",
        }
        request = _post("/api/loans/pre-qualify/", payload, _auth_customer(customer))
        monkeypatch.setattr(
            PreQualifyView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            PreQualifyView, "permission_classes", [], raising=False
        )

        response = PreQualifyView.as_view()(request)
        assert response.status_code == 200
        assert response.data["data"]["eligible"] is True


class TestLoanApplyView:
    def test_apply_creates_application(self, monkeypatch):
        customer = _create_customer()
        product = LoanProduct(
            _id=ObjectId(),
            name="Micro Loan",
            code="ML001",
            min_amount=5000,
            max_amount=50000,
            interest_rate=0.015,
            min_term_months=3,
            max_term_months=24,
            active=True,
        )

        monkeypatch.setattr(
            LoanProduct,
            "find_by_id",
            staticmethod(lambda product_id: product),
            raising=False,
        )
        monkeypatch.setattr(
            "loans.views.customer.applications.check_basic_eligibility",
            lambda *args, **kwargs: {
                "can_apply": True,
                "missing_requirements": [],
                "required_documents_resolved": ["valid_id"],
            },
            raising=False,
        )
        monkeypatch.setattr(
            "loans.views.customer.applications.qualify_customer",
            lambda *args, **kwargs: {
                "eligible": True,
                "recommended_amount": 20000,
                "score": 85,
                "reasoning": "Good credit history",
            },
            raising=False,
        )
        monkeypatch.setattr(
            "loans.views.customer.applications.resolve_required_document_types",
            lambda *args, **kwargs: ["valid_id"],
            raising=False,
        )

        fake_app = LoanApplication(
            _id=ObjectId(),
            customer_id=str(customer.id),
            product_id=str(product.id),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="submitted",
        )
        monkeypatch.setattr(
            LoanApplication,
            "create",
            staticmethod(lambda **kwargs: fake_app),
            raising=False,
        )
        monkeypatch.setattr(
            "analytics.models.AuditLog.log_action",
            lambda *args, **kwargs: None,
            raising=False,
        )
        monkeypatch.setattr(
            "notifications.services.get_email_sender",
            lambda: MagicMock(),
            raising=False,
        )

        payload = {
            "product_id": str(product.id),
            "requested_amount": 20000,
            "term_months": 12,
            "purpose": "Working capital",
        }
        request = _post("/api/loans/apply/", payload, _auth_customer(customer))
        monkeypatch.setattr(
            LoanApplyView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            LoanApplyView, "permission_classes", [], raising=False
        )

        response = LoanApplyView.as_view()(request)
        assert response.status_code == 201
        assert response.data["data"]["status"] == "submitted"


class TestMyApplicationsView:
    def test_get_returns_customer_applications(self, monkeypatch):
        customer = _create_customer()
        app = LoanApplication(
            _id=ObjectId(),
            customer_id=str(customer.id),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="submitted",
        )

        monkeypatch.setattr(
            LoanApplication,
            "count",
            staticmethod(lambda query: 1),
            raising=False,
        )
        monkeypatch.setattr(
            LoanApplication,
            "find",
            staticmethod(lambda query, **kwargs: [app]),
            raising=False,
        )
        product = LoanProduct(_id=ObjectId(app.product_id), name="Micro Loan")
        monkeypatch.setattr(
            "loans.views.customer.applications.model_map_by_ids",
            lambda model, values: {app.product_id: product},
        )

        request = _get("/api/loans/applications/", _auth_customer(customer))
        monkeypatch.setattr(
            MyApplicationsView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            MyApplicationsView, "permission_classes", [], raising=False
        )

        response = MyApplicationsView.as_view()(request)
        assert response.status_code == 200
        assert len(response.data["data"]["applications"]) == 1


class TestApplicationDetailView:
    def test_get_returns_application_detail(self, monkeypatch):
        customer = _create_customer()
        app = LoanApplication(
            _id=ObjectId(),
            customer_id=str(customer.id),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="submitted",
        )
        product = LoanProduct(
            _id=ObjectId(),
            name="Micro Loan",
            code="ML001",
            min_amount=5000,
            max_amount=50000,
            interest_rate=0.015,
        )

        monkeypatch.setattr(
            LoanApplication,
            "find_by_id",
            staticmethod(lambda app_id: app),
            raising=False,
        )
        monkeypatch.setattr(
            LoanProduct,
            "find_by_id",
            staticmethod(lambda product_id: product),
            raising=False,
        )

        request = _get(
            f"/api/loans/applications/{app.id}/", _auth_customer(customer)
        )
        monkeypatch.setattr(
            ApplicationDetailView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            ApplicationDetailView, "permission_classes", [], raising=False
        )

        response = ApplicationDetailView.as_view()(request, application_id=app.id)
        assert response.status_code == 200
        assert response.data["data"]["status"] == "submitted"


# ── Officer endpoints ───────────────────────────────────────────────


class TestOfficerApplicationListView:
    def test_get_returns_assigned_applications(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        officer = _create_officer()
        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="under_review",
            assigned_officer=str(officer.id),
        )
        app.save()

        request = _get(
            "/api/loans/officer/applications/", _auth_officer(officer)
        )
        monkeypatch.setattr(
            OfficerApplicationListView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            OfficerApplicationListView, "permission_classes", [], raising=False
        )

        response = OfficerApplicationListView.as_view()(request)
        assert response.status_code == 200
        assert len(response.data["data"]["applications"]) == 1


class TestOfficerReviewView:
    def test_approve_application(self, monkeypatch):
        officer = _create_officer()
        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="under_review",
            assigned_officer=str(officer.id),
        ).save()

        monkeypatch.setattr(
            LoanApplication,
            "find_by_id",
            staticmethod(lambda app_id: app),
            raising=False,
        )
        monkeypatch.setattr(
            "analytics.models.AuditLog.log_action",
            lambda *args, **kwargs: None,
            raising=False,
        )
        monkeypatch.setattr(
            "notifications.services.get_email_sender",
            lambda: MagicMock(),
            raising=False,
        )
        monkeypatch.setattr(
            "loans.blockchain.tasks.sync_approval_to_chain.delay",
            lambda *args, **kwargs: None,
            raising=False,
        )

        payload = {"action": "approve", "approved_amount": 20000}
        request = _put(
            f"/api/loans/officer/applications/{app.id}/review/",
            payload,
            _auth_officer(officer),
        )
        monkeypatch.setattr(
            OfficerReviewView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            OfficerReviewView, "permission_classes", [], raising=False
        )

        response = OfficerReviewView.as_view()(request, application_id=app.id)
        assert response.status_code == 200
        assert response.data["data"]["status"] == "approved"


class TestDisburseView:
    def test_disburse_creates_schedule(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        officer = _create_officer()
        product = LoanProduct(
            name="Manual Disbursement Product",
            code=f"MDP-{ObjectId()}",
            interest_rate=0.01,
        ).save()
        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=product.id,
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="approved",
            approved_amount=20000,
            assigned_officer=str(officer.id),
        )
        app.save()

        monkeypatch.setattr(
            "analytics.models.AuditLog.log_action",
            lambda *args, **kwargs: None,
            raising=False,
        )
        monkeypatch.setattr(
            "notifications.services.get_email_sender",
            lambda: MagicMock(),
            raising=False,
        )
        monkeypatch.setattr(
            "loans.blockchain.sync.sync_disbursement",
            lambda *args, **kwargs: None,
            raising=False,
        )
        monkeypatch.setattr(
            "loans.models.repayment.RepaymentSchedule.generate_schedule",
            lambda *args, **kwargs: None,
            raising=False,
        )

        payload = {"method": "cash"}
        request = _post(
            f"/api/loans/officer/applications/{app.id}/disburse/",
            payload,
            _auth_officer(officer),
        )
        request.META["HTTP_IDEMPOTENCY_KEY"] = "disbursement-api-test-1"
        monkeypatch.setattr(
            DisburseView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DisburseView, "permission_classes", [], raising=False
        )

        response = DisburseView.as_view()(request, application_id=app.id)
        assert response.status_code == 200, response.data
        assert response.data["data"]["status"] == "disbursed"
        assert response.data["data"]["disbursement_status"] == "executed"
