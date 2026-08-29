"""Stage 2 request, cost, readiness, and provider-boundary coverage."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from django.test import override_settings

from accounts.utils.throttles import ChatRateThrottle
from ai_assistant.services.llm_service import PUBLIC_PROVIDER_ERROR, GroqService
from ai_assistant.services.provider_boundary import (
    ProviderConcurrencyExceeded,
    ProviderSession,
)
from ai_assistant.services.request_limits import validate_chat_message
from ai_assistant.views.history import ChatHistoryView


@override_settings(
    AI_ASSISTANT_MESSAGE_MAX_CHARS=10,
    AI_ASSISTANT_MESSAGE_MAX_BYTES=20,
    AI_ASSISTANT_REQUEST_MAX_BYTES=21,
)
def test_chat_message_limits_distinguish_character_and_payload_errors():
    message, error = validate_chat_message('a' * 11)
    assert message is None
    assert error.status_code == 400
    assert error.data['code'] == 'AI_MESSAGE_CHARS_EXCEEDED'

    request = SimpleNamespace(META={'CONTENT_LENGTH': '22'})
    message, error = validate_chat_message('hello', request)
    assert message is None
    assert error.status_code == 413
    assert error.data['code'] == 'AI_REQUEST_BYTES_EXCEEDED'


@override_settings(AI_ASSISTANT_CHAT_RATE='100/hour')
def test_chat_throttle_uses_validated_environment_rate():
    assert ChatRateThrottle().get_rate() == '100/hour'


def test_unknown_provider_is_never_silently_treated_as_groq():
    with pytest.raises(ValueError, match='provider must be groq or ollama'):
        GroqService(provider='unknown')


@override_settings(
    AI_ASSISTANT_MAX_OUTPUT_TOKENS=64,
    AI_ASSISTANT_MAX_TOOL_ROUNDS=1,
)
def test_provider_generation_limits_are_hard_caps():
    assert GroqService._bounded_limits(500, 9) == (64, 1)


@override_settings(
    AI_ASSISTANT_MAX_CONCURRENT_REQUESTS=2,
    AI_ASSISTANT_CONNECT_TIMEOUT_SECONDS=3,
    AI_ASSISTANT_READ_TIMEOUT_SECONDS=9,
    AI_ASSISTANT_PROVIDER_RETRY_ATTEMPTS=2,
    AI_ASSISTANT_PROVIDER_RETRY_BACKOFF_SECONDS=0,
    AI_ASSISTANT_CIRCUIT_FAILURE_THRESHOLD=5,
    AI_ASSISTANT_CIRCUIT_RECOVERY_SECONDS=30,
)
def test_safe_readiness_get_retries_and_uses_configured_timeout(monkeypatch):
    boundary = ProviderSession()
    response = Mock(status_code=200)
    request = Mock(side_effect=[requests.ConnectionError('private detail'), response])
    monkeypatch.setattr(boundary._session, 'request', request)

    assert boundary.get('https://provider.example/models') is response
    assert request.call_count == 2
    assert request.call_args.kwargs['timeout'] == (3, 9)


@override_settings(
    AI_ASSISTANT_MAX_CONCURRENT_REQUESTS=2,
    AI_ASSISTANT_CONNECT_TIMEOUT_SECONDS=3,
    AI_ASSISTANT_READ_TIMEOUT_SECONDS=9,
    AI_ASSISTANT_STREAM_MAX_DURATION_SECONDS=4,
    AI_ASSISTANT_PROVIDER_RETRY_ATTEMPTS=1,
    AI_ASSISTANT_PROVIDER_RETRY_BACKOFF_SECONDS=0,
)
def test_stream_read_timeout_does_not_exceed_total_stream_duration(monkeypatch):
    boundary = ProviderSession()
    response = Mock(status_code=200)
    request = Mock(return_value=response)
    monkeypatch.setattr(boundary._session, 'request', request)

    boundary.post('https://provider.example/chat', stream=True).close()

    assert request.call_args.kwargs['timeout'] == (3, 4)


@override_settings(
    AI_ASSISTANT_MAX_CONCURRENT_REQUESTS=2,
    AI_ASSISTANT_CONNECT_TIMEOUT_SECONDS=3,
    AI_ASSISTANT_READ_TIMEOUT_SECONDS=9,
    AI_ASSISTANT_PROVIDER_RETRY_ATTEMPTS=4,
    AI_ASSISTANT_PROVIDER_RETRY_BACKOFF_SECONDS=0,
    AI_ASSISTANT_CIRCUIT_FAILURE_THRESHOLD=5,
    AI_ASSISTANT_CIRCUIT_RECOVERY_SECONDS=30,
)
def test_paid_chat_post_is_not_retried(monkeypatch):
    boundary = ProviderSession()
    request = Mock(side_effect=requests.ConnectionError('private detail'))
    monkeypatch.setattr(boundary._session, 'request', request)

    with pytest.raises(requests.ConnectionError):
        boundary.post('https://provider.example/chat')
    assert request.call_count == 1


@override_settings(
    AI_ASSISTANT_MAX_CONCURRENT_REQUESTS=1,
    AI_ASSISTANT_CONNECT_TIMEOUT_SECONDS=3,
    AI_ASSISTANT_READ_TIMEOUT_SECONDS=9,
    AI_ASSISTANT_PROVIDER_RETRY_ATTEMPTS=1,
    AI_ASSISTANT_PROVIDER_RETRY_BACKOFF_SECONDS=0,
    AI_ASSISTANT_CIRCUIT_FAILURE_THRESHOLD=5,
    AI_ASSISTANT_CIRCUIT_RECOVERY_SECONDS=30,
)
def test_stream_holds_concurrency_slot_until_closed(monkeypatch):
    boundary = ProviderSession()
    upstream = Mock(status_code=200)
    monkeypatch.setattr(boundary._session, 'request', Mock(return_value=upstream))

    response = boundary.post('https://provider.example/chat', stream=True)
    with pytest.raises(ProviderConcurrencyExceeded):
        boundary.post('https://provider.example/chat', stream=True)

    response.close()
    boundary.post('https://provider.example/chat', stream=True).close()


@override_settings(
    AI_ASSISTANT_CIRCUIT_FAILURE_THRESHOLD=1,
    AI_ASSISTANT_CIRCUIT_RECOVERY_SECONDS=30,
    AI_ASSISTANT_MAX_CONCURRENT_REQUESTS=2,
    AI_ASSISTANT_CONNECT_TIMEOUT_SECONDS=3,
    AI_ASSISTANT_READ_TIMEOUT_SECONDS=9,
    AI_ASSISTANT_PROVIDER_RETRY_ATTEMPTS=1,
    AI_ASSISTANT_PROVIDER_RETRY_BACKOFF_SECONDS=0,
)
def test_provider_failure_opens_circuit(monkeypatch):
    boundary = ProviderSession()
    monkeypatch.setattr(
        boundary._session,
        'request',
        Mock(side_effect=requests.ConnectionError('private detail')),
    )

    with pytest.raises(requests.ConnectionError):
        boundary.get('https://provider.example/models')
    assert boundary.circuit_state() == 'open'


def test_provider_failure_is_stable_and_does_not_expose_exception_text():
    result = GroqService._provider_failure(requests.ConnectionError('secret upstream detail'))
    assert result['success'] is False
    assert result['error'] == PUBLIC_PROVIDER_ERROR
    assert 'secret upstream detail' not in str(result)


def test_readiness_distinguishes_authentication_failure(monkeypatch):
    service = GroqService(api_key='configured', provider='groq')
    response = Mock(status_code=401)
    response.json.return_value = {}
    monkeypatch.setattr(
        'ai_assistant.services.llm_service._session',
        SimpleNamespace(
            circuit_state=lambda: 'closed',
            get=lambda *args, **kwargs: response,
        ),
    )

    readiness = service.readiness()
    assert readiness == {
        'provider': 'groq',
        'model': service.model,
        'configured': True,
        'reachable': True,
        'authenticated': False,
        'model_available': False,
        'available': False,
        'state': 'authentication_failed',
        'circuit': 'closed',
    }


def test_readiness_requires_selected_model(monkeypatch):
    service = GroqService(api_key='configured', model='required-model', provider='groq')
    response = Mock(status_code=200)
    response.json.return_value = {'data': [{'id': 'different-model'}]}
    monkeypatch.setattr(
        'ai_assistant.services.llm_service._session',
        SimpleNamespace(
            circuit_state=lambda: 'closed',
            get=lambda *args, **kwargs: response,
        ),
    )

    readiness = service.readiness()
    assert readiness['reachable'] is True
    assert readiness['authenticated'] is True
    assert readiness['model_available'] is False
    assert readiness['available'] is False
    assert readiness['state'] == 'model_unavailable'


@override_settings(
    AI_ASSISTANT_HISTORY_MAX_PAGE=5,
    AI_ASSISTANT_HISTORY_SEARCH_MAX_CHARS=8,
)
def test_history_rejects_excessive_page_and_search_before_database(monkeypatch):
    view = ChatHistoryView()
    monkeypatch.setattr(view, 'check_ai_consent', lambda request: (True, None))
    user = SimpleNamespace(customer_id='customer')

    page_response = view.get(
        SimpleNamespace(user=user, query_params={'page': '6'})
    )
    assert page_response.status_code == 400
    assert page_response.data['code'] == 'AI_HISTORY_PAGE_EXCEEDED'

    search_response = view.get(
        SimpleNamespace(user=user, query_params={'search': 'a' * 9})
    )
    assert search_response.status_code == 400
    assert search_response.data['code'] == 'AI_HISTORY_SEARCH_EXCEEDED'
