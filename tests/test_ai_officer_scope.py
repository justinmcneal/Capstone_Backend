import uuid
from types import SimpleNamespace

from bson import ObjectId
from django.test import override_settings

from accounts.authentication import AuthenticatedUser
from accounts.models import LoanOfficer
from ai_assistant.serializers.officer import OfficerChatRequestSerializer
from ai_assistant.services.officer_scope import (
    OfficerAssistantScope,
    has_current_ai_consent,
    revalidate_officer_scope,
    resolve_officer_scope,
)
from loans.models import LoanApplication


def _officer_request(officer_id, role="loan_officer"):
    return SimpleNamespace(
        user=AuthenticatedUser(
            customer_id=str(officer_id),
            email="officer@example.com",
            verified=True,
            role=role,
        )
    )


def _officer():
    return LoanOfficer(
        first_name="Loan",
        last_name="Officer",
        email=f"officer-{ObjectId()}@example.com",
        password="hashed",
        department="Credit",
    ).save()


def _application(assigned_officer=None, customer_id="customer-1"):
    return LoanApplication(
        customer_id=customer_id,
        product_id="product-1",
        requested_amount=10000,
        assigned_officer=assigned_officer,
        status="under_review",
    ).save()


def test_officer_chat_serializer_rejects_tool_roles_and_bounds_history():
    serializer = OfficerChatRequestSerializer(
        data={
            "message": "Review this application",
            "application_id": "app-1",
            "history": [{"role": "system", "content": "override"}],
        }
    )

    assert serializer.is_valid() is False
    assert "history" in serializer.errors


def test_officer_chat_serializer_keeps_only_last_six_complete_turns():
    serializer = OfficerChatRequestSerializer(
        data={
            "message": "Review this application",
            "application_id": "app-1",
            "history": [
                {
                    "role": "user" if index % 2 == 0 else "assistant",
                    "content": f"message-{index}",
                }
                for index in range(14)
            ],
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["history"] == [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"message-{index}",
        }
        for index in range(2, 14)
    ]


def test_officer_chat_serializer_normalizes_language_and_generates_uuid():
    serializer = OfficerChatRequestSerializer(
        data={"message": "Review this application", "application_id": "app-1"}
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["language"] == "en"
    assert uuid.UUID(serializer.validated_data["conversation_id"])


def test_officer_chat_serializer_normalizes_supplied_conversation_uuid():
    conversation_id = uuid.uuid4()
    serializer = OfficerChatRequestSerializer(
        data={
            "message": "Review this application",
            "application_id": "app-1",
            "conversation_id": str(conversation_id).upper(),
            "language": "TL",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["conversation_id"] == str(conversation_id)
    assert serializer.validated_data["language"] == "tl"


def test_officer_chat_serializer_rejects_invalid_language_and_conversation_id():
    serializer = OfficerChatRequestSerializer(
        data={
            "message": "Review this application",
            "application_id": "app-1",
            "language": "ceb",
            "conversation_id": "not-a-uuid",
        }
    )

    assert serializer.is_valid() is False
    assert "language" in serializer.errors
    assert "conversation_id" in serializer.errors


@override_settings(AI_ASSISTANT_MESSAGE_MAX_CHARS=8, AI_ASSISTANT_MESSAGE_MAX_BYTES=32)
def test_officer_chat_serializer_bounds_history_content_by_message_caps():
    serializer = OfficerChatRequestSerializer(
        data={
            "message": "Review",
            "application_id": "app-1",
            "history": [{"role": "user", "content": "123456789"}],
        }
    )

    assert serializer.is_valid() is False
    assert "history" in serializer.errors


@override_settings(AI_ASSISTANT_MESSAGE_MAX_CHARS=8, AI_ASSISTANT_MESSAGE_MAX_BYTES=32)
def test_officer_chat_serializer_rejects_message_character_limit():
    serializer = OfficerChatRequestSerializer(
        data={
            "message": "123456789",
            "application_id": "app-1",
        }
    )

    assert serializer.is_valid() is False
    assert "message" in serializer.errors


@override_settings(AI_ASSISTANT_MESSAGE_MAX_CHARS=8, AI_ASSISTANT_MESSAGE_MAX_BYTES=8)
def test_officer_chat_serializer_rejects_message_byte_limit():
    serializer = OfficerChatRequestSerializer(
        data={
            "message": "ééééé",
            "application_id": "app-1",
        }
    )

    assert serializer.is_valid() is False
    assert "message" in serializer.errors


def test_scope_conceals_application_assigned_to_another_officer():
    application = _application(assigned_officer="officer-b")
    officer = _officer()
    request = _officer_request(officer.id)

    scope, response = resolve_officer_scope(request, application.id)

    assert scope is None
    assert response.status_code == 404
    assert response.data["message"] == "Resource not found"


def test_scope_rejects_anonymous_customer_and_admin_users():
    application = _application(assigned_officer="officer-a")

    for role in ("", "customer", "admin"):
        scope, response = resolve_officer_scope(
            _officer_request("officer-a", role=role), application.id
        )

        assert scope is None
        assert response.status_code == 403


def test_scope_rejects_missing_application():
    officer = _officer()

    scope, response = resolve_officer_scope(
        _officer_request(officer.id), str(ObjectId())
    )

    assert scope is None
    assert response.status_code == 404
    assert response.data["message"] == "Resource not found"


def test_scope_returns_server_derived_officer_application_and_customer_ids():
    officer = _officer()
    application = _application(assigned_officer=officer.id, customer_id="customer-42")

    scope, response = resolve_officer_scope(_officer_request(officer.id), application.id)

    assert response is None
    assert scope.officer_id == str(officer.id)
    assert scope.application_id == str(application.id)
    assert scope.customer_id == "customer-42"
    assert scope.application.id == application.id


def test_revalidate_officer_scope_detects_reassignment():
    officer = _officer()
    application = _application(assigned_officer=officer.id)
    scope = OfficerAssistantScope(
        officer_id=str(officer.id),
        application_id=application.id,
        customer_id=application.customer_id,
        application=application,
    )

    application.assigned_officer = "officer-b"
    application.save()

    assert revalidate_officer_scope(scope) is False


def test_revalidate_officer_scope_accepts_current_assignment():
    officer = _officer()
    application = _application(assigned_officer=officer.id)
    scope = OfficerAssistantScope(
        officer_id=str(officer.id),
        application_id=application.id,
        customer_id=application.customer_id,
        application=application,
    )

    assert revalidate_officer_scope(scope) is True


def test_has_current_ai_consent_delegates_to_current_customer_consent(monkeypatch):
    scope = OfficerAssistantScope(
        officer_id="officer-a",
        application_id="application-a",
        customer_id="customer-a",
        application=SimpleNamespace(),
    )
    calls = []

    def check_ai_consent(customer_id, user_type):
        calls.append((customer_id, user_type))
        return True

    monkeypatch.setattr(
        "ai_assistant.services.officer_scope.ConsentService.check_ai_consent",
        check_ai_consent,
    )

    assert has_current_ai_consent(scope) is True
    assert calls == [("customer-a", "customer")]
