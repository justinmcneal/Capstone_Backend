from mongoengine import Document, StringField, EmailField, BooleanField, DateTimeField, IntField
from datetime import datetime
import bcrypt


class Customer(Document):
    first_name = StringField(required=True, max_length=100)
    middle_name = StringField(max_length=100)
    last_name = StringField(required=True, max_length=100)
    email = EmailField(required=True, unique=True)
    password = StringField(required=True)
    verified = BooleanField(default=False)
    # two_factor_enabled = BooleanField(default=False) (wait muna)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)
    
    #email verification
    verification_token = StringField()
    verification_token_expires = DateTimeField()
    verification_resend_count = IntField(default=0)
    otp_attempt_count = IntField(default=0)
    otp_last_attempt = DateTimeField()

    # login rate limiting
    last_login_attempt = DateTimeField()
    login_attempt_count = IntField(default=0)
    
    meta = {
        'collection': 'customer',
        'indexes': ['email']
    }
    
    def set_password(self, raw_password):
        """Hash and set the password"""
        self.password = bcrypt.hashpw(raw_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, raw_password):
        """Verify password"""
        return bcrypt.checkpw(raw_password.encode('utf-8'), self.password.encode('utf-8'))
    
    def save(self, *args, **kwargs):
        """Override save to update timestamp"""
        self.updated_at = datetime.utcnow()
        return super(Customer, self).save(*args, **kwargs)

class BlacklistedToken(Document):
    """Store blacklisted refresh tokens"""
    token = StringField(required=True, unique=True)
    blacklisted_at = DateTimeField(default=datetime.utcnow)
    expires_at = DateTimeField(required=True)
    
    meta = {
        'collection': 'blacklisted_tokens',
        'indexes': [
            'token',
            {'fields': ['expires_at'], 'expireAfterSeconds': 0}
        ]
    }


class RefreshTokenEntry(Document):
    """Store issued refresh tokens or their hashes per customer"""
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

