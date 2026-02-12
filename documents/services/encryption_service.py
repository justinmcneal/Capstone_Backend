from __future__ import annotations

import base64
import os

from config.security_events import log_security_event


class DocumentEncryptionError(Exception):
    """Raised when document encryption/decryption fails."""


class DocumentEncryptionService:
    ALGORITHM = "aes-256-gcm"
    VERSION = "v2"
    ENV_KEY_NAME = "DOCUMENT_ENCRYPTION_KEY"
    NONCE_LENGTH = 12
    LEGACY_FERNET_ALGORITHM = "fernet"

    @classmethod
    def _get_legacy_fernet_cipher(cls):
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise DocumentEncryptionError(
                "cryptography package is required for document encryption"
            ) from exc

        key = os.getenv(cls.ENV_KEY_NAME, "").strip()
        if not key:
            raise DocumentEncryptionError(
                f"{cls.ENV_KEY_NAME} is not configured. Document encryption is required."
            )

        return Fernet(key.encode("utf-8"))

    @classmethod
    def _get_aes_key(cls) -> bytes:
        key = os.getenv(cls.ENV_KEY_NAME, "").strip()
        if not key:
            raise DocumentEncryptionError(
                f"{cls.ENV_KEY_NAME} is not configured. Document encryption is required."
            )

        # Preferred format: URL-safe base64 encoded 32-byte key
        try:
            decoded = base64.urlsafe_b64decode(key.encode("utf-8"))
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass

        # Optional fallback: 64-char hex key
        try:
            decoded = bytes.fromhex(key)
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass

        raise DocumentEncryptionError(
            f"Invalid {cls.ENV_KEY_NAME}. Provide base64/hex encoded 32-byte key."
        )

    @classmethod
    def _get_aesgcm_cipher(cls):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise DocumentEncryptionError(
                "cryptography package is required for document encryption"
            ) from exc

        key = cls._get_aes_key()
        return AESGCM(key)

    @classmethod
    def encrypt(cls, plaintext: bytes, event_details: dict | None = None) -> bytes:
        try:
            cipher = cls._get_aesgcm_cipher()
            nonce = os.urandom(cls.NONCE_LENGTH)
            encrypted = nonce + cipher.encrypt(nonce, plaintext, None)
            log_security_event(
                event="document_encryption_triggered",
                outcome="success",
                details=event_details or {},
            )
            return encrypted
        except Exception as exc:
            log_security_event(
                event="document_encryption_triggered",
                outcome="error",
                details={"reason": str(exc)},
            )
            raise DocumentEncryptionError("Document encryption failed") from exc

    @classmethod
    def decrypt(
        cls,
        ciphertext: bytes,
        event_details: dict | None = None,
        algorithm: str | None = None,
    ) -> bytes:
        algo = (algorithm or cls.ALGORITHM).lower()
        try:
            if algo == cls.LEGACY_FERNET_ALGORITHM:
                cipher = cls._get_legacy_fernet_cipher()
                decrypted = cipher.decrypt(ciphertext)
            else:
                if len(ciphertext) <= cls.NONCE_LENGTH:
                    raise DocumentEncryptionError("Encrypted payload is too short")
                nonce = ciphertext[: cls.NONCE_LENGTH]
                payload = ciphertext[cls.NONCE_LENGTH :]
                cipher = cls._get_aesgcm_cipher()
                decrypted = cipher.decrypt(nonce, payload, None)

            log_security_event(
                event="document_decryption_triggered",
                outcome="success",
                details=event_details or {},
            )
            return decrypted
        except Exception as exc:
            error_type = type(exc).__name__.lower()
            is_auth_failure = "invalidtag" in error_type or "invalidtoken" in error_type
            log_security_event(
                event="document_decryption_triggered",
                outcome="blocked" if is_auth_failure else "error",
                details={
                    "reason": "invalid_ciphertext_or_key" if is_auth_failure else str(exc),
                    "algorithm": algo,
                },
            )
            if is_auth_failure:
                raise DocumentEncryptionError("Invalid encrypted document data") from exc
            raise DocumentEncryptionError("Document decryption failed") from exc
