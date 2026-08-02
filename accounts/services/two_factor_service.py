import base64
import hashlib
import io
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from hmac import compare_digest

import pyotp
import qrcode
from django.conf import settings

from accounts.utils.exception_types import NON_FATAL_EXCEPTIONS

logger = logging.getLogger("authentication")


class TwoFactorService:
    """
    Service for handling Two-Factor Authentication (2FA) using TOTP.

    Uses pyotp for TOTP generation and verification.
    Compatible with Google Authenticator, Authy, and other TOTP apps.
    """

    BACKUP_CODE_COUNT = 10
    BACKUP_CODE_LENGTH = 8
    ISSUER_NAME = "CapstoneApp"
    SETUP_EXPIRY_MINUTES = 10

    @staticmethod
    def generate_secret() -> str:
        """
        Generate a new TOTP secret for a user.

        Returns:
            str: Base32 encoded secret key
        """
        return pyotp.random_base32()

    @staticmethod
    def get_provisioning_uri(email: str, secret: str) -> str:
        """
        Generate the provisioning URI for QR code generation.
        This URI is scanned by authenticator apps.

        Args:
            email: User's email address
            secret: TOTP secret key

        Returns:
            str: otpauth:// URI for QR code
        """
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(
            name=email, issuer_name=TwoFactorService.ISSUER_NAME
        )

    @staticmethod
    def verify_totp(secret: str, code: str) -> bool:
        """
        Verify a TOTP code against the secret.

        Args:
            secret: User's TOTP secret
            code: 6-digit code from authenticator app

        Returns:
            bool: True if code is valid
        """
        if not secret or not code:
            return False
        try:
            totp = pyotp.TOTP(secret)
            # valid_window=1 allows for slight time drift (30 seconds before/after)
            return totp.verify(code, valid_window=1)
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"TOTP verification error: {e!s}")
            return False

    @staticmethod
    def _matching_totp_timestep(secret: str, code: str) -> int | None:
        """Return the accepted timestep, allowing one interval of clock drift."""
        if not secret or not code:
            return None
        try:
            totp = pyotp.TOTP(secret)
            current_timestep = int(totp.timecode(datetime.now(timezone.utc)))
            for offset in (-1, 0, 1):
                timestep = current_timestep + offset
                if timestep >= 0 and compare_digest(
                    totp.generate_otp(timestep), str(code)
                ):
                    return timestep
        except NON_FATAL_EXCEPTIONS as exc:
            logger.error("TOTP timestep verification error: %s", exc)
        return None

    @staticmethod
    def verify_and_consume_totp(customer, code: str) -> bool:
        """Accept a valid TOTP timestep at most once for an account."""
        timestep = TwoFactorService._matching_totp_timestep(
            customer.two_factor_secret, code
        )
        if timestep is None:
            return False

        now = datetime.now(timezone.utc)
        result = settings.MONGODB[customer.collection_name].update_one(
            {
                "_id": customer._id,
                "two_factor_enabled": True,
                "$or": [
                    {"last_totp_timestep": {"$exists": False}},
                    {"last_totp_timestep": None},
                    {"last_totp_timestep": {"$lt": timestep}},
                ],
            },
            {
                "$set": {
                    "last_totp_timestep": timestep,
                    "updated_at": now,
                }
            },
        )
        if result.modified_count != 1:
            return False
        customer.last_totp_timestep = timestep
        return True

    @staticmethod
    def generate_backup_codes(count: int | None = None) -> tuple[list[str], list[str]]:
        """
        Generate one-time backup codes for 2FA recovery.

        Args:
            count: Number of backup codes to generate

        Returns:
            Tuple of (plain_codes, hashed_codes)
            - plain_codes: Show to user once
            - hashed_codes: Store in database
        """
        if count is None:
            count = TwoFactorService.BACKUP_CODE_COUNT

        plain_codes = []
        hashed_codes = []

        for _ in range(count):
            # Generate readable backup code (e.g., "ABCD-1234")
            code = secrets.token_hex(TwoFactorService.BACKUP_CODE_LENGTH // 2).upper()
            formatted_code = f"{code[:4]}-{code[4:]}"

            plain_codes.append(formatted_code)
            hashed_codes.append(TwoFactorService._hash_backup_code(formatted_code))

        return plain_codes, hashed_codes

    @staticmethod
    def _hash_backup_code(code: str) -> str:
        """Hash a backup code for secure storage."""
        # Normalize: remove dashes and uppercase
        normalized = code.replace("-", "").upper()
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def verify_backup_code(
        code: str, hashed_codes: list[str]
    ) -> tuple[bool, str | None]:
        """
        Verify a backup code against stored hashes.

        Args:
            code: Backup code entered by user
            hashed_codes: List of hashed backup codes from database

        Returns:
            Tuple of (is_valid, used_hash)
            - is_valid: True if code matches
            - used_hash: The hash that was used (to remove from list)
        """
        code_hash = TwoFactorService._hash_backup_code(code)

        if code_hash in hashed_codes:
            return (True, code_hash)

        return (False, None)

    @staticmethod
    def setup_2fa(customer, password: str | None = None) -> dict | None:
        """
        Initialize 2FA setup for a customer.

        Returns:
            dict: Contains secret and provisioning_uri for QR code
        """
        if password is not None and not customer.check_password(password):
            return None

        secret = TwoFactorService.generate_secret()
        setup_id = str(uuid.uuid4())
        setup_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=TwoFactorService.SETUP_EXPIRY_MINUTES
        )
        provisioning_uri = TwoFactorService.get_provisioning_uri(
            email=customer.email, secret=secret
        )
        qr_code_data_url = TwoFactorService.generate_qr_code_data_url(provisioning_uri)

        # Store the pending secret without enabling 2FA. A setup identity and
        # expiration prevent stale confirmation requests from enabling a newer setup.
        customer.two_factor_secret = secret
        encrypted_secret = customer.to_dict()["two_factor_secret"]
        result = settings.MONGODB[customer.collection_name].update_one(
            {"_id": customer._id, "two_factor_enabled": {"$ne": True}},
            {
                "$set": {
                    "two_factor_secret": encrypted_secret,
                    "two_factor_setup_id": setup_id,
                    "two_factor_setup_expires_at": setup_expires_at,
                    "last_totp_timestep": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        if result.modified_count != 1:
            return None
        customer.two_factor_setup_id = setup_id
        customer.two_factor_setup_expires_at = setup_expires_at
        customer.last_totp_timestep = None

        logger.info(f"2FA setup initiated for {customer.email}")

        return {
            "secret": secret,
            "provisioning_uri": provisioning_uri,
            "manual_entry_key": secret,  # For manual entry if QR scan fails
            "qr_code_data_url": qr_code_data_url,
        }

    @staticmethod
    def generate_qr_code_data_url(content: str) -> str:
        """
        Generate a PNG QR code as a data URL so frontend does not depend on
        third-party QR image services.
        """
        if not content:
            return ""

        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=8,
                border=2,
            )
            qr.add_data(content)
            qr.make(fit=True)

            image = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return f"data:image/png;base64,{encoded}"
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"QR code generation error: {e!s}")
            return ""

    @staticmethod
    def confirm_2fa_setup(customer, code: str) -> tuple[bool, list[str] | None]:
        """
        Confirm 2FA setup by verifying the first code.

        Args:
            customer: Customer document
            code: First TOTP code from authenticator app

        Returns:
            Tuple of (success, backup_codes)
            - success: True if verification passed
            - backup_codes: List of backup codes (only on success)
        """
        if not customer.two_factor_secret:
            return (False, None)

        setup_expires_at = getattr(customer, "two_factor_setup_expires_at", None)
        if setup_expires_at is None:
            return (False, None)
        if setup_expires_at.tzinfo is None:
            setup_expires_at = setup_expires_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if setup_expires_at <= now:
            return (False, None)

        timestep = TwoFactorService._matching_totp_timestep(
            customer.two_factor_secret, code
        )
        if timestep is None:
            return (False, None)

        # Generate backup codes
        plain_codes, hashed_codes = TwoFactorService.generate_backup_codes()

        result = settings.MONGODB[customer.collection_name].update_one(
            {
                "_id": customer._id,
                "two_factor_enabled": {"$ne": True},
                "two_factor_setup_id": customer.two_factor_setup_id,
                "two_factor_setup_expires_at": {"$gte": now},
            },
            {
                "$set": {
                    "two_factor_enabled": True,
                    "backup_codes": hashed_codes,
                    "last_totp_timestep": timestep,
                    "two_factor_setup_id": None,
                    "two_factor_setup_expires_at": None,
                    "updated_at": now,
                }
            },
        )
        if result.modified_count != 1:
            return (False, None)

        customer.two_factor_enabled = True
        customer.backup_codes = hashed_codes
        customer.last_totp_timestep = timestep
        customer.two_factor_setup_id = None
        customer.two_factor_setup_expires_at = None

        logger.info(f"2FA enabled for {customer.email}")

        return (True, plain_codes)

    @staticmethod
    def disable_2fa(customer, password: str) -> bool:
        """
        Disable 2FA for a customer (requires password verification).

        Args:
            customer: Customer document
            password: Current password for verification

        Returns:
            bool: True if 2FA was disabled
        """
        if not customer.check_password(password):
            return False

        result = settings.MONGODB[customer.collection_name].update_one(
            {"_id": customer._id, "two_factor_enabled": True},
            {
                "$set": {
                    "two_factor_enabled": False,
                    "two_factor_secret": None,
                    "backup_codes": [],
                    "last_totp_timestep": None,
                    "two_factor_setup_id": None,
                    "two_factor_setup_expires_at": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        if result.modified_count != 1:
            return False
        customer.two_factor_enabled = False
        customer.two_factor_secret = None
        customer.backup_codes = []
        customer.last_totp_timestep = None
        customer.two_factor_setup_id = None
        customer.two_factor_setup_expires_at = None

        logger.info(f"2FA disabled for {customer.email}")
        return True

    @staticmethod
    def use_backup_code(customer, code: str) -> bool:
        """
        Use a backup code for 2FA verification.
        The code is consumed (removed) after use.

        Args:
            customer: Customer document
            code: Backup code entered by user

        Returns:
            bool: True if code was valid and consumed
        """
        is_valid, used_hash = TwoFactorService.verify_backup_code(
            code, customer.backup_codes
        )

        if is_valid:
            now = datetime.now(timezone.utc)
            result = settings.MONGODB[customer.collection_name].update_one(
                {"_id": customer._id, "backup_codes": used_hash},
                {"$pull": {"backup_codes": used_hash}, "$set": {"updated_at": now}},
            )
            if result.modified_count != 1:
                return False
            customer.backup_codes = [
                stored_hash
                for stored_hash in customer.backup_codes
                if stored_hash != used_hash
            ]
            logger.info(
                f"Backup code used for {customer.email}. {len(customer.backup_codes)} remaining."
            )
            return True

        return False

    @staticmethod
    def regenerate_backup_codes(customer, password: str) -> list[str] | None:
        """
        Regenerate backup codes (requires password verification).

        Args:
            customer: Customer document
            password: Current password for verification

        Returns:
            List of new backup codes, or None if password invalid
        """
        if not customer.check_password(password):
            return None

        plain_codes, hashed_codes = TwoFactorService.generate_backup_codes()
        settings.MONGODB[customer.collection_name].update_one(
            {"_id": customer._id},
            {
                "$set": {
                    "backup_codes": hashed_codes,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        customer.backup_codes = hashed_codes

        logger.info(f"Backup codes regenerated for {customer.email}")
        return plain_codes
