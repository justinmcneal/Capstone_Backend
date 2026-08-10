"""Stage 3 concurrency, replacement, and storage-recovery coverage."""

import hashlib
import io

import pytest
from bson import ObjectId
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from documents.models import (
    Document,
    DocumentRevisionConflict,
    DocumentStorageCleanup,
    DocumentUploadSession,
)
from documents.services.presigned_upload import finalize_presigned_upload
from documents.services.storage_reconciliation import reconcile_storage_operations
from documents.views import DocumentDetailView, DocumentUploadView


def _document(**overrides):
    values = {
        "customer_id": str(ObjectId()),
        "document_type": "valid_id",
        "original_filename": "identity.jpg",
        "file_path": "documents/customer/valid_id/identity.jpg",
        "file_size": 1024,
        "mime_type": "image/jpeg",
    }
    values.update(overrides)
    return Document(**values).save()


def _image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (320, 320), color=(255, 255, 255)).save(
        output, format="JPEG"
    )
    return output.getvalue()


class RetryStorage:
    def __init__(self, *, delete_result=True):
        self.delete_result = delete_result
        self.deleted = []

    def delete(self, file_path):
        self.deleted.append(file_path)
        return self.delete_result


class QuarantineStorage(RetryStorage):
    def __init__(self):
        super().__init__()
        self.objects = {}

    def put_for_session(self, session, contents):
        self.objects[session.object_key] = {
            "contents": contents,
            "mime_type": session.expected_mime_type,
            "metadata": {
                "upload-session": session.id,
                "sha256": session.expected_sha256,
            },
        }

    def get_object_metadata(self, object_key):
        item = self.objects[object_key]
        return {
            "size": len(item["contents"]),
            "mime_type": item["mime_type"],
            "metadata": item["metadata"],
        }

    def get_file_bytes(self, object_key):
        return self.objects[object_key]["contents"]

    def promote_quarantined_upload(
        self, object_key, customer_id, document_type, original_filename
    ):
        destination = f"documents/{customer_id}/{document_type}/final.jpg"
        self.objects[destination] = self.objects.pop(object_key)
        return {"file_path": destination, "filename": "final.jpg"}

    def delete(self, file_path):
        self.deleted.append(file_path)
        self.objects.pop(file_path, None)
        return True


def test_stale_review_and_review_delete_race_return_revision_conflict():
    original = _document()
    first = Document.find_by_id(original.id)
    stale = Document.find_by_id(original.id)

    first.review(action="approve", reviewer_id=str(ObjectId()))
    with pytest.raises(DocumentRevisionConflict):
        stale.review(
            action="reject",
            reviewer_id=str(ObjectId()),
            rejection_reason="Unreadable",
        )

    deleting = _document()
    stale_reviewer = Document.find_by_id(deleting.id)
    deleting.claim_deletion()
    with pytest.raises(DocumentRevisionConflict):
        stale_reviewer.review(action="approve", reviewer_id=str(ObjectId()))


def test_replacement_is_linked_without_reopening_review_history():
    old = _document(status="rejected", rejection_reason="Unreadable")
    old.request_reupload(officer_id=str(ObjectId()), reason="Upload a clearer copy")
    replacement = _document(
        customer_id=old.customer_id,
        replaces_document_id=old.id,
        file_path="documents/customer/valid_id/replacement.jpg",
    )
    old.mark_superseded(replacement.id)

    refreshed = Document.find_by_id(old.id)
    assert refreshed.status == "needs_review"
    assert refreshed.verified is False
    assert refreshed.superseded_by_document_id == replacement.id
    assert Document.find_by_id(replacement.id).replaces_document_id == old.id


def test_failed_delete_is_retained_then_reconciled(monkeypatch):
    document = _document()
    user = AuthenticatedUser(
        customer_id=document.customer_id,
        email="customer@example.test",
        verified=True,
        role="customer",
    )
    request = APIRequestFactory().delete(
        f"/api/documents/{document.id}/", {"revision": 0}, format="json"
    )
    force_authenticate(request, user=user)
    failing_storage = RetryStorage(delete_result=False)
    monkeypatch.setattr(
        "documents.views.document_views.get_storage_backend",
        lambda: failing_storage,
    )
    monkeypatch.setattr(
        DocumentDetailView,
        "require_customer",
        lambda self, request: (True, request.user),
    )
    monkeypatch.setattr(
        DocumentDetailView,
        "require_owner",
        lambda self, request, owner_id, conceal_existence=True: (True, request.user),
    )

    response = DocumentDetailView.as_view(authentication_classes=[])(
        request, document_id=document.id
    )

    assert response.status_code == 202
    assert Document.find_by_id(document.id).storage_state == "delete_failed"

    succeeding_storage = RetryStorage(delete_result=True)
    result = reconcile_storage_operations(storage=succeeding_storage)
    assert result["document_deletions_completed"] == 1
    assert Document.find_by_id(document.id) is None


