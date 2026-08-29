import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from bson import ObjectId
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import LoanOfficer
from analytics.models import AuditLog
from ai_assistant.models import AIInteraction
from ai_assistant.services.officer_tools import OFFICER_TOOL_SCHEMAS
from ai_assistant.services.officer_prompt import (
    build_officer_system_prompt,
    officer_suggestions,
)
from ai_assistant.views.officer import (
    OfficerAIStatusView,
    OfficerChatView,
    OfficerStreamingChatView,
    OfficerSuggestionsView,
)
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


def _request(
    method,
    path,
    user_id,
    *,
    role="loan_officer",
    data=None,
    query=None,
    headers=None,
):
    factory = APIRequestFactory()
    request = getattr(factory, method.lower())(
        path,
        query if method.upper() == "GET" else (data or {}),
        format="json",
        **(headers or {}),
    )
    force_authenticate(
        request,
        user=AuthenticatedUser(
            customer_id=str(user_id),
            email="actor@example.com",
            verified=True,
            role=role,
        ),
    )
    return request


def _chat_request(officer_id, application_id, **overrides):
    payload = {
        "message": "Summarize review readiness",
        "application_id": str(application_id),
        "language": "en",
    }
    payload.update(overrides)
    return _request(
        "POST",
        "/api/ai/officer/chat/",
        officer_id,
        data=payload,
    )


def _audit_events():
    return [
        AuditLog.from_dict(row)
        for row in settings.MONGODB[AuditLog.collection_name].find().sort("timestamp", 1)
    ]


class JsonLLM:
    provider = "groq"
    model = "officer-model"

    def __init__(self, result=None, *, available=True, before_chat=None):
        self.available = available
        self.result = result or {
            "success": True,
            "response": "<Review summary>",
            "model": self.model,
            "provider": self.provider,
            "response_time_ms": 17,
            "tokens_used": 8,
            "tools_called": ["get_application_summary", "unknown_tool"],
        }
        self.before_chat = before_chat
        self.kwargs = None

    def is_available(self):
        return self.available

    def readiness(self):
        return {
            "available": self.available,
            "configured": True,
            "reachable": self.available,
            "authenticated": self.available,
            "model_available": self.available,
            "state": "available" if self.available else "unavailable",
            "circuit": "closed",
        }

    def chat_with_tools(self, **kwargs):
        self.kwargs = kwargs
        if self.before_chat:
            self.before_chat()
        return self.result


class CloseAwareStream:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.chunks)

    def close(self):
        self.closed = True


class CloseRaisingStream(CloseAwareStream):
    def close(self):
        self.closed = True
        raise RuntimeError("provider cleanup secret")


class EndlessCloseAwareStream:
    def __init__(self):
        self.closed = False
        self.sent = False

    def __iter__(self):
        return self

    def __next__(self):
        if not self.sent:
            self.sent = True
            return {"type": "tool_call", "name": "get_application_summary"}
        return {"type": "token", "content": "later"}

    def close(self):
        self.closed = True


class StreamLLM(JsonLLM):
    def __init__(self, chunks, *, before_stream=None):
        super().__init__()
        self.stream = chunks
        self.before_stream = before_stream

    def chat_with_tools_stream(self, **kwargs):
        self.kwargs = kwargs
        if self.before_stream:
            self.before_stream()
        return self.stream


class ExplodingJsonLLM(JsonLLM):
    def chat_with_tools(self, **kwargs):
        self.kwargs = kwargs
        raise RuntimeError("provider secret failure")


class ExplodingStream:
    def __init__(self):
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        raise RuntimeError("provider stream secret failure")

    def close(self):
        self.closed = True


def _stream_frames(response):
    raw = b"".join(response.streaming_content).decode("utf-8")
    frames = []
    for block in raw.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line[7:] for line in lines if line.startswith("event: "))
        payload = next(line[6:] for line in lines if line.startswith("data: "))
        frames.append((event, json.loads(payload)))
    return frames


def test_officer_routes_are_registered():
    assert reverse("ai_assistant:officer-status") == "/api/ai/officer/status/"
    assert reverse("ai_assistant:officer-suggestions") == "/api/ai/officer/suggestions/"
    assert reverse("ai_assistant:officer-chat") == "/api/ai/officer/chat/"
    assert reverse("ai_assistant:officer-chat-stream") == "/api/ai/officer/chat/stream/"


def test_officer_prompt_exposes_only_four_read_only_capabilities():
    prompt = build_officer_system_prompt()

    assert prompt.count("get_application_summary") == 1
    assert prompt.count("get_profile_readiness") == 1
    assert prompt.count("get_document_review_status") == 1
    assert prompt.count("get_repayment_summary") == 1
    assert "read-only" in prompt.lower()
    assert "must not make approval or rejection decisions" in prompt.lower()
    assert "must not mutate" in prompt.lower()
    for forbidden in ("customer_id", "officer_id", "email", "phone", "address"):
        assert forbidden not in prompt.lower()


