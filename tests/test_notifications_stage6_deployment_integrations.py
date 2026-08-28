"""Explicitly opted-in, synthetic Notifications deployment probes."""

import asyncio
import multiprocessing
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests
from redis import Redis

pytestmark = pytest.mark.deployment_integration


def _opt_in(flag, *required):
    values = {name: (os.getenv(name, "") or "").strip() for name in required}
    if os.getenv(flag) != "1" or not all(values.values()):
        pytest.skip(f"Set {flag}=1 and {', '.join(required)} for the approved target")
    return values


def _increment(url, key, count):
    client = Redis.from_url(url)
    try:
        for _ in range(count):
            client.incr(key)
    finally:
        client.close()


def _authorized_get(url, token):
    response = requests.get(
        url, headers={"Authorization": f"Bearer {token}"}, timeout=30
    )
    response.raise_for_status()
    return response


def test_two_processes_share_deployment_redis_state():
    values = _opt_in(
        "RUN_NOTIFICATIONS_REDIS_DEPLOYMENT_TESTS",
        "NOTIFICATIONS_DEPLOYMENT_REDIS_URL",
    )
    url = values["NOTIFICATIONS_DEPLOYMENT_REDIS_URL"]
    key = f"notifications:release-probe:{uuid.uuid4().hex}"
    client = Redis.from_url(url)
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_increment, args=(url, key, 25)) for _ in range(2)
    ]
    try:
        assert client.set(key, 0, ex=60, nx=True)
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=20)
        assert all(process.exitcode == 0 for process in processes)
        assert int(client.get(key)) == 50
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        client.delete(key)
        client.close()


def test_multiple_workers_consume_notifications_queue():
    _opt_in("RUN_NOTIFICATIONS_CELERY_DEPLOYMENT_TESTS", "CELERY_BROKER_URL")
    from config.celery import app

    inspector = app.control.inspect(timeout=10)
    pings = inspector.ping() or {}
    queues = inspector.active_queues() or {}
    workers = {
        worker
        for worker, configured in queues.items()
        if any(queue.get("name") == "notifications" for queue in configured)
    }
    assert len(workers) >= 2
    assert workers.issubset(set(pings))


def test_authenticated_inbox_contract_and_read_load_through_https():
    values = _opt_in(
        "RUN_NOTIFICATIONS_HTTPS_DEPLOYMENT_TESTS",
        "NOTIFICATIONS_DEPLOYMENT_INBOX_URL",
        "NOTIFICATIONS_DEPLOYMENT_ACCESS_TOKEN",
    )
    url = values["NOTIFICATIONS_DEPLOYMENT_INBOX_URL"]
    token = values["NOTIFICATIONS_DEPLOYMENT_ACCESS_TOKEN"]
    assert url.startswith("https://")
    request_count = int(os.getenv("NOTIFICATIONS_DEPLOYMENT_LOAD_REQUESTS", "20"))
    concurrency = int(os.getenv("NOTIFICATIONS_DEPLOYMENT_LOAD_CONCURRENCY", "4"))
    assert 1 <= request_count <= 500
    assert 1 <= concurrency <= 50
    first = _authorized_get(url, token)
    assert first.headers.get("Content-Type", "").startswith("application/json")
    for forbidden in ("recipient_email", "idempotency_key", "mongodb://", "traceback"):
        assert forbidden not in first.text.lower()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        responses = list(
            executor.map(lambda _: _authorized_get(url, token), range(request_count))
        )
    assert len(responses) == request_count


def test_authenticated_wss_connect_ping_and_disconnect():
    values = _opt_in(
        "RUN_NOTIFICATIONS_WSS_DEPLOYMENT_TESTS",
        "NOTIFICATIONS_DEPLOYMENT_WSS_URL",
        "NOTIFICATIONS_DEPLOYMENT_ACCESS_TOKEN",
    )
    assert values["NOTIFICATIONS_DEPLOYMENT_WSS_URL"].startswith("wss://")

    async def exercise():
        from websockets.asyncio.client import connect

        async with connect(
            values["NOTIFICATIONS_DEPLOYMENT_WSS_URL"],
            subprotocols=[
                "access_token",
                values["NOTIFICATIONS_DEPLOYMENT_ACCESS_TOKEN"],
            ],
            open_timeout=20,
            close_timeout=10,
        ) as socket:
            established = await asyncio.wait_for(socket.recv(), timeout=20)
            assert '"sync_required": true' in established.lower()
            await socket.send('{"action":"ping"}')
            pong = await asyncio.wait_for(socket.recv(), timeout=20)
            assert '"type": "pong"' in pong.lower()

    asyncio.run(exercise())


def test_deployed_metrics_expose_notifications_families():
    values = _opt_in(
        "RUN_NOTIFICATIONS_METRICS_DEPLOYMENT_TESTS",
        "NOTIFICATIONS_DEPLOYMENT_METRICS_URL",
    )
    response = requests.get(values["NOTIFICATIONS_DEPLOYMENT_METRICS_URL"], timeout=15)
    response.raise_for_status()
    for metric in (
        "notifications_requests_total",
        "notifications_channel_outcomes_total",
        "notifications_delivery_backlog",
        "notifications_delivery_oldest_age_seconds",
        "notifications_websocket_connections_total",
        "notifications_websocket_actions_total",
        "notifications_metrics_last_success_timestamp_seconds",
    ):
        assert metric in response.text


def test_approved_synthetic_smtp_delivery():
    values = _opt_in(
        "RUN_NOTIFICATIONS_SMTP_DEPLOYMENT_TESTS",
        "NOTIFICATIONS_DEPLOYMENT_SMTP_RECIPIENT",
    )
    from django.core.mail import send_mail

    sent = send_mail(
        "Synthetic Notifications release probe",
        "Synthetic deployment validation only.",
        None,
        [values["NOTIFICATIONS_DEPLOYMENT_SMTP_RECIPIENT"]],
        fail_silently=False,
    )
    assert sent == 1


def test_approved_synthetic_firebase_delivery():
    values = _opt_in(
        "RUN_NOTIFICATIONS_FIREBASE_DEPLOYMENT_TESTS",
        "NOTIFICATIONS_DEPLOYMENT_FCM_TOKEN",
    )
    from firebase_admin import messaging

    message_id = messaging.send(
        messaging.Message(
            token=values["NOTIFICATIONS_DEPLOYMENT_FCM_TOKEN"],
            notification=messaging.Notification(
                title="Synthetic release probe",
                body="Notifications deployment validation only.",
            ),
        )
    )
    assert message_id
