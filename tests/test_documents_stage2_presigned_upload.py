"""Stage 2 tests for tracked, quarantined, one-time document uploads."""

import hashlib
import io

import boto3
import pytest
from botocore.exceptions import ClientError
from bson import ObjectId
from PIL import Image
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from documents.models import Document, DocumentUploadSession
from documents.services.presigned_upload import (
    PresignedUploadError,
    cleanup_expired_upload_sessions,
    finalize_presigned_upload,
)
from documents.storage.backends import S3StorageBackend
from documents.views import DocumentPresignedUploadView

try:
    from moto import mock_s3
except Exception:  # noqa: BLE001 - moto exposes different compatibility APIs
    from moto import mock_aws as mock_s3


def _image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (320, 320), color=(255, 255, 255)).save(output, format="JPEG")
    return output.getvalue()


class QuarantineStorage:
    supports_presigned_uploads = True

    def __init__(self):
        self.objects = {}
        self.deleted = []

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
            "etag": "test-etag",
        }

    def get_file_bytes(self, object_key):
        return self.objects[object_key]["contents"]

    def promote_quarantined_upload(
        self, object_key, customer_id, document_type, original_filename
    ):
        destination = f"documents/{customer_id}/{document_type}/final.jpg"
        self.objects[destination] = self.objects.pop(object_key)
        return {
            "file_path": destination,
            "filename": "final.jpg",
            "size": len(self.objects[destination]["contents"]),
            "etag": "test-etag",
        }

    def delete(self, object_key):
        self.deleted.append(object_key)
        return self.objects.pop(object_key, None) is not None


class PresignStorage(QuarantineStorage):
    def create_quarantined_presigned_upload(self, **kwargs):
        object_key = (
            f"document-uploads/quarantine/{kwargs['session_id']}/payload.jpg"
        )
        return {
            "object_key": object_key,
            "post": {
                "url": "https://storage.example.test",
                "fields": {"key": object_key},
            },
        }


def _issue_session(contents, *, customer_id=None, lifetime_seconds=900):
    customer_id = customer_id or str(ObjectId())
    digest = hashlib.sha256(contents).hexdigest()
    session, token = DocumentUploadSession.issue(
        customer_id=customer_id,
        document_type="valid_id",
        original_filename="identity.jpg",
        description="Identity document",
        expected_size=len(contents),
        expected_mime_type="image/jpeg",
        expected_sha256=digest,
        lifetime_seconds=lifetime_seconds,
    )
    session.set_object_key(
        f"document-uploads/quarantine/{session.id}/payload.jpg"
    )
    return session, token


@pytest.fixture
def safe_finalize_settings(settings, monkeypatch):
    settings.DOCUMENT_UPLOAD_AI_ANALYSIS = False
    settings.DOCUMENT_UPLOAD_NOTIFY_REVIEWERS = False
    monkeypatch.setattr(
        "documents.services.presigned_upload.AuditLog.log_action",
        staticmethod(lambda *args, **kwargs: None),
    )


def test_finalize_validates_promotes_and_creates_document_once(
    safe_finalize_settings,
):
    contents = _image_bytes()
    session, token = _issue_session(contents)
    storage = QuarantineStorage()
    storage.put_for_session(session, contents)

    document, replayed = finalize_presigned_upload(
        session_id=session.id,
        customer_id=session.customer_id,
        finalize_token=token,
        storage=storage,
    )

    assert replayed is False
    assert document.upload_session_id == session.id
    assert document.sha256 == hashlib.sha256(contents).hexdigest()
    assert document.file_path.startswith("documents/")
    assert Document.find_one({"upload_session_id": session.id}).id == document.id
    completed = DocumentUploadSession.find_by_id(session.id)
    assert completed.status == "completed"
    assert completed.document_id == document.id

    same_document, replayed = finalize_presigned_upload(
        session_id=session.id,
        customer_id=session.customer_id,
        finalize_token=token,
        storage=storage,
    )
    assert replayed is True
    assert same_document.id == document.id
    assert len(Document.find({"upload_session_id": session.id})) == 1


def test_finalize_rejects_wrong_owner_or_token_without_disclosing_session(
    safe_finalize_settings,
):
    contents = _image_bytes()
    session, token = _issue_session(contents)
    storage = QuarantineStorage()
    storage.put_for_session(session, contents)

    with pytest.raises(PresignedUploadError) as wrong_owner:
        finalize_presigned_upload(
            session_id=session.id,
            customer_id=str(ObjectId()),
            finalize_token=token,
            storage=storage,
        )
    assert wrong_owner.value.status_code == 404

    with pytest.raises(PresignedUploadError) as wrong_token:
        finalize_presigned_upload(
            session_id=session.id,
            customer_id=session.customer_id,
            finalize_token="x" * 43,
            storage=storage,
        )
    assert wrong_token.value.status_code == 404