def test_officer_suggestions_are_static_and_language_specific():
    english = officer_suggestions("en")
    tagalog = officer_suggestions("tl")

    assert len(english) == 4
    assert len(tagalog) == 4
    assert english != tagalog
    assert all(isinstance(value, str) and value for value in english + tagalog)


def test_officer_chat_rejects_admin_before_provider(monkeypatch):
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)
    request = _request(
        "POST",
        "/api/ai/officer/chat/",
        "admin-1",
        role="admin",
        data={"message": "Review", "application_id": str(ObjectId())},
    )

    response = OfficerChatView.as_view()(request)

    assert response.status_code == 403
    provider.assert_not_called()


def test_officer_endpoints_enforce_role_before_body_or_query_validation(monkeypatch):
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)

    chat = OfficerChatView.as_view()(
        _request("POST", "/api/ai/officer/chat/", "admin-1", role="admin", data={})
    )
    stream = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            "customer-1",
            role="customer",
            data={},
        )
    )
    suggestions = OfficerSuggestionsView.as_view()(
        _request(
            "GET",
            "/api/ai/officer/suggestions/",
            "admin-1",
            role="admin",
            query={},
        )
    )

    assert chat.status_code == 403
    assert stream.status_code == 403
    assert suggestions.status_code == 403
    provider.assert_not_called()


@pytest.mark.parametrize(
    "restricted_content",
    [
        "Customer name: Ana Santos",
        "Review Ana Santos's repayment status",
        "Review Ana Santos",
        "review ana santos's repayment status",
        "Customer email: customer@example.com",
        "Customer mobile: +639171234567",
        "Call +1 202 555 0147",
        "Customer address: 123 Rizal Street",
        "Review the application at 123 Rizal, Quezon City",
        "The applicant was born 1990-01-01",
        "Government ID: PH-1234-5678",
        "Document filename: identity-card.png",
        "Document content: birth certificate scan",
        "Document storage path: private/customer/id.png",
        "Wallet address: 0x1234567890abcdef",
        "Transaction hash: 0xabcdef1234567890",
        "Payment reference: PAY-12345",
        "Internal note: confidential review",
        "Staff password: hunter2",
        "Łukasz Żółć",
        "李 小龙",
        "محمد علي",
        "1990年1月1日",
        "ana.santos",
        "Ana‑Santos",
        "a@b。com",
        "1990⁄01⁄01",
        "123 Rizal،",
        "pay‐12345",
    ],
)
@pytest.mark.parametrize("view_class", [OfficerChatView, OfficerStreamingChatView])
def test_officer_context_privacy_rejects_restricted_current_message(
    monkeypatch, restricted_content, view_class
):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)

    response = view_class.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/",
            officer.id,
            data={
                "message": restricted_content,
                "application_id": str(application.id),
            },
        )
    )

    assert response.status_code == 400
    serialized = json.dumps(response.data).lower()
    assert restricted_content.lower() not in serialized
    assert "customer" not in serialized
    assert "provider" not in serialized
    provider.assert_not_called()


@pytest.mark.parametrize(
    "restricted_content",
    [
        "Review Ana Santos's repayment status",
        "Ana Santos",
        "review ana santos",
        "The applicant was born 1990-01-01",
        "born March 3, 1990",
        "Call +1 202 555 0147",
        "Call 001 202 555 0147",
        "Review the application at 123 Rizal, Quezon City",
        "123 rizal quezon city",
        "Customer email customer@example.com",
        "ana.santos",
        "Ana‑Santos",
        "a@b。com",
        "1990⁄01⁄01",
        "123 Rizal،",
        "pay‐12345",
    ],
)
@pytest.mark.parametrize("view_class", [OfficerChatView, OfficerStreamingChatView])
def test_officer_context_privacy_rejects_restricted_history_before_provider(
    monkeypatch, restricted_content, view_class
):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)

    response = view_class.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/",
            officer.id,
            data={
                "message": "Review missing documents and repayment status",
                "application_id": str(application.id),
                "history": [
                    {
                        "role": "user",
                        "content": restricted_content,
                    }
                ],
            },
        )
    )

    assert response.status_code == 400
    serialized = json.dumps(response.data).lower()
    assert "customer@example.com" not in serialized
    assert "customer" not in serialized
    provider.assert_not_called()


def test_officer_context_privacy_preserves_safe_review_prompts(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    llm = JsonLLM()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/",
            officer.id,
            data={
                "message": "Review missing documents and repayment status",
                "application_id": str(application.id),
            },
        )
    )

    assert response.status_code == 200
    assert llm.kwargs["message"] == "Review missing documents and repayment status"


@pytest.mark.parametrize(
    "message",
    [
        "Review missing documents.",
        "Summarize what is still needed before review.",
    ],
)
def test_officer_context_privacy_preserves_documented_safe_prompts(
    monkeypatch, message
):
    officer = _officer()
    application = _application(officer.id)
    llm = JsonLLM()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/",
            officer.id,
            data={"message": message, "application_id": str(application.id)},
        )
    )

    assert response.status_code == 200
    assert llm.kwargs["message"] == message


