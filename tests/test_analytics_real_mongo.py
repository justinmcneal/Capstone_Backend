"""Explicitly opt-in Analytics proof against an isolated real MongoDB database."""

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pymongo import MongoClient

from analytics.models import AuditLog
from analytics.services.audit_writer import reconcile_audit_failures
from analytics.services.lifecycle import (
    audit_integrity_inventory,
    enforce_audit_retention,
    release_audit_legal_hold,
    set_audit_legal_hold,
)
from config.field_encryption import encrypt_value


def _plan_has_stage(plan, stage):
    if isinstance(plan, dict):
        return plan.get("stage") == stage or any(
            _plan_has_stage(value, stage) for value in plan.values()
        )
    if isinstance(plan, list):
        return any(_plan_has_stage(value, stage) for value in plan)
    return False


@pytest.fixture
def analytics_real_mongo(settings, monkeypatch):
    uri = os.getenv("REAL_MONGO_TEST_URI")
    approved = os.getenv("RUN_ANALYTICS_REAL_MONGO_TESTS") == "1"
    if not uri or not approved:
        pytest.skip(
            "Set REAL_MONGO_TEST_URI and RUN_ANALYTICS_REAL_MONGO_TESTS=1 "
            "for an explicitly approved isolated MongoDB target"
        )
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    database_name = f"an_{uuid.uuid4().hex[:24]}"
    assert len(database_name.encode("utf-8")) <= 38
    database = client[database_name]
    monkeypatch.setattr(settings, "MONGODB", database)
    try:
        yield database
    finally:
        client.drop_database(database_name)
        client.close()


def _protected_event(index, officer_id):
    timestamp = datetime.now(timezone.utc) - timedelta(seconds=index)
    event = AuditLog(
        action="loan_submitted",
        user_id=f"customer-{index % 250}",
        user_type="customer",
        resource_type="loan",
        resource_id=f"loan-{index}",
        details={"amount": index + 1, "product": "Load", "term": 6},
        scope_officer_id=officer_id,
        scope_policy_version="event-time-assignment-v1",
        timestamp=timestamp,
        retention_expires_at=timestamp + timedelta(days=2555),
    )
    event._validate()
    event.payload_digest = hashlib.sha256(
        AuditLog._canonical_json(event._payload_for_digest())
    ).hexdigest()
    return event.to_storage_dict()


@pytest.mark.real_mongo
def test_analytics_real_mongo_indexes_validator_and_query_plan(analytics_real_mongo):
    database = analytics_real_mongo
    database.create_collection(AuditLog.collection_name)
    AuditLog.create_indexes()
    AuditLog.create_validator()
    officer_id = str(uuid.uuid4())
    database[AuditLog.collection_name].insert_many(
        [_protected_event(index, officer_id) for index in range(5000)]
    )

    indexes = database[AuditLog.collection_name].index_information()
    assert indexes["event_id_1"]["unique"] is True
    assert "audit_officer_event_scope" in indexes
    assert "audit_actor_filter_sort" in indexes
    query = {"scope_officer_index": AuditLog.blind_index(officer_id)}
    explain = database.command(
        "explain",
        {
            "find": AuditLog.collection_name,
            "filter": query,
            "sort": {"timestamp": -1, "_id": -1},
            "limit": 50,
        },
        verbosity="executionStats",
    )
    assert explain["executionStats"]["nReturned"] == 50
    assert explain["executionStats"]["totalDocsExamined"] <= 100
    assert _plan_has_stage(explain["queryPlanner"]["winningPlan"], "IXSCAN")


@pytest.mark.real_mongo
def test_analytics_real_mongo_idempotent_recovery_and_lifecycle(analytics_real_mongo):
    database = analytics_real_mongo
    AuditLog.create_indexes()
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = {
        "action": "user_login",
        "user_id": str(uuid.uuid4()),
        "user_type": "customer",
        "event_id": event_id,
        "details": {},
    }
    database["audit_write_failures"].insert_one(
        {
            "domain": "analytics",
            "event_id": event_id,
            "action": "user_login",
            "payload_encrypted": encrypt_value(payload),
            "occurred_at": datetime.now(timezone.utc),
            "resolved_at": None,
            "attempt_count": 0,
        }
    )
    assert reconcile_audit_failures() == {"resolved": 1, "failed": 0}
    assert reconcile_audit_failures() == {"resolved": 0, "failed": 0}
    assert database[AuditLog.collection_name].count_documents({"event_id": event_id}) == 1

    event = AuditLog(
        action="user_logout",
        user_type="customer",
        timestamp=datetime.now(timezone.utc) - timedelta(days=10),
        retention_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    ).save()
    assert set_audit_legal_hold(event.event_id, reason="release test", set_by="tester")
    assert enforce_audit_retention()["deleted"] == 0
    assert release_audit_legal_hold(event.event_id, released_by="tester")
    assert enforce_audit_retention()["deleted"] == 1
    inventory = audit_integrity_inventory(limit=10000)
    assert inventory["invalid_integrity"] == 0
    assert inventory["plaintext_sensitive_fields"] == 0
