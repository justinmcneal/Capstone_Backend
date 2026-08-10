"""Explicitly opt-in workflow proof against an isolated real S3 bucket."""

import hashlib
import io
import os
import uuid

import pytest
import requests
from botocore.exceptions import ClientError
from PIL import Image

from documents.models import DocumentUploadSession
from documents.services.presigned_upload import finalize_presigned_upload
from documents.storage.backends import S3StorageBackend

REAL_S3_BUCKET = os.getenv("REAL_S3_TEST_BUCKET")
REAL_S3_ALLOW_MUTATION = os.getenv("REAL_S3_TEST_ALLOW_MUTATION") == "yes"


def _image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (320, 320), color=(240, 240, 240)).save(
        output, format="JPEG"
    )
    return output.getvalue()


@pytest.mark.real_s3
def test_real_s3_presigned_finalize_replay_and_cleanup(settings, monkeypatch):
    """Mutate only unique objects in a bucket explicitly approved for testing."""
    if not REAL_S3_BUCKET or not REAL_S3_ALLOW_MUTATION:
        pytest.skip(
            "REAL_S3_TEST_BUCKET and REAL_S3_TEST_ALLOW_MUTATION=yes are required"
        )

    region = os.getenv("REAL_S3_TEST_REGION") or "us-east-1"
    endpoint = os.getenv("REAL_S3_TEST_ENDPOINT") or None
    encryption = os.getenv("REAL_S3_TEST_SSE") or "AES256"
    object_parameters = {"ServerSideEncryption": encryption}
    kms_key_id = os.getenv("REAL_S3_TEST_KMS_KEY_ID")
    if kms_key_id:
        object_parameters["SSEKMSKeyId"] = kms_key_id

    settings.AWS_STORAGE_BUCKET_NAME = REAL_S3_BUCKET
    settings.AWS_S3_REGION_NAME = region
    settings.AWS_S3_ENDPOINT_URL = endpoint
    settings.AWS_DEFAULT_ACL = None
    settings.AWS_S3_OBJECT_PARAMETERS = object_parameters
    settings.DOCUMENT_UPLOAD_AI_ANALYSIS = False
    settings.DOCUMENT_UPLOAD_NOTIFY_REVIEWERS = False
    backend = S3StorageBackend()
    contents = _image_bytes()
    digest = hashlib.sha256(contents).hexdigest()
    customer_id = f"real-s3-validation-{uuid.uuid4().hex}"
    session, token = DocumentUploadSession.issue(
        customer_id=customer_id,
        document_type="valid_id",
        original_filename="validation.jpg",
        description="",
        expected_size=len(contents),
        expected_mime_type="image/jpeg",
        expected_sha256=digest,
        lifetime_seconds=900,
    )
    upload = backend.create_quarantined_presigned_upload(
        session_id=session.id,
        original_filename=session.original_filename,
        expected_size=session.expected_size,
        expected_mime_type=session.expected_mime_type,
        expected_sha256=session.expected_sha256,
        expires_in=900,
    )
    assert upload is not None
    session.set_object_key(upload["object_key"])
    final_key = None
    s3 = backend.s3
    try:
        response = requests.post(
            upload["post"]["url"],
            data=upload["post"]["fields"],
            files={"file": ("validation.jpg", contents, "image/jpeg")},
            timeout=30,
        )
        assert response.status_code in {200, 201, 204}
        monkeypatch.setattr(
            "documents.services.presigned_upload.AuditLog.log_action",
            staticmethod(lambda *args, **kwargs: None),
        )

        document, replayed = finalize_presigned_upload(
            session_id=session.id,
            customer_id=customer_id,
            finalize_token=token,
            storage=backend,
        )
        final_key = document.file_path
        assert replayed is False
        replay, replayed = finalize_presigned_upload(
            session_id=session.id,
            customer_id=customer_id,
            finalize_token=token,
            storage=backend,
        )
        assert replayed is True
        assert replay.id == document.id
        assert s3.head_object(Bucket=REAL_S3_BUCKET, Key=final_key)[
            "ContentLength"
        ] == len(contents)
        with pytest.raises(ClientError):
            s3.head_object(Bucket=REAL_S3_BUCKET, Key=session.object_key)
    finally:
        for key in (session.object_key, final_key):
            if key:
                s3.delete_object(Bucket=REAL_S3_BUCKET, Key=key)