@pytest.mark.parametrize("view_class", [OfficerChatView, OfficerStreamingChatView])
def test_officer_ai_metrics_are_low_cardinality_for_json_and_stream(
    monkeypatch, view_class
):
    officer = _officer()
    application = _application(officer.id)
    if view_class is OfficerChatView:
        llm = JsonLLM()
    else:
        llm = StreamLLM(
            CloseAwareStream(
                [
                    {"type": "token", "content": "summary"},
                    {"type": "done", "model": "officer-model", "tokens_used": 1},
                ]
            )
        )
    officer_metric_calls = Mock()
    mixin_metric_calls = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )
    monkeypatch.setattr(
        "ai_assistant.views.officer.increment", officer_metric_calls, raising=False
    )
    monkeypatch.setattr("ai_assistant.views.chat_views.increment", mixin_metric_calls)

    response = view_class.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/",
            officer.id,
            data={"message": "Review summary", "application_id": str(application.id)},
        )
    )
    if view_class is OfficerStreamingChatView:
        _stream_frames(response)

    assert response.status_code == 200
    provider_calls = [
        call.kwargs
        for call in officer_metric_calls.call_args_list
        if call.kwargs.get("provider") == "groq"
    ]
    assert any(call.get("outcome") == "success" for call in provider_calls)
    assert any("amount" in call.kwargs for call in officer_metric_calls.call_args_list)
    assert any(call.kwargs.get("endpoint") for call in mixin_metric_calls.call_args_list)
    assert all(
        not {"message", "conversation_history", "customer_id"}.intersection(call.kwargs)
        for call in officer_metric_calls.call_args_list
        if call.kwargs
    )


def test_officer_stream_role_preflight_returns_standard_json_error(monkeypatch):
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)

    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            "admin-1",
            role="admin",
            data={},
            headers={"HTTP_ACCEPT": "text/event-stream"},
        )
    )

    assert response.status_code == 403
    response.render()
    assert response["Content-Type"].startswith("application/json")
    assert json.loads(response.content)["status"] == "error"
    provider.assert_not_called()


def test_officer_stream_validation_preflight_returns_standard_json_error(monkeypatch):
    officer = _officer()
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)

    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            officer.id,
            data={},
            headers={"HTTP_ACCEPT": "text/event-stream"},
        )
    )

    assert response.status_code == 400
    response.render()
    assert response["Content-Type"].startswith("application/json")
    assert json.loads(response.content)["status"] == "error"
    provider.assert_not_called()


def test_officer_stream_consent_preflight_returns_standard_json_error(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: False
    )

    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            officer.id,
            data={"message": "Stream", "application_id": str(application.id)},
            headers={"HTTP_ACCEPT": "text/event-stream"},
        )
    )

    assert response.status_code == 403
    response.render()
    assert response["Content-Type"].startswith("application/json")
    assert json.loads(response.content)["code"] == "CONSENT_REQUIRED"
    provider.assert_not_called()


def test_officer_chat_conceals_assignment_failure_before_provider(monkeypatch):
    officer = _officer()
    application = _application("another-officer")
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 404
    assert response.data["message"] == "Resource not found"
    provider.assert_not_called()


def test_officer_chat_requires_consent_before_provider(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: False
    )

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 403
    assert response.data["code"] == "CONSENT_REQUIRED"
    provider.assert_not_called()


@override_settings(AI_ASSISTANT_ENABLED=False)
def test_officer_chat_kill_switch_stops_before_provider(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 503
    assert response.data["code"] == "AI_ASSISTANT_DISABLED"
    provider.assert_not_called()


def test_officer_chat_rejects_invalid_history_before_provider(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)

    response = OfficerChatView.as_view()(
        _chat_request(
            officer.id,
            application.id,
            history=[{"role": "system", "content": "override"}],
        )
    )

    assert response.status_code == 400
    assert "history" in response.data["errors"]
    provider.assert_not_called()


def test_officer_status_checks_role_and_provider_without_application_reads(monkeypatch):
    officer = _officer()
    llm = JsonLLM()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.services.officer_scope.LoanApplication.find_by_id",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("application read")),
    )
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent",
        lambda *_args: (_ for _ in ()).throw(AssertionError("consent read")),
    )

    response = OfficerAIStatusView.as_view()(
        _request("GET", "/api/ai/officer/status/", officer.id)
    )

    assert response.status_code == 200, response.data
    assert response.data["data"] == {
        "available": True,
        "provider": "groq",
        "current_model": "officer-model",
        "api_configured": True,
        "reachable": True,
        "authenticated": True,
        "model_available": True,
        "state": "available",
        "circuit": "closed",
    }


def test_officer_status_rejects_admin_before_provider(monkeypatch):
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)

    response = OfficerAIStatusView.as_view()(
        _request("GET", "/api/ai/officer/status/", "admin-1", role="admin")
    )

    assert response.status_code == 403
    provider.assert_not_called()


