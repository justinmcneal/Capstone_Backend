import uuid
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from django.conf import settings
from pymongo import ReturnDocument

from accounts.models import Consent, Customer
from accounts.models.activity import ActiveSession, LoginActivity
from accounts.services.otp_service import OTPService
from accounts.utils.email_utils import EmailUtils
from accounts.utils.identity_policy import assert_email_available_globally
from accounts.utils.token_utils import TokenUtils
from analytics.models import AuditLog


ACCOUNT_STATES = {
    "active",
    "suspended",
    "deactivated",
    "pending_deletion",
    "deleted",
}


class AccountLifecycleService:
    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    @staticmethod
    def _serialize_datetime(value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc).isoformat()
            return value.astimezone(timezone.utc).isoformat()
        return value

    @staticmethod
    def _serialize_document(value):
        if isinstance(value, dict):
            return {
                key: AccountLifecycleService._serialize_document(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [AccountLifecycleService._serialize_document(item) for item in value]
        return AccountLifecycleService._serialize_datetime(value)

    @staticmethod
    def get_customer_by_id(customer_id):
        if not ObjectId.is_valid(str(customer_id)):
            return None
        return Customer.find_one({"_id": ObjectId(str(customer_id))})

    @staticmethod
    def get_customer_by_email(email):
        normalized_email = EmailUtils.normalize_email(email)
        if not normalized_email:
            return None
        customer = Customer.find_one({"email": normalized_email})
        if customer:
            return customer
        import re

        return Customer.find_one(
            {"email": re.compile(f"^{re.escape(normalized_email)}$", re.IGNORECASE)}
        )

    @staticmethod
    def set_customer_state(customer, account_state, *, reason=""):
        state = str(account_state or "").strip().lower()
        if state not in ACCOUNT_STATES:
            raise ValueError("Invalid account_state")

        now = AccountLifecycleService._now()
        update = {
            "account_state": state,
            "account_state_reason": str(reason or "").strip(),
            "account_state_changed_at": now,
            "active": state == "active",
            "updated_at": now,
        }
        increment_security = state in {"suspended", "deactivated", "deleted"}
        operation = {"$set": update}
        if increment_security:
            operation["$inc"] = {"security_version": 1}

        document = settings.MONGODB[Customer.collection_name].find_one_and_update(
            {"_id": customer._id},
            operation,
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            return None
        updated = Customer.from_dict(document)
        if increment_security:
            TokenUtils.revoke_all_sessions(updated.id, "customer")
        return updated

    @staticmethod
    def request_email_change(customer, *, new_email, password):
        if not customer.check_password(password):
            return (False, "Invalid password")

        normalized_email = assert_email_available_globally(
            new_email,
            exclude_role="customer",
            exclude_id=customer._id,
        )
        if normalized_email == customer.email:
            return (False, "New email must be different from current email")

        now = AccountLifecycleService._now()
        otp = OTPService.generate_otp()
        expires_at = OTPService.get_otp_expiry()
        customer.pending_email_otp = otp
        encrypted_otp = customer.to_dict()["pending_email_otp"]

        settings.MONGODB[Customer.collection_name].update_one(
            {"_id": customer._id},
            {
                "$set": {
                    "pending_email": normalized_email,
                    "pending_email_otp": encrypted_otp,
                    "pending_email_otp_expires": expires_at,
                    "pending_email_requested_at": now,
                    "pending_email_attempt_count": 0,
                    "pending_email_last_attempt": None,
                    "updated_at": now,
                }
            },
        )

        EmailUtils.send_verification_email(
            email=normalized_email,
            first_name=customer.first_name,
            token=otp,
        )
        return (True, "Verification OTP sent to the new email address")

    @staticmethod
    def confirm_email_change(customer, *, otp):
        pending_email = EmailUtils.normalize_email(getattr(customer, "pending_email", ""))
        if not pending_email:
            return (False, "No pending email change request found")

        allowed, seconds_remaining = OTPService.check_otp_rate_limit(
            customer,
            "pending_email_attempt_count",
            "pending_email_last_attempt",
        )
        if not allowed:
            return (
                False,
                f"Too many OTP attempts. Please try again in {seconds_remaining} seconds.",
            )

        valid, _ = OTPService.validate_otp(
            customer,
            otp,
            "pending_email_otp",
            "pending_email_otp_expires",
        )
        if not valid:
            OTPService.increment_otp_attempt(
                customer,
                "pending_email_attempt_count",
                "pending_email_last_attempt",
            )
            return (False, "Invalid OTP")

        assert_email_available_globally(
            pending_email,
            exclude_role="customer",
            exclude_id=customer._id,
        )
        now = AccountLifecycleService._now()
        document = settings.MONGODB[Customer.collection_name].find_one_and_update(
            {
                "_id": customer._id,
                "pending_email": pending_email,
                "pending_email_otp": {"$ne": None},
                "pending_email_otp_expires": customer.pending_email_otp_expires,
            },
            {
                "$set": {
                    "email": pending_email,
                    "pending_email": None,
                    "pending_email_otp": None,
                    "pending_email_otp_expires": None,
                    "pending_email_requested_at": None,
                    "pending_email_attempt_count": 0,
                    "pending_email_last_attempt": None,
                    "updated_at": now,
                },
                "$inc": {"security_version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            return (False, "Email change request is no longer valid")

        updated = Customer.from_dict(document)
        TokenUtils.revoke_all_sessions(updated.id, "customer")
        return (True, "Email address updated successfully")

    @staticmethod
    def request_deletion(customer, *, reason=""):
        now = AccountLifecycleService._now()
        retention_days = int(getattr(settings, "ACCOUNT_DELETION_RETENTION_DAYS", 30))
        scheduled_for = now + timedelta(days=retention_days)
        document = settings.MONGODB[Customer.collection_name].find_one_and_update(
            {"_id": customer._id, "account_state": {"$nin": ["deleted"]}},
            {
                "$set": {
                    "account_state": "pending_deletion",
                    "account_state_reason": str(reason or "").strip(),
                    "account_state_changed_at": now,
                    "deletion_requested_at": now,
                    "deletion_scheduled_for": scheduled_for,
                    "active": False,
                    "updated_at": now,
                },
                "$inc": {"security_version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            return None
        updated = Customer.from_dict(document)
        TokenUtils.revoke_all_sessions(updated.id, "customer")
        return updated

    @staticmethod
    def cancel_deletion(customer):
        now = AccountLifecycleService._now()
        document = settings.MONGODB[Customer.collection_name].find_one_and_update(
            {"_id": customer._id, "account_state": "pending_deletion"},
            {
                "$set": {
                    "account_state": "active",
                    "account_state_reason": "",
                    "account_state_changed_at": now,
                    "deletion_requested_at": None,
                    "deletion_scheduled_for": None,
                    "active": True,
                    "updated_at": now,
                },
                "$inc": {"security_version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            return None
        updated = Customer.from_dict(document)
        TokenUtils.revoke_all_sessions(updated.id, "customer")
        return updated

    @staticmethod
    def finalize_deletion(customer, *, reason=""):
        now = AccountLifecycleService._now()
        placeholder_email = f"deleted-{customer.id}-{uuid.uuid4().hex[:8]}@deleted.local"
        document = settings.MONGODB[Customer.collection_name].find_one_and_update(
            {"_id": customer._id, "account_state": {"$ne": "deleted"}},
            {
                "$set": {
                    "first_name": "Deleted",
                    "middle_name": "",
                    "last_name": "User",
                    "phone": "",
                    "email": placeholder_email,
                    "password": "",
                    "verification_token": None,
                    "verification_token_expires": None,
                    "password_reset_otp": None,
                    "password_reset_otp_expires": None,
                    "pending_email": None,
                    "pending_email_otp": None,
                    "pending_email_otp_expires": None,
                    "pending_email_requested_at": None,
                    "two_factor_enabled": False,
                    "two_factor_secret": None,
                    "backup_codes": [],
                    "last_totp_timestep": None,
                    "two_factor_setup_id": None,
                    "two_factor_setup_expires_at": None,
                    "account_state": "deleted",
                    "account_state_reason": str(reason or "").strip(),
                    "account_state_changed_at": now,
                    "deleted_at": now,
                    "anonymized_at": now,
                    "active": False,
                    "updated_at": now,
                },
                "$inc": {"security_version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            return None
        updated = Customer.from_dict(document)
        TokenUtils.revoke_all_sessions(updated.id, "customer")
        return updated

    @staticmethod
    def request_two_factor_recovery(email, password):
        customer = AccountLifecycleService.get_customer_by_email(email)
        if not customer or not customer.check_password(password):
            return (True, None, "If the account is eligible, a recovery OTP has been sent.")
        if not customer.two_factor_enabled:
            return (False, customer, "Two-factor authentication is not enabled")

        now = AccountLifecycleService._now()
        otp = OTPService.generate_otp()
        expires_at = OTPService.get_otp_expiry(minutes=15)
        customer.two_factor_recovery_otp = otp
        encrypted_otp = customer.to_dict()["two_factor_recovery_otp"]
        settings.MONGODB[Customer.collection_name].update_one(
            {"_id": customer._id},
            {
                "$set": {
                    "two_factor_recovery_requested_at": now,
                    "two_factor_recovery_verified_at": None,
                    "two_factor_recovery_otp": encrypted_otp,
                    "two_factor_recovery_otp_expires": expires_at,
                    "two_factor_recovery_attempt_count": 0,
                    "two_factor_recovery_last_attempt": None,
                    "updated_at": now,
                }
            },
        )
        EmailUtils.send_verification_email(customer.email, customer.first_name, otp)
        return (True, customer, "If the account is eligible, a recovery OTP has been sent.")

    @staticmethod
    def verify_two_factor_recovery(email, otp):
        customer = AccountLifecycleService.get_customer_by_email(email)
        if not customer:
            return (False, None, "Invalid email or OTP")

        allowed, seconds_remaining = OTPService.check_otp_rate_limit(
            customer,
            "two_factor_recovery_attempt_count",
            "two_factor_recovery_last_attempt",
        )
        if not allowed:
            return (
                False,
                customer,
                f"Too many OTP attempts. Please try again in {seconds_remaining} seconds.",
            )

        valid, _ = OTPService.validate_otp(
            customer,
            otp,
            "two_factor_recovery_otp",
            "two_factor_recovery_otp_expires",
        )
        if not valid:
            OTPService.increment_otp_attempt(
                customer,
                "two_factor_recovery_attempt_count",
                "two_factor_recovery_last_attempt",
            )
            return (False, customer, "Invalid email or OTP")

        now = AccountLifecycleService._now()
        document = settings.MONGODB[Customer.collection_name].find_one_and_update(
            {
                "_id": customer._id,
                "two_factor_recovery_otp": {"$ne": None},
                "two_factor_recovery_otp_expires": customer.two_factor_recovery_otp_expires,
            },
            {
                "$set": {
                    "two_factor_recovery_otp": None,
                    "two_factor_recovery_otp_expires": None,
                    "two_factor_recovery_attempt_count": 0,
                    "two_factor_recovery_last_attempt": None,
                    "two_factor_recovery_verified_at": now,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            return (False, customer, "Invalid email or OTP")
        return (True, Customer.from_dict(document), "Recovery request verified and queued")

    @staticmethod
    def decide_two_factor_recovery(customer, *, approve):
        now = AccountLifecycleService._now()
        if approve:
            operation = {
                "$set": {
                    "two_factor_enabled": False,
                    "two_factor_secret": None,
                    "backup_codes": [],
                    "last_totp_timestep": None,
                    "two_factor_setup_id": None,
                    "two_factor_setup_expires_at": None,
                    "two_factor_recovery_requested_at": None,
                    "two_factor_recovery_verified_at": None,
                    "two_factor_recovery_otp": None,
                    "two_factor_recovery_otp_expires": None,
                    "two_factor_recovery_attempt_count": 0,
                    "two_factor_recovery_last_attempt": None,
                    "updated_at": now,
                },
                "$inc": {"security_version": 1},
            }
        else:
            operation = {
                "$set": {
                    "two_factor_recovery_requested_at": None,
                    "two_factor_recovery_verified_at": None,
                    "two_factor_recovery_otp": None,
                    "two_factor_recovery_otp_expires": None,
                    "two_factor_recovery_attempt_count": 0,
                    "two_factor_recovery_last_attempt": None,
                    "updated_at": now,
                }
            }

        document = settings.MONGODB[Customer.collection_name].find_one_and_update(
            {"_id": customer._id},
            operation,
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            return None
        updated = Customer.from_dict(document)
        if approve:
            TokenUtils.revoke_all_sessions(updated.id, "customer")
        return updated

    @staticmethod
    def list_pending_two_factor_recovery():
        rows = settings.MONGODB[Customer.collection_name].find(
            {
                "two_factor_recovery_requested_at": {"$ne": None},
                "two_factor_recovery_verified_at": {"$ne": None},
            },
            {
                "first_name": 1,
                "last_name": 1,
                "email": 1,
                "two_factor_recovery_requested_at": 1,
                "two_factor_recovery_verified_at": 1,
            },
        )
        items = []
        for row in rows:
            items.append(
                {
                    "id": str(row.get("_id")),
                    "email": row.get("email"),
                    "full_name": " ".join(
                        [
                            str(row.get("first_name") or "").strip(),
                            str(row.get("last_name") or "").strip(),
                        ]
                    ).strip(),
                    "requested_at": AccountLifecycleService._serialize_datetime(
                        row.get("two_factor_recovery_requested_at")
                    ),
                    "verified_at": AccountLifecycleService._serialize_datetime(
                        row.get("two_factor_recovery_verified_at")
                    ),
                }
            )
        return items

    @staticmethod
    def export_customer_data(customer):
        consent = Consent.find_by_user(customer.id, "customer")
        sessions = ActiveSession.find({"user_id": customer.id}, sort=[("created_at", -1)])
        login_activity = LoginActivity.find({"user_id": customer.id}, limit=200)
        audit_entries = AuditLog.find_by_user(customer.id, limit=200)

        payload = {
            "generated_at": AccountLifecycleService._serialize_datetime(
                AccountLifecycleService._now()
            ),
            "customer": {
                "id": customer.id,
                "first_name": customer.first_name,
                "middle_name": customer.middle_name,
                "last_name": customer.last_name,
                "email": customer.email,
                "phone": customer.phone,
                "verified": customer.verified,
                "active": customer.active,
                "account_state": getattr(customer, "account_state", "active"),
                "created_at": AccountLifecycleService._serialize_datetime(customer.created_at),
                "updated_at": AccountLifecycleService._serialize_datetime(customer.updated_at),
            },
            "consent": consent.to_dict() if consent else None,
            "active_sessions": [session.to_dict() for session in sessions],
            "login_activity": [entry.to_dict() for entry in login_activity],
            "audit_logs": [entry.to_dict() for entry in audit_entries],
        }
        return AccountLifecycleService._serialize_document(payload)
