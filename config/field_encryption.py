"""
Field-level encryption utilities for sensitive database fields.

Behavior:
- Production (DEBUG=False): FIELD_ENCRYPTION_KEY is required. Startup fails if missing/invalid.
- Development (DEBUG=True): FIELD_ENCRYPTION_KEY is optional. When missing, values pass through
  as plaintext so local development does not require key management. Production deployments
  must set FIELD_ENCRYPTION_KEY to ensure sensitive fields are never stored unencrypted.
- New values carry a non-secret primary-key identifier. Previous keys may remain readable during
  an online rotation, and strict mode rejects corruption or unavailable keys.
"""
import hashlib
from decimal import Decimal
from functools import lru_cache

from bson import BSON
from bson.decimal128 import Decimal128
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

ENCRYPTED_PREFIX = "enc::"
ENCRYPTED_BSON_PREFIX = "encbson::"
VERSIONED_ENCRYPTED_PREFIX = "enc::v2::"
VERSIONED_ENCRYPTED_BSON_PREFIX = "encbson::v2::"
_TYPE_MARKER = "__field_encryption_type__"
_DECIMAL_TYPE = "decimal"


class FieldDecryptionError(ValueError):
    """Raised when configured keys cannot authenticate encrypted field data."""


def _configured_key_values():
    primary = (getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "").strip()
    previous = getattr(settings, "FIELD_ENCRYPTION_PREVIOUS_KEYS", ()) or ()
    if isinstance(previous, str):
        previous = tuple(value.strip() for value in previous.split(",") if value.strip())
    return primary, tuple(previous)


def _key_id(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=32)
def _build_keyring(primary, previous):
    values = tuple(dict.fromkeys(value for value in (primary, *previous) if value))
    try:
        return tuple((_key_id(value), Fernet(value.encode("utf-8"))) for value in values)
    except Exception as exc:
        raise ImproperlyConfigured(
            "A field-encryption key is invalid. Generate Fernet keys with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        ) from exc


def _get_keyring():
    return _build_keyring(*_configured_key_values())


@lru_cache(maxsize=1)
def _get_fernet():
    keyring = _get_keyring()
    return keyring[0][1] if keyring else None


def is_encrypted_value(value):
    return isinstance(value, str) and value.startswith(
        (
            ENCRYPTED_PREFIX,
            ENCRYPTED_BSON_PREFIX,
            VERSIONED_ENCRYPTED_PREFIX,
            VERSIONED_ENCRYPTED_BSON_PREFIX,
        )
    )


def encrypted_value_key_id(value):
    """Return the embedded key ID, or None for plaintext/legacy ciphertext."""
    if not isinstance(value, str):
        return None
    for prefix in (VERSIONED_ENCRYPTED_PREFIX, VERSIONED_ENCRYPTED_BSON_PREFIX):
        if value.startswith(prefix):
            key_id, separator, _token = value[len(prefix) :].partition("::")
            return key_id if separator and key_id else None
    return None


def primary_key_id():
    keyring = _get_keyring()
    return keyring[0][0] if keyring else None


def is_primary_encrypted_value(value):
    key_id = encrypted_value_key_id(value)
    return bool(key_id and key_id == primary_key_id())


def encrypt_value(value):
    if value is None:
        return None
    if is_encrypted_value(value) or value == "":
        return value

    keyring = _get_keyring()
    if not keyring:
        return value
    key_id, fernet = keyring[0]

    if isinstance(value, str):
        payload = value.encode("utf-8")
        prefix = VERSIONED_ENCRYPTED_PREFIX
    elif isinstance(value, Decimal):
        payload = BSON.encode(
            {"value": {_TYPE_MARKER: _DECIMAL_TYPE, "value": str(value)}}
        )
        prefix = VERSIONED_ENCRYPTED_BSON_PREFIX
    elif (
        isinstance(value, (dict, list, tuple, Decimal128))
        or isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        # BSON preserves the native values used in Mongo documents (including
        # numeric width, Decimal128, datetimes, and ObjectIds) without lossy JSON
        # conversion. Booleans are intentionally excluded from numeric handling.
        payload = BSON.encode({"value": value})
        prefix = VERSIONED_ENCRYPTED_BSON_PREFIX
    else:
        return value

    token = fernet.encrypt(payload).decode("utf-8")
    return f"{prefix}{key_id}::{token}"


def _decryption_failure(value, reason):
    strict = getattr(settings, "FIELD_ENCRYPTION_STRICT_DECRYPTION", not settings.DEBUG)
    if strict:
        raise FieldDecryptionError(reason)
    return value


def decrypt_value(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if not is_encrypted_value(value):
        return value

    keyring = _get_keyring()
    if not keyring:
        return _decryption_failure(value, "Encrypted field cannot be read without a key")

    structured = value.startswith(
        (ENCRYPTED_BSON_PREFIX, VERSIONED_ENCRYPTED_BSON_PREFIX)
    )
    versioned_prefix = (
        VERSIONED_ENCRYPTED_BSON_PREFIX
        if structured
        else VERSIONED_ENCRYPTED_PREFIX
    )
    legacy_prefix = ENCRYPTED_BSON_PREFIX if structured else ENCRYPTED_PREFIX

    candidates = keyring
    if value.startswith(versioned_prefix):
        key_id, separator, token = value[len(versioned_prefix) :].partition("::")
        if not separator or not key_id or not token:
            return _decryption_failure(value, "Encrypted field has an invalid envelope")
        candidates = tuple(item for item in keyring if item[0] == key_id)
        if not candidates:
            return _decryption_failure(
                value, f"Encrypted field references unavailable key {key_id}"
            )
    else:
        token = value[len(legacy_prefix) :]

    for _candidate_id, fernet in candidates:
        try:
            plaintext = fernet.decrypt(token.encode("utf-8"))
            if structured:
                decoded = BSON(plaintext).decode()["value"]
                if (
                    isinstance(decoded, dict)
                    and decoded.get(_TYPE_MARKER) == _DECIMAL_TYPE
                    and set(decoded) == {_TYPE_MARKER, "value"}
                ):
                    return Decimal(decoded["value"])
                return decoded
            return plaintext.decode("utf-8")
        except (InvalidToken, KeyError, TypeError, ValueError):
            continue
    return _decryption_failure(value, "Encrypted field failed authentication")


def reencrypt_value(value):
    """Rewrite ciphertext with the primary key while preserving native value types."""
    if value is None or value == "":
        return value
    plaintext = decrypt_value(value) if is_encrypted_value(value) else value
    return encrypt_value(plaintext)


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