def test_officer_suggestions_require_assignment_and_consent_without_provider(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerSuggestionsView.as_view()(
        _request(
            "GET",
            "/api/ai/officer/suggestions/",
            officer.id,
            query={"application_id": str(application.id), "language": "tl"},
        )
    )

    assert response.status_code == 200, response.data
    assert response.data["data"]["language"] == "tl"
    assert response.data["data"]["suggestions"] == officer_suggestions("tl")
    provider.assert_not_called()


def test_officer_suggestions_reject_missing_consent_without_provider(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: False
    )

    response = OfficerSuggestionsView.as_view()(
        _request(
            "GET",
            "/api/ai/officer/suggestions/",
            officer.id,
            query={"application_id": str(application.id)},
        )
    )

    assert response.status_code == 403
    assert response.data["code"] == "CONSENT_REQUIRED"
    provider.assert_not_called()


def test_officer_chat_audits_before_provider_and_returns_minimized_json(monkeypatch):
    officer = _officer()
    application = _application(officer.id, customer_id="server-customer")
    request_id = str(uuid.uuid4())

    def assert_access_audited():
        assert settings.MONGODB[AuditLog.collection_name].count_documents(
            {"action": "ai_officer_assistant_access"}
        ) == 1

    llm = JsonLLM(before_chat=assert_access_audited)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/",
            officer.id,
            data={
                "message": "Summarize",
                "application_id": str(application.id),
                "customer_id": "attacker-selected-customer",
                "history": [{"role": "user", "content": "Earlier question"}],
            },
            headers={"HTTP_IDEMPOTENCY_KEY": request_id},
        )
    )

    assert response.status_code == 200, response.data
    assert set(response.data["data"]) == {
        "response",
        "conversation_id",
        "model",
        "response_time_ms",
        "request_id",
        "tools_called",
    }
    assert response.data["data"]["response"] == "&lt;Review summary&gt;"
    assert response.data["data"]["request_id"] == request_id
    assert response.data["data"]["tools_called"] == ["get_application_summary"]
    assert llm.kwargs["customer_id"] == "server-customer"
    assert llm.kwargs["conversation_history"] == [
        {"role": "user", "content": "Earlier question"}
    ]
    assert llm.kwargs["tools"] == OFFICER_TOOL_SCHEMAS
    assert callable(llm.kwargs["tool_executor"])
    assert "server-customer" not in llm.kwargs["system_prompt"]
    assert AIInteraction.find_by_conversation(
        response.data["data"]["conversation_id"], "server-customer"
    ) == []

    events = _audit_events()
    assert [event.action for event in events] == [
        "ai_officer_assistant_access",
        "ai_officer_assistant_result",
    ]
    allowed = {
        "application_id",
        "request_id",
        "language",
        "outcome",
        "tool_names",
        "tool_count",
        "duration_ms",
    }
    for event in events:
        assert set(event.details) <= allowed
        serialized = json.dumps(event.details).lower()
        for forbidden in (
            "summarize",
            "review summary",
            "server-customer",
            str(officer.id).lower(),
            "actor@example.com",
            "attacker-selected-customer",
        ):
            assert forbidden not in serialized


