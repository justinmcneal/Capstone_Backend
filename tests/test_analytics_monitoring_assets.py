"""Repository-level validation for deployable Analytics monitoring assets."""

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "monitoring" / "analytics" / "prometheus-rules.yml"
DASHBOARD_PATH = ROOT / "monitoring" / "analytics" / "grafana-dashboard.json"
RULE_TEST_PATH = ROOT / "monitoring" / "analytics" / "prometheus-rules.test.yml"
SMOKE_CONFIG_PATH = ROOT / "monitoring" / "analytics" / "prometheus-smoke.yml"
GRAFANA_PROVISIONING_ROOT = ROOT / "monitoring" / "grafana" / "provisioning"

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
    test_definition = yaml.safe_load(RULE_TEST_PATH.read_text(encoding="utf-8"))
    assert len(test_definition["tests"]) == 3
    smoke_config = yaml.safe_load(SMOKE_CONFIG_PATH.read_text(encoding="utf-8"))
    assert smoke_config["scrape_configs"][0]["job_name"] == "capstone-analytics-smoke"


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
    assert all(
        panel["datasource"]["uid"] == "capstone-prometheus"
        for panel in dashboard["panels"]
    )


def test_grafana_provisioning_connects_prometheus_and_dashboard_directory():
    datasource = yaml.safe_load(
        (GRAFANA_PROVISIONING_ROOT / "datasources" / "prometheus.yml").read_text(
            encoding="utf-8"
        )
    )["datasources"][0]
    provider = yaml.safe_load(
        (GRAFANA_PROVISIONING_ROOT / "dashboards" / "analytics.yml").read_text(
            encoding="utf-8"
        )
    )["providers"][0]
    assert datasource["uid"] == "capstone-prometheus"
    assert datasource["url"] == "http://127.0.0.1:9090"
    assert provider["options"]["path"] == "$ANALYTICS_DASHBOARD_PATH"
