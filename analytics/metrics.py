"""Low-cardinality Analytics request and audit-pipeline metrics."""

try:
    from prometheus_client import Counter, Gauge, Histogram

    ANALYTICS_REQUESTS = Counter(
        "analytics_requests_total",
        "Analytics request outcomes",
        ("endpoint", "outcome"),
    )
    ANALYTICS_REQUEST_LATENCY = Histogram(
        "analytics_request_duration_seconds",
        "Analytics request latency",
        ("endpoint",),
    )
    ANALYTICS_RESPONSE_SIZE = Histogram(
        "analytics_response_size_bytes",
        "Serialized Analytics response size",
        ("endpoint",),
        buckets=(256, 1024, 4096, 16384, 65536, 262144, float("inf")),
    )
    ANALYTICS_AUDIT_WRITE_FAILURES = Counter(
        "analytics_audit_write_failures_total",
        "Audit writes queued after a persistence failure",
        ("domain",),
    )
    ANALYTICS_AUDIT_REPLAYS = Counter(
        "analytics_audit_replays_total",
        "Audit recovery replay outcomes",
        ("outcome",),
    )
    ANALYTICS_AUDIT_BACKLOG = Gauge(
        "analytics_audit_failure_backlog",
        "Unresolved audit writes awaiting recovery",
    )
    ANALYTICS_AUDIT_OLDEST_AGE = Gauge(
        "analytics_audit_failure_oldest_age_seconds",
        "Age of the oldest unresolved audit write",
    )
    ANALYTICS_INTEGRITY_GAPS = Gauge(
        "analytics_audit_integrity_gaps",
        "Audit integrity inventory findings",
        ("kind",),
    )
except (ImportError, ValueError):
    ANALYTICS_REQUESTS = None
    ANALYTICS_REQUEST_LATENCY = None
    ANALYTICS_RESPONSE_SIZE = None
    ANALYTICS_AUDIT_WRITE_FAILURES = None
    ANALYTICS_AUDIT_REPLAYS = None
    ANALYTICS_AUDIT_BACKLOG = None
    ANALYTICS_AUDIT_OLDEST_AGE = None
    ANALYTICS_INTEGRITY_GAPS = None


def increment(metric, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).inc()


def observe(metric, value, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).observe(value)


def set_gauge(metric, value, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).set(value)
