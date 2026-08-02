from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Invalidate legacy active-session records and remove plaintext "
        "session_token fields. Dry-run unless --apply is supplied."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the invalidation and plaintext-field removal.",
        )

    def handle(self, *args, **options):
        collection = settings.MONGODB["active_sessions"]
        query = {"session_token": {"$exists": True}}
        count = collection.count_documents(query)

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {count} legacy session record(s) require scrubbing. "
                    "Run with --apply during an approved maintenance window."
                )
            )
            return

        result = collection.update_many(
            query,
            {
                "$unset": {"session_token": ""},
                "$set": {
                    "is_active": False,
                    "legacy_invalidated_at": datetime.now(timezone.utc),
                },
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Scrubbed and invalidated {result.modified_count} legacy "
                "session record(s)."
            )
        )