def test_finalize_rejects_hash_mismatch_and_removes_quarantine(
    safe_finalize_settings,
):
    expected_contents = _image_bytes()
    session, token = _issue_session(expected_contents)
    storage = QuarantineStorage()
    different_contents = expected_contents + b"changed"
    storage.put_for_session(session, different_contents)
    storage.objects[session.object_key]["metadata"]["sha256"] = session.expected_sha256

    with pytest.raises(PresignedUploadError) as failure:
        finalize_presigned_upload(
            session_id=session.id,
            customer_id=session.customer_id,
            finalize_token=token,
            storage=storage,
        )

    assert failure.value.failure_code in {
        "size_mismatch",
        "content_size_mismatch",
        "content_hash_mismatch",
    }
    assert session.object_key in storage.deleted
    assert Document.find_one({"upload_session_id": session.id}) is None


def test_finalize_rejects_unsafe_content_after_hash_verification(
    safe_finalize_settings,
):
    contents = b"MZ" + (b"\x00" * 512)
    session, token = _issue_session(contents)
    storage = QuarantineStorage()
    storage.put_for_session(session, contents)

    with pytest.raises(PresignedUploadError) as failure:
        finalize_presigned_upload(
            session_id=session.id,
            customer_id=session.customer_id,
            finalize_token=token,
            storage=storage,
        )

    assert failure.value.failure_code == "content_validation_failed"
    assert session.object_key in storage.deleted
    assert Document.find_one({"upload_session_id": session.id}) is None


def test_cleanup_removes_expired_quarantine_objects():
    contents = _image_bytes()
    session, _ = _issue_session(contents, lifetime_seconds=-1)
    storage = QuarantineStorage()
    storage.put_for_session(session, contents)

    result = cleanup_expired_upload_sessions(storage=storage)

    assert result == {"cleaned": 1, "failed": 0}
    assert session.object_key in storage.deleted
    assert DocumentUploadSession.find_by_id(session.id).status == "expired"


def test_create_endpoint_issues_owner_bound_quarantine_session(
    settings, monkeypatch
):
    settings.DOCUMENT_PRESIGNED_UPLOAD_ENABLED = True
    settings.DOCUMENT_PRESIGNED_UPLOAD_EXPIRY_SECONDS = 900
    contents = _image_bytes()
    customer_id = str(ObjectId())
    user = AuthenticatedUser(
        customer_id=customer_id,
        email="presigned-customer@example.com",
        verified=True,
        role="customer",
    )
    request = APIRequestFactory().post(
        "/api/documents/presigned-upload/",
        {
            "document_type": "valid_id",
            "original_filename": "identity.jpg",
            "description": "Identity document",
            "file_size": len(contents),
            "mime_type": "image/jpeg",
            "sha256": hashlib.sha256(contents).hexdigest(),
        },
        format="json",
    )
    force_authenticate(request, user=user)
    monkeypatch.setattr(
        DocumentPresignedUploadView, "authentication_classes", [], raising=False
    )
    monkeypatch.setattr(
        DocumentPresignedUploadView, "permission_classes", [], raising=False
    )
    monkeypatch.setattr(
        DocumentPresignedUploadView,
        "require_customer",
        lambda self, request: (True, request.user),
        raising=False,
    )
    monkeypatch.setattr(
        "documents.views.document_views.get_storage_backend",
        lambda: PresignStorage(),
    )

    response = DocumentPresignedUploadView.as_view()(request)

    assert response.status_code == 201
    data = response.data["data"]
    assert len(data["finalize_token"]) >= 32
    assert data["post"]["fields"]["key"].startswith(
        "document-uploads/quarantine/"
    )
    session = DocumentUploadSession.find_by_id(data["upload_session_id"])
    assert session.customer_id == customer_id
    assert session.status == "issued"
    assert session.object_key == data["post"]["fields"]["key"]


@mock_s3
def test_finalize_against_isolated_mock_s3(settings, monkeypatch):
    settings.AWS_STORAGE_BUCKET_NAME = "documents-stage2"
    settings.AWS_S3_REGION_NAME = "us-east-1"
    settings.AWS_DEFAULT_ACL = "private"
    settings.AWS_S3_OBJECT_PARAMETERS = {}
    settings.DOCUMENT_UPLOAD_AI_ANALYSIS = False
    settings.DOCUMENT_UPLOAD_NOTIFY_REVIEWERS = False
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
    backend = S3StorageBackend()
    contents = _image_bytes()
    session, token = _issue_session(contents)
    upload = backend.create_quarantined_presigned_upload(
        session_id=session.id,
        original_filename=session.original_filename,
        expected_size=session.expected_size,
        expected_mime_type=session.expected_mime_type,
        expected_sha256=session.expected_sha256,
        expires_in=900,
    )
    session.set_object_key(upload["object_key"])
    s3.put_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
        Key=session.object_key,
        Body=contents,
        ContentType=session.expected_mime_type,
        Metadata={
            "upload-session": session.id,
            "sha256": session.expected_sha256,
        },
    )
    monkeypatch.setattr(
        "documents.services.presigned_upload.AuditLog.log_action",
        staticmethod(lambda *args, **kwargs: None),
    )

    document, replayed = finalize_presigned_upload(
        session_id=session.id,
        customer_id=session.customer_id,
        finalize_token=token,
        storage=backend,
    )

    assert replayed is False
    assert backend.get_file_bytes(document.file_path) == contents
    with pytest.raises(ClientError):
        s3.head_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=session.object_key,
        )
