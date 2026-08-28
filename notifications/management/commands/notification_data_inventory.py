"""Read-only inventory for Notifications legacy/privacy readiness."""

import json

from django.core.management.base import BaseCommand

from notifications.services.persistence import inventory_notification_data


class Command(BaseCommand):
    help = (
        "Inventory notification, shared-delivery, and token legacy gaps without writes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=10_000,
            help="Maximum rows per collection inspected for field-level findings.",
        )

    def handle(self, *args, **options):
        self.stdout.write(
            json.dumps(
                inventory_notification_data(limit=options["limit"]), sort_keys=True
            )
        )
