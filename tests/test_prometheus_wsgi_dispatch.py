from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from config.wsgi import _MetricsDispatcher


class PrometheusWsgiDispatchTests(SimpleTestCase):
    def test_metrics_path_dispatches_to_metrics_app(self):
        called = {}

        def django_app(environ, start_response):
            called["django"] = True
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b"django"]

        def metrics_app(environ, start_response):
            called["metrics"] = True
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b"metrics"]

        dispatcher = _MetricsDispatcher(django_app, metrics_app)

        with patch("config.wsgi.is_metrics_enabled", return_value=True):
            status_headers = {}

            def start_response(status, headers):
                status_headers["status"] = status
                status_headers["headers"] = headers

            response = b"".join(
                dispatcher({"PATH_INFO": "/metrics/"}, start_response)
            )

        self.assertEqual(response, b"metrics")
        self.assertTrue(called.get("metrics"))
        self.assertNotIn("django", called)
        self.assertEqual(status_headers["status"], "200 OK")

    def test_non_metrics_path_dispatches_to_django_app(self):
        called = {}

        def django_app(environ, start_response):
            called["django"] = True
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b"django"]

        dispatcher = _MetricsDispatcher(django_app, None)

        with patch("config.wsgi.is_metrics_enabled", return_value=True):
            status_headers = {}

            def start_response(status, headers):
                status_headers["status"] = status
                status_headers["headers"] = headers

            response = b"".join(
                dispatcher({"PATH_INFO": "/api/health/"}, start_response)
            )

        self.assertEqual(response, b"django")
        self.assertTrue(called.get("django"))
        self.assertEqual(status_headers["status"], "200 OK")
