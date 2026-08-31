import json
from unittest.mock import Mock, patch

from ai_assistant.services.llm_service import GroqService


class ProviderResponse:
    def __init__(self, lines):
        self.status_code = 200
        self._lines = list(lines)
        self.closed = False

    def iter_lines(self):
        yield from self._lines

    def close(self):
        self.closed = True


def _provider_completion(content='{"intent":"application_readiness"}'):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": content},
            }
        ],
        "usage": {"total_tokens": 1},
    }
    return response


def _provider_stream(*parts):
    lines = [
        f'data: {json.dumps({"choices": [{"delta": {"content": part}}]})}'.encode()
        for part in parts
    ]
    lines.append(b"data: [DONE]")
    return ProviderResponse(lines)


def test_officer_provider_stream_emits_only_one_validated_terminal_event():
    service = GroqService(
        api_key="synthetic-key",
        provider="ollama",
        model="test-model",
    )
    with patch(
        "ai_assistant.services.llm_service._session.post",
        return_value=_provider_completion(),
    ) as post:
        events = list(
            service.chat_with_tools_stream(
                message="Summarize review readiness.",
                customer_id="synthetic-customer",
                officer_mode=True,
            )
        )

    assert [event["type"] for event in events] == ["done"]
    assert events[0]["response"] == ""
    assert events[0]["planner_used"] is True
    assert post.call_count == 1


def test_officer_provider_stream_does_not_open_a_final_prose_stream():
    service = GroqService(
        api_key="synthetic-key",
        provider="ollama",
        model="test-model",
    )
    with patch(
        "ai_assistant.services.llm_service._session.post",
        return_value=_provider_completion(),
    ) as post:
        events = list(
            service.chat_with_tools_stream(
                message="Summarize review readiness.",
                customer_id="synthetic-customer",
                officer_mode=True,
            )
        )

    assert [event["type"] for event in events] == ["done"]
    assert post.call_count == 1
