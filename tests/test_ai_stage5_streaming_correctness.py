import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import override_settings

from accounts.authentication import AuthenticatedUser
from accounts.utils.access_control import AccessControlMixin
from ai_assistant.models import AIInteraction
from ai_assistant.services.llm_service import GroqService
from ai_assistant.views import StreamingChatView

CUSTOMER_ID = "65b7e7f7e4f1a2b3c4d5e6f7"
USER = AuthenticatedUser(
    customer_id=CUSTOMER_ID,
    email="stage5-stream@example.com",
    role="customer",
    verified=True,
)


class FakeProviderResponse:
    def __init__(self, lines):
        self.lines = list(lines)
        self.closed = False

    def iter_lines(self):
        yield from self.lines

    def close(self):
        self.closed = True


class CloseAwareStream:
    def __init__(self):
        self.closed = False
        self._sent = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._sent:
            return {"type": "token", "content": "later"}
        self._sent = True
        return {"type": "token", "content": "first"}

    def close(self):
        self.closed = True


def _request(data, request_id=None):
    headers = {"Idempotency-Key": request_id} if request_id else {}
    return SimpleNamespace(
        data=data,
        user=USER,
        method="POST",
        headers=headers,
        META={},
    )


def _call_stream(data, llm, request_id=None):
    view = StreamingChatView()
    view.authentication_classes = []
    view.permission_classes = []
    view.throttle_classes = []
    with (
        patch.object(
            AccessControlMixin,
            "require_customer",
            return_value=(True, USER),
        ),
        patch.object(
            StreamingChatView,
            "check_ai_consent",
            return_value=(True, None),
        ),
        patch("ai_assistant.views.streaming.get_llm_service", return_value=llm),
    ):
        return view.post(_request(data, request_id=request_id))


def _frames(response):
    raw = b"".join(response.streaming_content).decode("utf-8")
    parsed = []
    for block in raw.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line[7:] for line in lines if line.startswith("event: "))
        payload = next(line[6:] for line in lines if line.startswith("data: "))
        parsed.append((event, json.loads(payload)))
    return parsed


def _service():
    return GroqService(api_key="synthetic-key", model="synthetic-model", provider="groq")


def test_provider_stream_rejects_truncation_and_closes_response():
    response = FakeProviderResponse([
        b'data: {"choices":[{"delta":{"content":"partial"}}]}',
    ])

    chunks = list(_service()._provider_stream_chunks(response, request_id=str(uuid.uuid4())))

    assert chunks[0] == {"type": "token", "content": "partial"}
    assert chunks[-1]["type"] == "error"
    assert chunks[-1]["code"] == "AI_PROVIDER_STREAM_TRUNCATED"
    assert response.closed is True


def test_provider_stream_rejects_malformed_json_and_closes_response():
    response = FakeProviderResponse([b"data: {not-json", b"data: [DONE]"])

    chunks = list(_service()._provider_stream_chunks(response))

    assert chunks == [{
        "type": "error",
        "content": "AI service is temporarily unavailable. Please try again later.",
        "code": "AI_PROVIDER_STREAM_MALFORMED",
    }]
    assert response.closed is True


@override_settings(
    AI_ASSISTANT_STREAM_MAX_CHARS=100,
    AI_ASSISTANT_STREAM_MAX_BYTES=5,
)
def test_provider_stream_enforces_cumulative_output_bytes_and_closes_response():
    response = FakeProviderResponse([
        'data: {"choices":[{"delta":{"content":"éé"}}]}'.encode('utf-8'),
        'data: {"choices":[{"delta":{"content":"é"}}]}'.encode('utf-8'),
        b"data: [DONE]",
    ])

    chunks = list(_service()._provider_stream_chunks(response))

    assert chunks == [
        {"type": "token", "content": "éé"},
        {
            "type": "error",
            "content": "AI service is temporarily unavailable. Please try again later.",
            "code": "AI_PROVIDER_STREAM_OUTPUT_LIMIT",
        },
    ]
    assert response.closed is True


@override_settings(
    AI_ASSISTANT_STREAM_MAX_CHARS=5,
    AI_ASSISTANT_STREAM_MAX_BYTES=100,
)
def test_provider_stream_enforces_cumulative_output_characters():
    response = FakeProviderResponse([
        b'data: {"choices":[{"delta":{"content":"12345"}}]}',
        b'data: {"choices":[{"delta":{"content":"6"}}]}',
        b"data: [DONE]",
    ])

    chunks = list(_service()._provider_stream_chunks(response))

    assert chunks[-1]["code"] == "AI_PROVIDER_STREAM_OUTPUT_LIMIT"
    assert chunks[-1]["type"] == "error"
    assert response.closed is True


@override_settings(AI_ASSISTANT_STREAM_MAX_DURATION_SECONDS=1)
def test_provider_stream_enforces_total_duration_and_closes_response():
    response = FakeProviderResponse([
        b'data: {"choices":[{"delta":{"content":"late"}}]}',
        b"data: [DONE]",
    ])

    with patch(
        "ai_assistant.services.llm_service.time.monotonic",
        side_effect=[0, 2],
    ):
        chunks = list(_service()._provider_stream_chunks(response))

    assert chunks == [
        {
            "type": "error",
            "content": "AI service is temporarily unavailable. Please try again later.",
            "code": "AI_PROVIDER_STREAM_DURATION_LIMIT",
        },
    ]
    assert response.closed is True


