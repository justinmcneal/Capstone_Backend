"""Fail-closed, dry-run-first Notifications index and validator installation."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from notifications.models.delivery import NotificationDelivery
from notifications.models.device_token import DeviceToken
from notifications.models.notification import Notification
from notifications.services.persistence import (
    install_notification_validators,
    inventory_notification_data,
)

BLOCKING_INVENTORY_KEYS = (
    "legacy_read_status",
    "missing_user_type",
    "invalid_user_type",
    "missing_read_state",
    "missing_retention",
    "missing_idempotency_hash",
    "plaintext_sensitive_fields",
    "invalid_notification_timestamps",
    "duplicate_idempotency_hash_groups",
    "plaintext_device_tokens",
    "missing_token_hash",
    "missing_token_session",
    "invalid_token_owner_type",
    "invalid_token_platform",
    "missing_token_expiry",
    "duplicate_token_hash_groups",
    "plaintext_delivery_event_keys",
)


class Command(BaseCommand):
    help = "Install Notifications indexes/validators after a clean inventory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Apply schema changes after checks."
        )

    def handle(self, *args, **options):
        inventory = inventory_notification_data()
        blockers = {
            key: inventory.get(key, 0)
            for key in BLOCKING_INVENTORY_KEYS
            if inventory.get(key, 0)
        }
        self.stdout.write(json.dumps({"blockers": blockers}, sort_keys=True))
        if not options["apply"]:
            self.stdout.write("DRY RUN: no indexes or validators changed")
            return
        if blockers:
            raise CommandError(
                "Notification inventory is not clean; backfill/encrypt and review it first."
            )

        collection = settings.MONGODB[Notification.collection_name]
        legacy = collection.index_information().get("idempotency_key_1")
        if legacy and legacy.get("key") == [("idempotency_key", 1)]:
            collection.drop_index("idempotency_key_1")
        Notification.create_indexes()
        DeviceToken.create_indexes()
        NotificationDelivery.create_indexes()
        install_notification_validators()
        self.stdout.write(self.style.SUCCESS("Notifications schema installed"))
