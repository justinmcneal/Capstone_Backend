"""Opt-in Stage 4 validator, uniqueness, and query-plan proof on real MongoDB."""

import os
import uuid
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, OperationFailure

from config import field_encryption
from notifications.models.delivery import NotificationDelivery
from notifications.models.device_token import DeviceToken
from notifications.models.notification import Notification
from notifications.services.inbox import mark_notification_read
from notifications.services.persistence import install_notification_validators

pytestmark = [pytest.mark.deployment_integration, pytest.mark.real_mongo]


def _plan_uses_index(plan, index_name):
    if isinstance(plan, dict):
        return plan.get("indexName") == index_name or any(
            _plan_uses_index(value, index_name) for value in plan.values()
        )
    if isinstance(plan, list):
        return any(_plan_uses_index(value, index_name) for value in plan)
    return False


@pytest.fixture
def notifications_stage4_real_mongo(settings, monkeypatch):
    uri = os.getenv("REAL_MONGO_TEST_URI")
    approved = os.getenv("RUN_NOTIFICATIONS_STAGE4_REAL_MONGO_TESTS") == "1"
    if not uri or not approved:
        pytest.skip(
            "Set REAL_MONGO_TEST_URI and "
            "RUN_NOTIFICATIONS_STAGE4_REAL_MONGO_TESTS=1 for an explicitly "
            "approved isolated MongoDB target"
        )
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    database_name = f"notif_s4_{uuid.uuid4().hex[:18]}_isolated"
    database = client[database_name]
    monkeypatch.setattr(settings, "MONGODB", database)
    monkeypatch.setattr(
        settings, "FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    field_encryption._build_keyring.cache_clear()
    field_encryption._get_fernet.cache_clear()
    for collection_name in (
        Notification.collection_name,
        DeviceToken.collection_name,
        NotificationDelivery.collection_name,
    ):
        database.create_collection(collection_name)
    Notification.create_indexes()
    DeviceToken.create_indexes()
    NotificationDelivery.create_indexes()
    install_notification_validators(database)
    try:
        yield database
    finally:
        client.drop_database(database_name)
        client.close()
        field_encryption._build_keyring.cache_clear()
        field_encryption._get_fernet.cache_clear()


def test_real_mongo_validators_uniqueness_and_owner_query_plan(
    notifications_stage4_real_mongo,
):
    database = notifications_stage4_real_mongo
    now = datetime.now(timezone.utc)
    documents = []
    for index in range(500):
        documents.append(
            Notification(
                user_id="customer-stage4",
                user_type="customer",
                notification_type="loan_approved",
                subject=f"Outcome {index}",
                message="Approved",
                channel="in_app",
                status="sent",
                created_at=now,
            ).to_dict()
        )
    database[Notification.collection_name].insert_many(documents)

    with pytest.raises(OperationFailure):
        database[Notification.collection_name].insert_one(
            {
                "user_id": "customer-stage4",
                "user_type": "invalid-role",
                "notification_type": "loan_approved",
                "channel": "in_app",
                "status": "sent",
                "delivery_status": "sent",
                "is_read": False,
                "created_at": now,
                "retention_expires_at": now,
                "legal_hold": False,
            }
        )
    with pytest.raises(OperationFailure):
        database[DeviceToken.collection_name].insert_one(
            {
                "user_id": "customer-stage4",
                "user_type": "customer",
                "session_id": "session-invalid",
                "token": "encrypted-or-plain",
                "token_hash": "not-a-digest",
                "platform": "desktop",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
                "expires_at": now,
            }
        )

    first = Notification.create_idempotent(
        Notification(
            user_id="customer-stage4",
            user_type="customer",
            notification_type="password_changed",
            channel="in_app",
            status="sent",
        ),
        "real-mongo-event",
    )[0]
    with pytest.raises(DuplicateKeyError):
        database[Notification.collection_name].insert_one(
            {
                **first.to_dict(),
                "_id": None,
                "idempotency_key_hash": Notification.fingerprint("real-mongo-event"),
            }
        )

    wrong_owner = mark_notification_read(
        database,
        first.id,
        {"user_id": "another-customer", "user_type": "customer"},
    )
    right_owner = mark_notification_read(
        database,
        first.id,
        {"user_id": "customer-stage4", "user_type": "customer"},
    )
    assert wrong_owner["found"] is False
    assert right_owner["found"] is True

    explain = database.command(
        "explain",
        {
            "find": Notification.collection_name,
            "filter": {
                "user_id": "customer-stage4",
                "user_type": "customer",
            },
            "sort": {"created_at": -1, "_id": -1},
            "limit": 20,
        },
        verbosity="executionStats",
    )
    assert _plan_uses_index(
        explain["queryPlanner"]["winningPlan"], "notification_owner_created_page"
    )
    assert explain["executionStats"]["nReturned"] == 20

    plan_matrix = (
        (
            Notification.collection_name,
            {
                "user_id": "customer-stage4",
                "user_type": "customer",
                "is_read": False,
            },
            {"created_at": -1, "_id": -1},
            "notification_owner_read_page",
        ),
        (
            Notification.collection_name,
            {
                "user_id": "customer-stage4",
                "user_type": "customer",
                "channel": "in_app",
            },
            {"created_at": -1, "_id": -1},
            "notification_owner_channel_page",
        ),
        (
            Notification.collection_name,
            {"legal_hold": False, "retention_expires_at": {"$lte": now}},
            {"_id": 1},
            "notification_retention_due",
        ),
    )
    for collection_name, query, sort, index_name in plan_matrix:
        plan = database.command(
            "explain",
            {
                "find": collection_name,
                "filter": query,
                "sort": sort,
                "limit": 20,
            },
            verbosity="executionStats",
        )
        assert _plan_uses_index(plan["queryPlanner"]["winningPlan"], index_name)
