#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

from dotenv import load_dotenv


def main():
    """Run administrative tasks."""
    load_dotenv()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

    # Developer-friendly default: expose Django dev server to LAN devices
    # when running `python manage.py runserver` without explicit host/port.
    if len(sys.argv) == 2 and sys.argv[1] == 'runserver':
        sys.argv.append('0.0.0.0:8000')

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and"
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    if not os.environ.get('SECRET_PEPPER'):
        raise SystemExit(
            "SECRET_PEPPER environment variable is not set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
