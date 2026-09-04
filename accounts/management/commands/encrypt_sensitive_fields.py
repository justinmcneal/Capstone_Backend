from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Admin, Customer, LoanOfficer
from ai_assistant.models import AIInteraction
from config.field_encryption import (
    FieldDecryptionError,
    decrypt_value,
    encrypt_value,
    is_encrypted_value,
    is_primary_encrypted_value,
    reencrypt_value,
)
from documents.models import Document
from loans.models import LoanApplication, LoanPayment, LoanProduct, RepaymentSchedule
from notifications.models.delivery import NotificationDelivery
from notifications.models.device_token import DeviceToken
from notifications.models.notification import Notification
from profiles.models import (
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
    RiskReviewRequest,
)

ENCRYPTED_MODELS = (
    Customer,
    LoanOfficer,
    Admin,
    CustomerProfile,
    BusinessProfile,
    AlternativeData,
    RiskReviewRequest,
    Document,
    LoanApplication,
    LoanPayment,
    LoanProduct,
    RepaymentSchedule,
    AIInteraction,
    DeviceToken,
    Notification,
    NotificationDelivery,
)

# Retained as a public constant for operational tooling and tests. Deriving this
# from model declarations prevents a backfill from encrypting fields that the
# corresponding model cannot decrypt.
FIELD_MAP = {
    model.collection_name: tuple(model.encrypted_fields) for model in ENCRYPTED_MODELS
}


class Command(BaseCommand):
    help = (
        "Safely backfill, rotate, or verify configured encrypted MongoDB fields. "
        "Writes require --apply; the default is a dry run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply conditional writes. Without this flag, changes are only reported.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Explicit dry-run alias retained for compatibility.",
        )
        parser.add_argument(
            "--rotate",
            action="store_true",
            help="Re-encrypt legacy/previous-key ciphertext with the primary key.",
        )
        parser.add_argument(
            "--verify",
            action="store_true",
            help="Fail unless every populated supported field decrypts with the primary key.",
        )
        parser.add_argument(
            "--collection",
            action="append",
            dest="collection_names",
            choices=tuple(FIELD_MAP),
            help=(
                "Limit work to a supported collection. Repeat this option to "
                "select multiple collections."
            ),
        )

    def handle(self, *args, **options):
        if not getattr(settings, "FIELD_ENCRYPTION_KEY", ""):
            raise CommandError(
                "FIELD_ENCRYPTION_KEY is not set. Configure it in your environment first."
            )
        if settings.MONGODB is None:
            raise CommandError(
                "MongoDB connection is not available (settings.MONGODB is None)."
            )
        if options["apply"] and options["dry_run"]:
            raise CommandError("Use either --apply or --dry-run, not both.")
        if options["verify"] and (options["apply"] or options["rotate"]):
            raise CommandError("Run --verify separately after backfill or rotation.")

        verify = options["verify"]
        apply_changes = options["apply"]
        rotate = options["rotate"]
        totals = {
            "scanned": 0,
            "changed": 0,
            "fields": 0,
            "unsupported": 0,
            "conflicts": 0,
            "failures": 0,
        }

        selected_names = options.get("collection_names") or tuple(FIELD_MAP)
        selected_fields = {
            collection_name: FIELD_MAP[collection_name]
            for collection_name in selected_names
        }

        for collection_name, fields in selected_fields.items():
            counts = {key: 0 for key in totals}
            projection = {field: 1 for field in fields}
            for document in settings.MONGODB[collection_name].find({}, projection):
                counts["scanned"] += 1
                if verify:
                    self._verify_document(document, fields, counts)
                    continue

                originals = {}
                updates = {}
                for field in fields:
                    value = document.get(field)
                    if value is None or value == "":
                        continue
                    if is_encrypted_value(value):
                        if not rotate or is_primary_encrypted_value(value):
                            continue
                        encrypted = reencrypt_value(value)
                    else:
                        encrypted = encrypt_value(value)
                    if encrypted == value:
                        counts["unsupported"] += 1
                        continue
                    originals[field] = value
                    updates[field] = encrypted

                if not updates:
                    continue
                counts["changed"] += 1
                counts["fields"] += len(updates)
                if apply_changes:
                    query = {"_id": document["_id"]}
                    query.update(originals)
                    result = settings.MONGODB[collection_name].update_one(
                        query, {"$set": updates}
                    )
                    if result.modified_count != 1:
                        counts["conflicts"] += 1

            for key in totals:
                totals[key] += counts[key]
            mode = "VERIFY" if verify else ("APPLIED" if apply_changes else "DRY-RUN")
            self.stdout.write(
                f"[{mode}] {collection_name}: scanned={counts['scanned']}, "
                f"documents_changed={counts['changed']}, fields_changed={counts['fields']}, "
                f"unsupported={counts['unsupported']}, conflicts={counts['conflicts']}, "
                f"failures={counts['failures']}"
            )

        self.stdout.write(
            "Summary: " + ", ".join(f"{key}={value}" for key, value in totals.items())
        )
        if totals["conflicts"]:
            raise CommandError(
                "Encryption writes encountered concurrent changes; rerun the command."
            )
        if totals["failures"]:
            raise CommandError(
                "Encryption verification failed; keep previous keys configured and review the counts."
            )
        self.stdout.write(self.style.SUCCESS("Encryption operation completed"))

    @staticmethod
    def _verify_document(document, fields, counts):
        for field in fields:
            value = document.get(field)
            if value is None or value == "":
                continue
            if not is_encrypted_value(value):
                encrypted = encrypt_value(value)
                if encrypted == value:
                    counts["unsupported"] += 1
                else:
                    counts["failures"] += 1
                continue
            try:
                decrypted = decrypt_value(value)
            except FieldDecryptionError:
                counts["failures"] += 1
                continue
            if decrypted == value:
                counts["failures"] += 1
                continue
            if not is_primary_encrypted_value(value):
                counts["failures"] += 1