def test_officer_chat_rejects_malformed_provider_tool_metadata(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    llm = JsonLLM(
        result={
            "success": True,
            "response": "summary",
            "tools_called": 42,
        }
    )
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 500
    assert response.data["code"] == "AI_PROVIDER_ERROR"
    assert _audit_events()[-1].details["outcome"] == "AI_PROVIDER_ERROR"


def test_officer_ai_audit_documents_pseudonymize_officer_and_customer_identifiers(
    monkeypatch,
):
    officer = _officer()
    application = _application(officer.id, customer_id="customer-direct-identifier")
    llm = JsonLLM()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 200, response.data
    events = _audit_events()
    assert len(events) == 2
    for event in events:
        assert event.user_id != str(officer.id)
        assert event.scope_officer_index == AuditLog.blind_index(str(officer.id))
        assert str(officer.id) not in json.dumps(event.to_dict(), default=str)
        assert "customer-direct-identifier" not in json.dumps(
            event.to_dict(), default=str
        )

    stored = list(settings.MONGODB[AuditLog.collection_name].find())
    assert stored
    assert all(row.get("user_id") != str(officer.id) for row in stored)
    assert all(row.get("scope_officer_id") != str(officer.id) for row in stored)


def test_failed_officer_audits_recover_with_distinct_stable_event_ids(monkeypatch):
    from ai_assistant.services.officer_audit import (
        record_officer_ai_access,
        record_officer_ai_result,
    )
    from ai_assistant.services.officer_scope import OfficerAssistantScope
    from analytics.services.audit_writer import reconcile_audit_failures

    officer = _officer()
    application = _application(officer.id)
    scope = OfficerAssistantScope(
        officer_id=str(officer.id),
        customer_id=application.customer_id,
        application_id=str(application.id),
        application=application,
    )
    monkeypatch.setattr(
        "ai_assistant.services.officer_audit.AuditLog.log_action",
        Mock(side_effect=RuntimeError("audit backend unavailable")),
    )

    record_officer_ai_access(scope, "request-1", "en")
    record_officer_ai_access(scope, "request-1", "en")
    record_officer_ai_result(scope, "request-1", "en", outcome="AI_PROVIDER_ERROR")

    rows = list(
        settings.MONGODB["audit_write_failures"].find({"domain": "ai_assistant"})
    )
    event_ids = {row["event_id"] for row in rows}
    assert len(rows) == 2
    assert event_ids == {
        f"evt_{AuditLog.blind_index('officer-ai:request-1:ai_officer_assistant_access')}",
        f"evt_{AuditLog.blind_index('officer-ai:request-1:ai_officer_assistant_result')}",
    }

    monkeypatch.undo()
    replay = reconcile_audit_failures(domains={"ai_assistant"})

    assert replay == {"resolved": 2, "failed": 0}
    assert settings.MONGODB["audit_write_failures"].count_documents(
        {"domain": "ai_assistant", "resolved_at": None}
    ) == 0
    assert settings.MONGODB[AuditLog.collection_name].count_documents(
        {
            "action": {
                "$in": [
                    "ai_officer_assistant_access",
                    "ai_officer_assistant_result",
                ]
            }
        }
    ) == 2


def test_officer_chat_provider_failure_records_metadata_result(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    llm = JsonLLM(
        result={
            "success": False,
            "error": "raw provider exception text",
            "code": "AI_PROVIDER_TIMEOUT",
        }
    )
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 503
    assert response.data["code"] == "AI_PROVIDER_TIMEOUT"
    result_event = _audit_events()[-1]
    assert result_event.action == "ai_officer_assistant_result"
    assert result_event.details["outcome"] == "AI_PROVIDER_TIMEOUT"
    assert "raw provider exception text" not in json.dumps(result_event.details)


def test_officer_chat_unknown_provider_error_code_maps_to_safe_code(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    llm = JsonLLM(
        result={
            "success": False,
            "error": "provider internal secret",
            "code": "PROVIDER_INTERNAL_SECRET_CODE",
        }
    )
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 503
    assert response.data["code"] == "AI_PROVIDER_ERROR"
    assert "PROVIDER_INTERNAL_SECRET_CODE" not in json.dumps(response.data)
    result_event = _audit_events()[-1]
    assert result_event.details["outcome"] == "AI_PROVIDER_ERROR"
    assert "PROVIDER_INTERNAL_SECRET_CODE" not in json.dumps(result_event.details)


def test_officer_chat_uses_trusted_model_and_normalizes_provider_tokens(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    llm = JsonLLM(
        result={
            "success": True,
            "response": "safe response",
            "model": "attacker-model\ncustomer@example.com",
            "provider": "groq",
            "response_time_ms": 17,
            "tokens_used": "not-a-token-count",
            "tools_called": [],
        }
    )
    metric_calls = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )
    monkeypatch.setattr("ai_assistant.views.officer.increment", metric_calls)

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 200
    assert response.data["data"]["model"] == "officer-model"
    token_calls = [
        call.kwargs for call in metric_calls.call_args_list if "amount" in call.kwargs
    ]
    assert token_calls[-1]["amount"] == 0
    assert "attacker-model" not in json.dumps(response.data)


def test_officer_chat_provider_exception_returns_safe_error_and_audits(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    llm = ExplodingJsonLLM()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 500
    assert response.data["code"] == "AI_PROVIDER_ERROR"
    assert "secret" not in json.dumps(response.data).lower()
    result_event = _audit_events()[-1]
    assert result_event.action == "ai_officer_assistant_result"
    assert result_event.details["outcome"] == "AI_PROVIDER_ERROR"
    assert "secret" not in json.dumps(result_event.details).lower()


def test_officer_chat_fails_closed_when_access_audit_is_not_durable(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )
    monkeypatch.setattr(
        "ai_assistant.services.officer_audit.AuditLog.log_action",
        Mock(side_effect=RuntimeError("audit unavailable")),
    )
    monkeypatch.setattr(
        "ai_assistant.services.officer_audit.queue_audit_failure",
        Mock(side_effect=RuntimeError("queue unavailable")),
    )

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 503
    assert response.data["code"] == "AI_AUDIT_UNAVAILABLE"
    provider.assert_not_called()


def test_officer_chat_fails_closed_on_non_retryable_access_audit_schema_error(
    monkeypatch,
):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    queue = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )
    monkeypatch.setattr(
        "ai_assistant.services.officer_audit.AuditLog.log_action",
        Mock(side_effect=ValueError("invalid audit schema")),
    )
    monkeypatch.setattr(
        "ai_assistant.services.officer_audit.queue_audit_failure", queue
    )

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 503
    assert response.data["code"] == "AI_AUDIT_UNAVAILABLE"
    provider.assert_not_called()
    queue.assert_not_called()


def test_officer_chat_may_continue_when_failed_access_audit_is_durably_queued(
    monkeypatch,
):
    officer = _officer()
    application = _application(officer.id)
    llm = JsonLLM()
    queued = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )
    monkeypatch.setattr(
        "ai_assistant.services.officer_audit.AuditLog.log_action",
        Mock(side_effect=RuntimeError("primary unavailable")),
    )
    monkeypatch.setattr(
        "ai_assistant.services.officer_audit.queue_audit_failure", queued
    )

    response = OfficerChatView.as_view()(
        _chat_request(officer.id, application.id)
    )

    assert response.status_code == 200, response.data
    assert queued.call_count == 2
    assert [call.kwargs["payload"]["action"] for call in queued.call_args_list] == [
        "ai_officer_assistant_access",
        "ai_officer_assistant_result",
    ]
    assert llm.kwargs is not None


def test_officer_stream_emits_safe_named_events_and_one_done_terminal(monkeypatch):
    officer = _officer()
    application = _application(officer.id, customer_id="server-customer")
    request_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    provider_stream = CloseAwareStream(
        [
            {"type": "tool_call", "name": "get_application_summary"},
            {"type": "tool_result", "name": "get_application_summary", "success": True},
            {"type": "tool_call", "name": "unknown_tool"},
            {"type": "token", "content": "A & <summary>"},
            {
                "type": "done",
                "model": "officer-model",
                "provider": "groq",
                "tokens_used": 4,
                "tools_called": ["get_application_summary", "unknown_tool"],
            },
            {"type": "error", "content": "must not appear"},
        ]
    )

    def assert_access_audited():
        assert settings.MONGODB[AuditLog.collection_name].count_documents(
            {"action": "ai_officer_assistant_access"}
        ) == 1

    llm = StreamLLM(provider_stream, before_stream=assert_access_audited)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            officer.id,
            data={
                "message": "Stream summary",
                "application_id": str(application.id),
                "conversation_id": conversation_id,
            },
            headers={"HTTP_IDEMPOTENCY_KEY": request_id},
        )
    )
    frames = _stream_frames(response)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    assert response["Cache-Control"] == "no-cache"
    assert response["X-Accel-Buffering"] == "no"
    assert [event for event, _payload in frames] == [
        "tool_call",
        "tool_result",
        "done",
    ]
    assert frames[-1][1] == {
        "model": "officer-model",
        "tokens_used": 4,
        "response_time_ms": frames[-1][1]["response_time_ms"],
        "conversation_id": conversation_id,
        "response": "A &",
        "tools_called": ["get_application_summary"],
        "request_id": request_id,
    }
    assert sum(event in {"done", "error"} for event, _payload in frames) == 1
    assert provider_stream.closed is True
    assert llm.kwargs["customer_id"] == "server-customer"
    assert llm.kwargs["tools"] == OFFICER_TOOL_SCHEMAS
    assert callable(llm.kwargs["tool_executor"])
    assert settings.MONGODB["ai_interactions"].count_documents({}) == 0
    result_event = _audit_events()[-1]
    assert result_event.action == "ai_officer_assistant_result"
    assert result_event.details["outcome"] == "success"
    assert result_event.details["tool_names"] == ["get_application_summary"]


