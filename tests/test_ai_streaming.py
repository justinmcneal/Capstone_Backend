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
