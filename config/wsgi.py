"""
WSGI config for capstone_backend project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os
from typing import Callable

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application

from config.prometheus_metrics import is_metrics_enabled

from . import prometheus_metrics  # noqa: F401 - optional startup side-effects

try:
	from prometheus_client import make_wsgi_app
except Exception:
	make_wsgi_app = None


django_application = get_wsgi_application()


def _not_found(environ, start_response):
	start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
	return [b"not found"]


class _MetricsDispatcher:
	def __init__(self, app: Callable, metrics_app: Callable | None) -> None:
		self.app = app
		self.metrics_app = metrics_app

	def __call__(self, environ, start_response):
		path_info = environ.get("PATH_INFO", "")
		if path_info.rstrip("/") == "/metrics":
			if self.metrics_app is None or not is_metrics_enabled():
				return _not_found(environ, start_response)
			return self.metrics_app(environ, start_response)
		return self.app(environ, start_response)


application = _MetricsDispatcher(django_application, make_wsgi_app() if make_wsgi_app else None)
