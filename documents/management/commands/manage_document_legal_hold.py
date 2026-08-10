"""Preview or apply a legal hold change to one document."""

from django.core.management.base import BaseCommand, CommandError

from documents.models import Document
from documents.services.audit import (
    DocumentAuditUnavailable,
    record_document_audit,
)


class Command(BaseCommand):
    help = "Set/release a document legal hold; dry-run unless --apply is supplied"

    def add_arguments(self, parser):
        parser.add_argument("document_id")
        parser.add_argument("--action", choices=("set", "release"), required=True)
        parser.add_argument("--reason", default="")
        parser.add_argument("--operator", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        document = Document.find_by_id(options["document_id"])
        if not document:
            raise CommandError("Document not found")
        if options["action"] == "set" and not options["reason"].strip():
            raise CommandError("--reason is required when setting a legal hold")
        if not options["apply"]:
            self.stdout.write(
                f"DRY RUN: would {options['action']} legal hold for document {document.id}"
            )
            return
        if options["action"] == "set":
            changed = document.set_legal_hold(
                reason=options["reason"], set_by=options["operator"]
            )
        else:
            changed = document.release_legal_hold(
                released_by=options["operator"]
            )
        if not changed:
            raise CommandError("Legal hold state changed concurrently or is ineligible")
        try:
            record_document_audit(
                required=True,
                action=f"document_legal_hold_{options['action']}",
                user_id=options["operator"],
                user_type="admin",
                description="Document legal hold state changed",
                resource_type="document",
                resource_id=document.id,
                details={"status": options["action"]},
                ip_address="",
            )
        except DocumentAuditUnavailable as exc:
            raise CommandError(
                "Legal hold state updated, but its audit record was queued for recovery"
            ) from exc
        self.stdout.write(self.style.SUCCESS("Legal hold state updated"))
