from __future__ import annotations

import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class TogglePrometheusCommandTests(SimpleTestCase):
    def test_enable_status_disable_and_url_output(self):
        with TemporaryDirectory() as tmpdir:
            flag_file = Path(tmpdir) / ".prometheus_metrics_enabled"
            metrics_url = "http://example.com:9000/metrics/"

            with override_settings(
                PROMETHEUS_METRICS_RUNTIME_FLAG_FILE=str(flag_file),
            ):
                with patch.dict(os.environ, {"PROMETHEUS_METRICS_URL": metrics_url}, clear=False):
                    stdout = io.StringIO()
                    call_command("toggle_prometheus", "status", stdout=stdout)
                    status_output = stdout.getvalue()
                    self.assertIn("Present: False", status_output)
                    self.assertIn(str(flag_file), status_output)

                    stdout = io.StringIO()
                    call_command("toggle_prometheus", "enable", "--url", stdout=stdout)
                    enable_output = stdout.getvalue()
                    self.assertTrue(flag_file.exists())
                    self.assertIn("Prometheus runtime flag enabled", enable_output)
                    self.assertIn(f"Metrics URL: {metrics_url}", enable_output)

                    stdout = io.StringIO()
                    call_command("toggle_prometheus", "status", "--url", stdout=stdout)
                    status_enabled_output = stdout.getvalue()
                    self.assertIn("Present: True", status_enabled_output)
                    self.assertIn(f"Metrics URL: {metrics_url}", status_enabled_output)

                    stdout = io.StringIO()
                    call_command("toggle_prometheus", "disable", stdout=stdout)
                    disable_output = stdout.getvalue()
                    self.assertFalse(flag_file.exists())
                    self.assertIn("Prometheus runtime flag removed", disable_output)

                    stdout = io.StringIO()
                    call_command("toggle_prometheus", "disable", stdout=stdout)
                    disable_missing_output = stdout.getvalue()
                    self.assertIn("Prometheus runtime flag not present", disable_missing_output)
