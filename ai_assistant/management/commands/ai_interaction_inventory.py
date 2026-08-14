"""Read-only AI interaction encryption and lifecycle inventory."""

from django.core.management.base import BaseCommand

from ai_assistant.services.lifecycle import ai_interaction_inventory


class Command(BaseCommand):
    help = 'Inventory AI interaction encryption and lifecycle metadata.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=10000)

    def handle(self, *args, **options):
        result = ai_interaction_inventory(limit=options['limit'])
        self.stdout.write('AI interaction privacy inventory')
        for key, value in result.items():
            self.stdout.write(f'{key}: {value}')
