"""Low-cardinality Prometheus metrics for document operations."""

try:
    from prometheus_client import Counter, Gauge

    DOCUMENT_OPERATIONS = Counter(
        "documents_operations_total",
        "Document workflow outcomes",
        ("operation", "outcome"),
    )
    DOCUMENT_URL_ERRORS = Counter(
        "documents_url_generation_errors_total",
        "Failed private document URL generation attempts",
    )
    DOCUMENT_BACKLOG = Gauge(
        "documents_backlog",
        "Document operational backlog by queue and state",
        ("queue", "status"),
    )
    DOCUMENT_OLDEST_AGE_SECONDS = Gauge(
        "documents_oldest_backlog_age_seconds",
        "Age of the oldest document backlog item",
        ("queue",),
    )
except (ImportError, ValueError):
    DOCUMENT_OPERATIONS = None
    DOCUMENT_URL_ERRORS = None
    DOCUMENT_BACKLOG = None
    DOCUMENT_OLDEST_AGE_SECONDS = None


def increment(metric, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).inc()


def set_gauge(metric, value, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).set(value)
