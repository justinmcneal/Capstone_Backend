"""Explicitly opted-in, non-secret Analytics deployment integration probes."""

import os
import uuid

import pytest
import requests
from pymongo import MongoClient
from redis import Redis


pytestmark = pytest.mark.deployment_integration


def _opt_in(flag, *required):
    values = {name: (os.getenv(name, "") or "").strip() for name in required}
    if os.getenv(flag) != "1" or not all(values.values()):
        pytest.skip(
            f"Set {flag}=1 and {', '.join(required)} for the approved target"
        )
    return values


def test_runtime_mongodb_identity_is_least_privilege():
    values = _opt_in(
        "RUN_ANALYTICS_DEPLOYMENT_MONGO_TESTS",
        "ANALYTICS_DEPLOYMENT_MONGO_URI",
        "ANALYTICS_DEPLOYMENT_MONGO_DB",
    )
    client = MongoClient(
        values["ANALYTICS_DEPLOYMENT_MONGO_URI"], serverSelectionTimeoutMS=5000
    )
    try:
        status = client.admin.command({"connectionStatus": 1, "showPrivileges": True})
    finally:
        client.close()

    auth = status.get("authInfo", {})
    roles = {item.get("role") for item in auth.get("authenticatedUserRoles", [])}
    privileges = auth.get("authenticatedUserPrivileges", [])
    actions = {
        action
        for privilege in privileges
        for action in privilege.get("actions", [])
    }
    forbidden_roles = {"root", "dbAdminAnyDatabase", "userAdminAnyDatabase"}
    forbidden_actions = {
        "createUser",
        "dropAllUsersFromDatabase",
        "dropDatabase",
        "grantRole",
        "revokeRole",
        "setFeatureCompatibilityVersion",
        "shutdown",
    }
    assert not roles.intersection(forbidden_roles)
    assert not actions.intersection(forbidden_actions)
    assert any(
        "find" in privilege.get("actions", [])
        and privilege.get("resource", {}).get("db")
        == values["ANALYTICS_DEPLOYMENT_MONGO_DB"]
        for privilege in privileges
    )


def test_two_clients_share_the_redis_throttle_counter():
    values = _opt_in(
        "RUN_ANALYTICS_DEPLOYMENT_REDIS_TESTS", "ANALYTICS_DEPLOYMENT_REDIS_URL"
    )
    key = f"analytics:release-probe:{uuid.uuid4().hex}"
    first = Redis.from_url(values["ANALYTICS_DEPLOYMENT_REDIS_URL"])
    second = Redis.from_url(values["ANALYTICS_DEPLOYMENT_REDIS_URL"])
    try:
        assert first.set(key, 0, ex=60, nx=True)
        assert first.incr(key) == 1
        assert second.incr(key) == 2
        assert first.ttl(key) > 0
    finally:
        first.delete(key)
        first.close()
        second.close()


def test_deployed_metrics_endpoint_exposes_all_analytics_families():
    values = _opt_in(
        "RUN_ANALYTICS_DEPLOYMENT_HTTP_TESTS",
        "ANALYTICS_DEPLOYMENT_METRICS_URL",
    )
    try:
        response = requests.get(
            values["ANALYTICS_DEPLOYMENT_METRICS_URL"], timeout=10
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        pytest.fail(f"Metrics probe failed: {type(exc).__name__}")
    payload = response.text
    for metric in (
        "analytics_requests_total",
        "analytics_request_duration_seconds",
        "analytics_response_size_bytes",
        "analytics_audit_write_failures_total",
        "analytics_audit_replays_total",
        "analytics_audit_failure_backlog",
        "analytics_audit_failure_oldest_age_seconds",
        "analytics_audit_integrity_gaps",
    ):
        assert metric in payload


def test_proxy_preserves_https_and_sanitized_health_contract():
    values = _opt_in(
        "RUN_ANALYTICS_DEPLOYMENT_HTTP_TESTS",
        "ANALYTICS_DEPLOYMENT_HEALTH_URL",
    )
    try:
        response = requests.get(
            values["ANALYTICS_DEPLOYMENT_HEALTH_URL"],
            headers={"X-Forwarded-Proto": "https"},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        pytest.fail(f"Health probe failed: {type(exc).__name__}")
    assert response.url.startswith("https://")
    body = response.json()
    serialized = str(body).lower()
    assert "mongodb://" not in serialized
    assert "redis://" not in serialized
    assert "password" not in serialized
