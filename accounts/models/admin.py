from datetime import datetime
from django.conf import settings
from config.field_encryption import decrypt_fields, encrypt_fields


def get_db():
    """Helper function to get the MongoDB database instance"""
    return settings.MONGODB


# Available admin permissions
ADMIN_PERMISSIONS = [
    "create_loan_officer",  # Can create new loan officer accounts
    "manage_loan_officers",  # Can edit/deactivate loan officers
    "manage_users",  # Can lock/unlock any user account
    "view_analytics",  # Can access system-wide analytics
    "view_logs",  # Can access audit logs
    "manage_system",  # Can modify system configurations
]


class Admin:
    """
    Admin model for system administrators.

    Admins can:
    - Create and manage loan officer accounts
    - View system logs and analytics
    - Lock/unlock user accounts
    - Manage system configurations

    Super admins have all permissions automatically.
    """

    collection_name = "admins"
    encrypted_fields = (
        "two_factor_secret",
        "password_reset_otp",
    )

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.username = kwargs.get("username")
        self.email = kwargs.get("email")
        self.password = kwargs.get("password")
        self.first_name = kwargs.get("first_name", "")
        self.last_name = kwargs.get("last_name", "")
        self.role = "admin"  # Fixed role
        self.permissions = kwargs.get("permissions", [])  # List of permission strings
        self.super_admin = kwargs.get("super_admin", False)  # Full system access
        self.active = kwargs.get("active", True)
        self.created_at = kwargs.get("created_at", datetime.utcnow())
        self.updated_at = kwargs.get("updated_at", datetime.utcnow())

        # Login rate limiting
        self.last_login_attempt = kwargs.get("last_login_attempt")
        self.login_attempt_count = kwargs.get("login_attempt_count", 0)

        # Account lockout protection
        self.failed_login_attempts = kwargs.get("failed_login_attempts", 0)
        self.locked_until = kwargs.get("locked_until")

        # Two-Factor Authentication (2FA) - recommended for admins
        self.two_factor_enabled = kwargs.get("two_factor_enabled", False)
        self.two_factor_secret = kwargs.get("two_factor_secret")
        self.backup_codes = kwargs.get("backup_codes", [])

        # Password Reset OTP
        self.password_reset_otp = kwargs.get("password_reset_otp")
        self.password_reset_otp_expires = kwargs.get("password_reset_otp_expires")
        self.password_reset_attempt_count = kwargs.get(
            "password_reset_attempt_count", 0
        )
        self.password_reset_last_attempt = kwargs.get("password_reset_last_attempt")

    @property
    def id(self):
        """Get string representation of _id"""
        return str(self._id) if self._id else None

    @property
    def full_name(self):
        """Get full name"""
        name = f"{self.first_name} {self.last_name}".strip()
        return name if name else self.username

    def has_permission(self, permission):
        """Check if admin has a specific permission"""
        if self.super_admin:
            return True
        return permission in self.permissions

    def has_any_permission(self, permissions):
        """Check if admin has any of the specified permissions"""
        if self.super_admin:
            return True
        return any(p in self.permissions for p in permissions)

    def has_all_permissions(self, permissions):
        """Check if admin has all of the specified permissions"""
        if self.super_admin:
            return True
        return all(p in self.permissions for p in permissions)

    def to_dict(self):
        """Convert instance to dictionary for MongoDB operations"""
        data = {
            "username": self.username,
            "email": self.email,
            "password": self.password,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "role": self.role,
            "permissions": self.permissions,
            "super_admin": self.super_admin,
            "active": self.active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_login_attempt": self.last_login_attempt,
            "login_attempt_count": self.login_attempt_count,
            "failed_login_attempts": self.failed_login_attempts,
            "locked_until": self.locked_until,
            "two_factor_enabled": self.two_factor_enabled,
            "two_factor_secret": self.two_factor_secret,
            "backup_codes": self.backup_codes,
            "password_reset_otp": self.password_reset_otp,
            "password_reset_otp_expires": self.password_reset_otp_expires,
            "password_reset_attempt_count": self.password_reset_attempt_count,
            "password_reset_last_attempt": self.password_reset_last_attempt,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

        def __repr__(self):
            return f"<Admin id={self.id} username={self.username} email={self.email}>"

    @classmethod
    def from_dict(cls, data):
        """Create Admin instance from MongoDB document"""
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
        """Save admin to database"""
        db = get_db()
        collection = db[self.collection_name]

        self.updated_at = datetime.utcnow()
        data = self.to_dict()

        if self._id:
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id

        return self

    def delete(self):
        """Delete admin from database"""
        if self._id:
            db = get_db()
            collection = db[self.collection_name]
            collection.delete_one({"_id": self._id})

    @classmethod
    def find_one(cls, query):
        """Find one admin by query"""
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find(cls, query, **kwargs):
        """Find multiple admins by query"""
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find(query, **kwargs)
        return [cls.from_dict(doc) for doc in docs]

    @classmethod
    def create_indexes(cls):
        """Create indexes for the collection"""
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("username", unique=True)
        collection.create_index("email", unique=True)
