"""Explicitly opted-in, non-destructive Loans Stage 6 deployment probes."""

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


def _increment_redis_counter(url, key, count):
    client = Redis.from_url(url)
    try:
        for _ in range(count):
            client.incr(key)
    finally:
        client.close()


def _authorized_get(url, token):
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response


def test_two_processes_share_deployment_redis_state():
    values = _opt_in("RUN_LOANS_REDIS_DEPLOYMENT_TESTS", "LOANS_DEPLOYMENT_REDIS_URL")
    key = f"loans:release-probe:{uuid.uuid4().hex}"
    client = Redis.from_url(values["LOANS_DEPLOYMENT_REDIS_URL"])
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(
            target=_increment_redis_counter,
            args=(values["LOANS_DEPLOYMENT_REDIS_URL"], key, 25),
        )
        for _ in range(2)
    ]
    try:
        assert client.set(key, 0, ex=60, nx=True)
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=20)
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


def test_multiple_deployed_workers_consume_the_loans_queue():
    _opt_in("RUN_LOANS_CELERY_DEPLOYMENT_TESTS", "CELERY_BROKER_URL")
    from config.celery import app

    inspector = app.control.inspect(timeout=10)
    pings = inspector.ping() or {}
    queues = inspector.active_queues() or {}
    loan_workers = {
        worker
        for worker, worker_queues in queues.items()
        if any(queue.get("name") == "loans" for queue in worker_queues)
    }
    assert len(pings) >= 2
    assert len(loan_workers) >= 2
    assert loan_workers.issubset(set(pings))


def test_authenticated_api_contract_and_representative_read_load_through_https():
    values = _opt_in(
        "RUN_LOANS_HTTPS_DEPLOYMENT_TESTS",
        "LOANS_DEPLOYMENT_PRODUCTS_URL",
        "LOANS_DEPLOYMENT_CUSTOMER_TOKEN",
    )
    url = values["LOANS_DEPLOYMENT_PRODUCTS_URL"]
    token = values["LOANS_DEPLOYMENT_CUSTOMER_TOKEN"]
    assert url.startswith("https://")
    request_count = int(os.getenv("LOANS_DEPLOYMENT_LOAD_REQUESTS", "20"))
    concurrency = int(os.getenv("LOANS_DEPLOYMENT_LOAD_CONCURRENCY", "4"))
    assert 1 <= request_count <= 500
    assert 1 <= concurrency <= 50

    first = _authorized_get(url, token)
    assert first.headers.get("Content-Type", "").startswith("application/json")
    serialized = first.text.lower()
    for forbidden in (
        "raw_transaction",
        "idempotency_key",
        "private_key",
        "mongodb://",
        "traceback",
    ):
        assert forbidden not in serialized

    invalid = requests.get(
        f"{url.rstrip('/')}/not-a-valid-object-id/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    assert invalid.status_code in {400, 404}
    assert invalid.headers.get("Content-Type", "").startswith("application/json")
    invalid_payload = invalid.text.lower()
    assert "traceback" not in invalid_payload
    assert "mongodb://" not in invalid_payload

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        responses = list(
            executor.map(lambda _: _authorized_get(url, token), range(request_count))
        )
    assert len(responses) == request_count


def test_deployed_metrics_expose_every_loans_metric_family():
    values = _opt_in(
        "RUN_LOANS_METRICS_DEPLOYMENT_TESTS", "LOANS_DEPLOYMENT_METRICS_URL"
    )
    response = requests.get(values["LOANS_DEPLOYMENT_METRICS_URL"], timeout=15)
    response.raise_for_status()
    for metric in (
        "loans_requests_total",
        "loans_request_duration_seconds",
        "loans_domain_events_total",
        "loans_notification_delivery_total",
        "loans_backlog",
        "loans_oldest_backlog_age_seconds",
        "loans_job_last_success_timestamp_seconds",
        "loans_reconciliation_integrity_gaps",
    ):
        assert metric in response.text
