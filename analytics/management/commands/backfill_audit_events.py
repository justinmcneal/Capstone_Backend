"""Dry-run-first protection backfill for legacy audit events."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from analytics.models import AuditLog
from analytics.services.lifecycle import prepare_legacy_audit_backfill


class Command(BaseCommand):
    help = "Encrypt, version, retain, and integrity-sign legacy audit events."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--limit", type=int, default=10000)

    def handle(self, *args, **options):
        if not getattr(settings, "FIELD_ENCRYPTION_KEY", ""):
            raise CommandError("FIELD_ENCRYPTION_KEY must be configured")
        collection = settings.MONGODB[AuditLog.collection_name]
        counts = {"scanned": 0, "changed": 0, "conflicts": 0, "invalid": 0}
        for raw in collection.find(
            {}, sort=[("timestamp", 1), ("_id", 1)], limit=options["limit"]
        ):
            counts["scanned"] += 1
            try:
                protected = prepare_legacy_audit_backfill(raw)
            except ValueError:
                counts["invalid"] += 1
                continue
            comparable = {key: raw.get(key) for key in protected}
            if comparable == protected:
                continue
            counts["changed"] += 1
            if options["apply"]:
                result = collection.update_one(
                    {"_id": raw["_id"], "integrity_hash": raw.get("integrity_hash")},
                    {"$set": protected},
                )
                if result.modified_count != 1:
                    counts["conflicts"] += 1
        mode = "APPLIED" if options["apply"] else "DRY-RUN"
        self.stdout.write(
            f"[{mode}] " + ", ".join(f"{key}={value}" for key, value in counts.items())
        )
        if counts["invalid"] or counts["conflicts"]:
            raise CommandError("Audit backfill requires operator review")
