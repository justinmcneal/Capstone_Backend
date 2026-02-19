from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


ENCRYPTED_PREFIX = 'enc::'


@lru_cache(maxsize=1)
def _get_fernet():
    key = (getattr(settings, 'FIELD_ENCRYPTION_KEY', '') or '').strip()
    if not key:
        return None

    try:
        return Fernet(key.encode('utf-8'))
    except Exception as exc:
        raise ImproperlyConfigured(
            'FIELD_ENCRYPTION_KEY is invalid. Generate one with: '
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        ) from exc


def is_encrypted_value(value):
    return isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX)


def encrypt_value(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if value == '' or is_encrypted_value(value):
        return value

    fernet = _get_fernet()
    if fernet is None:
        return value

    token = fernet.encrypt(value.encode('utf-8')).decode('utf-8')
    return f'{ENCRYPTED_PREFIX}{token}'


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

    token = value[len(ENCRYPTED_PREFIX):]
    try:
        return fernet.decrypt(token.encode('utf-8')).decode('utf-8')
    except InvalidToken:
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
