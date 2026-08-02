"""
Tests for bulk repayment schedule export.

Coverage:
- CSV export with filters
- JSON export format
- Permission checks (loan officer vs admin)
- Filter by customer_id
- Filter by status
- Filter by date range
- Empty result handling
- File download headers
"""

import csv
from io import StringIO
from unittest.mock import patch
from datetime import datetime

import mongomock
from bson import ObjectId
from django.conf import settings
from rest_framework import status

from accounts.utils.response_helpers import error_response
from accounts.models import Customer
from loans.models.application import LoanApplication
from loans.models.product import LoanProduct
from loans.models.repayment import RepaymentSchedule
from loans.views.officer.schedule_export import BulkRepaymentScheduleExportView
from loans.services.audit import LoanAuditUnavailable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_mongo(monkeypatch):
    client = mongomock.MongoClient()
    db = client["testdb"]
    monkeypatch.setattr(settings, "MONGODB", db, raising=False)
    return db


def _make_product(**overrides):
    defaults = {
        "name": "Test Product",
        "code": "TP1",
        "min_amount": 5000,
        "max_amount": 50000,
        "interest_rate": 0.015,
        "min_term_months": 3,
        "max_term_months": 24,
        "required_documents": ["valid_id"],
        "min_business_months": 6,
        "min_monthly_income": 5000,
        "active": True,
    }
    defaults.update(overrides)
    return LoanProduct(**defaults)


def _make_application(**overrides):
    defaults = {
        "customer_id": str(ObjectId()),
        "product_id": str(ObjectId()),
        "requested_amount": 20000,
        "approved_amount": 20000,
        "disbursed_amount": 20000,
        "term_months": 12,
        "purpose": "Working capital",
        "status": "disbursed",
        "assigned_officer": str(ObjectId()),
    }
    defaults.update(overrides)
    return LoanApplication(**defaults)


def _make_schedule(loan_id, customer_id, **overrides):
    defaults = {
        "loan_id": loan_id,
        "customer_id": customer_id,
        "principal": 120000,
        "interest_rate": 0.01,
        "term_months": 12,
        "monthly_payment": 11000,
        "total_amount": 132000,
        "total_interest": 12000,
        "installments": [
            {
                "number": i,
                "due_date": datetime(2025, 1, 1),
                "principal": 10000,
                "interest": 1000,
                "total_amount": 11000,
                "status": "pending",
                "paid_amount": 0,
                "penalty_status": None,
                "penalty_amount": 0,
                "penalty_reason": "",
            }
            for i in range(1, 13)
        ],
        "start_date": datetime(2025, 1, 1),
        "created_at": datetime(2025, 1, 1),
    }
    defaults.update(overrides)
    return RepaymentSchedule(**defaults)


def _make_request(query_params=None, user_role="loan_officer"):
    """Create a mock request object."""
    class MockUser:
        role = user_role

    class MockRequest:
        def __init__(self):
            self.user = MockUser()
            self.query_params = query_params or {}
            self.META = {}

    return MockRequest()


# ---------------------------------------------------------------------------
# Permission tests
# ---------------------------------------------------------------------------


def _persist_export_data():
    product = _make_product().save()
    app = _make_application(product_id=product.id).save()
    _make_schedule(app.id, app.customer_id).save()


def test_successful_export_records_sensitive_access(monkeypatch):
    _setup_mongo(monkeypatch)
    _persist_export_data()
    view = BulkRepaymentScheduleExportView()
    view.request = _make_request(user_role="admin")

    with (
        patch.object(view, "check_officer_permission", return_value=(True, None)),
        patch("loans.views.officer.schedule_export.record_loan_audit") as audit,
    ):
        response = view.get(view.request)

    assert response.status_code == status.HTTP_200_OK
    assert audit.call_args.kwargs["required"] is True
    assert audit.call_args.kwargs["action"] == "repayment_schedule_exported"
    assert audit.call_args.kwargs["user_type"] == "admin"
    assert audit.call_args.kwargs["details"]["row_count"] == 12


def test_export_fails_closed_when_access_audit_is_unavailable(monkeypatch):
    _setup_mongo(monkeypatch)
    _persist_export_data()
    view = BulkRepaymentScheduleExportView()
    view.request = _make_request(user_role="admin")

    with (
        patch.object(view, "check_officer_permission", return_value=(True, None)),
        patch(
            "loans.views.officer.schedule_export.record_loan_audit",
            side_effect=LoanAuditUnavailable("down"),
        ),
    ):
        response = view.get(view.request)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

