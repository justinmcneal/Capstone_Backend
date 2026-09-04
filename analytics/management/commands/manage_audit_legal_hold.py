"""Dry-run-first legal-hold management for one audit event."""

from django.core.management.base import BaseCommand, CommandError

from analytics.services.lifecycle import (
    release_audit_legal_hold,
    set_audit_legal_hold,
)


class Command(BaseCommand):
    help = "Set or release an audit legal hold. Writes require --apply."

    def add_arguments(self, parser):
        parser.add_argument("event_id")
        parser.add_argument("--action", choices=("set", "release"), required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", default="")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if options["action"] == "set" and not options["reason"].strip():
            raise CommandError("--reason is required when setting a hold")
        if not options["apply"]:
            self.stdout.write(
                f"[DRY-RUN] would {options['action']} hold for {options['event_id']}"
            )
            return
        if options["action"] == "set":
            changed = set_audit_legal_hold(
                options["event_id"],
                reason=options["reason"],
                set_by=options["actor"],
            )
        else:
            changed = release_audit_legal_hold(
                options["event_id"], released_by=options["actor"]
            )
        if not changed:
            raise CommandError("Audit event was not found or already in the requested state")
        self.stdout.write(self.style.SUCCESS("Audit legal hold updated"))
