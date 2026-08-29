"""
=============================================================================
AI STREAMING SSE BEHAVIOR TESTS
=============================================================================

Validates SSE formatting and streaming endpoint behavior:
- Missing message returns 400
- Invalid conversation_id / language returns 400
- Prohibited content returns a simple SSE stream with token and done events
- Event stream contains expected event types when LLM is mocked
=============================================================================
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from accounts.authentication import AuthenticatedUser
from accounts.utils.access_control import AccessControlMixin
from ai_assistant.views import StreamingChatView
from ai_assistant.views.chat_views import EventStreamRenderer

# =============================================================================
# HELPERS
# =============================================================================

DEFAULT_USER = AuthenticatedUser(
    customer_id='65b7e7f7e4f1a2b3c4d5e6f7',
    email='stream@example.com',
    role='customer',
    verified=True,
)


def test_chat_stream_accepts_non_empty_conversation_history():
    """Legacy streaming must reach the provider when history is supplied."""
    from ai_assistant.services.llm_service import GroqService

    provider_response = MagicMock(status_code=200)
    provider_response.iter_lines.return_value = [
        b'data: {"choices":[{"delta":{"content":"history ok"}}]}',
        b"data: [DONE]",
    ]

    history = [
        {"role": "user", "content": "Earlier synthetic question"},
        {"role": "assistant", "content": "Earlier synthetic answer"},
    ]
    with patch(
        "ai_assistant.services.llm_service._session.post",
        return_value=provider_response,
    ) as provider_post:
        events = list(
            GroqService(
                api_key="synthetic-key",
                model="synthetic-model",
                provider="groq",
            ).chat_stream(
                "Current synthetic question",
                conversation_history=history,
            )
        )

    assert events[0] == {"type": "token", "content": "history ok"}
    assert events[-1]["type"] == "done"
    assert provider_post.call_args.kwargs["json"]["messages"][-3:-1] == history


def test_json_and_streaming_tool_transports_send_same_six_complete_turns():
    """JSON and streaming tool calls must send the same twelve history entries."""
    from ai_assistant.services.llm_service import GroqService

    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"Synthetic history entry {index}",
        }
        for index in range(14)
    ]
    expected_history = history[-12:]
    service = GroqService(
        api_key="synthetic-key",
        model="synthetic-model",
        provider="groq",
    )

    json_response = MagicMock(status_code=200)
    json_response.json.return_value = {
        "choices": [{"message": {"content": "Synthetic JSON response"}}],
    }
    with patch(
        "ai_assistant.services.llm_service._session.post",
        return_value=json_response,
    ) as json_post:
        service.chat_with_tools(
            message="Current synthetic question",
            customer_id="synthetic-customer",
            conversation_history=history,
            tools=[],
        )
    json_history = json_post.call_args.kwargs["json"]["messages"][1:-1]

    phase_response = MagicMock(status_code=200)
    phase_response.json.return_value = {
        "choices": [{"message": {"content": "Synthetic phase response"}}],
    }
    stream_response = MagicMock(status_code=200)
    stream_response.iter_lines.return_value = [
        b'data: {"choices":[{"delta":{"content":"Synthetic stream response"}}]}',
        b"data: [DONE]",
    ]
    with patch(
        "ai_assistant.services.llm_service._session.post",
        side_effect=[phase_response, stream_response],
    ) as stream_post:
        list(
            service.chat_with_tools_stream(
                message="Current synthetic question",
                customer_id="synthetic-customer",
                conversation_history=history,
                tools=[],
            )
        )
    stream_history = stream_post.call_args_list[-1].kwargs["json"]["messages"][1:-1]

    assert json_history == expected_history
    assert stream_history == expected_history


def _make_fake_request(data=None, user=None):
    return SimpleNamespace(
        data=data or {},
        user=user or DEFAULT_USER,
        method='POST',
    )


@pytest.fixture(autouse=True)
def bypass_access_control(monkeypatch):
    monkeypatch.setattr(AccessControlMixin, 'require_customer', lambda self, request: (True, request.user), raising=False)


def _call_view(request):
    view = StreamingChatView()
    view.authentication_classes = []
    view.permission_classes = []
    view.throttle_classes = []
    with patch.object(StreamingChatView, 'check_ai_consent', return_value=(True, None)):
        return view.post(request)


# =============================================================================
# EVENT STREAM RENDERER TESTS
# =============================================================================

class TestEventStreamRenderer:
    """Renderer should preserve raw SSE bytes/strings."""

    def test_render_returns_raw_string(self):
        renderer = EventStreamRenderer()
        ctx = {}
        result = renderer.render("raw-stream-data", accepted_media_type=None, renderer_context=ctx)
        assert result == "raw-stream-data"


# =============================================================================
# STREAMING VIEW INPUT VALIDATION TESTS
# =============================================================================

class TestStreamingInputValidation:
    """StreamingChatView should validate inputs before calling LLM."""

    def test_missing_message_returns_400(self):
        response = _call_view(_make_fake_request(data={}))
        assert response.status_code == 400

    def test_invalid_conversation_id_returns_400(self):
        response = _call_view(_make_fake_request(data={
            'message': 'Hello',
            'conversation_id': 'not-a-uuid',
        }))
        assert response.status_code == 400

    def test_invalid_language_returns_400(self):
        response = _call_view(_make_fake_request(data={
            'message': 'Hello',
            'language': 'jp',
        }))
        assert response.status_code == 400

    @override_settings(AI_ASSISTANT_ENABLED=False)
    def test_incident_kill_switch_returns_json_before_stream_starts(self):
        with patch("ai_assistant.views.streaming.get_llm_service") as provider:
            response = _call_view(
                _make_fake_request(data={"message": "Synthetic incident probe"})
            )

        assert response.status_code == 503
        assert response.data["code"] == "AI_ASSISTANT_DISABLED"
        assert provider.call_count == 0


# =============================================================================
# STREAMING CONTENT FILTER TESTS
# =============================================================================

class TestStreamingContentFilter:
    """Prohibited messages should return a simple SSE stream."""

    @patch('ai_assistant.services.knowledge_base.check_prohibited_content')
    def test_prohibited_content_returns_sse_stream(self, mock_check_prohibited):
        mock_check_prohibited.return_value = (True, 'I cannot help with that.')

        response = _call_view(_make_fake_request(data={'message': 'Give me your password.'}))

        assert response.status_code == 200
        assert response['Content-Type'] == 'text/event-stream'
        content = b''.join(response.streaming_content).decode('utf-8')
        assert 'event: token' in content
        assert 'event: done' in content


# =============================================================================
# SSE FRAME FORMATTING TESTS
# =============================================================================

def _parse_sse_frames(raw_text):
    """Parse raw SSE text into a list of (event_name, data_dict) tuples."""
    frames = []
    for block in raw_text.strip().split('\n\n'):
        if not block:
            continue
        event_name = None
        data_text = None
        for line in block.split('\n'):
            if line.startswith('event: '):
                event_name = line[len('event: '):]
            elif line.startswith('data: '):
                data_text = line[len('data: '):]
        if event_name is not None and data_text is not None:
            frames.append((event_name, json.loads(data_text)))
    return frames


class TestSSEFrameFormatting:
    """Integration test for exact SSE frame structure and headers."""

    @patch('ai_assistant.services.tools.invalidate_user_tool_cache')
    @patch('ai_assistant.views.streaming.get_llm_service')
    def test_sse_frames_have_exact_event_data_format(self, mock_get_llm, mock_invalidate):
        from ai_assistant.services.llm_service import GroqService
        mock_llm = MagicMock(spec=GroqService)
        mock_llm.is_available.return_value = True
        mock_llm.chat_with_tools_stream.return_value = iter([
            {'type': 'tool_call', 'name': 'get_profile_status'},
            {'type': 'tool_result', 'name': 'get_profile_status', 'success': True},
            {'type': 'token', 'content': 'Hello'},
            {'type': 'token', 'content': ' world'},
            {'type': 'done', 'model': 'llama3.1', 'tokens_used': 7},
        ])
        mock_get_llm.return_value = mock_llm

        response = _call_view(_make_fake_request(data={'message': 'Hi'}))

        assert response.status_code == 200
        assert response['Content-Type'] == 'text/event-stream'
        assert response['Cache-Control'] == 'no-cache'
        assert response['X-Accel-Buffering'] == 'no'

        raw = b''.join(response.streaming_content).decode('utf-8')
        frames = _parse_sse_frames(raw)

        event_names = [name for name, _ in frames]
        assert event_names == ['tool_call', 'tool_result', 'token', 'token', 'done']

        assert frames[0][1] == {'name': 'get_profile_status'}
        assert frames[1][1] == {'name': 'get_profile_status', 'success': True}
        assert frames[2][1] == {'content': 'Hello'}
        assert frames[3][1] == {'content': ' world'}
        done_payload = frames[4][1]
        assert done_payload['model'] == 'llama3.1'
        assert done_payload['tokens_used'] == 7
        assert 'conversation_id' in done_payload
        assert done_payload['tools_called'] == ['get_profile_status']

    @patch('ai_assistant.views.streaming.check_prohibited_content')
    def test_prohibited_content_sse_frames_parse_correctly(self, mock_check_prohibited):
        mock_check_prohibited.return_value = (True, 'I cannot help with that.')

        response = _call_view(_make_fake_request(data={'message': 'Give me your password.'}))

        assert response.status_code == 200
        assert response['Content-Type'] == 'text/event-stream'

        raw = b''.join(response.streaming_content).decode('utf-8')
        frames = _parse_sse_frames(raw)

        event_names = [name for name, _ in frames]
        assert event_names == ['token', 'done']
        assert frames[0][1]['content'] == mock_check_prohibited.return_value[1]
        assert frames[1][1]['filtered'] is True
        assert frames[1][1]['request_id']
