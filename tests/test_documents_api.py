"""
Documents API tests for /api/documents/ endpoints.
"""
import io
from datetime import datetime, timezone

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from bson import ObjectId
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Admin, Consent, Customer, LoanOfficer
from documents.models import DOCUMENT_TYPES, DOCUMENT_STATUSES, Document
from documents.views import (
    DocumentDetailView,
    DocumentListView,
    DocumentPresignedUploadView,
    DocumentTypesView,
    DocumentVerifyView,
    RequestReuploadView,
    DocumentUploadView,
)


def _create_test_image():
    image = Image.new("RGB", (320, 320), color=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _create_customer(customer_id=None):
    customer = Customer(
        first_name="Test",
        last_name="User",
        email=f"docs_customer_{ObjectId()}@example.com",
        password="hashed",
        verified=True,
    ).save()
    if customer_id is not None:
        customer.id = customer_id
        customer.save()
    return customer


def _create_officer():
    officer = LoanOfficer(
        first_name="Officer",
        last_name="Test",
        email=f"docs_officer_{ObjectId()}@example.com",
        password="hashed",
        department="Operations",
    ).save()
    return officer


def _create_admin(permissions=None):
    admin = Admin(
        username=f"docs_admin_{ObjectId()}",
        email=f"docs_admin_{ObjectId()}@example.com",
        password="hashed",
        first_name="Admin",
        last_name="Test",
        permissions=permissions or ["manage_loans"],
        super_admin=False,
    ).save()
    return admin


def _auth_customer(customer):
    return AuthenticatedUser(
        customer_id=str(customer.id),
        email=customer.email,
        verified=True,
        role="customer",
    )


def _auth_officer(officer):
    return AuthenticatedUser(
        customer_id=str(officer.id),
        email=officer.email,
        verified=True,
        role="loan_officer",
    )


def _auth_admin(admin):
    return AuthenticatedUser(
        customer_id=str(admin.id),
        email=admin.email,
        verified=True,
        role="admin",
    )


def _post(path, payload, user, format="json"):
    factory = APIRequestFactory()
    request = factory.post(path, payload, format=format)
    force_authenticate(request, user=user)
    return request


def _get(path, user, query=None):
    factory = APIRequestFactory()
    request = factory.get(path, query or {}, format="json")
    force_authenticate(request, user=user)
    return request


def _put(path, payload, user):
    factory = APIRequestFactory()
    request = factory.put(path, payload, format="json")
    force_authenticate(request, user=user)
    return request


def _delete(path, user):
    factory = APIRequestFactory()
    request = factory.delete(path, {}, format="json")
    force_authenticate(request, user=user)
    return request


class FakeStorage:
    def save(self, file, customer_id, document_type, original_filename):
        return {
            "file_path": f"documents/{customer_id}/{document_type}/fake.jpg",
            "filename": "fake.jpg",
            "size": file.size,
        }

    def get_url(self, file_path):
        return f"http://example.com/{file_path}"

    def get_file_bytes(self, file_path):
        return b"fake-image-bytes"

    def delete(self, file_path):
        return True


class FakeEmailSender:
    def send_document_pending_review(self, **kwargs):
        return True

    def send_document_approved(self, **kwargs):
        return True

    def send_document_flagged(self, **kwargs):
        return True


class TestDocumentUpload:
    def test_upload_requires_customer(self, monkeypatch):
        customer = _create_customer()
        officer = _create_officer()

        monkeypatch.setattr(
            "documents.views.document_views.get_storage_backend",
            lambda: FakeStorage(),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.validate_uploaded_file",
            lambda file: (True, None),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.AuditLog.log_action",
            staticmethod(lambda *args, **kwargs: None),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.DocumentResponseSerializer",
            type(
                "Serializer",
                (),
                {
                    "data": property(
                        lambda self: {
                            "id": "doc-1",
                            "status": "pending",
                            "document_type": "valid_id",
                        }
                    )
                },
            ),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.services.analyze_document",
            lambda *args, **kwargs: {"quality_score": 1.0, "is_valid": True},
            raising=False,
        )

        upload = SimpleUploadedFile(
            "id.jpg", _create_test_image(), content_type="image/jpeg"
        )
        request = _post(
            "/api/documents/upload/",
            {"document_type": "valid_id", "file": upload},
            _auth_officer(officer),
            format="multipart",
        )
        monkeypatch.setattr(
            DocumentUploadView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentUploadView, "permission_classes", [], raising=False
        )

        response = DocumentUploadView.as_view()(request)
        assert response.status_code == 403

    def test_upload_accepts_valid_image(self, monkeypatch):
        customer = _create_customer()

        monkeypatch.setattr(
            "documents.views.document_views.get_storage_backend",
            lambda: FakeStorage(),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.validate_uploaded_file",
            lambda file: (True, None),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.AuditLog.log_action",
            staticmethod(lambda *args, **kwargs: None),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.DocumentResponseSerializer",
            type(
                "Serializer",
                (),
                {
                    "data": property(
                        lambda self: {
                            "id": "doc-1",
                            "status": "pending",
                            "document_type": "valid_id",
                        }
                    )
                },
            ),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.services.analyze_document",
            lambda *args, **kwargs: {"quality_score": 1.0, "is_valid": True},
            raising=False,
        )

        upload = SimpleUploadedFile(
            "id.jpg", _create_test_image(), content_type="image/jpeg"
        )
        request = _post(
            "/api/documents/upload/",
            {"document_type": "valid_id", "file": upload},
            _auth_customer(customer),
            format="multipart",
        )
        monkeypatch.setattr(
            DocumentUploadView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentUploadView, "permission_classes", [], raising=False
        )

        response = DocumentUploadView.as_view()(request)
        assert response.status_code in (200, 201)


class TestDocumentPresignedUpload:
    def test_presigned_upload_requires_customer(self, monkeypatch):
        officer = _create_officer()

        request = _post(
            "/api/documents/presigned-upload/",
            {"document_type": "valid_id", "original_filename": "photo.jpg"},
            _auth_officer(officer),
        )
        monkeypatch.setattr(
            DocumentPresignedUploadView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentPresignedUploadView, "permission_classes", [], raising=False
        )

        response = DocumentPresignedUploadView.as_view()(request)
        assert response.status_code == 403

    def test_presigned_upload_returns_400_when_backend_unsupported(self, monkeypatch):
        customer = _create_customer()

        monkeypatch.setattr(
            "documents.views.document_views.get_storage_backend",
            lambda: FakeStorage(),
            raising=False,
        )

        request = _post(
            "/api/documents/presigned-upload/",
            {"document_type": "valid_id", "original_filename": "photo.jpg"},
            _auth_customer(customer),
        )
        monkeypatch.setattr(
            DocumentPresignedUploadView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentPresignedUploadView, "permission_classes", [], raising=False
        )

        response = DocumentPresignedUploadView.as_view()(request)
        assert response.status_code == 400
        assert "not supported" in response.data["message"].lower()


class TestDocumentList:
    def test_list_requires_authenticated_role(self, monkeypatch):
        customer = _create_customer()

        monkeypatch.setattr(
            "documents.views.document_views.Document.find",
            lambda query, sort=None: [],
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.Document.count_by_customer",
            staticmethod(lambda customer_id, document_type=None: 0),
            raising=False,
        )

        request = _get("/api/documents/", _auth_customer(customer))
        monkeypatch.setattr(
            DocumentListView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentListView, "permission_classes", [], raising=False
        )

        response = DocumentListView.as_view()(request)
        assert response.status_code == 200
        assert "documents" in response.data["data"]

    def test_list_filters_documents_for_customer(self, monkeypatch):
        customer = _create_customer()
        docs = [
            Document(
                customer_id=str(customer.id),
                document_type="valid_id",
                original_filename="id.jpg",
                file_path="documents/id.jpg",
                file_size=1024,
                mime_type="image/jpeg",
                status="pending",
            ),
            Document(
                customer_id=str(customer.id),
                document_type="proof_of_address",
                original_filename="address.jpg",
                file_path="documents/address.jpg",
                file_size=2048,
                mime_type="image/jpeg",
                status="approved",
            ),
        ]
        for doc in docs:
            doc.save()

        monkeypatch.setattr(
            "documents.views.document_views.Document.find",
            lambda query, sort=None: docs,
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.Document.count_by_customer",
            staticmethod(lambda customer_id, document_type=None: len(docs)),
            raising=False,
        )

        request = _get(
            "/api/documents/",
            _auth_customer(customer),
            {"type": DOCUMENT_TYPES[0]},
        )
        monkeypatch.setattr(
            DocumentListView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentListView, "permission_classes", [], raising=False
        )

        response = DocumentListView.as_view()(request)
        assert response.status_code == 200
        assert response.data["data"]["total"] == len(docs)


class TestDocumentTypes:
    def test_types_returns_document_type_list(self, monkeypatch):
        customer = _create_customer()

        request = _get("/api/documents/types/", _auth_customer(customer))
        monkeypatch.setattr(
            DocumentTypesView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentTypesView, "permission_classes", [], raising=False
        )

        response = DocumentTypesView.as_view()(request)
        assert response.status_code == 200
        assert "document_types" in response.data["data"]
        assert len(response.data["data"]["document_types"]) == len(DOCUMENT_TYPES)


class TestDocumentDetail:
    def test_detail_returns_404_for_missing_document(self, monkeypatch):
        customer = _create_customer()

        monkeypatch.setattr(
            "documents.views.document_views.Document.find_one",
            staticmethod(lambda query: None),
            raising=False,
        )

        missing_id = str(ObjectId())
        request = _get(
            f"/api/documents/{missing_id}/", _auth_customer(customer)
        )
        monkeypatch.setattr(
            DocumentDetailView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentDetailView, "permission_classes", [], raising=False
        )

        response = DocumentDetailView.as_view()(request, document_id=missing_id)
        assert response.status_code == 404

    def test_delete_verified_document_returns_400(self, monkeypatch):
        customer = _create_customer()
        document = Document(
            customer_id=str(customer.id),
            document_type="valid_id",
            original_filename="id.jpg",
            file_path="documents/id.jpg",
            file_size=1024,
            mime_type="image/jpeg",
            status="approved",
            verified=True,
        )
        document.save()

        monkeypatch.setattr(
            "documents.views.document_views.Document.find_one",
            staticmethod(lambda query: document),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.get_storage_backend",
            lambda: FakeStorage(),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.Document.delete",
            lambda self: None,
            raising=False,
        )

        request = _delete(
            f"/api/documents/{document.id}/", _auth_customer(customer)
        )
        monkeypatch.setattr(
            DocumentDetailView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentDetailView, "permission_classes", [], raising=False
        )

        response = DocumentDetailView.as_view()(
            request, document_id=document.id
        )
        assert response.status_code == 400
        assert "verified" in response.data["message"].lower()


class TestDocumentVerify:
    def test_verify_approves_document(self, monkeypatch):
        customer = _create_customer()
        officer = _create_officer()
        document = Document(
            customer_id=str(customer.id),
            document_type="valid_id",
            original_filename="id.jpg",
            file_path="documents/id.jpg",
            file_size=1024,
            mime_type="image/jpeg",
            status="pending",
            verified=False,
        )
        document.save()

        monkeypatch.setattr(
            "documents.views.document_views.Document.find_one",
            staticmethod(lambda query: document),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.get_customer_by_identifier",
            staticmethod(lambda customer_id: customer),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.get_display_name",
            staticmethod(lambda user, fallback="User": "Test User"),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.AuditLog.log_action",
            staticmethod(lambda *args, **kwargs: None),
            raising=False,
        )
        monkeypatch.setattr(
            "notifications.services.get_email_sender",
            staticmethod(lambda: FakeEmailSender()),
            raising=False,
        )

        request = _put(
            f"/api/documents/{document.id}/verify/",
            {"action": "approve"},
            _auth_officer(officer),
        )
        monkeypatch.setattr(
            DocumentVerifyView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentVerifyView, "permission_classes", [], raising=False
        )

        response = DocumentVerifyView.as_view()(request, document_id=document.id)
        assert response.status_code == 200
        assert response.data["data"]["status"] == "approved"
        assert response.data["data"]["verified"] is True

    def test_verify_reject_requires_rejection_reason(self, monkeypatch):
        customer = _create_customer()
        officer = _create_officer()
        document = Document(
            customer_id=str(customer.id),
            document_type="valid_id",
            original_filename="id.jpg",
            file_path="documents/id.jpg",
            file_size=1024,
            mime_type="image/jpeg",
            status="pending",
            verified=False,
        )
        document.save()

        monkeypatch.setattr(
            "documents.views.document_views.Document.find_one",
            staticmethod(lambda query: document),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.get_customer_by_identifier",
            staticmethod(lambda customer_id: customer),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.get_display_name",
            staticmethod(lambda user, fallback="User": "Test User"),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.AuditLog.log_action",
            staticmethod(lambda *args, **kwargs: None),
            raising=False,
        )
        monkeypatch.setattr(
            "notifications.services.get_email_sender",
            staticmethod(lambda: FakeEmailSender()),
            raising=False,
        )

        request = _put(
            f"/api/documents/{document.id}/verify/",
            {"action": "reject"},
            _auth_officer(officer),
        )
        monkeypatch.setattr(
            DocumentVerifyView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            DocumentVerifyView, "permission_classes", [], raising=False
        )

        response = DocumentVerifyView.as_view()(request, document_id=document.id)
        assert response.status_code == 400
        assert "rejection_reason" in response.data["errors"]


class TestRequestReupload:
    def test_request_reupload_creates_reupload_request(self, monkeypatch):
        customer = _create_customer()
        officer = _create_officer()
        document = Document(
            customer_id=str(customer.id),
            document_type="valid_id",
            original_filename="id.jpg",
            file_path="documents/id.jpg",
            file_size=1024,
            mime_type="image/jpeg",
            status="pending",
            verified=False,
        )
        document.save()

        monkeypatch.setattr(
            "documents.views.document_views.Document.find_one",
            staticmethod(lambda query: document),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.get_customer_by_identifier",
            staticmethod(lambda customer_id: customer),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.get_display_name",
            staticmethod(lambda user, fallback="User": "Test User"),
            raising=False,
        )
        monkeypatch.setattr(
            "notifications.services.get_email_sender",
            staticmethod(lambda: FakeEmailSender()),
            raising=False,
        )

        request = _post(
            f"/api/documents/{document.id}/request-reupload/",
            {"reason": "Please upload a clearer image"},
            _auth_officer(officer),
        )
        monkeypatch.setattr(
            RequestReuploadView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            RequestReuploadView, "permission_classes", [], raising=False
        )

        response = RequestReuploadView.as_view()(request, document_id=document.id)
        assert response.status_code == 200
        assert response.data["data"]["status"] == "needs_review"
        assert response.data["data"]["reupload_requested"] is True

    def test_request_reupload_requires_reason(self, monkeypatch):
        customer = _create_customer()
        officer = _create_officer()
        document = Document(
            customer_id=str(customer.id),
            document_type="valid_id",
            original_filename="id.jpg",
            file_path="documents/id.jpg",
            file_size=1024,
            mime_type="image/jpeg",
            status="pending",
            verified=False,
        )
        document.save()

        monkeypatch.setattr(
            "documents.views.document_views.Document.find_one",
            staticmethod(lambda query: document),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.get_customer_by_identifier",
            staticmethod(lambda customer_id: customer),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.views.document_views.get_display_name",
            staticmethod(lambda user, fallback="User": "Test User"),
            raising=False,
        )

        request = _post(
            f"/api/documents/{document.id}/request-reupload/",
            {"reason": ""},
            _auth_officer(officer),
        )
        monkeypatch.setattr(
            RequestReuploadView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            RequestReuploadView, "permission_classes", [], raising=False
        )

        response = RequestReuploadView.as_view()(request, document_id=document.id)
        assert response.status_code == 400
