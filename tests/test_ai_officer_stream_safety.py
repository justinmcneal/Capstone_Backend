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


def _provider_completion(content="The summary is ready."):
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
    stream = _provider_stream(
        "The applicant is Alice",
        " Santos's application is ready for review.",
    )

    with patch(
        "ai_assistant.services.llm_service._session.post",
        side_effect=[_provider_completion(), stream],
    ):
        events = list(
            service.chat_with_tools_stream(
                message="Summarize review readiness.",
                customer_id="synthetic-customer",
                officer_mode=True,
            )
        )

    assert [event["type"] for event in events] == ["done"]
    assert "Alice" not in json.dumps(events)
    assert "Santos" not in json.dumps(events)
    assert events[0]["response"]
    assert stream.closed is True


def test_officer_provider_stream_rejects_an_oversized_buffer():
    service = GroqService(
        api_key="synthetic-key",
        provider="ollama",
        model="test-model",
    )
    stream = _provider_stream("x" * 9)

    with patch(
        "ai_assistant.services.llm_service._session.post",
        side_effect=[_provider_completion(), stream],
    ), patch(
        "ai_assistant.services.llm_service.settings.AI_ASSISTANT_MAX_OUTPUT_TOKENS",
        1,
    ):
        events = list(
            service.chat_with_tools_stream(
                message="Summarize review readiness.",
                customer_id="synthetic-customer",
                officer_mode=True,
            )
        )

    assert events == [
        {
            "type": "error",
            "content": "AI service is temporarily unavailable. Please try again later.",
            "code": "AI_PROVIDER_STREAM_OUTPUT_LIMIT",
        }
    ]
    assert stream.closed is True
