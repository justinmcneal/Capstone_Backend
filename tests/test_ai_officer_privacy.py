from unittest.mock import Mock, patch

import pytest

from ai_assistant.services.llm_service import GroqService


EXPECTED_UNSUPPORTED_RESPONSE = (
    "I can help summarize this application's status, profile readiness, document "
    "review, or repayment information. I can't help with that request here."
)


def _provider_response(content):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "usage": {"total_tokens": 3},
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": content},
            }
        ],
    }
    return response


@pytest.mark.parametrize(
    "message",
    [
        "The applicant is Alice. Summarize review readiness.",
        "The applicant is 李 小龙. Summarize review readiness.",
        "Review the applicant's phone +63 917 123 4567.",
    ],
)
def test_officer_privacy_blocks_identifiers_before_provider_call(message):
    service = GroqService(
        api_key="synthetic-key",
        provider="ollama",
        model="test-model",
    )

    with patch("ai_assistant.services.llm_service._session.post") as provider_post:
        result = service.chat_with_tools(
            message=message,
            customer_id="synthetic-customer",
            officer_mode=True,
        )

    assert result["success"] is True
    assert result["response"] == EXPECTED_UNSUPPORTED_RESPONSE
    assert result["privacy_blocked"] is True
    assert message not in result["response"]
    provider_post.assert_not_called()


def test_officer_privacy_blocks_identifiers_in_replayed_history():
    service = GroqService(
        api_key="synthetic-key",
        provider="ollama",
        model="test-model",
    )

    with patch("ai_assistant.services.llm_service._session.post") as provider_post:
        result = service.chat_with_tools(
            message="Summarize review readiness.",
            customer_id="synthetic-customer",
            conversation_history=[
                {
                    "role": "user",
                    "content": "Earlier, the applicant was Alice Santos.",
                },
                {
                    "role": "assistant",
                    "content": "The phone number is +63 917 123 4567.",
                },
            ],
            officer_mode=True,
        )

    assert result["success"] is True
    assert result["privacy_blocked"] is True
    assert "Alice Santos" not in result["response"]
    assert "+63 917 123 4567" not in result["response"]
    provider_post.assert_not_called()


def test_officer_planner_rejects_provider_identifier_echo():
    service = GroqService(
        api_key="synthetic-key",
        provider="ollama",
        model="test-model",
    )

    with patch(
        "ai_assistant.services.llm_service._session.post",
        return_value=_provider_response(
            "Alice Santos's application is ready for review."
        ),
    ):
        result = service.chat_with_tools(
            message="Summarize review readiness.",
            customer_id="synthetic-customer",
            officer_mode=True,
        )

    # Phase 3 never accepts provider prose for officer review. A non-JSON
    # planner response fails closed before any deterministic tool execution.
    assert result["success"] is False
    assert result["code"] == "AI_PROVIDER_PLANNER_INVALID"
    assert "Alice Santos" not in str(result)
