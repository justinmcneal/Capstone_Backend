"""Read-only Analytics release readiness report."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from analytics.services.operations import analytics_release_readiness


class Command(BaseCommand):
    help = "Run non-secret, read-only Analytics deployment readiness checks."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        try:
            report = analytics_release_readiness(settings.MONGODB)
        except Exception as exc:
            raise CommandError(
                f"Analytics release check could not complete: {type(exc).__name__}"
            ) from exc
        if options["as_json"]:
            self.stdout.write(json.dumps(report, sort_keys=True))
        else:
            self.stdout.write("Analytics release readiness")
            for name, passed in report["checks"].items():
                self.stdout.write(f"{name}: {'PASS' if passed else 'FAIL'}")
            self.stdout.write(f"overall: {'PASS' if report['ready'] else 'FAIL'}")
        if not report["ready"]:
            raise CommandError("Analytics deployment readiness checks failed")
