"""
Loan model tests for business logic methods.

Coverage:
- LoanApplication status transitions (submit, approve, reject, disburse, resubmit)
- RepaymentSchedule installment calculations
- LoanPayment aggregation
- LoanProduct active filtering
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from bson import ObjectId
import pytest

from loans.models import LoanApplication, LoanProduct, RepaymentSchedule, LoanPayment
from loans.utils.time import utcnow


def test_loan_product_active_filter(monkeypatch):
    import mongomock
    from django.conf import settings

    client = mongomock.MongoClient()
    db = client["testdb"]
    monkeypatch.setattr(settings, "MONGODB", db, raising=False)

    active = LoanProduct(name="Active", code="A1", active=True)
    inactive = LoanProduct(name="Inactive", code="I1", active=False)
    active.save()
    inactive.save()

    results = LoanProduct.find(active_only=True)
    assert len(results) == 1
    assert results[0].name == "Active"


class TestLoanApplicationStatusTransitions:
    def test_submit_changes_status(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="draft",
        )
        app.save()

        assert app.status == "draft"
        assert app.submitted_at is None

        app.submit()
        assert app.status == "submitted"
        assert app.submitted_at is not None

    def test_approve_changes_status(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="under_review",
        )
        app.save()

        app.approve(officer_id="officer123", approved_amount=18000, notes="Looks good")
        assert app.status == "approved"
        assert app.approved_amount == 18000
        assert app.decision_date is not None

    def test_reject_changes_status(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="under_review",
        )
        app.save()

        app.reject(officer_id="officer123", reason="Insufficient documents")
        assert app.status == "rejected"
        assert app.rejection_reason == "Insufficient documents"
        assert app.decision_date is not None

    def test_disburse_changes_status(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="approved",
            approved_amount=18000,
        )
        app.save()

        app.disburse(
            amount=18000,
            method="bank_transfer",
            reference="REF-001",
            processed_by="officer123",
        )
        assert app.status == "disbursed"
        assert app.disbursed_amount == 18000
        assert app.disbursement_method == "bank_transfer"
        assert app.disbursed_at is not None

    def test_resubmit_resets_to_draft(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="rejected",
            rejection_reason="Incomplete",
        )
        app.save()

        assert app.can_resubmit() is True

        app.resubmit()
        assert app.status == "draft"
        assert app.rejection_reason is None

    def test_add_internal_note(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="under_review",
        )
        app.save()

        app.add_internal_note(
            author_id="officer123",
            author_role="loan_officer",
            content="Customer has good credit history.",
        )

        assert len(app.internal_notes) == 1
        assert app.internal_notes[0]["content"] == "Customer has good credit history."
        assert app.internal_notes[0]["author_id"] == "officer123"

    def test_set_preferred_disbursement_method(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = LoanApplication(
            customer_id=str(ObjectId()),
            product_id=str(ObjectId()),
            requested_amount=20000,
            term_months=12,
            purpose="Working capital",
            status="submitted",
        )
        app.save()

        app.set_preferred_disbursement_method("gcash")
        assert app.preferred_disbursement_method == "gcash"


class TestRepaymentSchedule:
    def _make_schedule(self, loan_id, customer_id, principal=100000, rate=0.015, term=12):
        installments = []
        for i in range(1, term + 1):
            installments.append({
                "number": i,
                "due_date": datetime.now(timezone.utc),
                "principal": principal / term,
                "interest": principal * rate,
                "total_amount": (principal / term) + (principal * rate),
                "status": "pending",
                "paid_amount": 0,
            })
        return RepaymentSchedule(
            loan_id=loan_id,
            customer_id=customer_id,
            principal=principal,
            interest_rate=rate,
            term_months=term,
            monthly_payment=(principal / term) + (principal * rate),
            total_amount=principal * (1 + rate * term),
            total_interest=principal * rate * term,
            installments=installments,
        )

    def test_get_next_payment(self):
        schedule = self._make_schedule(
            loan_id=str(ObjectId()),
            customer_id=str(ObjectId()),
        )
        next_inst = schedule.get_next_payment()
        assert next_inst is not None
        assert next_inst["number"] == 1

    def test_get_paid_count(self):
        schedule = self._make_schedule(
            loan_id=str(ObjectId()),
            customer_id=str(ObjectId()),
        )
        schedule.installments[0]["status"] = "paid"
        schedule.installments[1]["status"] = "paid"
        assert schedule.get_paid_count() == 2

    def test_get_remaining_balance(self):
        schedule = self._make_schedule(
            loan_id=str(ObjectId()),
            customer_id=str(ObjectId()),
            principal=120000,
        )
        first_total = schedule.installments[0]["total_amount"]
        schedule.installments[0]["status"] = "paid"
        schedule.installments[0]["paid_amount"] = first_total
        remaining = schedule.get_remaining_balance()
        assert remaining == schedule.total_amount - first_total

    def test_record_payment(self):
        schedule = self._make_schedule(
            loan_id=str(ObjectId()),
            customer_id=str(ObjectId()),
        )
        inst_total = schedule.installments[0]["total_amount"]
        schedule.record_payment(1, inst_total)
        assert schedule.installments[0]["paid_amount"] == inst_total
        assert schedule.installments[0]["status"] == "paid"

    def test_mark_overdue_installments(self):
        schedule = self._make_schedule(
            loan_id=str(ObjectId()),
            customer_id=str(ObjectId()),
        )
        past = datetime.now(timezone.utc).replace(year=2020)
        schedule.installments[0]["due_date"] = past
        schedule.mark_overdue_installments(as_of=datetime.now(timezone.utc))
        assert schedule.installments[0]["status"] == "overdue"


class TestLoanPayment:
    def test_get_total_paid(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        loan_id = str(ObjectId())
        payments = [
            LoanPayment(
                loan_id=loan_id,
                customer_id=str(ObjectId()),
                installment_number=1,
                amount=5000,
                payment_method="gcash",
            ),
            LoanPayment(
                loan_id=loan_id,
                customer_id=str(ObjectId()),
                installment_number=2,
                amount=5000,
                payment_method="bank_transfer",
            ),
        ]
        for p in payments:
            p.save()

        total = LoanPayment.get_total_paid(loan_id)
        assert total == 10000

    def test_find_by_customer(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        customer_id = str(ObjectId())
        payment = LoanPayment(
            loan_id=str(ObjectId()),
            customer_id=customer_id,
            installment_number=1,
            amount=5000,
            payment_method="gcash",
        )
        payment.save()

        results = LoanPayment.find_by_customer(customer_id)
        assert len(results) == 1
        assert results[0].amount == 5000
