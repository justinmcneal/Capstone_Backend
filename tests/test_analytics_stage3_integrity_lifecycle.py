"""Stage 3 audit schema, encryption, recovery, and lifecycle regressions."""

from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command

from analytics.models import AuditLog
from analytics.services.audit_writer import reconcile_audit_failures, record_audit
from analytics.services.lifecycle import (
    audit_integrity_inventory,
    enforce_audit_retention,
    export_customer_audit_data,
    pseudonymize_customer_audit_data,
    release_audit_legal_hold,
    set_audit_legal_hold,
)
from config.field_encryption import (
    _build_keyring,
    _get_fernet,
    decrypt_value,
    is_encrypted_value,
)


@pytest.fixture
def audit_security(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = ()
    settings.ANALYTICS_AUDIT_RETENTION_DAYS = 30
    settings.ANALYTICS_AUDIT_RETENTION_POLICY_VERSION = "test-v1"
    settings.ANALYTICS_AUDIT_MAX_DETAILS_BYTES = 4096
    settings.ANALYTICS_AUDIT_MAX_DETAILS_DEPTH = 3
    _build_keyring.cache_clear()
    _get_fernet.cache_clear()
    AuditLog.create_indexes()
    yield settings.MONGODB
    _build_keyring.cache_clear()
    _get_fernet.cache_clear()


def test_sensitive_fields_are_ciphertext_and_round_trip(audit_security):
    event = AuditLog.log_action(
        action="loan_rejected",
        user_id="customer-1",
        user_type="customer",
        user_email="customer@example.com",
        description="Private rejection reason",
        resource_type="loan",
        resource_id="loan-1",
        details={"customer_id": "customer-1", "reason": "private"},
        ip_address="203.0.113.10",
    )

    raw = audit_security["audit_logs"].find_one({"_id": event._id})
    for field in AuditLog.encrypted_fields[:4]:
        assert is_encrypted_value(raw[field])
    loaded = AuditLog.from_dict(raw)
    assert loaded.user_email == "customer@example.com"
    assert loaded.details["reason"] == "private"
    assert raw["event_schema_version"] == 2
    assert raw["retention_policy_version"] == "test-v1"
    assert raw["subject_index"] == AuditLog.blind_index("customer-1")


@pytest.mark.parametrize(
    "details",
    [
        {"unexpected": "value"},
        {"reason": {"api_token": "secret"}},
        {"reason": {"a": {"b": {"c": {"d": "too deep"}}}}},
        {"reason": "x" * 5000},
    ],
)
def test_invalid_or_secret_shaped_metadata_fails_closed(audit_security, details):
    with pytest.raises(ValueError):
        AuditLog.log_action(
            action="loan_rejected",
            user_type="loan_officer",
            details=details,
        )
    assert audit_security["audit_logs"].count_documents({}) == 0


def test_idempotent_event_replay_is_exactly_once(audit_security):
    first = AuditLog.log_action(
        action="user_login",
        user_id="actor-1",
        user_type="customer",
        idempotency_key="login-request-1",
    )
    replay = AuditLog.log_action(
        action="user_login",
        user_id="actor-1",
        user_type="customer",
        idempotency_key="login-request-1",
    )

    assert replay.id == first.id
    assert audit_security["audit_logs"].count_documents({}) == 1
    with pytest.raises(ValueError, match="different payload"):
        AuditLog.log_action(
            action="user_logout",
            user_id="actor-1",
            user_type="customer",
            idempotency_key="login-request-1",
        )


def test_integrity_inventory_detects_storage_tampering(audit_security):
    event = AuditLog.log_action(action="user_login", user_type="customer")
    assert audit_integrity_inventory()["invalid_integrity"] == 0

    audit_security["audit_logs"].update_one(
        {"_id": event._id}, {"$set": {"resource_type": "tampered"}}
    )

    inventory = audit_integrity_inventory()
    assert inventory["invalid_integrity"] == 1


def test_encrypted_failure_recovery_is_idempotent(monkeypatch, audit_security):
    original = AuditLog.log_action

    def unavailable(**_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(AuditLog, "log_action", unavailable)
    assert (
        record_audit(
            domain="test",
            action="user_login",
            user_id="actor-1",
            user_type="customer",
        )
        is None
    )
    queued = audit_security["audit_write_failures"].find_one({"domain": "test"})
    assert is_encrypted_value(queued["payload_encrypted"])
    event_id = decrypt_value(queued["payload_encrypted"])["event_id"]

    monkeypatch.setattr(AuditLog, "log_action", original)
    assert reconcile_audit_failures(domains={"test"}) == {"resolved": 1, "failed": 0}
    assert reconcile_audit_failures(domains={"test"}) == {"resolved": 0, "failed": 0}
    assert audit_security["audit_logs"].count_documents({"event_id": event_id}) == 1


def test_legal_hold_blocks_retention_until_released(audit_security):
    now = datetime.now(timezone.utc)
    event = AuditLog(
        action="user_login",
        user_type="customer",
        timestamp=now - timedelta(days=60),
        retention_expires_at=now - timedelta(days=1),
    ).save()

    assert set_audit_legal_hold(event.event_id, reason="investigation", set_by="admin")
    assert enforce_audit_retention() == {"deleted": 0}
    held = audit_security["audit_logs"].find_one({"event_id": event.event_id})
    assert is_encrypted_value(held["legal_hold_reason"])
    assert AuditLog.verify_integrity_document(held)

    assert release_audit_legal_hold(event.event_id, released_by="admin")
    assert enforce_audit_retention() == {"deleted": 1}


def test_export_and_account_deletion_pseudonymization(audit_security):
    event = AuditLog.log_action(
        action="profile_updated",
        user_id="customer-1",
        user_type="customer",
        user_email="customer@example.com",
        description="Updated private profile",
        resource_type="customer_profile",
        resource_id="customer-1",
        details={"profile_revision": 2},
        ip_address="203.0.113.20",
    )

    exported = export_customer_audit_data(audit_security, "customer-1")
    assert exported["total"] == 1
    assert exported["items"][0]["event_id"] == event.event_id

    result = pseudonymize_customer_audit_data(audit_security, "customer-1")
    assert result["pseudonymized"] == 1
    raw = audit_security["audit_logs"].find_one({"event_id": event.event_id})
    loaded = AuditLog.from_dict(raw)
    assert loaded.user_id.startswith("deleted:")
    assert loaded.resource_id.startswith("deleted:")
    assert loaded.user_email == ""
    assert loaded.ip_address == ""
    assert loaded.details == {}
    assert AuditLog.verify_integrity_document(raw)


def test_legacy_backfill_is_dry_run_first_and_integrity_safe(audit_security):
    legacy_id = audit_security["audit_logs"].insert_one(
        {
            "action": "user_login",
            "user_id": "customer-1",
            "user_type": "customer",
            "user_email": "legacy@example.com",
            "description": "Legacy event",
            "details": {},
            "ip_address": "203.0.113.30",
            "timestamp": datetime.now(timezone.utc),
        }
    ).inserted_id

    dry_run = StringIO()
    call_command("backfill_audit_events", stdout=dry_run)
    assert "[DRY-RUN]" in dry_run.getvalue()
    assert audit_security["audit_logs"].find_one({"_id": legacy_id})[
        "user_email"
    ] == "legacy@example.com"

    call_command("backfill_audit_events", apply=True, stdout=StringIO())
    protected = audit_security["audit_logs"].find_one({"_id": legacy_id})
    assert is_encrypted_value(protected["user_email"])
    assert protected["event_id"] == f"evt_legacy_{legacy_id}"
    assert AuditLog.verify_integrity_document(protected)
