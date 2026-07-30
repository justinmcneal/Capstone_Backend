"""
Loan Celery task tests.

Coverage:
- check_overdue_installments_task marks overdue installments and syncs
"""

from unittest.mock import MagicMock, patch

from datetime import datetime
from bson import ObjectId
import pytest

from loans.utils.time import utcnow


def test_check_overdue_installments_task(monkeypatch):
    import mongomock
    from django.conf import settings

    client = mongomock.MongoClient()
    db = client["testdb"]
    monkeypatch.setattr(settings, "MONGODB", db, raising=False)

    from loans.models import RepaymentSchedule
    from loans.tasks import check_overdue_installments_task

    past = datetime.now(utcnow().tzinfo).replace(year=2020)
    installments = [
        {
            "number": 1,
            "due_date": past,
            "principal": 8000,
            "interest": 1800,
            "total_amount": 9800,
            "status": "pending",
            "paid_amount": 0,
            "penalty_status": None,
            "penalty_amount": 0,
        },
        {
            "number": 2,
            "due_date": datetime(2099, 1, 1, tzinfo=utcnow().tzinfo),
            "principal": 8000,
            "interest": 1800,
            "total_amount": 9800,
            "status": "pending",
            "paid_amount": 0,
            "penalty_status": None,
            "penalty_amount": 0,
        },
    ]

    schedule = RepaymentSchedule(
        loan_id=str(ObjectId()),
        customer_id=str(ObjectId()),
        principal=120000,
        interest_rate=0.015,
        term_months=12,
        monthly_payment=9800,
        total_amount=117600,
        total_interest=21600,
        installments=installments,
    )
    schedule.save()

    with patch(
        "loans.blockchain.sync.sync_overdue", return_value=None
    ) as mock_sync:
        result = check_overdue_installments_task()

    assert result["overdue_marked"] == 1
    mock_sync.assert_called_once()


def test_check_overdue_installments_task_no_db(monkeypatch):
    from django.conf import settings

    monkeypatch.setattr(settings, "MONGODB", None, raising=False)

    from loans.tasks import check_overdue_installments_task

    result = check_overdue_installments_task()
    assert result == {"overdue_marked": 0}


def test_check_overdue_installments_task_no_schedules(monkeypatch):
    import mongomock
    from django.conf import settings

    client = mongomock.MongoClient()
    db = client["testdb"]
    monkeypatch.setattr(settings, "MONGODB", db, raising=False)

    from loans.tasks import check_overdue_installments_task

    result = check_overdue_installments_task()
    assert result == {"overdue_marked": 0}
