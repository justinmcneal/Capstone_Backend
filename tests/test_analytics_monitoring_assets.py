"""Repository-level validation for deployable Analytics monitoring assets."""

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "monitoring" / "analytics" / "prometheus-rules.yml"
DASHBOARD_PATH = ROOT / "monitoring" / "analytics" / "grafana-dashboard.json"

EXPECTED_METRICS = {
    "analytics_requests_total",
    "analytics_request_duration_seconds_bucket",
    "analytics_response_size_bytes_bucket",
    "analytics_audit_write_failures_total",
    "analytics_audit_replays_total",
    "analytics_audit_failure_backlog",
    "analytics_audit_failure_oldest_age_seconds",
    "analytics_audit_integrity_gaps",
}


def test_analytics_prometheus_rules_are_parseable_and_have_runbooks():
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    groups = rules["groups"]
    alerts = [rule for group in groups for rule in group["rules"] if "alert" in rule]
    assert {rule["alert"] for rule in alerts} == {
        "AnalyticsMetricsMissing",
        "AnalyticsAuditRecoveryBacklog",
        "AnalyticsAuditRecoveryOldestItem",
        "AnalyticsAuditIntegrityFinding",
        "AnalyticsRequestErrorRatioHigh",
        "AnalyticsRequestLatencyHigh",
    }
    assert all(rule["labels"]["service"] == "analytics" for rule in alerts)
    assert all(rule["annotations"].get("runbook") for rule in alerts)


def test_analytics_dashboard_is_parseable_and_covers_every_metric_family():
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    assert dashboard["uid"] == "capstone-analytics"
    expressions = "\n".join(
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    )
    assert EXPECTED_METRICS.issubset(
        {metric for metric in EXPECTED_METRICS if metric in expressions}
    )
    assert len({panel["id"] for panel in dashboard["panels"]}) == len(
        dashboard["panels"]
    )
