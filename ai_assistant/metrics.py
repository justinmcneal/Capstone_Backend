"""Low-cardinality metrics for AI requests, tools, and audit persistence."""

try:
    from prometheus_client import Counter, Gauge, Histogram

    AI_REQUESTS = Counter(
        "ai_assistant_requests_total",
        "AI Assistant HTTP request outcomes",
        ("endpoint", "outcome"),
    )
    AI_REQUEST_LATENCY = Histogram(
        "ai_assistant_request_duration_seconds",
        "AI Assistant HTTP request latency",
        ("endpoint",),
    )
    AI_TOOL_CALLS = Counter(
        "ai_assistant_tool_calls_total",
        "AI Assistant tool-call outcomes",
        ("tool", "outcome"),
    )
    AI_TOOL_LATENCY = Histogram(
        "ai_assistant_tool_duration_seconds",
        "AI Assistant tool-call latency",
        ("tool",),
    )
    AI_TOOL_BUDGET_REJECTIONS = Counter(
        "ai_assistant_tool_budget_rejections_total",
        "AI Assistant tool calls rejected by a shared budget",
        ("window",),
    )
    AI_AUDIT_WRITE_FAILURES = Counter(
        "ai_assistant_audit_write_failures_total",
        "AI Assistant metadata audit write failures",
    )
    AI_PERSISTENCE_FAILURES = Counter(
        "ai_assistant_persistence_failures_total",
        "AI Assistant interaction persistence failures",
        ("operation",),
    )
    AI_TOKENS = Counter(
        "ai_assistant_tokens_total",
        "Provider-reported AI tokens",
        ("provider",),
    )
    AI_ACTIVE_STREAMS = Gauge(
        "ai_assistant_active_streams",
        "AI Assistant streams currently being consumed",
    )
    AI_PROVIDER_REQUESTS = Counter(
        "ai_assistant_provider_requests_total",
        "AI provider interaction outcomes",
        ("provider", "outcome"),
    )
    AI_PROVIDER_LATENCY = Histogram(
        "ai_assistant_provider_duration_seconds",
        "End-to-end AI provider interaction latency",
        ("provider", "operation"),
    )
    AI_STREAM_LIMIT_CANCELLATIONS = Counter(
        "ai_assistant_stream_limit_cancellations_total",
        "AI streams cancelled by an output or duration limit",
        ("provider", "limit"),
    )
except (ImportError, ValueError):
    AI_REQUESTS = None
    AI_REQUEST_LATENCY = None
    AI_TOOL_CALLS = None
    AI_TOOL_LATENCY = None
    AI_TOOL_BUDGET_REJECTIONS = None
    AI_AUDIT_WRITE_FAILURES = None
    AI_PERSISTENCE_FAILURES = None
    AI_TOKENS = None
    AI_ACTIVE_STREAMS = None
    AI_PROVIDER_REQUESTS = None
    AI_PROVIDER_LATENCY = None
    AI_STREAM_LIMIT_CANCELLATIONS = None


def increment(metric, amount=1, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).inc(amount)


def decrement(metric, amount=1):
    if metric is not None:
        metric.dec(amount)


def observe(metric, value, **labels):
    if metric is not None:
        (metric.labels(**labels) if labels else metric).observe(value)
