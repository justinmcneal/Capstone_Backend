# Notifications Metrics and Deployment Patterns

This document describes deployment options for exposing Prometheus metrics for the notifications/email subsystem.

Why metrics?
- Track email send success/failure rates
- Alert on sustained failures or delivery regressions
- Capacity planning (rate of sends -> threadpool sizing)

What the code exposes
- `notifications_email_send_success_total` — successful sends (EmailSender)
- `notifications_email_send_failure_total` — failed sends (EmailSender)
- `notifications_email_task_success_total` — successful async sends (Celery task)
- `notifications_email_task_failure_total` — failed async sends (Celery task)

Quick options to expose metrics

1) WSGI-mounted `/metrics/` endpoint (recommended)

- The project now mounts Prometheus's `make_wsgi_app()` behind `/metrics/` in `config/wsgi.py`.
- Enable metrics with either:

```py
PROMETHEUS_METRICS_ENABLED = True
```

or by creating the runtime flag file with the management command below.

- This is the simplest option for a single unified endpoint because Django and Prometheus share the same host/port.

2) Built-in HTTP server (optional)

- Enable via Django settings:

```py
PROMETHEUS_METRICS_ENABLED = True
PROMETHEUS_METRICS_HTTP_SERVER_ENABLED = True
PROMETHEUS_METRICS_HTTP_SERVER_PORT = 8001
```

- The project includes `config/prometheus_metrics.py` which will start an HTTP server
  on import when metrics are enabled and `PROMETHEUS_METRICS_HTTP_SERVER_ENABLED` is True.
  Import it from `config/wsgi.py` or `config/asgi.py` (already wired).

- This is simple, works in development, and is suitable for single-process deployments.

3) Kubernetes production patterns

- Sidecar exporter: run a small sidecar that exposes application metrics and scrapes via HTTP.
- Scrape application port directly if running a single worker process with the HTTP server enabled.
- For multiple replicas, make sure metrics are scraped per-pod (don't aggregate unless using a pushgateway).

4) Celery workers

- Celery tasks increment task-level counters; ensure that Prometheus scraping includes your worker processes or they export metrics to a shared endpoint.
- Alternatively, use a pushgateway if scraping workers is not possible (less preferred).

Notes & Caveats
- The included startup helper is intentionally guarded: if `prometheus-client` is not installed, it will no-op.
- The WSGI `/metrics/` endpoint is the lightweight default for a single app instance.
- The optional HTTP server is not suitable for high-scale multi-process deployments without per-process scraping considerations.
- Consider using `django-prometheus` or an application-wide metrics strategy for full coverage of Django internals.

Examples

- Example to start metrics server from `config/wsgi.py` (already wired):

```py
# config/wsgi.py
from . import prometheus_metrics  # starts server when enabled
```

- Management command:

```bash
python manage.py toggle_prometheus enable --url
python manage.py toggle_prometheus status --url
python manage.py toggle_prometheus disable --url
```

The command toggles the runtime flag file without editing settings or restarting the app.

- The URL output is resolved from `PROMETHEUS_METRICS_URL` or `PROMETHEUS_METRICS_BASE_URL` if set,
  otherwise it defaults to `http://127.0.0.1:8000/metrics/`.

- Example systemd unit that runs the app and relies on the metrics port being open:

```
[Unit]
Description=Capstone Backend
After=network.target

[Service]
User=www-data
WorkingDirectory=/srv/capstone
ExecStart=/srv/capstone/venv/bin/gunicorn config.wsgi:application --bind 0.0.0.0:8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then configure Prometheus to scrape `http://<host>:8000/metrics/` (or your deployed host URL).

Troubleshooting
- If you enable `PROMETHEUS_METRICS_ENABLED` and don't see metrics:
  - Ensure `prometheus-client` is installed in the environment.
  - Verify the port via `PROMETHEUS_METRICS_PORT` and check firewall rules.
  - Check application logs for startup errors related to the metrics server.

Security
- Metrics endpoints often contain operational data; restrict access with firewall rules or internal-only network policies.
- Avoid exposing metrics publicly.

Contact
- For questions about metrics design and alerting thresholds, contact the platform/infra team.
