"""Explicitly opted-in Stage 6 probes using synthetic data only."""

import json
import multiprocessing
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests
from redis import Redis

from ai_assistant.services import get_llm_service

pytestmark = pytest.mark.deployment_integration


def _increment_redis_counter(url, key, count):
    client = Redis.from_url(url)
    try:
        for _ in range(count):
            client.incr(key)
    finally:
        client.close()


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


def _officer_proxy_values():
    return _opt_in(
        "RUN_AI_OFFICER_PROXY_DEPLOYMENT_TESTS",
        "AI_ASSISTANT_DEPLOYMENT_OFFICER_BASE_URL",
        "AI_ASSISTANT_DEPLOYMENT_OFFICER_EMAIL",
        "AI_ASSISTANT_DEPLOYMENT_OFFICER_PASSWORD",
        "AI_ASSISTANT_DEPLOYMENT_OFFICER_APPLICATION_ID",
        "AI_ASSISTANT_DEPLOYMENT_OFFICER_UNASSIGNED_APPLICATION_ID",
        "AI_ASSISTANT_DEPLOYMENT_CUSTOMER_EMAIL",
        "AI_ASSISTANT_DEPLOYMENT_CUSTOMER_PASSWORD",
        "AI_ASSISTANT_DEPLOYMENT_RAW_TOKEN_CANARY",
    )


def _deployment_endpoint(base_url, path):
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _response_code(response):
    try:
        return response.json().get("code")
    except (ValueError, TypeError):
        return None


def _login_cookie_session(base_url, *, login_path, email, password, me_path=None):
    session = requests.Session()
    csrf_response = session.get(
        _deployment_endpoint(base_url, "/api/auth/csrf-token/"),
        timeout=30,
    )
    assert csrf_response.status_code == 200
    csrf_payload = csrf_response.json()
    csrf_token = csrf_payload["data"]["csrf_token"]

    login_response = session.post(
        _deployment_endpoint(base_url, login_path),
        headers={"X-CSRFToken": csrf_token},
        json={
            "email": email,
            "password": password,
            "remember_me": False,
            "token_transport": "cookie",
        },
        timeout=30,
    )
    assert login_response.status_code == 200, _response_code(login_response)
    login_payload = login_response.json()
    assert login_payload.get("status") == "success"
    login_data = login_payload.get("data") or {}
    assert login_data.get("requires_2fa") is not True
    assert "access" not in login_data
    assert "refresh" not in login_data

    csrf_cookie = session.cookies.get_dict().get("csrftoken")
    assert csrf_cookie
    if me_path:
        profile_response = session.get(
            _deployment_endpoint(base_url, me_path),
            timeout=30,
        )
        assert profile_response.status_code == 200
        assert profile_response.json().get("status") == "success"
    return session, csrf_cookie


def _officer_session(values):
    return _login_cookie_session(
        values["AI_ASSISTANT_DEPLOYMENT_OFFICER_BASE_URL"],
        login_path="/api/auth/loan-officer/login/",
        email=values["AI_ASSISTANT_DEPLOYMENT_OFFICER_EMAIL"],
        password=values["AI_ASSISTANT_DEPLOYMENT_OFFICER_PASSWORD"],
        me_path="/api/auth/loan-officer/me/",
    )


def _customer_session(values):
    return _login_cookie_session(
        values["AI_ASSISTANT_DEPLOYMENT_OFFICER_BASE_URL"],
        login_path="/api/auth/login/",
        email=values["AI_ASSISTANT_DEPLOYMENT_CUSTOMER_EMAIL"],
        password=values["AI_ASSISTANT_DEPLOYMENT_CUSTOMER_PASSWORD"],
    )


def _officer_stream_request(
    session,
    csrf_token,
    base_url,
    *,
    application_id,
    conversation_id,
    request_id,
    message,
):
    return session.post(
        _deployment_endpoint(base_url, "/api/ai/officer/chat/stream/"),
        headers={
            "Content-Type": "application/json",
            "X-CSRFToken": csrf_token,
            "Idempotency-Key": request_id,
        },
        json={
            "message": message,
            "application_id": application_id,
            "conversation_id": conversation_id,
            "language": "en",
            "history": [],
        },
        timeout=(10, 180),
        stream=True,
    )


