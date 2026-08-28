"""Dry-run-first deterministic Notifications legacy backfill."""

import json

from django.core.management.base import BaseCommand, CommandError

from notifications.services.persistence import backfill_notification_data


class Command(BaseCommand):
    help = "Backfill safe notification shapes; defaults to a read-only dry run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply conditional updates. Without this flag nothing is written.",
        )

    def handle(self, *args, **options):
        counts = backfill_notification_data(apply=options["apply"])
        mode = "APPLIED" if options["apply"] else "DRY-RUN"
        self.stdout.write(f"[{mode}] {json.dumps(counts, sort_keys=True)}")
        if counts["conflicts"]:
            raise CommandError("Concurrent changes detected; rerun inventory/backfill.")
