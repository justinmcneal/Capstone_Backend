"""
Field-level encryption utilities for sensitive database fields.

Behavior:
- Production (DEBUG=False): FIELD_ENCRYPTION_KEY is required. Startup fails if missing/invalid.
- Development (DEBUG=True): FIELD_ENCRYPTION_KEY is optional. When missing, values pass through
  as plaintext so local development does not require key management. Production deployments
  must set FIELD_ENCRYPTION_KEY to ensure sensitive fields are never stored unencrypted.
"""
from functools import lru_cache

from bson import BSON
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

ENCRYPTED_PREFIX = "enc::"
ENCRYPTED_BSON_PREFIX = "encbson::"


@lru_cache(maxsize=1)
def _get_fernet():
    key = (getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        return None

    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is invalid. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        ) from exc


def is_encrypted_value(value):
    return isinstance(value, str) and value.startswith(
        (ENCRYPTED_PREFIX, ENCRYPTED_BSON_PREFIX)
    )


def encrypt_value(value):
    if value is None:
        return None
    if is_encrypted_value(value) or value == "":
        return value

    fernet = _get_fernet()
    if fernet is None:
        return value

    if isinstance(value, str):
        payload = value.encode("utf-8")
        prefix = ENCRYPTED_PREFIX
    elif isinstance(value, (dict, list, tuple)):
        # BSON preserves the native values used in Mongo documents (including
        # datetimes and ObjectIds) without lossy JSON conversion.
        payload = BSON.encode({"value": value})
        prefix = ENCRYPTED_BSON_PREFIX
    else:
        return value

    token = fernet.encrypt(payload).decode("utf-8")
    return f"{prefix}{token}"


def decrypt_value(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if not is_encrypted_value(value):
        return value

    fernet = _get_fernet()
    if fernet is None:
        return value

    structured = value.startswith(ENCRYPTED_BSON_PREFIX)
    prefix = ENCRYPTED_BSON_PREFIX if structured else ENCRYPTED_PREFIX
    token = value[len(prefix) :]
    try:
        plaintext = fernet.decrypt(token.encode("utf-8"))
        if structured:
            return BSON(plaintext).decode()["value"]
        return plaintext.decode("utf-8")
    except (InvalidToken, KeyError, TypeError, ValueError):
        return value


def encrypt_fields(data, fields):
    if not data or not fields:
        return data

    encrypted = dict(data)
    for field in fields:
        if field in encrypted:
            encrypted[field] = encrypt_value(encrypted.get(field))
    return encrypted


def decrypt_fields(data, fields):
    if not data or not fields:
        return data

    decrypted = dict(data)
    for field in fields:
        if field in decrypted:
            decrypted[field] = decrypt_value(decrypted.get(field))
    return decrypted
