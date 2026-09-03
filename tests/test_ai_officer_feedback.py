import uuid
from unittest.mock import Mock, patch

from bson import ObjectId
from django.conf import settings
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import LoanOfficer
from ai_assistant.models.officer_feedback import OfficerAIFeedback
from ai_assistant.views.officer_feedback import OfficerFeedbackView
from analytics.models import AuditLog
from loans.models import LoanApplication


def _officer():
    return LoanOfficer(
        first_name="Loan",
        last_name="Officer",
        email=f"officer-{ObjectId()}@example.com",
        password="hashed",
        department="Credit",
    ).save()


def _application(officer_id, customer_id="customer-42"):
    return LoanApplication(
        customer_id=customer_id,
        product_id=str(ObjectId()),
        requested_amount=10000,
        assigned_officer=str(officer_id),
        status="under_review",
    ).save()


def _request(officer_id, data, *, role="loan_officer"):
    factory = APIRequestFactory()
    request = factory.post("/api/ai/officer/feedback/", data, format="json")
    force_authenticate(
        request,
        user=AuthenticatedUser(
            customer_id=str(officer_id),
            email="actor@example.com",
            verified=True,
            role=role,
        ),
    )
    return request


def _complete_lease(customer_id, request_id):
    settings.MONGODB['ai_chat_requests'].insert_one(
        {
            'customer_id': str(customer_id),
            'request_id': str(request_id),
            'status': 'complete',
        }
    )


def _feedback_payload(application_id, request_id, **overrides):
    payload = {
        "application_id": str(application_id),
        "request_id": str(request_id),
        "rating": "up",
    }
    payload.update(overrides)
    return payload


def _audit_actions():
    return [
        AuditLog.from_dict(row)
        for row in settings.MONGODB[AuditLog.collection_name].find()
    ]


def test_officer_feedback_route_is_registered():
    from django.urls import reverse

    assert reverse("ai_assistant:officer-feedback") == "/api/ai/officer/feedback/"


def test_officer_feedback_records_rating_for_completed_response():
    officer = _officer()
    application = _application(officer.id)
    request_id = str(uuid.uuid4())
    _complete_lease(application.customer_id, request_id)

    response = OfficerFeedbackView.as_view()(
        _request(
            officer.id,
            _feedback_payload(application.id, request_id, rating="down",
                               comment="Repayment math looked off."),
        )
    )

    assert response.status_code == 200, response.data
    assert response.data["data"] == {
        "rating": "down",
        "request_id": request_id,
        "updated": False,
    }
    stored = OfficerAIFeedback.find_for_request(
        str(officer.id), str(application.id), request_id
    )
    assert stored is not None
    assert stored.rating == "down"
    assert stored.comment == "Repayment math looked off."
    assert stored.customer_id == str(application.customer_id)


def test_officer_feedback_resubmission_updates_rating_without_duplicates():
    officer = _officer()
    application = _application(officer.id)
    request_id = str(uuid.uuid4())
    _complete_lease(application.customer_id, request_id)

    first = OfficerFeedbackView.as_view()(
        _request(officer.id, _feedback_payload(application.id, request_id))
    )
    second = OfficerFeedbackView.as_view()(
        _request(
            officer.id,
            _feedback_payload(application.id, request_id, rating="down"),
        )
    )

    assert first.data["data"]["updated"] is False
    assert second.data["data"]["updated"] is True
    rows = list(
        settings.MONGODB[OfficerAIFeedback.collection_name].find()
    )
    assert len(rows) == 1
    assert OfficerAIFeedback.from_dict(rows[0]).rating == "down"


def test_officer_feedback_rejects_phantom_request_ids():
    officer = _officer()
    application = _application(officer.id)

    response = OfficerFeedbackView.as_view()(
        _request(
            officer.id,
            _feedback_payload(application.id, str(uuid.uuid4())),
        )
    )

    assert response.status_code == 404
    assert response.data["code"] == "AI_FEEDBACK_REQUEST_UNKNOWN"
    assert settings.MONGODB[OfficerAIFeedback.collection_name].count_documents({}) == 0


def test_officer_feedback_requires_current_assignment():
    officer = _officer()
    application = _application(officer.id)
    request_id = str(uuid.uuid4())
    _complete_lease(application.customer_id, request_id)
    other = _officer()

    response = OfficerFeedbackView.as_view()(
        _request(
            other.id,
            _feedback_payload(application.id, request_id),
        )
    )

    assert response.status_code == 404
    assert settings.MONGODB[OfficerAIFeedback.collection_name].count_documents({}) == 0


def test_officer_feedback_rejects_non_officer_roles():
    officer = _officer()
    application = _application(officer.id)
    request_id = str(uuid.uuid4())
    _complete_lease(application.customer_id, request_id)

    response = OfficerFeedbackView.as_view()(
        _request(
            officer.id,
            _feedback_payload(application.id, request_id),
            role="customer",
        )
    )

    assert response.status_code == 403


def test_officer_feedback_validates_rating_and_ids():
    officer = _officer()
    application = _application(officer.id)

    bad_rating = OfficerFeedbackView.as_view()(
        _request(
            officer.id,
            _feedback_payload(application.id, str(uuid.uuid4()), rating="maybe"),
        )
    )
    assert bad_rating.status_code == 400

    bad_request_id = OfficerFeedbackView.as_view()(
        _request(
            officer.id,
            _feedback_payload(application.id, "not-a-uuid"),
        )
    )
    assert bad_request_id.status_code == 400

    long_comment = OfficerFeedbackView.as_view()(
        _request(
            officer.id,
            _feedback_payload(
                application.id, str(uuid.uuid4()), comment="x" * 501
            ),
        )
    )
    assert long_comment.status_code == 400


def test_officer_feedback_blocks_identifiers_in_comments():
    officer = _officer()
    application = _application(officer.id)
    request_id = str(uuid.uuid4())
    _complete_lease(application.customer_id, request_id)

    response = OfficerFeedbackView.as_view()(
        _request(
            officer.id,
            _feedback_payload(
                application.id,
                request_id,
                rating="down",
                comment="Call the borrower at +63 917 123 4567.",
            ),
        )
    )

    assert response.status_code == 400
    assert response.data["code"] == "AI_OFFICER_PRIVACY_BLOCKED"
    assert settings.MONGODB[OfficerAIFeedback.collection_name].count_documents({}) == 0


def test_officer_feedback_audit_stays_metadata_only():
    officer = _officer()
    application = _application(officer.id)
    request_id = str(uuid.uuid4())
    _complete_lease(application.customer_id, request_id)
    comment = "Sources were incomplete."

    OfficerFeedbackView.as_view()(
        _request(
            officer.id,
            _feedback_payload(
                application.id, request_id, rating="down", comment=comment
            ),
        )
    )

    feedback_events = [
        event for event in _audit_actions()
        if event.action == "ai_officer_feedback_recorded"
    ]
    assert len(feedback_events) == 1
    details = feedback_events[0].details
    assert details["rating"] == "down"
    assert details["request_id"] == request_id
    assert comment not in str(feedback_events[0].to_dict())


def test_officer_feedback_write_failure_returns_safe_error(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    request_id = str(uuid.uuid4())
    _complete_lease(application.customer_id, request_id)
    monkeypatch.setattr(
        OfficerAIFeedback,
        "record_feedback",
        Mock(side_effect=RuntimeError("db down")),
    )

    response = OfficerFeedbackView.as_view()(
        _request(officer.id, _feedback_payload(application.id, request_id))
    )

    assert response.status_code == 500
