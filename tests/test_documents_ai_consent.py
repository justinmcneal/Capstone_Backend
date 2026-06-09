import io

from PIL import Image
from rest_framework.test import APIRequestFactory, force_authenticate
from django.core.files.uploadedfile import SimpleUploadedFile

import accounts.views.consent_views as consent_views
import documents.views.document_views as document_views
from accounts.authentication import AuthenticatedUser
from documents.views import DocumentUploadView


class FakeDocument:
    def __init__(self, **kwargs):
        from datetime import datetime, timezone

        self.id = "fake-doc-id"
        self.uploaded_at = datetime.now(timezone.utc)
        self.file_size = kwargs.get("file_size", 0)
        self.file_size_display = f"{self.file_size} bytes"
        self.status = "pending"
        self.original_filename = kwargs.get("original_filename")
        self.document_type = kwargs.get("document_type")
        self.verified = False
        self.customer_id = kwargs.get("customer_id")

    def save(self):
        return True


class FakeStorage:
    def save(self, file, customer_id, document_type, original_filename):
        return {
            "file_path": f"documents/{customer_id}/{document_type}/fake.jpg",
            "filename": "fake.jpg",
            "size": file.size,
        }

    def get_url(self, file_path):
        return f"http://example.com/{file_path}"


def _create_test_image():
    image = Image.new("RGB", (320, 320), color=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _auth_customer(customer_id="customer-1"):
    return AuthenticatedUser(
        customer_id=customer_id,
        email="customer@example.com",
        verified=True,
        role="customer",
    )


def _auth_admin(admin_id="admin-1"):
    return AuthenticatedUser(
        customer_id=admin_id,
        email="admin@example.com",
        verified=True,
        role="admin",
    )


def test_document_upload_skips_ai_when_consent_is_false(monkeypatch):
    monkeypatch.setattr(document_views, "Document", FakeDocument, raising=False)
    monkeypatch.setattr(
        document_views,
        "AuditLog",
        type("Audit", (), {"log_action": staticmethod(lambda *args, **kwargs: None)}),
        raising=False,
    )
    monkeypatch.setattr(
        document_views,
        "get_storage_backend",
        lambda: FakeStorage(),
        raising=False,
    )
    monkeypatch.setattr(
        document_views,
        "validate_uploaded_file",
        lambda file: (True, None),
        raising=False,
    )
    monkeypatch.setattr(
        document_views.ConsentService,
        "check_ai_consent",
        staticmethod(lambda customer_id, user_type="customer": False),
    )

    # Bypass DB actor resolution in access control for the upload view
    monkeypatch.setattr(document_views.AccessControlMixin, "require_customer", lambda self, request: (True, request.user), raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("analyze_document should not run when ai_consent is False")

    monkeypatch.setattr("documents.services.analyze_document", fail_if_called, raising=False)

    factory = APIRequestFactory()
    upload = SimpleUploadedFile(
        "id.jpg",
        _create_test_image(),
        content_type="image/jpeg",
    )
    request = factory.post(
        "/api/documents/upload/",
        {"document_type": "valid_id", "file": upload},
        format="multipart",
    )
    force_authenticate(request, user=_auth_customer())

    monkeypatch.setattr(DocumentUploadView, "authentication_classes", [])
    monkeypatch.setattr(DocumentUploadView, "permission_classes", [])

    response = DocumentUploadView.as_view()(request)

    assert response.status_code in (200, 201)
    assert response.data["status"] == "success"
    assert response.data["data"]["status"] == "pending"
    assert "ai_analysis" not in response.data["data"]


def test_consent_audit_returns_customer_ai_consent_report(monkeypatch):
    class FakeCustomer:
        def __init__(self, customer_id, name, email, verified=True):
            self._id = customer_id
            self.customer_id = customer_id
            self.full_name = name
            self.email = email
            self.verified = verified

        @property
        def id(self):
            return self.customer_id

    class FakeConsent:
        def __init__(self, user_id, data_consent, ai_consent):
            self.user_id = user_id
            self.data_consent = data_consent
            self.ai_consent = ai_consent
            from datetime import datetime, timezone

            self.consent_date = datetime.now(timezone.utc)
            self.updated_at = datetime.now(timezone.utc)

    customers = [
        FakeCustomer("cust-1", "Alice Example", "alice@example.com"),
        FakeCustomer("cust-2", "Bob Example", "bob@example.com"),
        FakeCustomer("cust-3", "No Consent", "noconsent@example.com"),
    ]
    consents = [
        FakeConsent("cust-1", True, True),
        FakeConsent("cust-2", True, False),
    ]

    # Allow admin access without DB lookup
    monkeypatch.setattr(
        consent_views.AccessControlMixin,
        "require_admin",
        lambda self, request, required_permissions=None, super_admin_only=False: (True, object()),
    )
    monkeypatch.setattr(consent_views.Customer, "find", classmethod(lambda cls, query, **kwargs: customers))
    monkeypatch.setattr(consent_views.Consent, "find", classmethod(lambda cls, query, **kwargs: consents))

    factory = APIRequestFactory()
    request = factory.get("/api/accounts/consent/audit/")
    force_authenticate(request, user=_auth_admin())

    response = consent_views.ConsentAuditView.as_view()(request)

    assert response.status_code == 200
    assert response.data["status"] == "success"
    assert response.data["data"]["summary"]["total_customers"] == 3
    assert response.data["data"]["summary"]["ai_consent_true"] == 1
    assert response.data["data"]["summary"]["ai_consent_false"] == 2
    assert response.data["data"]["summary"]["missing_consent_records"] == 1
    assert len(response.data["data"]["customers"]) == 3