def test_officer_stream_revalidates_before_done_terminal(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = CloseAwareStream(
        [
            {"type": "token", "content": "partial"},
            {"type": "done", "model": "officer-model", "tokens_used": 1},
        ]
    )
    llm = StreamLLM(provider_stream)
    authorization_checks = 0

    def authorization_error(scope):
        nonlocal authorization_checks
        authorization_checks += 1
        return (
            "AI_OFFICER_SCOPE_CHANGED" if authorization_checks >= 3 else None
        )

    monkeypatch.setattr(
        "ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm
    )
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )
    monkeypatch.setattr(
        "ai_assistant.views.officer._authorization_error", authorization_error
    )

    frames = _stream_frames(
        OfficerStreamingChatView.as_view()(
            _request(
                "POST",
                "/api/ai/officer/chat/stream/",
                officer.id,
                data={"message": "Stream", "application_id": str(application.id)},
            )
        )
    )

    assert [event for event, _payload in frames] == ["error"]
    assert frames[-1][1]["code"] == "AI_OFFICER_SCOPE_CHANGED"
    assert provider_stream.closed is True
    assert _audit_events()[-1].details["outcome"] == "AI_OFFICER_SCOPE_CHANGED"


def test_officer_stream_accepts_event_stream_negotiation_for_successful_sse(
    monkeypatch,
):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = CloseAwareStream(
        [
            {"type": "token", "content": "The applicant is Alice Santos."},
            {"type": "done", "model": "officer-model", "tokens_used": 1},
        ]
    )
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            officer.id,
            data={"message": "Stream", "application_id": str(application.id)},
            headers={"HTTP_ACCEPT": "text/event-stream"},
        )
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    frames = _stream_frames(response)
    assert [event for event, _payload in frames] == ["done"]
    assert "Alice" not in json.dumps(frames)
    assert "Santos" not in json.dumps(frames)
    assert provider_stream.closed is True


def test_officer_stream_bounds_provider_model_and_tokens(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = CloseAwareStream(
        [
            {"type": "token", "content": "summary"},
            {
                "type": "done",
                "model": "attacker-model\nsecret",
                "tokens_used": "not-a-token-count",
            },
        ]
    )
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            officer.id,
            data={"message": "Stream", "application_id": str(application.id)},
        )
    )
    frames = _stream_frames(response)

    assert frames[-1][0] == "done"
    assert frames[-1][1]["model"] == "officer-model"
    assert frames[-1][1]["tokens_used"] == 0
    assert "attacker-model" not in json.dumps(frames)


