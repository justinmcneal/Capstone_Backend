"""Stage 4 permission, privacy, scope, and recoverable-audit tests."""

from bson import ObjectId
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Admin, Customer, LoanOfficer
from documents.models import Document
from documents.services.audit import reconcile_document_audit_failures
from documents.services.notification import notify_reviewers_document_pending
from documents.views import DocumentDetailView, DocumentListView, DocumentVerifyView


def _customer():
    return Customer(
        first_name="Customer",
        last_name="Scoped",
        email=f"customer-{ObjectId()}@example.test",
        password="hashed",
        verified=True,
    ).save()


def _officer(*, active=True, permissions=None):
    return LoanOfficer(
        employee_id=f"EMP-{ObjectId()}",
        first_name="Review",
        last_name="Officer",
        email=f"officer-{ObjectId()}@example.test",
        password="hashed",
        active=active,
        permissions=(
            ["review_documents"] if permissions is None else permissions
        ),
    ).save()


def _admin(*, permissions=None):
    return Admin(
        username=f"admin-{ObjectId()}",
        email=f"admin-{ObjectId()}@example.test",
        password="hashed",
        permissions=permissions or [],
    ).save()


def _auth(actor, role):
    return AuthenticatedUser(
        customer_id=actor.id,
        email=actor.email,
        verified=True,
        role=role,
    )


def _document(customer):
    return Document(
        customer_id=customer.id,
        document_type="valid_id",
        original_filename="private-name.jpg",
        file_path=f"documents/{customer.id}/valid_id/document.jpg",
        file_size=1024,
        mime_type="image/jpeg",
    ).save()


def test_admin_and_officer_review_mutations_require_explicit_permission():
    customer = _customer()
    document = _document(customer)
    factory = APIRequestFactory()

    for actor, role in (
        (_admin(permissions=[]), "admin"),
        (_officer(permissions=[]), "loan_officer"),
    ):
        request = factory.put(
            f"/api/documents/{document.id}/verify/",
            {"action": "approve"},
            format="json",
        )
        force_authenticate(request, user=_auth(actor, role))
        response = DocumentVerifyView.as_view(authentication_classes=[])(
            request, document_id=document.id
        )
        assert response.status_code == 403
        assert "permission" in response.data["message"].lower()


def test_real_access_helpers_conceal_cross_customer_and_inactive_officer(settings):
    customer = _customer()
    document = _document(customer)
    assigned = _officer()
    outside = _officer()
    inactive = _officer(active=False)
    settings.MONGODB["loan_applications"].insert_one(
        {
            "customer_id": customer.id,
            "assigned_officer": assigned.id,
            "status": "submitted",
        }
    )
    factory = APIRequestFactory()

    request = factory.get(f"/api/documents/{document.id}/")
    force_authenticate(request, user=_auth(outside, "loan_officer"))
    denied = DocumentDetailView.as_view(authentication_classes=[])(
        request, document_id=document.id
    )
    assert denied.status_code == 404
    assert settings.MONGODB["audit_logs"].count_documents(
        {"action": "document_access_denied"}
    ) == 1

    request = factory.get("/api/documents/")
    force_authenticate(request, user=_auth(inactive, "loan_officer"))
    inactive_response = DocumentListView.as_view(authentication_classes=[])(request)
    assert inactive_response.status_code == 403


def test_list_is_metadata_only_and_staff_read_is_audited(monkeypatch, settings):
    customer = _customer()
    officer = _officer()
    document = _document(customer)

    class NoUrlStorage:
        def get_url(self, file_path):
            raise AssertionError("list views must not mint document URLs")

    monkeypatch.setattr(
        "documents.serializers.document_serializers.get_storage_backend",
        lambda: NoUrlStorage(),
        raising=False,
    )
    request = APIRequestFactory().get("/api/documents/")
    force_authenticate(request, user=_auth(officer, "loan_officer"))

    response = DocumentListView.as_view(authentication_classes=[])(request)

    assert response.status_code == 200
    assert response.data["data"]["documents"][0]["id"] == document.id
    assert response.data["data"]["documents"][0]["file_url"] is None
    audit = settings.MONGODB["audit_logs"].find_one(
        {"action": "document_list_viewed"}
    )
    assert audit is not None
    assert "filename" not in audit.get("details", {})


def test_required_read_audit_failure_is_queued_and_reconciled(
    monkeypatch, settings
):
    customer = _customer()
    officer = _officer()
    _document(customer)
    request = APIRequestFactory().get("/api/documents/")
    force_authenticate(request, user=_auth(officer, "loan_officer"))

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(
        "documents.services.audit.AuditLog.log_action", unavailable
    )
    response = DocumentListView.as_view(authentication_classes=[])(request)
    assert response.status_code == 503
    queued = settings.MONGODB["audit_write_failures"].find_one(
        {"domain": "documents", "resolved_at": None}
    )
    assert queued is not None
    assert set(queued["payload"]["details"]) <= {
        "filter_customer_id",
        "filter_document_type",
        "filter_status",
        "page",
        "page_size",
        "result_count",
        "search_applied",
    }

    monkeypatch.setattr(
        "documents.services.audit.AuditLog.log_action",
        lambda **kwargs: object(),
    )
    assert reconcile_document_audit_failures() == 1
    assert settings.MONGODB["audit_write_failures"].find_one(
        {"_id": queued["_id"]}
    )["resolved_at"] is not None


def test_reviewer_notification_respects_permission_and_assignment(
    monkeypatch, settings
):
    customer = _customer()
    assigned = _officer()
    outside = _officer()
    allowed_admin = _admin(permissions=["review_documents"])
    denied_admin = _admin(permissions=[])
    document = _document(customer)
    settings.MONGODB["loan_applications"].insert_one(
        {
            "customer_id": customer.id,
            "assigned_officer": assigned.id,
            "status": "submitted",
        }
    )
    recipients = []

    class Sender:
        def send_document_pending_review(self, **kwargs):
            recipients.append(kwargs["reviewer_email"])

    monkeypatch.setattr(
        "documents.services.notification.get_email_sender", lambda: Sender()
    )

    notify_reviewers_document_pending(document)

    assert assigned.email in recipients
    assert allowed_admin.email in recipients
    assert outside.email not in recipients
    assert denied_admin.email not in recipients
