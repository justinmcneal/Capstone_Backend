"""Inventory and reconcile stored profile-completion policy metadata."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from profiles.models import (
    PROFILE_COMPLETION_POLICY_VERSION,
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
)

PROFILE_MODELS = (CustomerProfile, BusinessProfile, AlternativeData)


class Command(BaseCommand):
    help = (
        "Inventory completion metadata that differs from the current profile "
        "policy. Writes require --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist current completion metadata with revision guards.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        total_candidates = 0
        total_updated = 0
        total_conflicts = 0

        for model in PROFILE_MODELS:
            collection = settings.MONGODB[model.collection_name]
            candidates = 0
            updated = 0
            conflicts = 0
            for document in collection.find({}):
                profile = model.from_dict(document)
                desired = {
                    "profile_completed": profile.profile_completed,
                    "completion_percentage": profile.completion_percentage,
                    "profile_completion_policy_version": (
                        PROFILE_COMPLETION_POLICY_VERSION
                    ),
                    "profile_missing_fields": profile.profile_missing_fields,
                }
                if all(document.get(field) == value for field, value in desired.items()):
                    continue
                candidates += 1
                if not apply_changes:
                    continue

                revision = int(document.get("profile_revision", 0) or 0)
                query = {"_id": document["_id"]}
                if "profile_revision" in document:
                    query["profile_revision"] = revision
                else:
                    query["profile_revision"] = {"$exists": False}
                result = collection.update_one(query, {"$set": desired})
                if result.modified_count == 1:
                    updated += 1
                else:
                    conflicts += 1

            total_candidates += candidates
            total_updated += updated
            total_conflicts += conflicts
            mode = "APPLIED" if apply_changes else "DRY-RUN"
            self.stdout.write(
                f"[{mode}] {model.collection_name}: candidates={candidates}, "
                f"updated={updated}, conflicts={conflicts}"
            )

        self.stdout.write(
            "Summary: "
            f"policy={PROFILE_COMPLETION_POLICY_VERSION}, "
            f"candidates={total_candidates}, updated={total_updated}, "
            f"conflicts={total_conflicts}"
        )
        if total_conflicts:
            raise CommandError(
                "Completion reconciliation encountered concurrent updates; rerun "
                "the dry run before retrying."
            )
