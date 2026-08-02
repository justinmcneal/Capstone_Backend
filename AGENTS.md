# Capstone_Backend instructions

## Architecture

This is a Django + Django REST Framework API with ASGI real-time services:

- Django Channels and Daphne serve HTTP and authenticated WebSockets.
- PyMongo connects directly to MongoDB.
- Redis supports Channels, Celery, and optional caching.
- Domain apps include accounts, profiles, loans, documents, AI assistant, notifications, and analytics.
- Apps commonly organize code into `models/`, `serializers/`, `services/`, and `views/`.

This project uses PyMongo and MongoDB rather than normal Django ORM migrations. Do not introduce ORM migration assumptions.

## Security and behavior

Preserve authentication and authorization behavior, including custom JWT handling, access/refresh cookies, CSRF rules, 2FA, OTP/password recovery, consent/audit flows, session tracking, and django-axes lockout controls.

Treat the following as sensitive and do not read, expose, or casually modify them:

- `.env`, `media/`, `backups/`, `logs/`, and `dump.rdb`;
- ML training data and uploaded documents;
- wallet/private keys, Firebase credentials, and cloud credentials.

`dump.rdb` is a security concern requiring separate review. Do not remove it in ordinary work.

## Validation and operations

Do not run any state-changing command without explicit user approval, including:

- `python init_db.py`;
- migration, storage, backup, restore, or S3 scripts;
- blockchain deployment, transaction, or wallet operations;
- Celery/production deployment operations.

Preserve domain boundaries and existing API response, permission, and audit patterns.