from django.core.management.base import BaseCommand, CommandError
from accounts.models.admin import Admin, ADMIN_PERMISSIONS
import getpass


class Command(BaseCommand):
    help = "Create a new admin account"

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            type=str,
            help="Admin username (required)",
        )
        parser.add_argument(
            "--email",
            type=str,
            help="Admin email (required)",
        )
        parser.add_argument(
            "--password",
            type=str,
            help="Admin password (if not provided, will prompt securely)",
        )
        parser.add_argument(
            "--first-name",
            type=str,
            default="",
            help="Admin first name (optional)",
        )
        parser.add_argument(
            "--last-name",
            type=str,
            default="",
            help="Admin last name (optional)",
        )
        parser.add_argument(
            "--super-admin",
            action="store_true",
            help="Make this admin a super admin with all permissions",
        )
        parser.add_argument(
            "--permissions",
            type=str,
            nargs="*",
            help=f'Permissions for non-super admins. Available: {", ".join(ADMIN_PERMISSIONS)}',
        )
        parser.add_argument(
            "--all-permissions",
            action="store_true",
            help="Grant all available permissions (for non-super admins)",
        )
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_true",
            dest="no_input",
            help="Skip interactive prompts and use command line arguments only",
        )

    def handle(self, *args, **options):
        username = options.get("username")
        email = options.get("email")
        password = options.get("password")
        first_name = options.get("first_name") or ""
        last_name = options.get("last_name") or ""
        super_admin = options.get("super_admin", False)
        permissions = options.get("permissions") or []
        all_permissions = options.get("all_permissions", False)
        no_input = options.get("no_input", False)

        # Interactive mode if not all required fields provided
        if not no_input:
            if not username:
                username = input("Username: ").strip()
            if not email:
                email = input("Email: ").strip()
            if not password:
                password = getpass.getpass("Password: ")
                password_confirm = getpass.getpass("Password (confirm): ")
                if password != password_confirm:
                    raise CommandError("Passwords do not match.")
            if not first_name:
                first_name = input("First name (optional): ").strip()
            if not last_name:
                last_name = input("Last name (optional): ").strip()

            if not super_admin:
                make_super = input("Make super admin? (y/N): ").strip().lower()
                super_admin = make_super == "y"

            # Prompt for permissions if not super admin and none provided
            if not super_admin and not permissions and not all_permissions:
                self.stdout.write("\nAvailable permissions:")
                for i, perm in enumerate(ADMIN_PERMISSIONS, 1):
                    self.stdout.write(f"  {i}. {perm}")
                self.stdout.write("  A. All permissions")
                self.stdout.write("")
                perm_input = input(
                    "Select permissions (comma-separated numbers, A for all, or Enter for all): "
                ).strip()
                if not perm_input or perm_input.upper() == "A":
                    all_permissions = True
                else:
                    for num in perm_input.split(","):
                        num = num.strip()
                        if num.isdigit():
                            idx = int(num) - 1
                            if 0 <= idx < len(ADMIN_PERMISSIONS):
                                permissions.append(ADMIN_PERMISSIONS[idx])
                            else:
                                self.stderr.write(
                                    f"  Warning: Invalid number {num}, skipping"
                                )

        # Validate required fields
        if not username:
            raise CommandError("Username is required.")
        if not email:
            raise CommandError("Email is required.")
        if not password:
            raise CommandError("Password is required.")

        # Determine final permissions
        if super_admin:
            final_permissions = ["*"]
        elif all_permissions:
            final_permissions = list(ADMIN_PERMISSIONS)
        elif permissions:
            # Validate provided permissions
            invalid = [p for p in permissions if p not in ADMIN_PERMISSIONS]
            if invalid:
                raise CommandError(
                    f'Invalid permissions: {", ".join(invalid)}. Available: {", ".join(ADMIN_PERMISSIONS)}'
                )
            final_permissions = permissions
        else:
            # Default: grant all permissions for non-super admins created via CLI
            final_permissions = list(ADMIN_PERMISSIONS)

        # Check if admin already exists
        existing = Admin.find_one({"$or": [{"username": username}, {"email": email}]})
        if existing:
            raise CommandError(
                f'Admin with username "{username}" or email "{email}" already exists.'
            )

        # Create the admin
        admin = Admin(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            super_admin=super_admin,
            permissions=final_permissions,
        )
        admin.set_password(password)
        admin.save()

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created admin "{username}"')
        )
        if super_admin:
            self.stdout.write(
                self.style.SUCCESS("  → Super admin with all permissions")
            )
        else:
            self.stdout.write(f'  → Permissions: {", ".join(final_permissions)}')
        self.stdout.write(f"  → Email: {email}")
        self.stdout.write(f"  → ID: {admin.id}")
