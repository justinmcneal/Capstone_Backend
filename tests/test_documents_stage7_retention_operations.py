"""Stage 7 retention, account lifecycle, inventory, and storage safeguards."""

from datetime import datetime, timedelta, timezone
from io import StringIO
from types import SimpleNamespace

import pytest
from bson import ObjectId
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import Customer
from accounts.services.account_lifecycle_service import AccountLifecycleService
from documents.models import Document
from documents.services.retention import (
    collect_document_operational_metrics,
    enforce_document_retention,
)
from documents.services.storage_inventory import inventory_document_storage
from documents.services.storage_reconciliation import reconcile_storage_operations
from documents.storage.backends import LocalStorageBackend, get_storage_backend


def _customer(**overrides):
    values = {
        "first_name": "Retention",
        "last_name": "Customer",
        "email": f"retention-{ObjectId()}@example.test",
        "password": "hashed",
        "verified": True,
        "active": True,
        "account_state": "active",
    }
    values.update(overrides)
    return Customer(**values).save()


def _document(customer_id=None, **overrides):
    values = {
        "customer_id": str(customer_id or ObjectId()),
        "document_type": "valid_id",
        "original_filename": "identity.jpg",
        "file_path": f"documents/{ObjectId()}/valid_id/object.jpg",
        "file_size": 100,
        "mime_type": "image/jpeg",
    }
    values.update(overrides)
    return Document(**values).save()


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class InventoryStorage:
    def __init__(self, keys=()):
        self.keys = set(keys)
        self.deleted = []

    def object_exists(self, key):
        return key in self.keys

    def list_keys(self, prefix="documents"):
        return iter(key for key in self.keys if key.startswith(prefix))

    def delete(self, key):
        self.deleted.append(key)
        self.keys.discard(key)
        return True


def test_new_rejected_and_superseded_documents_receive_versioned_retention(settings):
    settings.DOCUMENT_RETENTION_DAYS = 365
    settings.DOCUMENT_REJECTED_RETENTION_DAYS = 30
    settings.DOCUMENT_SUPERSEDED_RETENTION_DAYS = 10
    settings.DOCUMENT_RETENTION_POLICY_VERSION = "test-v1"
    document = _document()
    initial_expiry = document.retention_expires_at

    document.review(
        action="reject", reviewer_id=str(ObjectId()), rejection_reason="Unreadable"
    )
    assert document.retention_policy_version == "test-v1"
    assert _aware(document.retention_expires_at) < _aware(initial_expiry)

    replacement = _document(customer_id=document.customer_id)
    document.mark_superseded(replacement.id)
    assert _aware(document.retention_expires_at) <= datetime.now(timezone.utc) + timedelta(days=11)


