"""Read-only inventory for Notifications legacy/privacy readiness."""

import json

from django.core.management.base import BaseCommand

from notifications.services.persistence import inventory_notification_data


class Command(BaseCommand):
    help = (
        "Inventory notification, shared-delivery, and token legacy gaps without writes."
    )

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(inventory_notification_data(), sort_keys=True))
