"""Prometheus metrics helpers for runtime toggles and optional HTTP server startup.

Importing this module is safe. It only starts an HTTP server when both metrics
are enabled and `PROMETHEUS_METRICS_HTTP_SERVER_ENABLED` is true.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("prometheus.startup")

try:
    from django.conf import settings
    from prometheus_client import start_http_server  # type: ignore[import-not-found]
except Exception:
    # If Django or prometheus_client is not available at import time, do nothing.
    settings = None
    start_http_server = None


def get_runtime_flag_file() -> str:
    """Return the path to the runtime metrics flag file."""
    default_flag = Path(__file__).resolve().parent.parent / ".prometheus_metrics_enabled"
    if settings is None:
        return str(default_flag)
    return getattr(settings, "PROMETHEUS_METRICS_RUNTIME_FLAG_FILE", str(default_flag))


def is_metrics_enabled() -> bool:
    """Return whether metrics are enabled via settings or runtime flag."""
    if settings is None:
        return False
    enabled = getattr(settings, "PROMETHEUS_METRICS_ENABLED", False)
    runtime_enabled = Path(get_runtime_flag_file()).exists()
    return bool(enabled or runtime_enabled)


def get_metrics_url() -> str:
    """Resolve the public metrics URL for the current environment."""
    if settings is not None:
        explicit_url = getattr(settings, "PROMETHEUS_METRICS_URL", None)
        if explicit_url:
            return explicit_url

        base_url = getattr(settings, "PROMETHEUS_METRICS_BASE_URL", None)
        if base_url:
            return f"{str(base_url).rstrip('/')}/metrics/"

    env_url = os.environ.get("PROMETHEUS_METRICS_URL")
    if env_url:
        return env_url

    env_base = os.environ.get("PROMETHEUS_METRICS_BASE_URL")
    if env_base:
        return f"{env_base.rstrip('/')}/metrics/"

    return "http://127.0.0.1:8000/metrics/"


def start_metrics_server_if_enabled() -> None:
    if settings is None or start_http_server is None:
        logger.debug("Prometheus client or Django settings unavailable; skipping metrics server startup")
        return

    if not is_metrics_enabled():
        logger.debug("Prometheus metrics disabled (settings or runtime flag not set)")
        return

    if not getattr(settings, "PROMETHEUS_METRICS_HTTP_SERVER_ENABLED", False):
        logger.debug("Prometheus HTTP server disabled; using WSGI /metrics endpoint only")
        return

    port = getattr(
        settings,
        "PROMETHEUS_METRICS_HTTP_SERVER_PORT",
        int(os.environ.get("PROMETHEUS_METRICS_HTTP_SERVER_PORT", 8001)),
    )

    try:
        # start_http_server is non-blocking and returns immediately
        start_http_server(port)
        logger.info("Prometheus metrics HTTP server started on port %s", port)
    except Exception:
        logger.exception("Failed to start Prometheus metrics HTTP server")


# Side-effect import: start when module is imported from WSGI/ASGI startup
start_metrics_server_if_enabled()
