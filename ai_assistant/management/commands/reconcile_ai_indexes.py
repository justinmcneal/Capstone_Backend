"""Dry-run-first reconciliation and installation of AI persistence metadata."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ai_assistant.models import AIActivityEvent, AIInteraction
from ai_assistant.services.idempotency import (
    create_indexes as create_request_indexes,
)
from ai_assistant.services.idempotency import (
    create_validator as create_request_validator,
)
from ai_assistant.services.operations import EXPECTED_INDEXES


def _validator_present(db, collection_name):
    result = db.command(
        {'listCollections': 1, 'filter': {'name': collection_name}}
    )
    collections = result.get('cursor', {}).get('firstBatch', [])
    return bool(collections and collections[0].get('options', {}).get('validator'))


class Command(BaseCommand):
    help = (
        'Inspect or reconcile the legacy AI conversation index, then install '
        'and verify all AI indexes and validators.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        db = settings.MONGODB
        if db is None:
            raise CommandError('MongoDB is not configured')

        try:
            result = AIInteraction.reconcile_legacy_conversation_index(
                apply=options['apply']
            )
        except Exception as exc:
            raise CommandError(f'Conversation index reconciliation refused: {exc}') from exc

        mode = 'APPLIED' if options['apply'] else 'DRY-RUN'
        self.stdout.write(
            f'[{mode}] conversation_index={result["status"]}, '
            f'changed={str(result["changed"]).lower()}'
        )
        if not options['apply']:
            if result['status'] in {'legacy', 'missing'}:
                self.stdout.write('Run again with --apply to install canonical AI metadata.')
            return

        try:
            AIInteraction.create_indexes()
            AIInteraction.create_validator()
            create_request_indexes()
            create_request_validator()
            AIActivityEvent.create_indexes()
            AIActivityEvent.create_validator()
        except Exception as exc:
            raise CommandError(f'AI metadata installation failed: {exc}') from exc

        missing_indexes = {
            collection_name: sorted(
                expected - set(db[collection_name].index_information())
            )
            for collection_name, expected in EXPECTED_INDEXES.items()
            if expected - set(db[collection_name].index_information())
        }
        missing_validators = [
            collection_name
            for collection_name in EXPECTED_INDEXES
            if not _validator_present(db, collection_name)
        ]
        if missing_indexes or missing_validators:
            raise CommandError(
                f'AI metadata verification failed: missing_indexes={missing_indexes}, '
                f'missing_validators={missing_validators}'
            )

        self.stdout.write(self.style.SUCCESS(
            'AI indexes and validators are installed and verified.'
        ))