@override_settings(
    AI_ASSISTANT_STREAM_MAX_CHARS=5,
    AI_ASSISTANT_STREAM_MAX_BYTES=100,
)
def test_officer_stream_enforces_output_budget_and_audits_cancellation(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = CloseAwareStream(
        [
            {"type": "token", "content": "12345"},
            {"type": "token", "content": "6"},
            {"type": "done", "model": "officer-model", "tokens_used": 1},
        ]
    )
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    frames = _stream_frames(
        OfficerStreamingChatView.as_view()(
            _request(
                "POST",
                "/api/ai/officer/chat/stream/",
                officer.id,
                data={"message": "Stream", "application_id": str(application.id)},
            )
        )
    )

    assert [event for event, _payload in frames] == ["error"]
    assert frames[0][1]["code"] == "AI_PROVIDER_STREAM_OUTPUT_LIMIT"
    assert provider_stream.closed is True
    assert _audit_events()[-1].details["outcome"] == "AI_PROVIDER_STREAM_OUTPUT_LIMIT"


@override_settings(AI_ASSISTANT_STREAM_MAX_DURATION_SECONDS=0.1)
def test_officer_stream_enforces_duration_budget_and_audits_cancellation(monkeypatch):
    officer = _officer()
    application = _application(officer.id)

    def delayed_chunks():
        time.sleep(0.2)
        yield {"type": "token", "content": "late"}

    provider_stream = CloseAwareStream(
        delayed_chunks()
    )
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    frames = _stream_frames(
        OfficerStreamingChatView.as_view()(
            _request(
                "POST",
                "/api/ai/officer/chat/stream/",
                officer.id,
                data={"message": "Stream", "application_id": str(application.id)},
            )
        )
    )

    assert [event for event, _payload in frames] == ["error"]
    assert frames[0][1]["code"] == "AI_PROVIDER_STREAM_DURATION_LIMIT"
    assert provider_stream.closed is True
    assert _audit_events()[-1].details["outcome"] == "AI_PROVIDER_STREAM_DURATION_LIMIT"


def test_officer_stream_without_terminal_emits_incomplete_error_and_audits(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = CloseAwareStream([{"type": "token", "content": "partial"}])
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            officer.id,
            data={"message": "Stream", "application_id": str(application.id)},
        )
    )
    frames = _stream_frames(response)

    assert [event for event, _payload in frames] == ["error"]
    assert frames[-1][1]["code"] == "AI_STREAM_INCOMPLETE"
    assert provider_stream.closed is True
    result_event = _audit_events()[-1]
    assert result_event.details["outcome"] == "AI_STREAM_INCOMPLETE"


