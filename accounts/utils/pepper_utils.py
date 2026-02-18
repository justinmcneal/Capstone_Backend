"""
Pepper utility for password hashing.

Adds an application-level pepper (via HMAC-SHA256) on top of bcrypt's
automatic salting.  The pepper is read from the SECRET_PEPPER environment
variable and must NEVER be stored in the database.

Usage (in any model):
    from accounts.utils.pepper_utils import hash_password, verify_password

    class MyModel:
        def set_password(self, raw_password):
            self.password = hash_password(raw_password)

        def check_password(self, raw_password):
            return verify_password(raw_password, self.password)
"""

import hmac
import hashlib
import os
import logging

import bcrypt

logger = logging.getLogger('authentication')

# ---------------------------------------------------------------------------
# Lazy pepper loader — evaluated on first use, not at import time.
# This avoids errors when the module is imported before load_dotenv() runs.
# ---------------------------------------------------------------------------
_pepper_cache = None


def _get_pepper() -> str:
    """Return the SECRET_PEPPER, loading it from the environment on first call."""
    global _pepper_cache
    if _pepper_cache is None:
        _pepper_cache = os.environ.get('SECRET_PEPPER', '')
        if not _pepper_cache:
            raise ValueError(
                "SECRET_PEPPER environment variable is not set! "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        logger.info("SECRET_PEPPER loaded successfully.")
    return _pepper_cache


def apply_pepper(raw_password: str) -> str:
    """
    Combine a raw password with the application pepper using HMAC-SHA256.

    Why HMAC instead of simple concatenation?
    - HMAC is resistant to length-extension attacks.
    - It produces a fixed 64-char hex string, safely under bcrypt's
      72-byte input limit (avoids silent truncation of long passwords).
    - It is the cryptographically correct way to key a hash.
    """
    pepper = _get_pepper()
    return hmac.new(
        key=pepper.encode('utf-8'),
        msg=raw_password.encode('utf-8'),
        digestmod=hashlib.sha256,
    ).hexdigest()


def hash_password(raw_password: str) -> str:
    """
    Hash a password with pepper + bcrypt (used during signup / password reset).

    Flow:  raw_password  ->  HMAC(pepper, password)  ->  bcrypt(peppered, salt)
    """
    peppered = apply_pepper(raw_password)
    hashed = bcrypt.hashpw(peppered.encode('utf-8'), bcrypt.gensalt())
    return hashed.decode('utf-8')


def verify_password(raw_password: str, stored_hash: str) -> bool:
    """
    Verify a password against a stored bcrypt hash (used during login).

    Flow:  raw_password  ->  HMAC(pepper, password)  ->  bcrypt.checkpw(peppered, stored)
    """
    peppered = apply_pepper(raw_password)
    return bcrypt.checkpw(peppered.encode('utf-8'), stored_hash.encode('utf-8'))
