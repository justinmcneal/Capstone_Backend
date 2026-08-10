"""Stage 1 document lifecycle and API contract regression tests."""

import pytest
from bson import ObjectId
from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from documents.models import Document
from documents.services.state_machine import (
    DOCUMENT_ALLOWED_TRANSITIONS,
    DocumentTransitionError,
    apply_reupload_request,
    apply_review_decision,
)
from documents.views import (
    DocumentDetailView,
    DocumentPresignedUploadView,
    DocumentVerifyView,
    RequestReuploadView,
)


def _user(role="customer"):
    return AuthenticatedUser(
        customer_id=str(ObjectId()),
        email=f"documents-{role}@example.com",
        verified=True,
        role=role,
    )


def _request(method, path, user, data=None):
    factory = APIRequestFactory()
    request = getattr(factory, method)(path, data or {}, format="json")
    force_authenticate(request, user=user)
    return request


def _disable_framework_auth(monkeypatch, view):
    monkeypatch.setattr(view, "authentication_classes", [], raising=False)
    monkeypatch.setattr(view, "permission_classes", [], raising=False)


def _document(status="pending", **overrides):
    values = {
        "_id": ObjectId(),
        "customer_id": str(ObjectId()),
        "document_type": "valid_id",
        "original_filename": "identity.jpg",
        "file_path": "documents/customer/valid_id/identity.jpg",
        "file_size": 1024,
        "mime_type": "image/jpeg",
        "status": status,
    }
    values.update(overrides)
    return Document(**values)


def test_state_machine_declares_terminal_states():
    assert DOCUMENT_ALLOWED_TRANSITIONS["approved"] == frozenset()
    assert DOCUMENT_ALLOWED_TRANSITIONS["expired"] == frozenset()
    assert DOCUMENT_ALLOWED_TRANSITIONS["rejected"] == frozenset({"needs_review"})


def test_approval_normalizes_incompatible_fields():
    document = _document(
        status="needs_review",
        verified=False,
        rejection_reason="Old rejection",
        reupload_requested=True,
        reupload_reason="Old request",
        reupload_requested_by=str(ObjectId()),
    )
    reviewer_id = str(ObjectId())

    apply_review_decision(document, action="approve", reviewer_id=reviewer_id)

    assert document.status == "approved"
    assert document.verified is True
    assert document.verified_by == reviewer_id
    assert document.verified_at is not None
    assert document.rejection_reason == ""
    assert document.reupload_requested is False
    assert document.reupload_reason == ""
    assert document.reupload_requested_by is None


def test_rejection_clears_stale_verification_and_reupload_fields():
    document = _document(
        status="needs_review",
        verified=True,
        verified_by=str(ObjectId()),
        reupload_requested=True,
        reupload_reason="Old request",
    )

    apply_review_decision(
        document,
        action="reject",
        reviewer_id=str(ObjectId()),
        rejection_reason="Unreadable",
    )

    assert document.status == "rejected"
    assert document.verified is False
    assert document.verified_by is None
    assert document.verified_at is None
    assert document.rejection_reason == "Unreadable"
    assert document.reupload_requested is False


@pytest.mark.parametrize("terminal_status", ["approved", "expired"])
def test_terminal_documents_reject_reupload_requests(terminal_status):
    document = _document(status=terminal_status, verified=terminal_status == "approved")

    with pytest.raises(DocumentTransitionError):
        apply_reupload_request(
            document,
            reviewer_id=str(ObjectId()),
            reason="Upload a replacement",
        )


@pytest.mark.parametrize(
    ("view", "method", "role", "suffix"),
    [
        (DocumentDetailView, "get", "customer", "/"),
        (DocumentDetailView, "delete", "customer", "/"),
        (DocumentVerifyView, "put", "loan_officer", "/verify/"),
        (RequestReuploadView, "post", "loan_officer", "/request-reupload/"),
    ],
)
def test_document_endpoints_reject_malformed_ids(
    monkeypatch, view, method, role, suffix
):
    invalid_id = "not-an-object-id"
    request_user = _user(role)
    path = f"/api/documents/{invalid_id}{suffix}"
    request = _request(method, path, request_user, {"action": "approve"})
    _disable_framework_auth(monkeypatch, view)

    monkeypatch.setattr(
        view,
        "require_roles",
        lambda self, request, roles: (True, request.user),
        raising=False,
    )
    monkeypatch.setattr(
        view,
        "require_customer",
        lambda self, request: (True, request.user),
        raising=False,
    )
    monkeypatch.setattr(
        view,
        "require_officer_or_admin",
        lambda self, request: (True, request.user),
        raising=False,
    )

    response = view.as_view()(request, document_id=invalid_id)

    assert response.status_code == 400
    assert response.data["message"] == "Invalid document_id format"


@override_settings(DOCUMENT_PRESIGNED_UPLOAD_ENABLED=False)
def test_presigned_upload_is_disabled_by_default(monkeypatch):
    request_user = _user("customer")
    request = _request(
        "post",
        "/api/documents/presigned-upload/",
        request_user,
        {"document_type": "valid_id", "original_filename": "identity.jpg"},
    )
    _disable_framework_auth(monkeypatch, DocumentPresignedUploadView)
    monkeypatch.setattr(
        DocumentPresignedUploadView,
        "require_customer",
        lambda self, request: (True, request.user),
        raising=False,
    )

    def fail_if_storage_is_called():
        raise AssertionError("disabled presigned route must not access storage")

    monkeypatch.setattr(
        "documents.views.document_views.get_storage_backend",
        fail_if_storage_is_called,
    )

    response = DocumentPresignedUploadView.as_view()(request)

    assert response.status_code == 404
    assert "not available" in response.data["message"].lower()
