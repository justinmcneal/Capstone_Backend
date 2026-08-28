"""Read-only Notifications deployment readiness report."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from notifications.services.operations import notification_release_readiness


class Command(BaseCommand):
    help = "Run non-secret, read-only Notifications Stage 6 readiness checks."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        try:
            report = notification_release_readiness(settings.MONGODB)
        except Exception as exc:
            raise CommandError(
                "Notifications release check could not complete: "
                f"{type(exc).__name__}"
            ) from exc
        if options["as_json"]:
            self.stdout.write(json.dumps(report, sort_keys=True, default=str))
        else:
            self.stdout.write("Notifications Stage 6 release readiness")
            for name, passed in report["checks"].items():
                self.stdout.write(f"{name}: {'PASS' if passed else 'FAIL'}")
            self.stdout.write(f"overall: {'PASS' if report['ready'] else 'FAIL'}")
        if not report["ready"]:
            raise CommandError("Notifications deployment readiness checks failed")