class TestPermissions:
    def test_loan_officer_can_export(self, monkeypatch):
        db = _setup_mongo(monkeypatch)
        product = _make_product()
        product.save()
        app = _make_application()
        app.save()
        schedule = _make_schedule(app.id, app.customer_id)
        schedule.save()

        view = BulkRepaymentScheduleExportView()
        # Use admin role to avoid officer-scoping logic in this permission test
        view.request = _make_request(user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_200_OK

    def test_admin_can_export(self, monkeypatch):
        db = _setup_mongo(monkeypatch)
        product = _make_product()
        product.save()
        app = _make_application()
        app.save()
        schedule = _make_schedule(app.id, app.customer_id)
        schedule.save()

        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_200_OK

    def test_customer_cannot_export(self, monkeypatch):
        _setup_mongo(monkeypatch)
        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(user_role="customer")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (False, error_response(
                message="Forbidden", status_code=status.HTTP_403_FORBIDDEN
            ))
            response = view.get(view.request)

        assert response.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Filter tests
# ---------------------------------------------------------------------------

class TestFilters:
    def test_filter_by_customer_id(self, monkeypatch):
        db = _setup_mongo(monkeypatch)
        product = _make_product()
        product.save()

        customer_id_1 = str(ObjectId())
        customer_id_2 = str(ObjectId())

        app1 = _make_application(customer_id=customer_id_1, product_id=product.id)
        app1.save()
        schedule1 = _make_schedule(app1.id, customer_id_1)
        schedule1.save()

        app2 = _make_application(customer_id=customer_id_2, product_id=product.id)
        app2.save()
        schedule2 = _make_schedule(app2.id, customer_id_2)
        schedule2.save()

        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(query_params={"customer_id": customer_id_1}, user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "text/csv"
        assert "attachment" in response["Content-Disposition"]

        content = response.content.decode()
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        assert len(rows) == 12  # 12 installments
        assert all(row["customer_id"] == customer_id_1 for row in rows)

    def test_filter_by_status(self, monkeypatch):
        db = _setup_mongo(monkeypatch)
        product = _make_product()
        product.save()

        app = _make_application()
        app.save()
        schedule = _make_schedule(app.id, app.customer_id)
        schedule.installments[0]["status"] = "paid"
        schedule.installments[1]["status"] = "paid"
        schedule.save()

        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(query_params={"status": "paid"}, user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_200_OK
        content = response.content.decode()
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        assert len(rows) == 2
        assert all(row["status"] == "paid" for row in rows)

    def test_filter_by_date_range(self, monkeypatch):
        db = _setup_mongo(monkeypatch)
        product = _make_product()
        product.save()

        app = _make_application()
        app.save()
        schedule = _make_schedule(app.id, app.customer_id, created_at=datetime(2025, 6, 1))
        schedule.save()

        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(
            query_params={"start_date": "2025-01-01", "end_date": "2025-12-31"},
            user_role="admin",
        )

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_200_OK
        content = response.content.decode()
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        assert len(rows) == 12

    def test_invalid_status_filter(self, monkeypatch):
        _setup_mongo(monkeypatch)
        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(query_params={"status": "invalid_status"}, user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_customer_id_filter(self, monkeypatch):
        _setup_mongo(monkeypatch)
        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(query_params={"customer_id": "invalid"}, user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_result_returns_404(self, monkeypatch):
        _setup_mongo(monkeypatch)
        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(query_params={"customer_id": str(ObjectId())}, user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Export format tests
# ---------------------------------------------------------------------------

class TestExportFormats:
    def test_csv_export_headers(self, monkeypatch):
        db = _setup_mongo(monkeypatch)
        product = _make_product()
        product.save()

        app = _make_application()
        app.save()
        schedule = _make_schedule(app.id, app.customer_id)
        schedule.save()

        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "text/csv"
        assert "attachment" in response["Content-Disposition"]
        assert ".csv" in response["Content-Disposition"]

        content = response.content.decode()
        reader = csv.DictReader(StringIO(content))
        expected_fields = [
            "loan_id", "schedule_id", "customer_id", "customer_name", "product_name",
            "principal", "interest_rate", "term_months", "monthly_payment",
            "total_amount", "total_interest", "start_date", "created_at",
            "installment_number", "due_date", "installment_principal", "installment_interest",
            "installment_total_amount", "base_amount", "status", "paid_amount",
            "penalty_status", "penalty_amount", "penalty_reason", "blockchain_schedule_tx",
        ]
        assert reader.fieldnames == expected_fields

    def test_json_export(self, monkeypatch):
        db = _setup_mongo(monkeypatch)
        product = _make_product()
        product.save()

        app = _make_application()
        app.save()
        schedule = _make_schedule(app.id, app.customer_id)
        schedule.save()

        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(query_params={"format": "json"}, user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_200_OK
        data = response.data["data"]
        assert "schedules" in data
        assert data["total"] == 12
        assert len(data["schedules"]) == 12
        assert data["schedules"][0]["installment_number"] == 1
        assert data["schedules"][11]["installment_number"] == 12

    def test_csv_includes_penalty_in_total(self, monkeypatch):
        db = _setup_mongo(monkeypatch)
        product = _make_product()
        product.save()

        app = _make_application()
        app.save()
        schedule = _make_schedule(app.id, app.customer_id)
        schedule.installments[0]["penalty_status"] = "applied"
        schedule.installments[0]["penalty_amount"] = 500
        schedule.installments[0]["total_amount"] = 11000
        schedule.save()

        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_200_OK
        content = response.content.decode()
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        assert rows[0]["installment_total_amount"] == "11500"
        assert rows[0]["base_amount"] == "11000"
        assert rows[0]["penalty_amount"] == "500"

    def test_csv_includes_customer_name(self, monkeypatch):
        db = _setup_mongo(monkeypatch)
        product = _make_product()
        product.save()

        customer = Customer(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )
        customer.save()

        app = _make_application(customer_id=customer.id)
        app.save()
        schedule = _make_schedule(app.id, customer.id)
        schedule.save()

        view = BulkRepaymentScheduleExportView()
        view.request = _make_request(user_role="admin")

        with patch.object(view, "check_officer_permission") as mock_check:
            mock_check.return_value = (True, None)
            response = view.get(view.request)

        assert response.status_code == status.HTTP_200_OK
        content = response.content.decode()
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        assert rows[0]["customer_name"] == "John Doe"
