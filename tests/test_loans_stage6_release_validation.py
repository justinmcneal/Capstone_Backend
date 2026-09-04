"""Offline coverage for the fail-closed Loans Stage 6 release gate."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from loans.services.operations import EXPECTED_LOAN_INDEXES, loan_release_readiness
from loans.services.persistence import LOAN_VALIDATORS, loan_data_inventory


class _ExplicitDatabase:
    """Match PyMongo Database's prohibition on truth-value testing."""

    def __init__(self, collection):
        self.collection = collection

    def __bool__(self):
        raise NotImplementedError("Database objects do not implement truth testing")

    def __getitem__(self, _name):
        return self.collection


def test_release_command_is_read_only_and_fails_closed(settings):
    report = {"ready": False, "checks": {"deployment_mongodb_verified": False}}
    with (
        patch(
            "loans.management.commands.loan_release_check.loan_release_readiness",
            return_value=report,
        ) as readiness,
        pytest.raises(CommandError, match="readiness checks failed"),
    ):
        call_command("loan_release_check", stdout=StringIO())
    readiness.assert_called_once_with(settings.MONGODB)


def test_release_readiness_passes_only_with_all_bound_evidence(settings, monkeypatch):
    settings.DEBUG = False
    settings.FIELD_ENCRYPTION_KEY = "configured"
    settings.FIELD_ENCRYPTION_STRICT_DECRYPTION = True
    settings.PROMETHEUS_METRICS_ENABLED = True
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.CELERY_BROKER_URL = "redis://broker/0"
    settings.CELERY_RESULT_BACKEND = "redis://broker/0"
    settings.LOANS_RETENTION_POLICY_APPROVED = True
    settings.LOANS_DEPLOYMENT_MONGODB_VERIFIED = True
    settings.LOANS_REDIS_CELERY_VERIFIED = True
    settings.LOANS_BLOCKCHAIN_VERIFIED = False
    settings.BLOCKCHAIN_ENABLED = False
    settings.LOANS_HTTPS_API_LOAD_VERIFIED = True
    settings.LOANS_BACKUP_RESTORE_VERIFIED = True
    settings.LOANS_SECRET_ROTATION_VERIFIED = True
    settings.LOANS_INCIDENT_ROLLBACK_APPROVED = True
    settings.LOANS_MONITORING_ALERTS_VERIFIED = True
    settings.LOANS_FULL_SUITE_SMOKE_VERIFIED = True
    monkeypatch.setattr(
        "loans.services.operations.loan_data_inventory",
        lambda limit, db=None: {
            "complete": True,
            "limit": limit,
            "collections": {},
        },
    )

    database = MagicMock()

    def command(argument, *args, **kwargs):
        if argument == "ping":
            return {"ok": 1}
        if isinstance(argument, dict) and argument.get("listCollections") == 1:
            name = argument["filter"]["name"]
            assert name in LOAN_VALIDATORS
            return {
                "cursor": {
                    "firstBatch": [
                        {
                            "options": {
                                "validator": {"$jsonSchema": {"bsonType": "object"}}
                            }
                        }
                    ]
                }
            }
        raise AssertionError(f"Unexpected database command: {argument!r}")

    database.command.side_effect = command
    collections = {}
    for collection, names in EXPECTED_LOAN_INDEXES.items():
        collections[collection] = MagicMock()
        collections[collection].index_information.return_value = {
            name: {} for name in names
        }
    database.__getitem__.side_effect = collections.__getitem__

    report = loan_release_readiness(database)

    assert report["ready"] is True, report
    assert all(report["checks"].values())
    assert all(report["index_checks"].values())
    assert all(report["validator_checks"].values())


def test_enabled_blockchain_requires_its_own_deployment_evidence(settings, monkeypatch):
    monkeypatch.setattr(
        "loans.services.operations.loan_data_inventory",
        lambda limit, db=None: {
            "complete": True,
            "limit": limit,
            "collections": {},
        },
    )
    settings.BLOCKCHAIN_ENABLED = True
    settings.LOANS_BLOCKCHAIN_VERIFIED = False
    database = MagicMock()
    database.command.return_value = {
        "cursor": {
            "firstBatch": [
                {"options": {"validator": {"$jsonSchema": {"bsonType": "object"}}}}
            ]
        }
    }
    database.__getitem__.return_value.index_information.return_value = {
        name: {} for names in EXPECTED_LOAN_INDEXES.values() for name in names
    }

    report = loan_release_readiness(database)

    assert report["checks"]["blockchain_baseline_verified_or_disabled"] is False
    assert report["ready"] is False


def test_unavailable_mongodb_reports_every_other_gate_without_leaking_error(settings):
    database = MagicMock()
    database.command.side_effect = RuntimeError("mongodb://secret-host/private")

    report = loan_release_readiness(database)

    assert report["ready"] is False
    assert report["checks"]["mongodb_connected"] is False
    assert report["checks"]["required_indexes_present"] is False
    assert report["checks"]["validators_present"] is False
    assert report["checks"]["inventory_clean_and_complete"] is False
    assert report["inventory"]["status"] == "mongodb_unavailable"
    assert "secret-host" not in repr(report)


def test_inventory_accepts_an_explicit_pymongo_style_database():
    collection = MagicMock()
    collection.count_documents.return_value = 0
    collection.find.return_value.sort.return_value.limit.return_value = []

    report = loan_data_inventory(db=_ExplicitDatabase(collection))

    assert report["complete"] is True
