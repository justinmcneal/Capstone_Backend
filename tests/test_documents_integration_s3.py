import io
import json
import boto3
import pytest
try:
    from moto import mock_s3
except Exception:
    from moto import mock_aws as mock_s3

from django.urls import reverse
from django.test import override_settings
from rest_framework.test import APIRequestFactory

import documents.views as doc_views
from documents.views import DocumentUploadView


class FakeDocument:
    def __init__(self, **kwargs):
        self.id = 'fake-doc-id'
        from datetime import datetime, timezone
        self.uploaded_at = datetime.now(timezone.utc)
        self.file_size = kwargs.get('file_size', 0)
        self.file_size_display = f"{self.file_size} bytes"
        self.status = 'pending'
        self.original_filename = kwargs.get('original_filename')
        self.document_type = kwargs.get('document_type')

    def save(self):
        return True


@mock_s3
@override_settings(DOCUMENT_STORAGE_BACKEND='s3', AWS_STORAGE_BUCKET_NAME='test-bucket', DOCUMENT_UPLOAD_AI_ANALYSIS=False)
def test_document_upload_endpoint_s3(monkeypatch, settings):
    # Create bucket
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.create_bucket(Bucket='test-bucket')

    # Patch Document to avoid DB calls and AuditLog
    monkeypatch.setattr(doc_views, 'Document', FakeDocument, raising=False)
    class DummyAudit:
        @staticmethod
        def log_action(*args, **kwargs):
            return None
    monkeypatch.setattr(doc_views, 'AuditLog', DummyAudit, raising=False)

    # Patch AccessControlMixin.require_customer to allow upload
    def allow_customer(self, request):
        return True, None
    import accounts.utils.access_control as access_control
    monkeypatch.setattr(access_control.AccessControlMixin, 'require_customer', allow_customer, raising=False)

    # Bypass strict upload validation for the integration test environment
    import documents.serializers.document_serializers as ds
    monkeypatch.setattr(ds, 'validate_uploaded_file', lambda f: (True, None), raising=False)
    # Also patch the name imported into the views module
    monkeypatch.setattr(doc_views, 'validate_uploaded_file', lambda f: (True, None), raising=False)

    # Prepare a small file
    from django.core.files.uploadedfile import SimpleUploadedFile
    # Minimal PDF content to avoid image processing in test environment
    file_content = b"%PDF-1.4\n%EOF\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<<>>\n%%EOF"
    upload = SimpleUploadedFile('test.pdf', file_content, content_type='application/pdf')

    from rest_framework.test import APIClient
    client = APIClient()

    # Attach a fake authenticated user
    class User:
        is_authenticated = True
        customer_id = 'customer123'
    client.force_authenticate(user=User())

    data = {'document_type': 'valid_id'}
    data['file'] = upload

    # Disable authentication and permissions for test (class-level)
    doc_views.DocumentUploadView.authentication_classes = []
    doc_views.DocumentUploadView.permission_classes = []

    response = client.post('/api/documents/upload/', data, format='multipart')

    if response.status_code not in (201, 200):
        # Helpful debug on failure
        try:
            print('RESPONSE:', response.status_code, response.render().content)
        except Exception:
            pass
    assert response.status_code in (201, 200)
    content = json.loads(response.render().content)
    assert 'data' in content
    assert content['data']['status'] in ('pending', 'needs_review')
