import pyotp
import secrets
import hashlib
from typing import List, Tuple, Optional
import logging

logger = logging.getLogger('authentication')


class TwoFactorService:
    """
    Service for handling Two-Factor Authentication (2FA) using TOTP.
    
    Uses pyotp for TOTP generation and verification.
    Compatible with Google Authenticator, Authy, and other TOTP apps.
    """
    
    BACKUP_CODE_COUNT = 10
    BACKUP_CODE_LENGTH = 8
    ISSUER_NAME = "CapstoneApp"
    
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
            name=email,
            issuer_name=TwoFactorService.ISSUER_NAME
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
        except Exception as e:
            logger.error(f"TOTP verification error: {str(e)}")
            return False
    
    @staticmethod
    def generate_backup_codes(count: int = None) -> Tuple[List[str], List[str]]:
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
    def verify_backup_code(code: str, hashed_codes: List[str]) -> Tuple[bool, Optional[str]]:
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
    def setup_2fa(customer) -> dict:
        """
        Initialize 2FA setup for a customer.
        
        Returns:
            dict: Contains secret and provisioning_uri for QR code
        """
        secret = TwoFactorService.generate_secret()
        provisioning_uri = TwoFactorService.get_provisioning_uri(
            email=customer.email,
            secret=secret
        )
        
        # Store secret temporarily (not enabled until verified)
        customer.two_factor_secret = secret
        customer.save()
        
        logger.info(f"2FA setup initiated for {customer.email}")
        
        return {
            'secret': secret,
            'provisioning_uri': provisioning_uri,
            'manual_entry_key': secret  # For manual entry if QR scan fails
        }
    
    @staticmethod
    def confirm_2fa_setup(customer, code: str) -> Tuple[bool, Optional[List[str]]]:
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
        
        if not TwoFactorService.verify_totp(customer.two_factor_secret, code):
            return (False, None)
        
        # Generate backup codes
        plain_codes, hashed_codes = TwoFactorService.generate_backup_codes()
        
        # Enable 2FA
        customer.two_factor_enabled = True
        customer.backup_codes = hashed_codes
        customer.save()
        
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
        
        customer.two_factor_enabled = False
        customer.two_factor_secret = None
        customer.backup_codes = []
        customer.save()
        
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
            code, 
            customer.backup_codes
        )
        
        if is_valid:
            # Remove used code
            customer.backup_codes.remove(used_hash)
            customer.save()
            logger.info(f"Backup code used for {customer.email}. {len(customer.backup_codes)} remaining.")
            return True
        
        return False
    
    @staticmethod
    def regenerate_backup_codes(customer, password: str) -> Optional[List[str]]:
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
        customer.backup_codes = hashed_codes
        customer.save()
        
        logger.info(f"Backup codes regenerated for {customer.email}")
        return plain_codes
