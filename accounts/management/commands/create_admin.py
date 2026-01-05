from django.core.management.base import BaseCommand, CommandError
from accounts.models.admin import Admin
import getpass


class Command(BaseCommand):
    help = 'Create a new admin account'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            help='Admin username (required)',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Admin email (required)',
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Admin password (if not provided, will prompt securely)',
        )
        parser.add_argument(
            '--first-name',
            type=str,
            default='',
            help='Admin first name (optional)',
        )
        parser.add_argument(
            '--last-name',
            type=str,
            default='',
            help='Admin last name (optional)',
        )
        parser.add_argument(
            '--super-admin',
            action='store_true',
            help='Make this admin a super admin with all permissions',
        )
        parser.add_argument(
            '--noinput',
            '--no-input',
            action='store_true',
            dest='no_input',
            help='Skip interactive prompts and use command line arguments only',
        )

    def handle(self, *args, **options):
        username = options.get('username')
        email = options.get('email')
        password = options.get('password')
        first_name = options.get('first_name') or ''
        last_name = options.get('last_name') or ''
        super_admin = options.get('super_admin', False)
        no_input = options.get('no_input', False)

        # Interactive mode if not all required fields provided
        if not no_input:
            if not username:
                username = input('Username: ').strip()
            if not email:
                email = input('Email: ').strip()
            if not password:
                password = getpass.getpass('Password: ')
                password_confirm = getpass.getpass('Password (confirm): ')
                if password != password_confirm:
                    raise CommandError('Passwords do not match.')
            if not first_name:
                first_name = input('First name (optional): ').strip()
            if not last_name:
                last_name = input('Last name (optional): ').strip()
            
            if not super_admin:
                make_super = input('Make super admin? (y/N): ').strip().lower()
                super_admin = make_super == 'y'

        # Validate required fields
        if not username:
            raise CommandError('Username is required.')
        if not email:
            raise CommandError('Email is required.')
        if not password:
            raise CommandError('Password is required.')

        # Check if admin already exists
        existing = Admin.find_one({'$or': [{'username': username}, {'email': email}]})
        if existing:
            raise CommandError(f'Admin with username "{username}" or email "{email}" already exists.')

        # Create the admin
        admin = Admin(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            super_admin=super_admin,
            permissions=['*'] if super_admin else [],
        )
        admin.set_password(password)
        admin.save()

        self.stdout.write(self.style.SUCCESS(f'Successfully created admin "{username}"'))
        if super_admin:
            self.stdout.write(self.style.SUCCESS('  → Super admin with all permissions'))
        self.stdout.write(f'  → Email: {email}')
        self.stdout.write(f'  → ID: {admin.id}')
