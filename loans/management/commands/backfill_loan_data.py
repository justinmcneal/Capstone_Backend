"""Dry-run-first Loans persistence and search-metadata backfill."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from loans.services.persistence import INVENTORY_CONFIG, prepare_loan_backfill


class Command(BaseCommand):
    help = "Backfill Loans encryption, centavos, search, scope, and timing metadata"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--limit", type=int, default=10_000)

    def handle(self, *args, **options):
        if not getattr(settings, "FIELD_ENCRYPTION_KEY", ""):
            raise CommandError("FIELD_ENCRYPTION_KEY must be configured")
        limit = max(1, int(options["limit"]))
        totals = {
            "scanned": 0,
            "changed": 0,
            "conflicts": 0,
            "invalid": 0,
            "truncated_collections": 0,
        }
        for collection_name in INVENTORY_CONFIG:
            collection = settings.MONGODB[collection_name]
            if collection.count_documents({}) > limit:
                totals["truncated_collections"] += 1
            for raw in collection.find({}).sort("_id", 1).limit(limit):
                totals["scanned"] += 1
                try:
                    protected = prepare_loan_backfill(collection_name, raw)
                except (TypeError, ValueError):
                    totals["invalid"] += 1
                    continue
                changed = {
                    key: value for key, value in protected.items() if raw.get(key) != value
                }
                if not changed:
                    continue
                totals["changed"] += 1
                if options["apply"]:
                    originals = {key: raw.get(key) for key in changed}
                    result = collection.update_one(
                        {"_id": raw["_id"], **originals}, {"$set": changed}
                    )
                    if result.modified_count != 1:
                        totals["conflicts"] += 1
        mode = "APPLIED" if options["apply"] else "DRY-RUN"
        self.stdout.write(
            f"[{mode}] " + ", ".join(f"{key}={value}" for key, value in totals.items())
        )
        if (
            totals["invalid"]
            or totals["conflicts"]
            or totals["truncated_collections"]
        ):
            raise CommandError("Loans backfill requires operator review")
