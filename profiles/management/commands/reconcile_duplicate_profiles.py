"""Inventory and reconcile duplicate profile documents by canonical customer ID."""

from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand

from profiles.models import AlternativeData, BusinessProfile, CustomerProfile

PROFILE_MODELS = (CustomerProfile, BusinessProfile, AlternativeData)


def _sort_key(document):
    def timestamp(value):
        try:
            return value.timestamp()
        except (AttributeError, OSError, ValueError):
            return 0

    return (
        timestamp(document.get("updated_at")),
        timestamp(document.get("created_at")),
        str(document.get("_id")),
    )


class Command(BaseCommand):
    help = (
        "Inventory profile records whose string/ObjectId customer IDs identify the "
        "same customer. --apply retains the newest authoritative document."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Delete older duplicates and canonicalize the retained customer ID.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        total_groups = 0
        total_removed = 0

        for model in PROFILE_MODELS:
            collection = settings.MONGODB[model.collection_name]
            grouped = defaultdict(list)
            for document in collection.find({"customer_id": {"$ne": None}}):
                grouped[str(document["customer_id"])].append(document)

            duplicate_groups = {
                customer_id: documents
                for customer_id, documents in grouped.items()
                if len(documents) > 1
            }
            removed = sum(len(documents) - 1 for documents in duplicate_groups.values())
            total_groups += len(duplicate_groups)
            total_removed += removed

            if apply_changes:
                for customer_id, documents in duplicate_groups.items():
                    newest_first = sorted(documents, key=_sort_key, reverse=True)
                    keeper, *duplicates = newest_first
                    collection.delete_many(
                        {"_id": {"$in": [document["_id"] for document in duplicates]}}
                    )
                    collection.update_one(
                        {"_id": keeper["_id"]},
                        {"$set": {"customer_id": customer_id}},
                    )

            mode = "APPLIED" if apply_changes else "DRY-RUN"
            self.stdout.write(
                f"[{mode}] {model.collection_name}: "
                f"duplicate_groups={len(duplicate_groups)}, "
                f"older_documents={removed}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Duplicate profile reconciliation complete: groups={total_groups}, "
                f"older_documents_{'removed' if apply_changes else 'found'}="
                f"{total_removed}."
            )
        )
