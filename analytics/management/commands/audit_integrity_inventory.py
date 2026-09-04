"""Read-only audit protection and integrity inventory."""

from django.core.management.base import BaseCommand

from analytics.services.lifecycle import audit_integrity_inventory


class Command(BaseCommand):
    help = "Inventory audit integrity, encryption, and retention metadata."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10000)

    def handle(self, *args, **options):
        result = audit_integrity_inventory(limit=options["limit"])
        self.stdout.write("Audit integrity inventory")
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
