"""Dry-run-first reconciliation for stale AI request leases/exchanges."""

from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ai_assistant.models import AIInteraction
from ai_assistant.services.idempotency import COLLECTION


class Command(BaseCommand):
    help = 'Inventory and reconcile stale AI request leases without provider calls.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--limit', type=int, default=10000)

    def handle(self, *args, **options):
        now = datetime.now(timezone.utc)
        collection = settings.MONGODB[COLLECTION]
        counts = {
            'scanned': 0,
            'completed_recovered': 0,
            'stale_failed': 0,
            'partial_exchange': 0,
        }
        cursor = collection.find(
            {
                '$or': [
                    {'status': 'processing', 'lease_expires_at': {'$lte': now}},
                    {'status': 'complete'},
                ]
            },
            limit=max(1, min(int(options['limit']), 100000)),
        )
        for request in cursor:
            counts['scanned'] += 1
            key = {
                'customer_id': request['customer_id'],
                'request_id': request['request_id'],
            }
            exchange = AIInteraction.find_by_request_id(**key)
            if len(exchange) == 2:
                if request.get('status') != 'complete':
                    counts['completed_recovered'] += 1
                    if options['apply']:
                        collection.update_one(
                            {'_id': request['_id'], 'status': 'processing'},
                            {'$set': {
                                'status': 'complete',
                                'updated_at': now,
                                'lease_expires_at': now,
                            }},
                        )
                continue
            if exchange:
                counts['partial_exchange'] += 1
            if request.get('status') == 'processing':
                counts['stale_failed'] += 1
                if options['apply']:
                    collection.update_one(
                        {'_id': request['_id'], 'status': 'processing'},
                        {'$set': {
                            'status': 'failed',
                            'updated_at': now,
                            'lease_expires_at': now,
                        }},
                    )

        mode = 'APPLIED' if options['apply'] else 'DRY-RUN'
        self.stdout.write(
            f'[{mode}] ' + ', '.join(f'{key}={value}' for key, value in counts.items())
        )
        if counts['partial_exchange']:
            raise CommandError(
                'Partial AI exchanges require retry/operator review; no content was fabricated'
            )
