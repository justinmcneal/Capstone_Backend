"""Dry-run-first legal-hold management for one loan application."""

from django.core.management.base import BaseCommand, CommandError

from loans.models import LoanApplication
from loans.services.lifecycle import release_loan_legal_hold, set_loan_legal_hold


class Command(BaseCommand):
    help = "Set or release a loan legal hold; writes require --apply."

    def add_arguments(self, parser):
        parser.add_argument("application_id")
        parser.add_argument("action", choices=("set", "release"))
        parser.add_argument("--reason", default="")
        parser.add_argument("--actor", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        application = LoanApplication.find_by_id(options["application_id"])
        if not application:
            raise CommandError("Loan application not found")
        if options["action"] == "set" and not options["reason"].strip():
            raise CommandError("--reason is required when setting a legal hold")
        if not options["apply"]:
            self.stdout.write(
                f"DRY RUN: would {options['action']} legal hold for loan {application.id}"
            )
            return
        if options["action"] == "set":
            changed = set_loan_legal_hold(
                application.id, reason=options["reason"], set_by=options["actor"]
            )
        else:
            changed = release_loan_legal_hold(
                application.id, released_by=options["actor"]
            )
        if changed:
            from loans.services.audit import record_loan_audit

            record_loan_audit(
                action=f"loan_legal_hold_{options['action']}",
                user_id=options["actor"],
                user_type="admin",
                description=f"Loan legal hold {options['action']} operation completed",
                resource_type="loan",
                resource_id=application.id,
                details={"legal_hold_action": options["action"]},
                ip_address="",
            )
        self.stdout.write(
            self.style.SUCCESS("Loan legal hold updated" if changed else "No change")
        )
