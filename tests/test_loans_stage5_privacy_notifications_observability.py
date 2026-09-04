"""Stage 5 Loans privacy, durable delivery, and monitoring regressions."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml
from bson import ObjectId
from cryptography.fernet import Fernet
from django.core.management import call_command

from config import field_encryption
from config.field_encryption import is_encrypted_value
from loans.blockchain.models import BlockchainTransaction
from loans.models import (
    LoanApplication,
    LoanNotificationDelivery,
    LoanPayment,
    RepaymentSchedule,
)
from loans.services.lifecycle import (
    enforce_loan_retention,
    export_customer_loan_data,
    pseudonymize_customer_loan_data,
    release_loan_legal_hold,
)
from loans.services.notifications import (
    deliver_loan_notification,
    queue_customer_loan_notification,
    reconcile_loan_notifications,
)
from loans.services.operations import collect_loan_operational_metrics
from loans.utils.time import utcnow

ROOT = Path(__file__).resolve().parents[1]


def _enable_encryption(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = ()
    field_encryption._build_keyring.cache_clear()
    field_encryption._get_fernet.cache_clear()


def _application(customer_id=None, **kwargs):
    return LoanApplication(
        customer_id=customer_id or str(ObjectId()),
        product_id=str(ObjectId()),
        requested_amount=1000,
        term_months=2,
        purpose="Working capital",
        ai_recommendation={"summary": "Eligible"},
        **kwargs,
    ).save()


def test_sensitive_application_payment_and_blockchain_fields_are_encrypted(settings):
    _enable_encryption(settings)
    app = _application(disbursement_error="provider detail")
    schedule = RepaymentSchedule(
        loan_id=app.id,
        customer_id=app.customer_id,
        principal=1000,
        total_amount=1000,
        installments=[],
    ).save()
    payment = LoanPayment(
        loan_id=app.id,
        schedule_id=schedule.id,
        customer_id=app.customer_id,
        installment_number=1,
        amount=100,
        failure_reason="provider declined",
        blockchain_sync_error="rpc detail",
    ).save()
    transaction = BlockchainTransaction.create_pending(
        app.id, "payment", "PaymentRecording", "recordPayment", {"private": "detail"}
    )
    transaction.mark_failed("rpc endpoint detail")

    raw_app = settings.MONGODB["loan_applications"].find_one({"_id": ObjectId(app.id)})
    raw_payment = settings.MONGODB["loan_payments"].find_one(
        {"_id": ObjectId(payment.id)}
    )
    raw_tx = settings.MONGODB["blockchain_transactions"].find_one(
        {"_id": transaction._id}
    )
    for field in ("purpose", "ai_recommendation", "disbursement_error"):
        assert is_encrypted_value(raw_app[field])
    for field in ("failure_reason", "blockchain_sync_error"):
        assert is_encrypted_value(raw_payment[field])
    assert is_encrypted_value(raw_tx["error"])
    assert raw_tx["details"] == {"private": "detail"}
    assert LoanApplication.find_by_id(app.id).purpose == "Working capital"
    assert BlockchainTransaction.find_by_loan(app.id)[0].error == "rpc endpoint detail"


def test_account_export_is_bounded_and_customer_readable(settings):
    _enable_encryption(settings)
    customer_id = str(ObjectId())
    first = _application(customer_id)
    _application(customer_id)
    RepaymentSchedule(
        loan_id=first.id,
        customer_id=customer_id,
        principal=1000,
        total_amount=1000,
        installments=[],
    ).save()
    exported = export_customer_loan_data(settings.MONGODB, customer_id, limit=1)
    assert exported["applications"]["total"] == 2
    assert exported["applications"]["truncated"] is True
    assert exported["applications"]["items"][0]["purpose"] == "Working capital"
    assert exported["repayment_schedules"]["total"] == 1


def test_account_cleanup_pseudonymizes_retained_financial_records(settings):
    customer_id = str(ObjectId())
    app = _application(customer_id)
    RepaymentSchedule(
        loan_id=app.id,
        customer_id=customer_id,
        principal=1000,
        total_amount=1000,
        installments=[],
    ).save()
    LoanPayment(
        loan_id=app.id,
        customer_id=customer_id,
        installment_number=1,
        amount=100,
    ).save()
    result = pseudonymize_customer_loan_data(settings.MONGODB, customer_id)
    assert result["remaining"] == 0
    assert result["pseudonym"].startswith("deleted:")
    assert (
        settings.MONGODB["loan_applications"].find_one({"_id": ObjectId(app.id)})[
            "customer_id"
        ]
        == result["pseudonym"]
    )
    assert (
        pseudonymize_customer_loan_data(settings.MONGODB, customer_id)["remaining"] == 0
    )


def test_legal_hold_blocks_retention_and_command_is_dry_run(settings, capsys):
    _enable_encryption(settings)
    app = _application(status="rejected")
    settings.MONGODB["loan_applications"].update_one(
        {"_id": ObjectId(app.id)},
        {"$set": {"retention_expires_at": utcnow() - timedelta(days=1)}},
    )
    call_command(
        "manage_loan_legal_hold", app.id, "set", actor="admin", reason="Dispute"
    )
    assert "DRY RUN" in capsys.readouterr().out
    call_command(
        "manage_loan_legal_hold",
        app.id,
        "set",
        actor="admin",
        reason="Dispute",
        apply=True,
    )
    held = settings.MONGODB["loan_applications"].find_one({"_id": ObjectId(app.id)})
    assert held["legal_hold"] is True
    assert is_encrypted_value(held["legal_hold_reason"])
    assert (
        settings.MONGODB["audit_logs"].count_documents(
            {"action": "loan_legal_hold_set"}
        )
        == 1
    )
    assert enforce_loan_retention()["applications_deleted"] == 0
    assert release_loan_legal_hold(app.id, released_by="admin") is True
    assert enforce_loan_retention()["applications_deleted"] == 1


def test_notification_outbox_is_encrypted_idempotent_and_retryable(
    monkeypatch, settings
):
    _enable_encryption(settings)
    LoanNotificationDelivery.create_indexes()
    customer = SimpleNamespace(
        id=str(ObjectId()), email="customer@example.test", full_name="Customer Name"
    )
    delivery = LoanNotificationDelivery.ensure(
        loan_id=str(ObjectId()),
        event_type="approved",
        event_key="transition-1",
        recipient={
            "id": customer.id,
            "user_type": "customer",
            "email": customer.email,
            "name": customer.full_name,
        },
        payload={"approved_amount": 1000},
    )
    raw = settings.MONGODB[delivery.collection_name].find_one(
        {"_id": ObjectId(delivery.id)}
    )
    assert is_encrypted_value(raw["recipient_email"])
    assert is_encrypted_value(raw["payload"])

    calls = []

    class Sender:
        def send_loan_approved(self, **kwargs):
            calls.append(kwargs)
            return len(calls) > 1

    monkeypatch.setattr(
        "loans.services.notifications.get_email_sender", lambda: Sender()
    )
    assert deliver_loan_notification(delivery.id) == "retry_wait"
    settings.MONGODB[delivery.collection_name].update_one(
        {"_id": ObjectId(delivery.id)},
        {"$set": {"next_attempt_at": datetime.now(timezone.utc)}},
    )
    assert reconcile_loan_notifications()["delivered"] == 1
    same = LoanNotificationDelivery.ensure(
        loan_id=delivery.loan_id,
        event_type="approved",
        event_key="transition-1",
        recipient={
            "id": customer.id,
            "user_type": "customer",
            "email": customer.email,
            "name": customer.full_name,
        },
        payload={"approved_amount": 1000},
    )
    assert same.id == delivery.id
    assert len(calls) == 2


def test_queue_survives_broker_failure(monkeypatch, settings):
    _enable_encryption(settings)
    customer = SimpleNamespace(
        id=str(ObjectId()), email="queue@example.test", full_name="Queue Customer"
    )
    monkeypatch.setattr(
        "loans.tasks.deliver_loan_notification_task.delay",
        lambda delivery_id: (_ for _ in ()).throw(RuntimeError("broker unavailable")),
    )
    outcome = queue_customer_loan_notification(
        loan_id=str(ObjectId()),
        event_type="submitted",
        event_key="submit-1",
        customer=customer,
        payload={"product_name": "Starter", "amount": 1000},
    )
    assert outcome["created"] is True and outcome["queued"] is False
    assert (
        settings.MONGODB["loan_notification_deliveries"].count_documents(
            {"status": "pending"}
        )
        == 1
    )


def test_operational_metrics_cover_critical_backlogs(settings):
    old = utcnow() - timedelta(minutes=20)
    settings.MONGODB["loan_notification_deliveries"].insert_one(
        {"status": "pending", "created_at": old, "next_attempt_at": old}
    )
    settings.MONGODB["audit_write_failures"].insert_one(
        {"domain": "loans", "resolved_at": None, "occurred_at": old}
    )
    settings.MONGODB["loan_operational_state"].insert_one(
        {"_id": "check_overdue_installments", "completed_at": old}
    )
    settings.MONGODB["repayment_schedules"].insert_one(
        {"loan_id": str(ObjectId()), "status": "active", "created_at": old}
    )
    summary = collect_loan_operational_metrics()
    assert summary["backlog"]["notification:retryable"] == 1
    assert summary["backlog"]["audit:unresolved"] == 1
    assert summary["oldest_age_seconds"]["notification"] >= 1200
    assert int(summary["job_last_success_timestamp"]["overdue"]) == int(old.timestamp())
    assert summary["integrity_gaps"]["orphan_schedule"] == 1


def test_loans_monitoring_assets_are_parseable_and_low_cardinality():
    rules = yaml.safe_load((ROOT / "monitoring/loans/prometheus-rules.yml").read_text())
    tests = yaml.safe_load(
        (ROOT / "monitoring/loans/prometheus-rules.test.yml").read_text()
    )
    smoke = yaml.safe_load((ROOT / "monitoring/loans/prometheus-smoke.yml").read_text())
    dashboard = json.loads(
        (ROOT / "monitoring/loans/grafana-dashboard.json").read_text()
    )
    alerts = [
        rule for group in rules["groups"] for rule in group["rules"] if "alert" in rule
    ]
    assert len(alerts) >= 6
    assert all(
        rule["annotations"]["runbook"].endswith("#loans-operations-runbook")
        for rule in alerts
    )
    assert tests["tests"] and smoke["scrape_configs"]
    assert dashboard["uid"] == "capstone-loans"
    assert all(
        panel["datasource"]["uid"] == "capstone-prometheus"
        for panel in dashboard["panels"]
    )
    metric_source = (ROOT / "loans/metrics.py").read_text()
    assert "customer_id" not in metric_source and "loan_id" not in metric_source
