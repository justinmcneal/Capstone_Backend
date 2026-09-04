"""Dry-run-first legal-hold management for AI interactions."""

from django.core.management.base import BaseCommand, CommandError

from ai_assistant.models import AIInteraction


class Command(BaseCommand):
    help = 'Set or release a legal hold on one AI interaction.'

    def add_arguments(self, parser):
        parser.add_argument('interaction_id')
        parser.add_argument('action', choices=('set', 'release'))
        parser.add_argument('--reason', default='')
        parser.add_argument('--operator', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        interaction = AIInteraction.find_by_id(options['interaction_id'])
        if not interaction:
            raise CommandError('AI interaction not found')
        if options['action'] == 'set' and not options['reason'].strip():
            raise CommandError('--reason is required when setting a legal hold')
        if not options['apply']:
            self.stdout.write(
                f"[DRY RUN] would {options['action']} legal hold for "
                f"interaction {interaction.id}"
            )
            return
        if options['action'] == 'set':
            changed = interaction.set_legal_hold(
                reason=options['reason'], set_by=options['operator']
            )
        else:
            changed = interaction.release_legal_hold(
                released_by=options['operator']
            )
        self.stdout.write(
            ('APPLIED' if changed else 'NO CHANGE') + f': interaction {interaction.id}'
        )
