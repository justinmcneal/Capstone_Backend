from datetime import datetime
from django.conf import settings
from config.field_encryption import decrypt_fields, encrypt_fields


def get_db():
    """Helper function to get the MongoDB database instance"""
    return settings.MONGODB


class Customer:
    """Customer model using PyMongo - represents MSME users"""

    collection_name = "customer"
    encrypted_fields = (
        "verification_token",
        "password_reset_otp",
        "two_factor_secret",
    )

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.first_name = kwargs.get("first_name")
        self.middle_name = kwargs.get("middle_name", "")
        self.last_name = kwargs.get("last_name")
        self.email = kwargs.get("email")
        self.password = kwargs.get("password")
        self.role = kwargs.get("role", "customer")
        self.verified = kwargs.get("verified", False)
        self.created_at = kwargs.get("created_at", datetime.utcnow())
        self.updated_at = kwargs.get("updated_at", datetime.utcnow())
        self.phone = kwargs.get("phone", "")  # Phone number (records only)
        self.language = kwargs.get("language", "en")  # Language preference (en, tl)

        # Email verification
        self.verification_token = kwargs.get("verification_token")
        self.verification_token_expires = kwargs.get("verification_token_expires")
        self.verification_resend_count = kwargs.get("verification_resend_count", 0)
        self.otp_attempt_count = kwargs.get("otp_attempt_count", 0)
        self.otp_last_attempt = kwargs.get("otp_last_attempt")

        # Login rate limiting
        self.last_login_attempt = kwargs.get("last_login_attempt")
        self.login_attempt_count = kwargs.get("login_attempt_count", 0)

        # Account lockout protection
        self.failed_login_attempts = kwargs.get("failed_login_attempts", 0)
        self.locked_until = kwargs.get("locked_until")

        # Password reset fields
        self.password_reset_otp = kwargs.get("password_reset_otp")
        self.password_reset_otp_expires = kwargs.get("password_reset_otp_expires")
        self.password_reset_attempt_count = kwargs.get(
            "password_reset_attempt_count", 0
        )
        self.password_reset_last_attempt = kwargs.get("password_reset_last_attempt")

        # Two-Factor Authentication (2FA)
        self.two_factor_enabled = kwargs.get("two_factor_enabled", False)
        self.two_factor_secret = kwargs.get("two_factor_secret")
        self.backup_codes = kwargs.get("backup_codes", [])

        # Notification preferences
        self.notification_preferences = kwargs.get(
            "notification_preferences",
            {
                "email_loan_updates": True,
                "email_payment_reminders": True,
                "email_promotions": False,
            },
        )

    @property
    def id(self):
        """Get string representation of _id"""
        return str(self._id) if self._id else None

    @property
    def full_name(self):
        """Get full name combining first, middle (if exists), and last name"""
        parts = [self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        parts.append(self.last_name)
        return " ".join(filter(None, parts))

    def to_dict(self):
        """Convert instance to dictionary for MongoDB operations"""
        data = {
            "first_name": self.first_name,
            "middle_name": self.middle_name,
            "last_name": self.last_name,
            "email": self.email,
            "password": self.password,
            "role": self.role,
            "verified": self.verified,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "phone": self.phone,
            "language": self.language,
            "verification_token": self.verification_token,
            "verification_token_expires": self.verification_token_expires,
            "verification_resend_count": self.verification_resend_count,
            "otp_attempt_count": self.otp_attempt_count,
            "otp_last_attempt": self.otp_last_attempt,
            "last_login_attempt": self.last_login_attempt,
            "login_attempt_count": self.login_attempt_count,
            "failed_login_attempts": self.failed_login_attempts,
            "locked_until": self.locked_until,
            "password_reset_otp": self.password_reset_otp,
            "password_reset_otp_expires": self.password_reset_otp_expires,
            "password_reset_attempt_count": self.password_reset_attempt_count,
            "password_reset_last_attempt": self.password_reset_last_attempt,
            "two_factor_enabled": self.two_factor_enabled,
            "two_factor_secret": self.two_factor_secret,
            "backup_codes": self.backup_codes,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        """Create Customer instance from MongoDB document"""
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))

    def set_password(self, raw_password):
        """Hash and set password (peppered + bcrypt)"""
        from accounts.utils.pepper_utils import hash_password

        self.password = hash_password(raw_password)

    def check_password(self, raw_password):
        """Verify password (peppered + bcrypt)"""
        from accounts.utils.pepper_utils import verify_password

        return verify_password(raw_password, self.password)

    def save(self):
        """Save customer to database"""
        db = get_db()
        collection = db[self.collection_name]

        self.updated_at = datetime.utcnow()
        data = self.to_dict()

        if self._id:
            # Update existing document
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            # Insert new document
            result = collection.insert_one(data)
            self._id = result.inserted_id

        return self

    def delete(self):
        """Delete customer from database"""
        if self._id:
            db = get_db()
            collection = db[self.collection_name]
            collection.delete_one({"_id": self._id})

    @classmethod
    def find_one(cls, query):
        """Find one customer by query"""
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find(cls, query, **kwargs):
        """Find multiple customers by query"""
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find(query, **kwargs)
        return [cls.from_dict(doc) for doc in docs]

    @classmethod
    def create_indexes(cls):
        """Create indexes for the collection"""
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("email", unique=True)