def _iter_sse_events(response):
    event_name = None
    data_lines = []
    for raw_line in response.iter_lines(decode_unicode=True):
        line = raw_line or ""
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())
        elif not line and event_name is not None:
            yield event_name, json.loads("\n".join(data_lines))
            event_name = None
            data_lines = []
    if event_name is not None:
        yield event_name, json.loads("\n".join(data_lines))


def _assert_officer_sse_contract(events, *, conversation_id, canary):
    terminal_positions = [
        index
        for index, (name, _payload) in enumerate(events)
        if name in {"done", "error"}
    ]
    assert len(terminal_positions) == 1
    assert terminal_positions[0] == len(events) - 1
    assert canary not in json.dumps(events, ensure_ascii=False)

    terminal_name, terminal_payload = events[-1]
    if terminal_name == "done":
        assert terminal_payload.get("response", "").strip()
        assert terminal_payload.get("conversation_id") == conversation_id
        assert terminal_payload.get("request_id")
        assert terminal_payload.get("response_time_ms") is not None
        assert terminal_payload.get("tokens_used") is not None
    else:
        assert terminal_payload.get("code")
        assert terminal_payload.get("request_id")


def _revoke_customer_ai_consent(session, csrf_token, base_url):
    response = session.put(
        _deployment_endpoint(base_url, "/api/auth/consent/"),
        headers={"Content-Type": "application/json", "X-CSRFToken": csrf_token},
        json={"ai_consent": False},
        timeout=30,
    )
    assert response.status_code == 200, _response_code(response)


def _restore_customer_ai_consent(session, csrf_token, base_url, consent_version):
    response = session.put(
        _deployment_endpoint(base_url, "/api/auth/consent/"),
        headers={"Content-Type": "application/json", "X-CSRFToken": csrf_token},
        json={
            "data_consent": True,
            "ai_consent": True,
            "consent_version": consent_version,
        },
        timeout=30,
    )
    assert response.status_code == 200, _response_code(response)


def test_real_officer_proxy_sse_contract_and_no_raw_token():
    values = _officer_proxy_values()
    officer_session, csrf_token = _officer_session(values)
    base_url = values["AI_ASSISTANT_DEPLOYMENT_OFFICER_BASE_URL"]
    conversation_id = str(uuid.uuid4())
    response = _officer_stream_request(
        officer_session,
        csrf_token,
        base_url,
        application_id=values["AI_ASSISTANT_DEPLOYMENT_OFFICER_APPLICATION_ID"],
        conversation_id=conversation_id,
        request_id=str(uuid.uuid4()),
        message="Summarize this synthetic application without naming the customer.",
    )
    try:
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/event-stream")
        assert response.headers.get("X-Accel-Buffering", "no").lower() == "no"
        events = list(_iter_sse_events(response))
    finally:
        response.close()

    _assert_officer_sse_contract(
        events,
        conversation_id=conversation_id,
        canary=values["AI_ASSISTANT_DEPLOYMENT_RAW_TOKEN_CANARY"],
    )
    assert events[-1][0] == "done"


def test_real_officer_proxy_denies_unassigned_application():
    values = _officer_proxy_values()
    officer_session, csrf_token = _officer_session(values)
    response = _officer_stream_request(
        officer_session,
        csrf_token,
        values["AI_ASSISTANT_DEPLOYMENT_OFFICER_BASE_URL"],
        application_id=values[
            "AI_ASSISTANT_DEPLOYMENT_OFFICER_UNASSIGNED_APPLICATION_ID"
        ],
        conversation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        message="Summarize this synthetic application.",
    )
    try:
        assert response.status_code == 404
        assert not response.headers.get("Content-Type", "").startswith(
            "text/event-stream"
        )
    finally:
        response.close()


