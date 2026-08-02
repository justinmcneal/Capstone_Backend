"""Stage 8 audit attribution, observability, and nested-encryption regressions."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from cryptography.fernet import Fernet

from config.field_encryption import _get_fernet
from loans.models import LoanApplication, RepaymentSchedule
from loans.services.assignment import manual_assign_application
from loans.services.audit import LoanAuditUnavailable, record_loan_audit
from loans.utils.time import utcnow


@pytest.fixture
def encrypted_db(settings):
    settings.MONGODB = mongomock.MongoClient()["stage8"]
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    _get_fernet.cache_clear()
    yield settings.MONGODB
    _get_fernet.cache_clear()


def _schedule():
    return RepaymentSchedule(
        loan_id=str(ObjectId()),
        customer_id=str(ObjectId()),
        principal=100,
        total_amount=100,
        installments=[
            {
                "number": 1,
                "due_date": utcnow() + timedelta(days=30),
                "total_amount": 100,
                "total_amount_centavos": 10_000,
                "paid_amount": 0,
                "paid_amount_centavos": 0,
                "status": "pending",
                "penalty_status": None,
                "penalty_amount": 0,
                "penalty_amount_centavos": 0,
            }
        ],
    )


def test_nested_application_and_schedule_fields_are_encrypted(encrypted_db):
    app = LoanApplication(
        customer_id=str(ObjectId()),
        product_id=str(ObjectId()),
        internal_notes=[{"content": "private", "created_at": utcnow()}],
    ).save()
    schedule = _schedule().save()

    raw_app = encrypted_db["loan_applications"].find_one({"_id": app._id})
    raw_schedule = encrypted_db["repayment_schedules"].find_one(
        {"_id": schedule._id}
    )
    assert raw_app["internal_notes"].startswith("encbson::")
    assert raw_schedule["installments"].startswith("encbson::")
    assert LoanApplication.find_by_id(app.id).internal_notes[0]["content"] == "private"
    assert RepaymentSchedule.find_by_loan(schedule.loan_id).installments[0]["number"] == 1


def test_atomic_payment_remains_supported_with_encrypted_installments(encrypted_db):
    schedule = _schedule().save()

    installment, replayed = schedule.apply_payment_atomic(1, 100, "payment-token")

    raw = encrypted_db["repayment_schedules"].find_one({"_id": schedule._id})
    assert replayed is False
    assert installment["status"] == "paid"
    assert raw["installments"].startswith("encbson::")
    assert raw["accounting_version"] == 1


def test_manual_assignment_attributes_admin_not_assignee(encrypted_db):
    app = LoanApplication(
        customer_id=str(ObjectId()), product_id=str(ObjectId()), status="submitted"
    ).save()
    officer = SimpleNamespace(
        id=str(ObjectId()), active=True, full_name="Officer", email="o@example.test"
    )
    admin = SimpleNamespace(id=str(ObjectId()), role="admin")

    with (
        patch("loans.services.assignment._find_officer", side_effect=[officer, None]),
        patch("loans.services.assignment._notify_assignment_change"),
        patch("analytics.models.audit_log.AuditLog.log_action") as audit,
    ):
        manual_assign_application(app, officer.id, assigned_by=admin)

    event = audit.call_args.kwargs
    assert event["user_id"] == admin.id
    assert event["user_type"] == "admin"
    assert event["details"]["assigned_officer"] == officer.id


def test_audit_failure_is_queued_and_required_access_fails_closed(encrypted_db):
    with patch(
        "loans.services.audit.AuditLog.log_action", side_effect=RuntimeError("down")
    ):
        assert record_loan_audit(action="loan_test", resource_type="loan") is None
        with pytest.raises(LoanAuditUnavailable):
            record_loan_audit(
                required=True,
                action="repayment_schedule_exported",
                resource_type="repayment_schedule_export",
            )

    failures = list(encrypted_db["audit_write_failures"].find({}))
    assert [item["action"] for item in failures] == [
        "loan_test",
        "repayment_schedule_exported",
    ]