def test_closing_provider_chunk_generator_closes_upstream_response():
    response = FakeProviderResponse([
        b'data: {"choices":[{"delta":{"content":"first"}}]}',
        b'data: {"choices":[{"delta":{"content":"second"}}]}',
        b"data: [DONE]",
    ])
    chunks = _service()._provider_stream_chunks(response)

    assert next(chunks)["content"] == "first"
    chunks.close()

    assert response.closed is True


def test_streaming_output_is_escaped_once_before_persistence():
    conversation_id = str(uuid.uuid4())
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.provider = "groq"
    llm.chat_with_tools_stream.return_value = iter([
        {"type": "token", "content": "A & B"},
        {"type": "done", "model": "synthetic", "tokens_used": 2},
    ])

    response = _call_stream(
        {"message": "escape", "conversation_id": conversation_id},
        llm,
    )
    frames = _frames(response)
    interactions = AIInteraction.find_by_conversation(conversation_id, CUSTOMER_ID)

    assert frames[0] == ("token", {"content": "A &amp; B"})
    assert interactions[-1].response == "A &amp; B"
    assert "&amp;amp;" not in interactions[-1].response


def test_done_is_terminal_even_if_provider_yields_more_events():
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.provider = "groq"
    llm.chat_with_tools_stream.return_value = iter([
        {"type": "token", "content": "complete"},
        {"type": "done", "model": "synthetic", "tokens_used": 1},
        {"type": "error", "content": "must not appear"},
    ])

    frames = _frames(_call_stream({"message": "terminal"}, llm))

    assert [event for event, _payload in frames] == ["token", "done"]


def test_stream_without_terminal_event_fails_without_persisting_partial_text():
    conversation_id = str(uuid.uuid4())
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.provider = "groq"
    llm.chat_with_tools_stream.return_value = iter([
        {"type": "token", "content": "partial"},
    ])

    frames = _frames(_call_stream(
        {"message": "truncated", "conversation_id": conversation_id},
        llm,
    ))

    assert [event for event, _payload in frames] == ["token", "error"]
    assert frames[-1][1]["code"] == "AI_STREAM_INCOMPLETE"
    assert AIInteraction.find_by_conversation(conversation_id, CUSTOMER_ID) == []


def test_empty_done_becomes_error_and_is_not_persisted():
    conversation_id = str(uuid.uuid4())
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.provider = "groq"
    llm.chat_with_tools_stream.return_value = iter([
        {"type": "done", "model": "synthetic", "tokens_used": 0},
    ])

    frames = _frames(_call_stream(
        {"message": "empty", "conversation_id": conversation_id},
        llm,
    ))

    assert [event for event, _payload in frames] == ["error"]
    assert frames[0][1]["code"] == "AI_EMPTY_RESPONSE"
    assert AIInteraction.find_by_conversation(conversation_id, CUSTOMER_ID) == []


def test_filtered_stream_persists_the_same_two_record_policy_as_normal_chat():
    conversation_id = str(uuid.uuid4())
    llm = MagicMock()
    with patch(
        "ai_assistant.views.streaming.check_prohibited_content",
        return_value=(True, "I cannot help with that."),
    ):
        frames = _frames(_call_stream(
            {"message": "filtered", "conversation_id": conversation_id},
            llm,
        ))

    interactions = AIInteraction.find_by_conversation(conversation_id, CUSTOMER_ID)
    assert [event for event, _payload in frames] == ["token", "done"]
    assert len(interactions) == 2
    assert interactions[0].role == "user"
    assert interactions[1].role == "assistant"
    assert interactions[1].model_used == "content_filter"


def test_terminal_error_contains_request_id_for_client_correlation():
    request_id = str(uuid.uuid4())
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.provider = "groq"
    llm.chat_with_tools_stream.return_value = iter([
        {
            "type": "error",
            "content": "safe public failure",
            "code": "AI_PROVIDER_STREAM_TRUNCATED",
        },
    ])

    frames = _frames(_call_stream(
        {"message": "correlate"},
        llm,
        request_id=request_id,
    ))

    assert frames == [("error", {
        "content": "safe public failure",
        "code": "AI_PROVIDER_STREAM_TRUNCATED",
        "request_id": request_id,
    })]


def test_client_disconnect_closes_provider_stream_and_releases_request_lease():
    request_id = str(uuid.uuid4())
    provider_stream = CloseAwareStream()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.provider = "groq"
    llm.chat_with_tools_stream.return_value = provider_stream
    response = _call_stream({"message": "disconnect"}, llm, request_id=request_id)

    iterator = iter(response.streaming_content)
    assert b"event: token" in next(iterator)
    response.close()

    request_record = settings.MONGODB["ai_chat_requests"].find_one(
        {"request_id": request_id}
    )
    assert provider_stream.closed is True
    # The request lease is released for an intentional retry after disconnect.
    assert request_record["status"] == "failed"
