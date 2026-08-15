"""Read-only, count-only Loans persistence inventory."""

from django.core.management.base import BaseCommand

from loans.services.persistence import loan_data_inventory


class Command(BaseCommand):
    help = "Read-only count inventory for Loans validators, indexes, and backfill"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10_000)

    def handle(self, *args, **options):
        result = loan_data_inventory(limit=options["limit"])
        self.stdout.write("Loans persistence inventory")
        self.stdout.write(f"complete: {result['complete']}")
        for collection_name, counts in result["collections"].items():
            self.stdout.write(collection_name)
            for key, value in counts.items():
                self.stdout.write(f"  {key}: {value}")
