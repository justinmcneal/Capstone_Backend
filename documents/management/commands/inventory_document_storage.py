"""Report aggregate document storage inconsistencies without changing state."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from documents.services.storage_inventory import inventory_document_storage
from documents.storage import get_storage_backend


class Command(BaseCommand):
    help = "Read-only document object/database inventory; never prints object keys"

    def handle(self, *args, **options):
        result = inventory_document_storage(
            settings.MONGODB, get_storage_backend()
        )
        self.stdout.write(json.dumps(result, sort_keys=True, default=str))
