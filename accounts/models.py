from mongoengine import Document, StringField, EmailField, BooleanField, DateTimeField, IntField, ListField
from datetime import datetime
import bcrypt


class Customer(Document):
    first_name = StringField(required=True, max_length=100)
    middle_name = StringField(max_length=100)
    last_name = StringField(required=True, max_length=100)
    email = EmailField(required=True, unique=True)
    password = StringField(required=True)
    role = StringField(default='customer', choices=['customer', 'admin'])
    verified = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)
    
    # Email verification
    verification_token = StringField()
    verification_token_expires = DateTimeField()
    verification_resend_count = IntField(default=0)
    otp_attempt_count = IntField(default=0)
    otp_last_attempt = DateTimeField()

    # Login rate limiting
    last_login_attempt = DateTimeField()
    login_attempt_count = IntField(default=0)

    # Account lockout protection
    failed_login_attempts = IntField(default=0)
    locked_until = DateTimeField()

    # Password reset fields
    password_reset_otp = StringField()
    password_reset_otp_expires = DateTimeField()
    password_reset_attempt_count = IntField(default=0)
    password_reset_last_attempt = DateTimeField()

    # Two-Factor Authentication (2FA)
    two_factor_enabled = BooleanField(default=False)
    two_factor_secret = StringField()  # Encrypted TOTP secret
    backup_codes = ListField(StringField())  # Hashed backup codes
    
    meta = {
        'collection': 'customer',
        'indexes': ['email']
    }
    
    def set_password(self, raw_password):
        self.password = bcrypt.hashpw(raw_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, raw_password):
        return bcrypt.checkpw(raw_password.encode('utf-8'), self.password.encode('utf-8'))
    
    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super(Customer, self).save(*args, **kwargs)

class BlacklistedToken(Document):
    token = StringField(required=True, unique=True)
    token_type = StringField(choices=['access', 'refresh'], default='refresh')
    blacklisted_at = DateTimeField(default=datetime.utcnow)
    expires_at = DateTimeField(required=True)
    
    meta = {
        'collection': 'blacklisted_tokens',
        'indexes': [
            'token',
            'token_type',
            {'fields': ['expires_at'], 'expireAfterSeconds': 0}
        ]
    }


class RefreshTokenEntry(Document):
    customer = StringField(required=True)  # Store customer ID as string
    token_hash = StringField(required=True)
    issued_at = DateTimeField(default=datetime.utcnow)
    expires_at = DateTimeField(required=True)

    meta = {
        'collection': 'refresh_tokens',
        'indexes': [
            'customer',
            'token_hash',
            {'fields': ['expires_at'], 'expireAfterSeconds': 0}
        ]
    }

