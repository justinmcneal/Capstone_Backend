"""Deterministic, offline-safe settings used by the pytest suite.

These environment values are intentionally set before importing the base
settings module. That prevents ``pytest`` from requiring production secrets or
constructing external service configuration during test collection.
"""

import os


os.environ["DEBUG"] = "True"
os.environ["SECRET_KEY"] = "stage9-test-secret-key-32-bytes-long"
os.environ["SECRET_PEPPER"] = "stage9-test-pepper"
os.environ["MONGODB_URI"] = ""
os.environ["MONGODB_NAME"] = "stage9_test_capstone"
os.environ["EMAIL_BACKEND"] = "django.core.mail.backends.locmem.EmailBackend"
os.environ["BLOCKCHAIN_ENABLED"] = "False"
os.environ["USE_REDIS_CACHE"] = "False"

from .settings import *  # noqa: E402,F401,F403

DEBUG = True
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
AUTH_COOKIE_SECURE = False

# No test may connect to the configured MongoDB, Redis, SMTP, or blockchain.
MONGODB_URI = ""
MONGODB_NAME = "stage9_test_capstone"
MONGODB = None
MONGO_CLIENT = None
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
BLOCKCHAIN_ENABLED = False
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
USE_REDIS_CACHE = False

# Use an in-memory SQLite database for tests to avoid DB ENGINE issues.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Speed up password hashing in tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
