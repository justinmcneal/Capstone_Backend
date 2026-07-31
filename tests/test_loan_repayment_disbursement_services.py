"""
Service-layer tests for repayment scheduling and disbursement.

Coverage:
- RepaymentSchedule.generate_for_loan() schedule generation
- RepaymentSchedule installment calculations and totals
- RepaymentSchedule.record_payment() partial and full payments
- RepaymentSchedule.get_remaining_balance() with penalties
- LoanApplication.disburse() state transitions
- LoanApplication.set_preferred_disbursement_method()
- Disbursement reference generation
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from loans.models.application import LoanApplication
from loans.models.product import LoanProduct
from loans.models.repayment import RepaymentSchedule
from loans.utils.reference_generator import (
    generate_disbursement_reference,
    generate_payment_reference,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        "status": "approved",
    }
    defaults.update(overrides)
    return LoanApplication(**defaults)


# ---------------------------------------------------------------------------
# RepaymentSchedule.generate_for_loan
# ---------------------------------------------------------------------------

class TestGenerateForLoan:
    def test_generates_correct_number_of_installments(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        product = _make_product()
        app = _make_application(term_months=6)
        app.save()

        schedule = RepaymentSchedule.generate_for_loan(app, product)
        assert len(schedule.installments) == 6

    def test_generates_installments_with_correct_structure(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        product = _make_product(interest_rate=0.02)
        app = _make_application(
            term_months=3,
            approved_amount=30000,
            disbursed_amount=30000,
        )
        app.save()

        schedule = RepaymentSchedule.generate_for_loan(app, product)

        for inst in schedule.installments:
            assert "number" in inst
            assert "due_date" in inst
            assert "principal" in inst
            assert "interest" in inst
            assert "total_amount" in inst
            assert "status" in inst
            assert inst["status"] == "pending"
            assert inst["paid_amount"] == 0

    def test_monthly_payment_calculation(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        product = _make_product(interest_rate=0.01)
        app = _make_application(
            term_months=12,
            approved_amount=120000,
            disbursed_amount=120000,
        )
        app.save()

        schedule = RepaymentSchedule.generate_for_loan(app, product)

        expected_principal = 120000 / 12
        expected_interest = 120000 * 0.01
        expected_monthly = expected_principal + expected_interest

        assert abs(schedule.monthly_payment - round(expected_monthly, 2)) < 0.01

    def test_total_amount_matches_sum_of_installments(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        product = _make_product(interest_rate=0.015)
        app = _make_application(
            term_months=6,
            approved_amount=60000,
            disbursed_amount=60000,
        )
        app.save()

        schedule = RepaymentSchedule.generate_for_loan(app, product)

        installment_sum = sum(inst["total_amount"] for inst in schedule.installments)
        assert abs(installment_sum - schedule.total_amount) < 0.02

    def test_uses_disbursed_amount_over_approved(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        product = _make_product(interest_rate=0.01)
        app = _make_application(
            approved_amount=50000,
            disbursed_amount=45000,
            term_months=6,
        )
        app.save()

        schedule = RepaymentSchedule.generate_for_loan(app, product)

        expected_principal = 45000 / 6
        assert abs(schedule.principal - 45000) < 0.01
        assert abs(schedule.monthly_payment - (expected_principal + 45000 * 0.01)) < 0.01

    def test_schedule_links_to_loan_and_customer(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        product = _make_product()
        app = _make_application()
        app.save()

        schedule = RepaymentSchedule.generate_for_loan(app, product)

        assert schedule.loan_id == app.id
        assert schedule.customer_id == app.customer_id

    def test_schedule_is_persisted_to_mongodb(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        product = _make_product()
        app = _make_application()
        app.save()

        schedule = RepaymentSchedule.generate_for_loan(app, product)
        assert schedule.id is not None

        loaded = RepaymentSchedule.find_by_loan(app.id)
        assert loaded is not None
        assert loaded.loan_id == app.id

    def test_interest_rate_preserved_from_product(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        product = _make_product(interest_rate=0.025)
        app = _make_application()
        app.save()

        schedule = RepaymentSchedule.generate_for_loan(app, product)
        assert abs(schedule.interest_rate - 0.025) < 0.0001


# ---------------------------------------------------------------------------
# RepaymentSchedule installment behavior
# ---------------------------------------------------------------------------

class TestRepaymentInstallments:
    def _make_schedule(self, loan_id, customer_id, principal=100000, rate=0.015, term=12):
        installments = []
        for i in range(1, term + 1):
            installments.append({
                "number": i,
                "due_date": datetime.now(timezone.utc),
                "principal": round(principal / term, 2),
                "interest": round(principal * rate, 2),
                "total_amount": round(principal / term + principal * rate, 2),
                "status": "pending",
                "paid_amount": 0,
                "penalty_status": None,
                "penalty_amount": 0,
            })
        return RepaymentSchedule(
            loan_id=loan_id,
            customer_id=customer_id,
            principal=principal,
            interest_rate=rate,
            term_months=term,
            monthly_payment=round(principal / term + principal * rate, 2),
            total_amount=round(principal * (1 + rate * term), 2),
            total_interest=round(principal * rate * term, 2),
            installments=installments,
        )

    def test_get_next_payment_returns_first_pending(self):
        schedule = self._make_schedule(str(ObjectId()), str(ObjectId()))
        next_inst = schedule.get_next_payment()
        assert next_inst is not None
        assert next_inst["number"] == 1

    def test_get_next_payment_returns_none_when_all_paid(self):
        schedule = self._make_schedule(str(ObjectId()), str(ObjectId()))
        for inst in schedule.installments:
            inst["status"] = "paid"
        assert schedule.get_next_payment() is None

    def test_get_paid_count(self):
        schedule = self._make_schedule(str(ObjectId()), str(ObjectId()))
        schedule.installments[0]["status"] = "paid"
        schedule.installments[2]["status"] = "paid"
        assert schedule.get_paid_count() == 2

    def test_record_full_payment_marks_paid(self):
        schedule = self._make_schedule(str(ObjectId()), str(ObjectId()))
        total = schedule.installments[0]["total_amount"]
        schedule.record_payment(1, total)
        assert schedule.installments[0]["status"] == "paid"
        assert schedule.installments[0]["paid_amount"] == total
        assert schedule.installments[0]["paid_at"] is not None

    def test_record_partial_payment_updates_status(self):
        schedule = self._make_schedule(str(ObjectId()), str(ObjectId()))
        total = schedule.installments[0]["total_amount"]
        partial = total / 2
        schedule.record_payment(1, partial)
        assert schedule.installments[0]["status"] == "partial"
        assert schedule.installments[0]["paid_amount"] == partial

    def test_record_multiple_payments_accumulate(self):
        schedule = self._make_schedule(str(ObjectId()), str(ObjectId()))
        total = schedule.installments[0]["total_amount"]
        schedule.record_payment(1, total / 2)
        schedule.record_payment(1, total / 2)
        assert schedule.installments[0]["status"] == "paid"
        assert schedule.installments[0]["paid_amount"] == total

    def test_record_payment_ignores_unknown_installment(self):
        schedule = self._make_schedule(str(ObjectId()), str(ObjectId()))
        result = schedule.record_payment(99, 1000)
        assert result is None

    def test_get_remaining_balance_without_penalties(self):
        schedule = self._make_schedule(
            str(ObjectId()), str(ObjectId()), principal=120000, rate=0.01, term=6
        )
        schedule.installments[0]["paid_amount"] = schedule.installments[0]["total_amount"]
        schedule.installments[0]["status"] = "paid"
        remaining = schedule.get_remaining_balance()
        expected = schedule.total_amount - schedule.installments[0]["total_amount"]
        assert abs(remaining - expected) < 0.01

    def test_get_remaining_balance_includes_unpaid_penalties(self):
        schedule = self._make_schedule(
            str(ObjectId()), str(ObjectId()), principal=120000, rate=0.01, term=6
        )
        schedule.installments[0]["penalty_status"] = "applied"
        schedule.installments[0]["penalty_amount"] = 500
        remaining = schedule.get_remaining_balance()
        assert remaining >= schedule.total_amount + 500

    def test_get_remaining_balance_never_negative(self):
        schedule = self._make_schedule(
            str(ObjectId()), str(ObjectId()), principal=60000, rate=0.01, term=6
        )
        for inst in schedule.installments:
            inst["paid_amount"] = inst["total_amount"] * 2
            inst["status"] = "paid"
        assert schedule.get_remaining_balance() >= 0

    def test_get_installment_remaining_with_penalty(self):
        schedule = self._make_schedule(
            str(ObjectId()), str(ObjectId()), principal=120000, rate=0.01, term=12
        )
        schedule.installments[0]["penalty_status"] = "applied"
        schedule.installments[0]["penalty_amount"] = 200
        remaining = schedule.get_installment_remaining(1)
        expected = schedule.installments[0]["total_amount"] - 0 + 200
        assert abs(remaining - expected) < 0.01

    def test_count_unpaid_before(self):
        schedule = self._make_schedule(
            str(ObjectId()), str(ObjectId()), term=6
        )
        schedule.installments[0]["status"] = "paid"
        schedule.installments[2]["status"] = "paid"
        assert schedule.count_unpaid_before(4) == 1  # installment 3 is unpaid before 4


# ---------------------------------------------------------------------------
# LoanApplication.disburse
# ---------------------------------------------------------------------------

class TestLoanDisbursement:
    def test_disburse_changes_status_to_disbursed(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        product = _make_product()
        product.save()
        app = _make_application(status="approved")
        app.save()

        app.disburse(
            amount=20000,
            method="bank_transfer",
            reference="DSB-001",
            processed_by=str(ObjectId()),
        )

        assert app.status == "disbursed"
        assert app.disbursed_amount == 20000
        assert app.disbursement_method == "bank_transfer"
        assert app.disbursement_reference == "DSB-001"
        assert app.disbursed_at is not None
        assert app.disbursed_by is not None

    def test_disburse_raises_for_non_approved(self):
        app = _make_application(status="submitted")
        with pytest.raises(ValueError, match="Only approved loans can be disbursed"):
            app.disburse(
                amount=20000,
                method="bank_transfer",
                reference="DSB-001",
                processed_by=str(ObjectId()),
            )

    def test_disburse_raises_for_rejected(self):
        app = _make_application(status="rejected")
        with pytest.raises(ValueError, match="Only approved loans can be disbursed"):
            app.disburse(
                amount=20000,
                method="bank_transfer",
                reference="DSB-001",
                processed_by=str(ObjectId()),
            )


# ---------------------------------------------------------------------------
# LoanApplication.set_preferred_disbursement_method
# ---------------------------------------------------------------------------

class TestPreferredDisbursementMethod:
    def test_set_valid_method(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = _make_application(status="approved")
        app.save()

        app.set_preferred_disbursement_method("gcash")
        assert app.preferred_disbursement_method == "gcash"

    def test_set_invalid_method_raises(self):
        app = _make_application()
        with pytest.raises(ValueError, match="Disbursement method must be one of"):
            app.set_preferred_disbursement_method("invalid_method")

    def test_set_method_raises_for_disbursed(self):
        app = _make_application(status="disbursed")
        with pytest.raises(ValueError, match="Cannot change disbursement method"):
            app.set_preferred_disbursement_method("gcash")


# ---------------------------------------------------------------------------
# Reference generation
# ---------------------------------------------------------------------------

class TestReferenceGeneration:
    def test_generate_disbursement_reference_format(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        db.counters.insert_one({"_id": "disbursement_counter", "seq": 0})
        ref = generate_disbursement_reference()
        assert ref.startswith("DSB-")
        assert len(ref) == 15  # DSB-YYYYMMDD-NNNNNN

    def test_generate_payment_reference_format(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        db.counters.insert_one({"_id": "payment_counter", "seq": 0})
        ref = generate_payment_reference()
        assert ref.startswith("PAY-")
        assert len(ref) == 15  # PAY-YYYYMMDD-NNNNNN

    def test_references_are_incrementing(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        db.counters.insert_one({"_id": "disbursement_counter", "seq": 100})
        ref1 = generate_disbursement_reference()
        ref2 = generate_disbursement_reference()

        seq1 = int(ref1.split("-")[-1])
        seq2 = int(ref2.split("-")[-1])
        assert seq2 == seq1 + 1
