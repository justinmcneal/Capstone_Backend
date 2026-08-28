"""Low-cardinality operational metrics for Notifications."""

try:
    from prometheus_client import Counter, Gauge, Histogram

    NOTIFICATION_REQUESTS = Counter(
        "notifications_requests_total",
        "Notifications REST request outcomes",
        ("method", "outcome"),
    )
    NOTIFICATION_REQUEST_LATENCY = Histogram(
        "notifications_request_duration_seconds",
        "Notifications REST request latency",
        ("method",),
    )
    NOTIFICATION_DELIVERY_OUTCOMES = Counter(
        "notifications_delivery_outcomes_total",
        "Durable delivery outcomes",
        ("outcome",),
    )
    NOTIFICATION_CHANNEL_OUTCOMES = Counter(
        "notifications_channel_outcomes_total",
        "Notification channel attempt outcomes",
        ("channel", "outcome"),
    )
    NOTIFICATION_TOKEN_INVALIDATIONS = Counter(
        "notifications_token_invalidations_total",
        "Push registrations permanently invalidated by provider outcome",
    )
    NOTIFICATION_BROADCAST_OUTCOMES = Counter(
        "notifications_websocket_broadcasts_total",
        "WebSocket broadcast publication outcomes",
        ("kind", "outcome"),
    )
    NOTIFICATION_WS_CONNECTIONS = Counter(
        "notifications_websocket_connections_total",
        "WebSocket connection outcomes",
        ("outcome",),
    )
    NOTIFICATION_WS_ACTIONS = Counter(
        "notifications_websocket_actions_total",
        "WebSocket action outcomes",
        ("action", "outcome"),
    )
    NOTIFICATION_WS_ACTIVE = Gauge(
        "notifications_websocket_active_connections",
        "Active WebSocket connections in this ASGI process",
    )
    NOTIFICATION_DELIVERY_BACKLOG = Gauge(
        "notifications_delivery_backlog",
        "Shared notification delivery rows by state",
        ("status",),
    )
    NOTIFICATION_DELIVERY_OLDEST_AGE = Gauge(
        "notifications_delivery_oldest_age_seconds",
        "Age of the oldest retryable shared notification delivery",
    )
    NOTIFICATION_METRICS_LAST_SUCCESS = Gauge(
        "notifications_metrics_last_success_timestamp_seconds",
        "Unix timestamp of the last successful Notifications metrics collection",
    )
except (ImportError, ValueError):
    NOTIFICATION_REQUESTS = None
    NOTIFICATION_REQUEST_LATENCY = None
    NOTIFICATION_DELIVERY_OUTCOMES = None
    NOTIFICATION_CHANNEL_OUTCOMES = None
    NOTIFICATION_TOKEN_INVALIDATIONS = None
    NOTIFICATION_BROADCAST_OUTCOMES = None
    NOTIFICATION_WS_CONNECTIONS = None
    NOTIFICATION_WS_ACTIONS = None
    NOTIFICATION_WS_ACTIVE = None
    NOTIFICATION_DELIVERY_BACKLOG = None
    NOTIFICATION_DELIVERY_OLDEST_AGE = None
    NOTIFICATION_METRICS_LAST_SUCCESS = None


def increment(metric, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).inc()


def decrement(metric):
    if metric is not None:
        metric.dec()


def observe(metric, value, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).observe(value)


def set_gauge(metric, value, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).set(value)