def test_real_officer_proxy_revalidates_consent_during_stream():
    values = _officer_proxy_values()
    officer_session, officer_csrf = _officer_session(values)
    customer_session, customer_csrf = _customer_session(values)
    base_url = values["AI_ASSISTANT_DEPLOYMENT_OFFICER_BASE_URL"]
    consent_response = customer_session.get(
        _deployment_endpoint(base_url, "/api/auth/consent/"),
        timeout=30,
    )
    assert consent_response.status_code == 200
    consent_data = consent_response.json()["data"]
    consent_version = consent_data.get("consent_version")
    if not consent_version:
        consent_version = consent_data["current_policy"]["consent_version"]

    response = _officer_stream_request(
        officer_session,
        officer_csrf,
        base_url,
        application_id=values["AI_ASSISTANT_DEPLOYMENT_OFFICER_APPLICATION_ID"],
        conversation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        message="Give a short synthetic review summary.",
    )
    events = []
    revoked = False
    try:
        for event in _iter_sse_events(response):
            events.append(event)
            if event[0] not in {"done", "error"}:
                _revoke_customer_ai_consent(customer_session, customer_csrf, base_url)
                revoked = True
                break
        assert revoked, "provider stream completed before consent could be revoked"
        events.extend(_iter_sse_events(response))
    finally:
        response.close()
        _restore_customer_ai_consent(
            customer_session,
            customer_csrf,
            base_url,
            consent_version,
        )

    terminal = [event for event in events if event[0] in {"done", "error"}]
    assert len(terminal) == 1
    assert terminal[0][0] == "error"
    assert terminal[0][1]["code"] == "AI_OFFICER_CONSENT_CHANGED"


def test_real_officer_proxy_cancellation_does_not_leave_request_in_progress():
    values = _officer_proxy_values()
    officer_session, csrf_token = _officer_session(values)
    base_url = values["AI_ASSISTANT_DEPLOYMENT_OFFICER_BASE_URL"]
    request_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    response = _officer_stream_request(
        officer_session,
        csrf_token,
        base_url,
        application_id=values["AI_ASSISTANT_DEPLOYMENT_OFFICER_APPLICATION_ID"],
        conversation_id=conversation_id,
        request_id=request_id,
        message="Give a longer synthetic review summary.",
    )
    saw_nonterminal = False
    try:
        for event_name, _payload in _iter_sse_events(response):
            if event_name not in {"done", "error"}:
                saw_nonterminal = True
                break
        assert saw_nonterminal, "provider stream completed before cancellation"
    finally:
        response.close()

    retry_response = None
    try:
        deadline = time.monotonic() + 10
        while True:
            retry_response = officer_session.post(
                _deployment_endpoint(base_url, "/api/ai/officer/chat/"),
                headers={
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrf_token,
                    "Idempotency-Key": request_id,
                },
                json={
                    "message": "Give a longer synthetic review summary.",
                    "application_id": values[
                        "AI_ASSISTANT_DEPLOYMENT_OFFICER_APPLICATION_ID"
                    ],
                    "conversation_id": conversation_id,
                    "language": "en",
                    "history": [],
                },
                timeout=(10, 180),
            )
            if not (
                retry_response.status_code == 409
                and _response_code(retry_response) == "AI_REQUEST_IN_PROGRESS"
            ):
                break
            retry_response.close()
            if time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        assert (
            retry_response.status_code != 409
            or _response_code(retry_response) != "AI_REQUEST_IN_PROGRESS"
        )
    finally:
        if retry_response is not None:
            retry_response.close()


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


def test_two_processes_share_atomic_redis_state():
    values = _opt_in(
        "RUN_AI_REDIS_DEPLOYMENT_TESTS", "AI_ASSISTANT_DEPLOYMENT_REDIS_URL"
    )
    key = f"ai-assistant:process-release-probe:{uuid.uuid4().hex}"
    client = Redis.from_url(values["AI_ASSISTANT_DEPLOYMENT_REDIS_URL"])
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(
            target=_increment_redis_counter,
            args=(values["AI_ASSISTANT_DEPLOYMENT_REDIS_URL"], key, 25),
        )
        for _ in range(2)
    ]
    try:
        assert client.set(key, 0, ex=60, nx=True)
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
        assert all(process.exitcode == 0 for process in processes)
        assert int(client.get(key)) == 50
        assert client.ttl(key) > 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        client.delete(key)
        client.close()


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
