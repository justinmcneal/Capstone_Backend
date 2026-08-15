"""Low-cardinality Prometheus metrics for the Loans domain."""

try:
    from prometheus_client import Counter, Gauge, Histogram

    LOAN_REQUESTS = Counter(
        "loans_requests_total",
        "Loans API request outcomes",
        ("scope", "method", "outcome"),
    )
    LOAN_REQUEST_LATENCY = Histogram(
        "loans_request_duration_seconds",
        "Loans API request latency",
        ("scope", "method"),
    )
    LOAN_DOMAIN_EVENTS = Counter(
        "loans_domain_events_total",
        "Loan transition and settlement outcomes",
        ("operation", "outcome"),
    )
    LOAN_NOTIFICATION_OUTCOMES = Counter(
        "loans_notification_delivery_total",
        "Loan notification delivery outcomes",
        ("event", "outcome"),
    )
    LOAN_BACKLOG = Gauge(
        "loans_backlog",
        "Loan operational backlog by queue and state",
        ("queue", "status"),
    )
    LOAN_OLDEST_AGE = Gauge(
        "loans_oldest_backlog_age_seconds",
        "Age of the oldest loan backlog item",
        ("queue",),
    )
    LOAN_JOB_LAST_SUCCESS = Gauge(
        "loans_job_last_success_timestamp_seconds",
        "Unix timestamp of the last completed Loans background scan",
        ("job",),
    )
    LOAN_INTEGRITY_GAPS = Gauge(
        "loans_reconciliation_integrity_gaps",
        "Bounded loan/schedule reconciliation findings",
        ("kind",),
    )
except (ImportError, ValueError):
    LOAN_REQUESTS = None
    LOAN_REQUEST_LATENCY = None
    LOAN_DOMAIN_EVENTS = None
    LOAN_NOTIFICATION_OUTCOMES = None
    LOAN_BACKLOG = None
    LOAN_OLDEST_AGE = None
    LOAN_JOB_LAST_SUCCESS = None
    LOAN_INTEGRITY_GAPS = None


def increment(metric, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).inc()


def observe(metric, value, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).observe(value)


def set_gauge(metric, value, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).set(value)
