import json
from unittest.mock import Mock

import pytest
from django.test import override_settings

from ai_assistant.services.llm_service import GroqService
from ai_assistant.services.officer_prompt import route_officer_intent


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("Summarize this application's review readiness.", "application_readiness"),
        ("What is the current application status?", "application_readiness"),
        ("What profile information is still incomplete?", "profile_readiness"),
        ("Ano pa ang kulang sa profile bago ang pagsusuri?", "profile_readiness"),
        ("Summarize the required document review statuses.", "document_status"),
        ("Ibuod ang katayuan ng mga kinakailangang dokumento.", "document_status"),
        ("Explain the current repayment summary.", "repayment_summary"),
        ("Ipaliwanag ang kasalukuyang buod ng pagbabayad.", "repayment_summary"),
    ],
)
def test_common_officer_questions_route_to_server_owned_intents(message, intent):
    assert route_officer_intent(message) == intent


def test_ambiguous_officer_planner_returns_only_an_allowlisted_intent(monkeypatch):
    service = GroqService(api_key="configured", model="planner-test", provider="groq")
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"intent": "repayment_summary"})}}],
        "usage": {"total_tokens": 12},
    }
    response.close = Mock()
    post = Mock(return_value=response)
    monkeypatch.setattr("ai_assistant.services.llm_service._session.post", post)

    result = service.plan_officer_request(
        "Can you tell me about the payment situation?",
        language="en",
        request_id="request-1",
    )

    assert result == {
        "success": True,
        "intent": "repayment_summary",
        "provider": "groq",
        "model": "planner-test",
        "response_time_ms": result["response_time_ms"],
        "tokens_used": 12,
    }
    request_body = post.call_args.kwargs["json"]
    assert "tools" not in request_body
    assert request_body["temperature"] == 0
    assert request_body["max_tokens"] <= 64
    assert response.close.called


def test_invalid_officer_planner_output_fails_closed(monkeypatch):
    service = GroqService(api_key="configured", model="planner-invalid-test", provider="groq")
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [{"message": {"content": "I think this is a repayment question."}}]
    }
    response.close = Mock()
    monkeypatch.setattr("ai_assistant.services.llm_service._session.post", Mock(return_value=response))

    result = service.plan_officer_request("Tell me what you see.", language="en")

    assert result["success"] is False
    assert result["code"] == "AI_PROVIDER_PLANNER_INVALID"
    assert "I think" not in json.dumps(result)


def test_officer_planner_accepts_json_code_fence_from_ollama(monkeypatch):
    service = GroqService(api_key="configured", model="planner-fenced-test", provider="ollama")
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "```json\n{\"intent\":\"application_readiness\"}\n```"
                }
            }
        ]
    }
    response.close = Mock()
    monkeypatch.setattr(
        "ai_assistant.services.llm_service._session.post", Mock(return_value=response)
    )

    result = service.plan_officer_request(
        "Can you tell me what needs attention in this record?", language="en"
    )

    assert result["success"] is True
    assert result["intent"] == "application_readiness"


def test_officer_planner_accepts_single_backtick_json_fence_from_ollama(monkeypatch):
    service = GroqService(api_key="configured", model="planner-single-fence-test", provider="ollama")
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "`json\n{\"intent\":\"application_readiness\"}\n`"
                }
            }
        ]
    }
    response.close = Mock()
    monkeypatch.setattr(
        "ai_assistant.services.llm_service._session.post", Mock(return_value=response)
    )

    result = service.plan_officer_request(
        "Can you tell me what needs attention in this record?", language="en"
    )

    assert result["success"] is True
    assert result["intent"] == "application_readiness"


def test_officer_chat_executes_the_plan_without_a_second_prose_request(monkeypatch):
    service = GroqService(api_key="configured", model="planner-only-test", provider="groq")
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [{"message": {"content": '{"intent":"profile_readiness"}'}}],
        "usage": {"total_tokens": 9},
    }
    response.close = Mock()
    post = Mock(return_value=response)
    monkeypatch.setattr("ai_assistant.services.llm_service._session.post", post)
    executor = Mock(return_value={"success": True, "result": {"complete": True}})

    result = service.chat_with_tools(
        "Which profile information needs attention?",
        customer_id="customer-1",
        officer_mode=True,
        tool_executor=executor,
    )

    assert result["success"] is True
    assert result["response"] == ""
    assert result["planner_used"] is True
    assert result["tools_called"] == ["get_profile_readiness"]
    assert post.call_count == 1
    assert "tools" not in post.call_args.kwargs["json"]
    executor.assert_called_once_with(
        "get_profile_readiness", {}, "customer-1", request_id=None
    )


@override_settings(AI_ASSISTANT_PROVIDER_READINESS_CACHE_SECONDS=30)
def test_provider_readiness_is_cached_for_a_short_window(monkeypatch):
    service = GroqService(api_key="configured", model="readiness-cache-test", provider="groq")
    response = Mock(status_code=200)
    response.json.return_value = {"data": [{"id": "readiness-cache-test"}]}
    get = Mock(return_value=response)
    monkeypatch.setattr("ai_assistant.services.llm_service._session.get", get)

    first = service.readiness()
    second = service.readiness()

    assert first["available"] is True
    assert second == first
    assert get.call_count == 1
