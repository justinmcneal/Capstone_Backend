import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import yaml
from django.conf import settings
from django.core.cache import cache

from ai_assistant.models import AIActivityEvent
from ai_assistant.services.llm_service import GroqService
from ai_assistant.services.tool_safety import (
    RateLimitConfig,
    ToolCallAuditor,
    ToolParameterValidator,
    ToolRateLimiter,
    get_tool_cost,
    safe_execute_tool,
)

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "monitoring" / "ai_assistant" / "prometheus-rules.yml"
DASHBOARD_PATH = ROOT / "monitoring" / "ai_assistant" / "grafana-dashboard.json"
PROVISIONING_PATH = (
    ROOT / "monitoring" / "grafana" / "provisioning" / "dashboards"
    / "ai-assistant.yml"
)
SMOKE_PATH = ROOT / "monitoring" / "ai_assistant" / "prometheus-smoke.yml"


def test_atomic_reservation_never_exceeds_shared_window():
    cache.clear()
    limiter = ToolRateLimiter(
        RateLimitConfig(max_calls_per_minute=5, max_calls_per_hour=100)
    )
    customer_id = f"atomic-{uuid.uuid4()}"
    barrier = threading.Barrier(20)

    def reserve():
        barrier.wait()
        return limiter.reserve_call(customer_id, "get_profile_status")["allowed"]

    with ThreadPoolExecutor(max_workers=20) as executor:
        outcomes = list(executor.map(lambda _: reserve(), range(20)))

    assert sum(outcomes) == 5
    assert limiter.get_usage_stats(customer_id)["minute"]["used"] == 5


def test_failed_validation_consumes_reserved_budget():
    cache.clear()
    limiter = ToolRateLimiter(
        RateLimitConfig(
            max_calls_per_minute=2,
            max_calls_per_hour=2,
            tool_costs={"get_payment_history": 1},
        )
    )
    with (
        patch("ai_assistant.services.tool_safety.rate_limiter", limiter),
        patch.object(ToolCallAuditor, "log_call"),
    ):
        first = safe_execute_tool(
            "get_payment_history",
            {"limit": "invalid"},
            "customer-validation",
        )
        second = safe_execute_tool(
            "get_payment_history",
            {"limit": "invalid"},
            "customer-validation",
        )
        third = safe_execute_tool(
            "get_payment_history",
            {"limit": "invalid"},
            "customer-validation",
        )

    assert first["success"] is False
    assert second["success"] is False
    assert third["rate_limited"] is True


def test_dashboard_tool_has_explicit_schema_and_expensive_cost():
    assert ToolParameterValidator.validate("get_customer_dashboard", {}) == {}
    assert get_tool_cost("get_customer_dashboard") == 3


def test_tool_audit_is_durable_metadata_only():
    request_id = str(uuid.uuid4())
    ToolCallAuditor.log_call(
        customer_id="customer-sensitive",
        tool_name="get_profile_status",
        params={"secret": "must-not-persist"},
        success=False,
        duration_ms=12,
        error="database host and customer payload must not persist",
        request_id=request_id,
        outcome="execution_error",
        cost=1,
    )

    raw = settings.MONGODB[AIActivityEvent.collection_name].find_one({})
    assert raw["request_id"] == request_id
    assert raw["tool"] == "get_profile_status"
    assert raw["outcome"] == "execution_error"
    assert len(raw["subject_index"]) == 64
    assert "customer_id" not in raw
    assert "params" not in raw
    assert "error" not in raw
    assert "message" not in raw
    assert "response" not in raw
    assert ToolCallAuditor.get_recent_calls("customer-sensitive")[0]["request_id"] == request_id


def test_unknown_tool_is_normalized_in_audit_and_metrics_labels():
    ToolCallAuditor.log_call(
        customer_id="customer-unknown",
        tool_name="attacker-controlled-tool-name",
        params={},
        success=False,
        duration_ms=0,
        outcome="execution_error",
    )
    raw = settings.MONGODB[AIActivityEvent.collection_name].find_one({})
    assert raw["tool"] == "unknown"


def test_parallel_tools_receive_request_correlation_id():
    service = object.__new__(GroqService)
    request_id = str(uuid.uuid4())
    calls = [
        {
            "id": "call-1",
            "function": {"name": "get_profile_status", "arguments": "{}"},
        }
    ]
    with patch(
        "ai_assistant.services.tool_safety.safe_execute_tool",
        return_value={"success": True, "result": json.dumps({"ok": True})},
    ) as execute:
        result = service._execute_tools_parallel(
            calls,
            "customer-correlation",
            request_id=request_id,
        )

    assert result[0][3] is True
    execute.assert_called_once_with(
        "get_profile_status",
        {},
        "customer-correlation",
        request_id=request_id,
    )


def test_ai_monitoring_assets_cover_every_metric_family():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    alerts = [
        rule
        for group in rules["groups"]
        for rule in group["rules"]
        if "alert" in rule
    ]
    assert alerts
    assert all(rule["labels"]["service"] == "ai-assistant" for rule in alerts)
    assert all(rule["annotations"].get("runbook") for rule in alerts)
    smoke = yaml.safe_load(SMOKE_PATH.read_text(encoding="utf-8"))
    assert smoke["scrape_configs"][0]["job_name"] == "capstone-ai-assistant-smoke"

    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    expressions = "\n".join(
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    )
    expected = {
        "ai_assistant_requests_total",
        "ai_assistant_request_duration_seconds_bucket",
        "ai_assistant_tool_calls_total",
        "ai_assistant_tool_duration_seconds_bucket",
        "ai_assistant_tool_budget_rejections_total",
        "ai_assistant_audit_write_failures_total",
        "ai_assistant_persistence_failures_total",
        "ai_assistant_tokens_total",
        "ai_assistant_active_streams",
        "ai_assistant_provider_requests_total",
        "ai_assistant_provider_duration_seconds_bucket",
    }
    assert all(metric in expressions for metric in expected)
    assert dashboard["uid"] == "capstone-ai-assistant"

    provider = yaml.safe_load(PROVISIONING_PATH.read_text(encoding="utf-8"))[
        "providers"
    ][0]
    assert provider["options"]["path"] == "$AI_ASSISTANT_DASHBOARD_PATH"
