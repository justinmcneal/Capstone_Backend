from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings

from config.prometheus_metrics import get_metrics_url, get_runtime_flag_file


class Command(BaseCommand):
    help = (
        "Enable/disable Prometheus runtime metrics flag file. "
        "Usage: manage.py toggle_prometheus enable|disable|status [--url]"
    )

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["enable", "disable", "status"])
        parser.add_argument("--url", action="store_true", help="Print the resolved metrics URL")

    def handle(self, *args, **options):
        action = options.get("action")
        show_url = options.get("url", False)

        flag_file = getattr(settings, "PROMETHEUS_METRICS_RUNTIME_FLAG_FILE", get_runtime_flag_file())
        flag_path = Path(flag_file)

        if action == "enable":
            try:
                flag_path.parent.mkdir(parents=True, exist_ok=True)
                with flag_path.open("w", encoding="utf-8") as fh:
                    fh.write("1")
                self.stdout.write(self.style.SUCCESS(f"Prometheus runtime flag enabled: {flag_file}"))
            except Exception as e:
                self.stderr.write(f"Failed to create flag file: {e}")
        elif action == "disable":
            try:
                if flag_path.exists():
                    flag_path.unlink()
                    self.stdout.write(self.style.SUCCESS(f"Prometheus runtime flag removed: {flag_file}"))
                else:
                    self.stdout.write(self.style.WARNING(f"Prometheus runtime flag not present: {flag_file}"))
            except Exception as e:
                self.stderr.write(f"Failed to remove flag file: {e}")
        else:  # status
            exists = flag_path.exists()
            self.stdout.write(f"Prometheus runtime flag file: {flag_file}\nPresent: {exists}")

        if show_url:
            self.stdout.write(f"Metrics URL: {get_metrics_url()}")
