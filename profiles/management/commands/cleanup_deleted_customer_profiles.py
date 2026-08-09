"""Reconcile profile records retained for already-deleted customers."""

from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.models import Customer
from profiles.services.lifecycle import (
    count_customer_profile_data,
    delete_customer_profile_data,
)


class Command(BaseCommand):
    help = (
        "Find profile records owned by deleted customers and remove them only "
        "when --apply is supplied."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Irreversibly remove the identified profile records.",
        )

    def handle(self, *args, **options):
        db = settings.MONGODB
        customers = Customer.find({"account_state": "deleted"})
        affected_customers = 0
        document_count = 0

        for customer in customers:
            counts = count_customer_profile_data(db, customer.id)
            total = sum(counts.values())
            if total:
                affected_customers += 1
                document_count += total

            if not options["apply"]:
                continue

            deleted = delete_customer_profile_data(db, customer.id)
            completed_at = datetime.now(timezone.utc)
            db[Customer.collection_name].update_one(
                {"_id": customer._id, "account_state": "deleted"},
                {
                    "$set": {
                        "profile_cleanup_status": "complete",
                        "profile_cleanup_counts": deleted,
                        "profile_cleanup_last_error": "",
                        "profile_cleanup_last_attempt_at": completed_at,
                        "profile_cleanup_completed_at": completed_at,
                        "updated_at": completed_at,
                    },
                    "$inc": {"profile_cleanup_attempts": 1},
                },
            )

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run: "
                    f"{document_count} profile record(s) across "
                    f"{affected_customers} deleted customer(s) require cleanup. "
                    "Run with --apply only after approved retention review and backup."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {document_count} profile record(s) for "
                f"{affected_customers} previously deleted customer(s)."
            )
        )
