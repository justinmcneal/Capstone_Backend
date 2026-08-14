"""Explicitly opted-in Stage 6 probes using synthetic data only."""

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests
from redis import Redis

from ai_assistant.services import get_llm_service

pytestmark = pytest.mark.deployment_integration


def _opt_in(flag, *required):
    values = {name: (os.getenv(name, "") or "").strip() for name in required}
    if os.getenv(flag) != "1" or not all(values.values()):
        pytest.skip(f"Set {flag}=1 and {', '.join(required)} for the approved target")
    return values


def _post_chat(url, token, *, stream=False, message=None):
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={
            "message": message
            or "Synthetic release probe: explain the loan application steps.",
            "language": "en",
        },
        timeout=180,
        stream=stream,
    )
    response.raise_for_status()
    return response


def test_selected_real_provider_chat_and_stream_contract():
    _opt_in("RUN_AI_PROVIDER_DEPLOYMENT_TESTS")
    service = get_llm_service(use_case="chat")
    readiness = service.readiness()
    assert readiness["available"] is True
    result = service.chat("Give a short synthetic greeting.", language="en", max_tokens=64)
    assert result["success"] is True
    assert result["response"].strip()
    assert int(result.get("tokens_used", 0)) >= 0
    events = list(
        service.chat_stream("Magbigay ng maikling sintetikong pagbati.", language="tl", max_tokens=64)
    )
    assert [event["type"] for event in events].count("done") == 1
    assert not any(event["type"] == "error" for event in events)


def test_two_clients_share_atomic_redis_state():
    values = _opt_in(
        "RUN_AI_REDIS_DEPLOYMENT_TESTS", "AI_ASSISTANT_DEPLOYMENT_REDIS_URL"
    )
    key = f"ai-assistant:release-probe:{uuid.uuid4().hex}"
    first = Redis.from_url(values["AI_ASSISTANT_DEPLOYMENT_REDIS_URL"])
    second = Redis.from_url(values["AI_ASSISTANT_DEPLOYMENT_REDIS_URL"])
    try:
        assert first.set(key, 0, ex=60, nx=True)
        assert first.incr(key) == 1
        assert second.incr(key) == 2
        assert first.ttl(key) > 0
    finally:
        first.delete(key)
        first.close()
        second.close()


def test_target_proxy_preserves_sse_terminal_contract():
    values = _opt_in(
        "RUN_AI_PROXY_DEPLOYMENT_TESTS",
        "AI_ASSISTANT_DEPLOYMENT_STREAM_URL",
        "AI_ASSISTANT_DEPLOYMENT_CUSTOMER_TOKEN",
    )
    response = _post_chat(
        values["AI_ASSISTANT_DEPLOYMENT_STREAM_URL"],
        values["AI_ASSISTANT_DEPLOYMENT_CUSTOMER_TOKEN"],
        stream=True,
        message="What is the status of my synthetic test documents?",
    )
    assert response.headers["Content-Type"].startswith("text/event-stream")
    assert response.headers.get("X-Accel-Buffering", "no").lower() == "no"
    event_name = None
    events = []
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
        elif line and line.startswith("data:"):
            events.append(
                (event_name, json.loads(line.removeprefix("data:").strip()))
            )
    terminal = [event for event in events if event[0] in {"done", "error"}]
    assert len(terminal) == 1
    assert terminal[0][0] == "done"
    assert any(name == "token" for name, _ in events)
    assert any(name == "tool_call" for name, _ in events)
    assert any(
        name == "tool_result" and payload.get("success") is True
        for name, payload in events
    )


def test_representative_deployed_chat_load():
    values = _opt_in(
        "RUN_AI_LOAD_DEPLOYMENT_TESTS",
        "AI_ASSISTANT_DEPLOYMENT_CHAT_URL",
        "AI_ASSISTANT_DEPLOYMENT_CUSTOMER_TOKEN",
    )
    requests_count = int(os.getenv("AI_ASSISTANT_DEPLOYMENT_LOAD_REQUESTS", "10"))
    concurrency = int(os.getenv("AI_ASSISTANT_DEPLOYMENT_LOAD_CONCURRENCY", "2"))
    assert 1 <= requests_count <= 100
    assert 1 <= concurrency <= 20

    def execute(_):
        response = _post_chat(
            values["AI_ASSISTANT_DEPLOYMENT_CHAT_URL"],
            values["AI_ASSISTANT_DEPLOYMENT_CUSTOMER_TOKEN"],
        )
        body = response.json()
        assert body.get("success") is True

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        list(executor.map(execute, range(requests_count)))