def test_officer_stream_provider_error_is_terminal_safe_and_audited(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = CloseAwareStream(
        [
            {
                "type": "error",
                "content": "Provider <busy> & retry",
                "code": "AI_PROVIDER_BUSY",
            },
            {"type": "done", "model": "must-not-appear"},
        ]
    )
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    frames = _stream_frames(
        OfficerStreamingChatView.as_view()(
            _request(
                "POST",
                "/api/ai/officer/chat/stream/",
                officer.id,
                data={"message": "Stream", "application_id": str(application.id)},
            )
        )
    )

    assert frames == [
        (
            "error",
            {
                "content": "AI service is temporarily unavailable",
                "code": "AI_PROVIDER_BUSY",
                "request_id": frames[0][1]["request_id"],
            },
        )
    ]
    assert "Provider" not in json.dumps(frames)
    assert _audit_events()[-1].details["outcome"] == "AI_PROVIDER_BUSY"


def test_officer_stream_unknown_provider_error_code_maps_to_safe_code(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = CloseAwareStream(
        [
            {
                "type": "error",
                "content": "provider internal secret",
                "code": "PROVIDER_INTERNAL_SECRET_CODE",
            }
        ]
    )
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    frames = _stream_frames(
        OfficerStreamingChatView.as_view()(
            _request(
                "POST",
                "/api/ai/officer/chat/stream/",
                officer.id,
                data={"message": "Stream", "application_id": str(application.id)},
            )
        )
    )

    assert len(frames) == 1
    assert frames[0][0] == "error"
    assert frames[0][1]["code"] == "AI_PROVIDER_ERROR"
    assert "PROVIDER_INTERNAL_SECRET_CODE" not in json.dumps(frames)
    assert _audit_events()[-1].details["outcome"] == "AI_PROVIDER_ERROR"


def test_officer_stream_provider_setup_exception_is_safe_and_audited(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    monkeypatch.setattr(
        "ai_assistant.views.officer.get_llm_service",
        Mock(side_effect=RuntimeError("provider setup secret")),
    )
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            officer.id,
            data={"message": "Stream", "application_id": str(application.id)},
        )
    )

    assert response.status_code == 500
    assert response.data["code"] == "AI_PROVIDER_ERROR"
    assert "secret" not in json.dumps(response.data).lower()
    result_event = _audit_events()[-1]
    assert result_event.action == "ai_officer_assistant_result"
    assert result_event.details["outcome"] == "AI_PROVIDER_ERROR"


def test_officer_stream_iterator_exception_is_safe_terminal_and_closes(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = ExplodingStream()
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    frames = _stream_frames(
        OfficerStreamingChatView.as_view()(
            _request(
                "POST",
                "/api/ai/officer/chat/stream/",
                officer.id,
                data={"message": "Stream", "application_id": str(application.id)},
            )
        )
    )

    assert len(frames) == 1
    assert frames[0][0] == "error"
    assert frames[0][1]["code"] == "AI_STREAM_ERROR"
    assert "secret" not in json.dumps(frames[0][1]).lower()
    assert provider_stream.closed is True
    assert _audit_events()[-1].details["outcome"] == "AI_STREAM_ERROR"


def test_officer_stream_empty_done_becomes_error(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    llm = StreamLLM(
        CloseAwareStream(
            [{"type": "done", "model": "officer-model", "tokens_used": 0}]
        )
    )
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    frames = _stream_frames(
        OfficerStreamingChatView.as_view()(
            _request(
                "POST",
                "/api/ai/officer/chat/stream/",
                officer.id,
                data={"message": "Stream", "application_id": str(application.id)},
            )
        )
    )

    assert [event for event, _payload in frames] == ["error"]
    assert frames[0][1]["code"] == "AI_EMPTY_RESPONSE"
    assert _audit_events()[-1].details["outcome"] == "AI_EMPTY_RESPONSE"


def test_officer_stream_malformed_done_metadata_emits_one_safe_terminal_error(
    monkeypatch,
):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = CloseAwareStream(
        [
            {"type": "token", "content": "partial"},
            {"type": "done", "model": object(), "tokens_used": 1},
        ]
    )
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    frames = _stream_frames(
        OfficerStreamingChatView.as_view()(
            _request(
                "POST",
                "/api/ai/officer/chat/stream/",
                officer.id,
                data={"message": "Stream", "application_id": str(application.id)},
            )
        )
    )

    assert [event for event, _payload in frames] == ["error"]
    assert frames[-1][1]["code"] == "AI_STREAM_ERROR"
    assert sum(event in {"done", "error"} for event, _payload in frames) == 1
    assert provider_stream.closed is True
    assert _audit_events()[-1].details["outcome"] == "AI_STREAM_ERROR"


def test_officer_stream_close_failure_cannot_escape_after_terminal_frame(
    monkeypatch,
):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = CloseRaisingStream(
        [
            {"type": "token", "content": "complete"},
            {"type": "done", "model": "officer-model", "tokens_used": 1},
        ]
    )
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    frames = _stream_frames(
        OfficerStreamingChatView.as_view()(
            _request(
                "POST",
                "/api/ai/officer/chat/stream/",
                officer.id,
                data={"message": "Stream", "application_id": str(application.id)},
            )
        )
    )

    assert [event for event, _payload in frames] == ["done"]
    assert sum(event in {"done", "error"} for event, _payload in frames) == 1
    assert provider_stream.closed is True
    assert _audit_events()[-1].details["outcome"] == "success"


def test_officer_stream_disconnect_records_end_to_end_provider_latency(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = EndlessCloseAwareStream()
    llm = StreamLLM(provider_stream)
    latency = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )
    monkeypatch.setattr("ai_assistant.views.officer.observe", latency)

    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            officer.id,
            data={"message": "Stream", "application_id": str(application.id)},
        )
    )
    iterator = iter(response.streaming_content)
    next(iterator)
    response.close()

    assert any(
        call.kwargs.get("operation") == "stream"
        for call in latency.call_args_list
    )


def test_officer_stream_disconnect_closes_provider_and_records_result(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider_stream = EndlessCloseAwareStream()
    llm = StreamLLM(provider_stream)
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", lambda **kwargs: llm)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )
    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            officer.id,
            data={"message": "Stream", "application_id": str(application.id)},
        )
    )

    iterator = iter(response.streaming_content)
    assert b"event: tool_call" in next(iterator)
    response.close()

    assert provider_stream.closed is True
    result_event = _audit_events()[-1]
    assert result_event.action == "ai_officer_assistant_result"
    assert result_event.details["outcome"] == "disconnected"


@override_settings(AI_ASSISTANT_ENABLED=False)
def test_officer_stream_kill_switch_stops_before_provider(monkeypatch):
    officer = _officer()
    application = _application(officer.id)
    provider = Mock()
    monkeypatch.setattr("ai_assistant.views.officer.get_llm_service", provider)
    monkeypatch.setattr(
        "ai_assistant.views.officer.has_current_ai_consent", lambda scope: True
    )

    response = OfficerStreamingChatView.as_view()(
        _request(
            "POST",
            "/api/ai/officer/chat/stream/",
            officer.id,
            data={"message": "Stream", "application_id": str(application.id)},
        )
    )

    assert response.status_code == 503
    assert response.data["code"] == "AI_ASSISTANT_DISABLED"
    provider.assert_not_called()
