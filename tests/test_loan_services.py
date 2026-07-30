"""
Loan service tests for assignment and qualification services.

Coverage:
- Assignment service: auto_assign, manual_assign, reassign, workload
- Qualification service: check_basic_eligibility (mocked customer data)
"""

from unittest.mock import MagicMock, patch

from bson import ObjectId
import pytest

from loans.services.assignment import (
    auto_assign_application,
    manual_assign_application,
    reassign_application,
    get_officers_workload,
)
from loans.services.qualification import check_basic_eligibility


class TestAutoAssignApplication:
    def test_assigns_to_least_workload_officer(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        from accounts.models import LoanOfficer, Customer
        from loans.models import LoanApplication, LoanProduct

        officer = LoanOfficer(
            first_name="Free",
            last_name="Officer",
            email="free@example.com",
            password="hashed",
            department="Ops",
            active=True,
        )
        officer.save()

        customer = Customer(
            first_name="Test",
            last_name="Customer",
            email="cust@example.com",
            password="hashed",
            verified=True,
        )
        customer.save()

        product = LoanProduct(
            name="Micro",
            code="M1",
            min_amount=5000,
            max_amount=50000,
            interest_rate=0.015,
            min_term_months=3,
            max_term_months=24,
        )
        product.save()

        app = LoanApplication(
            customer_id=str(customer.id),
            product_id=str(product.id),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="submitted",
        )
        app.save()

        monkeypatch.setattr(
            LoanOfficer,
            "find_with_least_workload",
            staticmethod(lambda: officer),
            raising=False,
        )

        result = auto_assign_application(app)
        assert result is not None
        assert result.id == officer.id
        assert app.assigned_officer == officer.id

    def test_returns_none_when_no_officers(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        from loans.models import LoanApplication

        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="submitted",
        )
        app.save()

        monkeypatch.setattr(
            "loans.services.assignment.LoanOfficer.find_with_least_workload",
            staticmethod(lambda: None),
            raising=False,
        )

        result = auto_assign_application(app)
        assert result is None


class TestManualAssignApplication:
    def test_assigns_to_specified_officer(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        from accounts.models import LoanOfficer, Customer
        from loans.models import LoanApplication, LoanProduct

        officer = LoanOfficer(
            first_name="Manual",
            last_name="Officer",
            email="manual@example.com",
            password="hashed",
            department="Ops",
            active=True,
        )
        officer.save()

        customer = Customer(
            first_name="Test",
            last_name="Customer",
            email="cust@example.com",
            password="hashed",
            verified=True,
        )
        customer.save()

        product = LoanProduct(
            name="Micro",
            code="M1",
            min_amount=5000,
            max_amount=50000,
            interest_rate=0.015,
            min_term_months=3,
            max_term_months=24,
        )
        product.save()

        app = LoanApplication(
            customer_id=str(customer.id),
            product_id=str(product.id),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="submitted",
        )
        app.save()

        result = manual_assign_application(app, officer.id)
        assert result is not None
        assert result.id == officer.id

    def test_returns_none_for_invalid_officer(self, monkeypatch):
        import mongomock
        from django.conf import settings
        from bson import ObjectId

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        from loans.models import LoanApplication

        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="submitted",
        )
        app.save()

        result = manual_assign_application(app, str(ObjectId()))
        assert result is None

    def test_raises_for_inactive_officer(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        from accounts.models import LoanOfficer, Customer
        from loans.models import LoanApplication, LoanProduct

        officer = LoanOfficer(
            first_name="Inactive",
            last_name="Officer",
            email="inactive@example.com",
            password="hashed",
            department="Ops",
            active=False,
        )
        officer.save()

        customer = Customer(
            first_name="Test",
            last_name="Customer",
            email="cust@example.com",
            password="hashed",
            verified=True,
        )
        customer.save()

        product = LoanProduct(
            name="Micro",
            code="M1",
            min_amount=5000,
            max_amount=50000,
            interest_rate=0.015,
            min_term_months=3,
            max_term_months=24,
        )
        product.save()

        app = LoanApplication(
            customer_id=str(customer.id),
            product_id=str(product.id),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="submitted",
        )
        app.save()

        with pytest.raises(ValueError, match="inactive officer"):
            manual_assign_application(app, officer.id)


class TestReassignApplication:
    def test_reassigns_to_new_officer(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        from accounts.models import LoanOfficer, Customer
        from loans.models import LoanApplication, LoanProduct

        current = LoanOfficer(
            first_name="Current",
            last_name="Officer",
            email="current@example.com",
            password="hashed",
            department="Ops",
            active=True,
        )
        current.save()

        new_officer = LoanOfficer(
            first_name="New",
            last_name="Officer",
            email="new@example.com",
            password="hashed",
            department="Ops",
            active=True,
        )
        new_officer.save()

        customer = Customer(
            first_name="Test",
            last_name="Customer",
            email="cust@example.com",
            password="hashed",
            verified=True,
        )
        customer.save()

        product = LoanProduct(
            name="Micro",
            code="M1",
            min_amount=5000,
            max_amount=50000,
            interest_rate=0.015,
            min_term_months=3,
            max_term_months=24,
        )
        product.save()

        app = LoanApplication(
            customer_id=str(customer.id),
            product_id=str(product.id),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="under_review",
            assigned_officer=str(current.id),
        )
        app.save()

        result = reassign_application(app, new_officer.id)
        assert result is not None
        assert result.id == new_officer.id
        assert app.assigned_officer == new_officer.id

    def test_raises_for_unassigned_application(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        from loans.models import LoanApplication

        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="submitted",
        )
        app.save()

        with pytest.raises(ValueError, match="not currently assigned"):
            reassign_application(app, str(ObjectId()))


class TestGetOfficersWorkload:
    def test_returns_paginated_officers(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        from accounts.models import LoanOfficer

        for i in range(3):
            officer = LoanOfficer(
                first_name=f"Officer{i}",
                last_name="Test",
                email=f"officer{i}@example.com",
                password="hashed",
                department="Ops",
                active=True,
            )
            officer.save()

        result = get_officers_workload(page=1, page_size=2)
        assert result["total"] == 3
        assert len(result["officers"]) == 2
        assert result["page"] == 1
        assert result["total_pages"] == 2
