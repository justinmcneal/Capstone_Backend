"""Dry-run-first encryption and lifecycle backfill for legacy AI history."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ai_assistant.models import AIInteraction
from ai_assistant.services.lifecycle import prepare_legacy_ai_backfill


class Command(BaseCommand):
    help = 'Encrypt and add retention metadata to legacy AI interactions.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--limit', type=int, default=10000)

    def handle(self, *args, **options):
        if not getattr(settings, 'FIELD_ENCRYPTION_KEY', ''):
            raise CommandError('FIELD_ENCRYPTION_KEY must be configured')
        collection = settings.MONGODB[AIInteraction.collection_name]
        counts = {'scanned': 0, 'changed': 0, 'conflicts': 0, 'invalid': 0}
        cursor = collection.find(
            {}, sort=[('timestamp', 1), ('_id', 1)], limit=max(1, options['limit'])
        )
        for raw in cursor:
            counts['scanned'] += 1
            try:
                protected = prepare_legacy_ai_backfill(raw)
            except (TypeError, ValueError):
                counts['invalid'] += 1
                continue
            comparable = {key: raw.get(key) for key in protected}
            if comparable == protected:
                continue
            counts['changed'] += 1
            if options['apply']:
                originals = {
                    key: raw.get(key)
                    for key in (
                        'message',
                        'response',
                        'retention_policy_version',
                        'retention_expires_at',
                    )
                }
                result = collection.update_one(
                    {'_id': raw['_id'], **originals}, {'$set': protected}
                )
                if result.modified_count != 1:
                    counts['conflicts'] += 1
        mode = 'APPLIED' if options['apply'] else 'DRY-RUN'
        self.stdout.write(
            f'[{mode}] ' + ', '.join(f'{key}={value}' for key, value in counts.items())
        )
        if counts['invalid'] or counts['conflicts']:
            raise CommandError('AI interaction backfill requires operator review')
