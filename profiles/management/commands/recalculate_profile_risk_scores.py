"""Inventory and queue profile scores that need the current policy."""

from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand

from profiles.models import AlternativeData
from profiles.services.risk_scoring import RISK_SCORING_POLICY_VERSION
from profiles.tasks import enqueue_risk_score_calculation


class Command(BaseCommand):
    help = (
        "Find alternative-data scores that do not match the current scoring "
        "policy and queue them only when --apply is supplied."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Mark matching records pending and queue recalculation.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Recalculate every alternative-data record, including current scores.",
        )

    def handle(self, *args, **options):
        collection = settings.MONGODB[AlternativeData.collection_name]
        candidates = []
        for document in collection.find({}):
            revision = int(document.get("risk_input_revision", 0) or 0)
            is_current = (
                document.get("risk_score_status") == "complete"
                and document.get("risk_score_policy_version")
                == RISK_SCORING_POLICY_VERSION
                and document.get("risk_calculated_revision") == revision
            )
            if options["all"] or not is_current:
                candidates.append((document, revision))

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run: "
                    f"{len(candidates)} alternative-data record(s) require scoring "
                    f"under policy {RISK_SCORING_POLICY_VERSION}."
                )
            )
            return

        queued = 0
        for document, revision in candidates:
            now = datetime.now(timezone.utc)
            collection.update_one(
                {"_id": document["_id"], "risk_input_revision": revision},
                {
                    "$set": {
                        "risk_score": None,
                        "risk_category": None,
                        "score_calculated_at": None,
                        "risk_score_status": "pending",
                        "risk_score_policy_version": None,
                        "risk_calculated_revision": None,
                        "risk_score_breakdown": {},
                        "risk_score_reason_codes": [],
                        "risk_score_error_code": "",
                        "risk_score_task_id": None,
                        "risk_score_requested_at": now,
                        "risk_score_failed_at": None,
                        "updated_at": now,
                    }
                },
            )
            if enqueue_risk_score_calculation(
                document.get("customer_id"), revision
            ):
                queued += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Queued {queued} of {len(candidates)} alternative-data record(s) "
                f"for policy {RISK_SCORING_POLICY_VERSION}."
            )
        )
