"""Optional low-cardinality Prometheus metrics for Profiles operations."""

try:
    from prometheus_client import Counter, Gauge

    PROFILE_AUDIT_FAILURES = Counter(
        "profiles_audit_write_failures_total",
        "Profile audit records that could not be written",
        ("action",),
    )
    PROFILE_OPERATIONS = Counter(
        "profiles_operations_total",
        "Security and customer workflow operations in Profiles",
        ("operation", "outcome"),
    )
    PROFILE_RISK_EVENTS = Counter(
        "profiles_risk_score_events_total",
        "Risk-score lifecycle outcomes",
        ("outcome",),
    )
    PROFILE_RISK_BACKLOG = Gauge(
        "profiles_risk_score_backlog",
        "Alternative-data records awaiting risk-score recovery",
        ("status",),
    )
    PROFILE_DUPLICATE_RECORDS = Gauge(
        "profiles_duplicate_records",
        "Extra profile records sharing a canonical customer identifier",
        ("collection",),
    )
    PROFILE_UNPROTECTED_FIELDS = Gauge(
        "profiles_unprotected_sensitive_fields",
        "Populated declared profile fields that are not encrypted",
        ("collection",),
    )
    PROFILE_AUDIT_BACKLOG = Gauge(
        "profiles_audit_failure_backlog",
        "Unresolved profile audit writes awaiting reconciliation",
    )
    PROFILE_REVIEW_BACKLOG = Gauge(
        "profiles_risk_review_backlog",
        "Profile risk reviews by active state",
        ("status",),
    )
except (ImportError, ValueError):
    PROFILE_AUDIT_FAILURES = None
    PROFILE_OPERATIONS = None
    PROFILE_RISK_EVENTS = None
    PROFILE_RISK_BACKLOG = None
    PROFILE_DUPLICATE_RECORDS = None
    PROFILE_UNPROTECTED_FIELDS = None
    PROFILE_AUDIT_BACKLOG = None
    PROFILE_REVIEW_BACKLOG = None


def increment(metric, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).inc()


def set_gauge(metric, value, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).set(value)
