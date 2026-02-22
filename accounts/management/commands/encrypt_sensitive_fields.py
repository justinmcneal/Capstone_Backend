from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.field_encryption import encrypt_value, is_encrypted_value


FIELD_MAP = {
    'customer': [
        'verification_token',
        'password_reset_otp',
        'two_factor_secret',
    ],
    'loan_officers': [
        'phone',
        'two_factor_secret',
        'password_reset_otp',
    ],
    'admins': [
        'two_factor_secret',
        'password_reset_otp',
    ],
    'customer_profiles': [
        'address_line1',
        'address_line2',
        'barangay',
        'city_municipality',
        'province',
        'zip_code',
        'emergency_contact_name',
        'emergency_contact_phone',
    ],
    'business_profiles': [
        'business_address',
        'business_barangay',
        'business_city',
        'business_province',
        'registration_number',
    ],
    'documents': [
        'original_filename',
        'file_path',
        'rejection_reason',
        'notes',
        'description',
        'reupload_reason',
    ],
    'loan_applications': [
        'purpose',
        'officer_notes',
        'rejection_reason',
        'missing_documents_reason',
        'disbursement_reference',
    ],
}


class Command(BaseCommand):
    help = 'Encrypts existing plaintext values for configured sensitive MongoDB fields.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Scan and report records that would be updated without writing changes.',
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'FIELD_ENCRYPTION_KEY', ''):
            raise CommandError(
                'FIELD_ENCRYPTION_KEY is not set. Configure it in your environment first.'
            )

        db = settings.MONGODB
        if db is None:
            raise CommandError('MongoDB connection is not available (settings.MONGODB is None).')

        dry_run = options['dry_run']
        total_docs_scanned = 0
        total_docs_updated = 0
        total_fields_encrypted = 0

        for collection_name, fields in FIELD_MAP.items():
            collection = db[collection_name]
            docs_scanned = 0
            docs_updated = 0
            fields_encrypted = 0

            projection = {field: 1 for field in fields}
            cursor = collection.find({}, projection)

            for doc in cursor:
                docs_scanned += 1
                total_docs_scanned += 1

                updates = {}
                for field in fields:
                    value = doc.get(field)
                    if not isinstance(value, str) or value == '':
                        continue
                    if is_encrypted_value(value):
                        continue

                    encrypted = encrypt_value(value)
                    if encrypted != value:
                        updates[field] = encrypted

                if not updates:
                    continue

                docs_updated += 1
                total_docs_updated += 1
                fields_encrypted += len(updates)
                total_fields_encrypted += len(updates)

                if not dry_run:
                    collection.update_one({'_id': doc['_id']}, {'$set': updates})

            mode = 'DRY-RUN' if dry_run else 'UPDATED'
            self.stdout.write(
                f'[{mode}] {collection_name}: scanned={docs_scanned}, '
                f'documents_changed={docs_updated}, fields_encrypted={fields_encrypted}'
            )

        self.stdout.write(self.style.SUCCESS('Done'))
        self.stdout.write(
            self.style.SUCCESS(
                f'Summary: scanned={total_docs_scanned}, '
                f'documents_changed={total_docs_updated}, fields_encrypted={total_fields_encrypted}'
            )
        )