def test_legal_hold_blocks_retention_until_released():
    due = _document(retention_expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    assert due.set_legal_hold(reason="Active dispute", set_by="admin-1") is True
    assert enforce_document_retention() == {"claimed": 0, "skipped_concurrent": 0}

    assert Document.find_by_id(due.id).release_legal_hold(released_by="admin-2") is True
    assert enforce_document_retention()["claimed"] == 1
    assert Document.find_by_id(due.id).storage_state == "delete_pending"


def test_account_deletion_waits_for_document_object_reconciliation(monkeypatch):
    customer = _customer(
        account_state="pending_deletion",
        active=False,
        deletion_scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    document = _document(customer_id=customer.id)
    monkeypatch.setattr(
        "accounts.services.account_lifecycle_service.TokenUtils.revoke_all_sessions",
        lambda *args, **kwargs: None,
    )

    deleted = AccountLifecycleService.finalize_deletion(customer)
    assert deleted.profile_cleanup_status == "complete"
    assert deleted.document_cleanup_status == "pending"
    assert Document.find_by_id(document.id).storage_state == "delete_pending"

    storage = InventoryStorage({document.file_path})
    result = reconcile_storage_operations(storage=storage)
    assert result["document_deletions_completed"] == 1
    refreshed = Customer.find_one({"_id": customer._id})
    assert refreshed.document_cleanup_status == "complete"


def test_customer_export_includes_safe_document_metadata_only():
    customer = _customer()
    document = _document(customer_id=customer.id)
    payload = AccountLifecycleService.export_customer_data(customer)
    exported = payload["documents"][0]

    assert exported["id"] == document.id
    assert exported["document_type"] == "valid_id"
    assert "file_path" not in exported
    assert "original_filename" not in exported
    assert "sha256" not in exported
    assert "url" not in exported


def test_inventory_is_count_only_and_detects_missing_orphan_and_deleted_customer():
    customer = _customer(account_state="deleted", active=False)
    _document(customer_id=customer.id)
    storage = InventoryStorage({"documents/orphan/file.jpg"})

    result = inventory_document_storage(settings.MONGODB, storage)

    assert result["missing_objects"] == 1
    assert result["orphan_objects"] == 1
    assert result["deleted_customer_records"] == 1
    assert all("path" not in key and "key" not in key for key in result)


def test_local_storage_rejects_path_escape_and_unknown_backend(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    with pytest.raises(ValueError, match="escapes"):
        LocalStorageBackend().get_full_path("../outside.txt")

    settings.DOCUMENT_STORAGE_BACKEND = "unsupported"
    with pytest.raises(ValueError, match="Unsupported"):
        get_storage_backend()


def test_legal_hold_command_is_dry_run_by_default():
    document = _document()
    output = StringIO()
    call_command(
        "manage_document_legal_hold",
        document.id,
        action="set",
        reason="Dispute",
        operator="admin-1",
        stdout=output,
    )
    assert "DRY RUN" in output.getvalue()
    assert Document.find_by_id(document.id).legal_hold is False


def test_operational_metrics_report_all_required_backlogs():
    _document(status="needs_review", ai_analysis_status="failed", storage_state="delete_failed")
    result = collect_document_operational_metrics()
    assert result["storage_failed"] == 1
    assert result["review_pending"] == 1
    assert result["ai_failed"] == 1
    assert "notification_failed" in result
    assert "audit_pending" in result
    assert "oldest_age_seconds" in result


def test_read_only_s3_validator_checks_bucket_security_controls(
    monkeypatch, settings
):
    class NoCors(Exception):
        pass

    class NoLifecycle(Exception):
        pass

    class S3:
        exceptions = SimpleNamespace(
            NoSuchCORSConfiguration=NoCors,
            NoSuchLifecycleConfiguration=NoLifecycle,
        )

        def get_public_access_block(self, **kwargs):
            return {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                }
            }

        def get_bucket_encryption(self, **kwargs):
            return {
                "ServerSideEncryptionConfiguration": {
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {
                                "SSEAlgorithm": "AES256"
                            }
                        }
                    ]
                }
            }

        def get_bucket_ownership_controls(self, **kwargs):
            return {
                "OwnershipControls": {
                    "Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]
                }
            }

        def get_bucket_cors(self, **kwargs):
            return {
                "CORSRules": [
                    {
                        "AllowedOrigins": ["https://customer.example.test"],
                        "AllowedMethods": ["POST"],
                    }
                ]
            }

        def get_bucket_versioning(self, **kwargs):
            return {"Status": "Enabled"}

        def get_bucket_lifecycle_configuration(self, **kwargs):
            return {
                "Rules": [
                    {
                        "Status": "Enabled",
                        "Filter": {"Prefix": "document-uploads/quarantine/"},
                        "Expiration": {"Days": 1},
                    }
                ]
            }

    backend = SimpleNamespace(
        bucket_name="private-documents",
        url_expiry=300,
        s3=S3(),
    )
    settings.DOCUMENT_STORAGE_BACKEND = "s3"
    settings.DOCUMENT_QUARANTINE_RETENTION_DAYS = 1
    monkeypatch.setattr(
        "documents.management.commands.validate_document_storage.get_storage_backend",
        lambda: backend,
    )
    output = StringIO()

    call_command("validate_document_storage", stdout=output)

    assert '"public_access_block": true' in output.getvalue()
    assert '"quarantine_lifecycle": true' in output.getvalue()

    backend.s3.get_bucket_versioning = lambda **kwargs: {}
    with pytest.raises(CommandError, match="checks failed"):
        call_command("validate_document_storage", stdout=StringIO())