def test_direct_upload_database_failure_queues_failed_object_rollback(monkeypatch):
    class UploadStorage(RetryStorage):
        def save(self, **kwargs):
            return {
                "file_path": "documents/customer/valid_id/orphan.jpg",
                "filename": "orphan.jpg",
                "size": kwargs["file"].size,
            }

    storage = UploadStorage(delete_result=False)
    monkeypatch.setattr(
        "documents.views.document_views.get_storage_backend", lambda: storage
    )
    monkeypatch.setattr(
        "documents.views.document_views.validate_uploaded_file",
        lambda file: (True, None),
    )
    monkeypatch.setattr(
        DocumentUploadView,
        "require_customer",
        lambda self, request: (True, request.user),
    )
    monkeypatch.setattr(
        "documents.views.document_views.ConsentService.check_ai_consent",
        staticmethod(lambda *args, **kwargs: False),
    )
    monkeypatch.setattr(Document, "save", lambda self: (_ for _ in ()).throw(RuntimeError("db")))
    user = AuthenticatedUser(
        customer_id=str(ObjectId()),
        email="customer@example.test",
        verified=True,
        role="customer",
    )
    upload = SimpleUploadedFile("identity.jpg", _image_bytes(), content_type="image/jpeg")
    request = APIRequestFactory().post(
        "/api/documents/upload/",
        {"document_type": "valid_id", "file": upload},
        format="multipart",
    )
    force_authenticate(request, user=user)

    response = DocumentUploadView.as_view(authentication_classes=[])(request)

    assert response.status_code == 500
    queued = DocumentStorageCleanup.find_pending()
    assert len(queued) == 1
    assert queued[0].file_path.endswith("orphan.jpg")


def test_presigned_completion_marker_failure_keeps_committed_object(
    settings, monkeypatch
):
    settings.DOCUMENT_UPLOAD_AI_ANALYSIS = False
    settings.DOCUMENT_UPLOAD_NOTIFY_REVIEWERS = False
    monkeypatch.setattr(
        "documents.services.presigned_upload.AuditLog.log_action",
        staticmethod(lambda *args, **kwargs: None),
    )
    contents = _image_bytes()
    session, token = DocumentUploadSession.issue(
        customer_id=str(ObjectId()),
        document_type="valid_id",
        original_filename="identity.jpg",
        description="",
        expected_size=len(contents),
        expected_mime_type="image/jpeg",
        expected_sha256=hashlib.sha256(contents).hexdigest(),
        lifetime_seconds=900,
    )
    session.set_object_key(f"document-uploads/quarantine/{session.id}/payload.jpg")
    storage = QuarantineStorage()
    storage.put_for_session(session, contents)
    original = DocumentUploadSession.mark_completed
    calls = {"count": 0}

    def fail_once(self, document_id):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("session marker unavailable")
        return original(self, document_id)

    monkeypatch.setattr(DocumentUploadSession, "mark_completed", fail_once)
    document, replayed = finalize_presigned_upload(
        session_id=session.id,
        customer_id=session.customer_id,
        finalize_token=token,
        storage=storage,
    )
    assert replayed is False
    assert document.file_path in storage.objects

    same, replayed = finalize_presigned_upload(
        session_id=session.id,
        customer_id=session.customer_id,
        finalize_token=token,
        storage=storage,
    )
    assert replayed is True
    assert same.id == document.id
    assert DocumentUploadSession.find_by_id(session.id).status == "completed"


def test_orphan_cleanup_queue_retries_idempotently():
    DocumentStorageCleanup.enqueue(
        "documents/customer/valid_id/orphan.jpg", reason="upload_rollback"
    )
    storage = RetryStorage(delete_result=True)

    first = reconcile_storage_operations(storage=storage)
    second = reconcile_storage_operations(storage=storage)

    assert first["orphan_cleanups_completed"] == 1
    assert second["orphan_cleanups_completed"] == 0
