import uuid
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from django.conf import settings
from pymongo import ReturnDocument

from accounts.models import Consent, Customer
from accounts.models.activity import ActiveSession, LoginActivity
from accounts.services.lockout_service import LockoutService
from accounts.services.otp_service import OTPService
from accounts.utils.email_utils import EmailUtils
from accounts.utils.identity_policy import assert_email_available_globally
from accounts.utils.token_utils import TokenUtils
from notifications.models.notification import Notification

ACCOUNT_STATES = {
    "active",
    "suspended",
    "deactivated",
    "pending_deletion",
    "deleted",
}

MANAGEABLE_ACCOUNT_STATES = {"active", "suspended", "deactivated"}
DELETION_CANCELLATION_MESSAGE = (
    "If the account has a pending deletion request and the credentials are valid, "
    "the request has been cancelled."
)
ACCOUNT_RECOVERY_ISSUE_COOLDOWN_SECONDS = 60
TWO_FACTOR_RECOVERY_WINDOW_SECONDS = 3600
TWO_FACTOR_RECOVERY_MAX_ISSUES_PER_WINDOW = 3


class AccountLifecycleService:
    DELETION_CANCELLATION_GENERIC_MESSAGE = DELETION_CANCELLATION_MESSAGE

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
        if isinstance(value, ObjectId):
            return str(value)
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
        if state not in MANAGEABLE_ACCOUNT_STATES:
            raise ValueError("Invalid account_state")

        now = AccountLifecycleService._now()
        current_state = getattr(customer, "account_state", "active") or "active"
        state_changed = current_state != state
        update = {
            "account_state": state,
            "account_state_reason": str(reason or "").strip(),
            "account_state_changed_at": now,
            "active": state == "active",
            "updated_at": now,
        }
        if state == "active" and current_state == "pending_deletion":
            update.update(
                {
                    "deletion_requested_at": None,
                    "deletion_scheduled_for": None,
                }
            )

        operation = {"$set": update}
        if state_changed:
            operation["$inc"] = {"security_version": 1}

        state_query = {"_id": customer._id}
        if current_state == "active":
            state_query["$or"] = [
                {"account_state": "active"},
                {"account_state": {"$exists": False}},
            ]
        else:
            state_query["account_state"] = current_state

        document = settings.MONGODB[Customer.collection_name].find_one_and_update(
            state_query,
            operation,
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            return None
        updated = Customer.from_dict(document)
        if state_changed:
            TokenUtils.revoke_all_sessions(updated.id, "customer")
        if state == "active":
            LockoutService.reset_lockout(updated)
        return updated

    @staticmethod
    def request_email_change(customer, *, new_email, password):
        if not customer.check_password(password):
            return (False, "Invalid password")

        requested_at = getattr(customer, "pending_email_requested_at", None)
        requested_at = EmailUtils.to_aware_utc(requested_at)
        if requested_at:
            elapsed = (AccountLifecycleService._now() - requested_at).total_seconds()
            if elapsed < ACCOUNT_RECOVERY_ISSUE_COOLDOWN_SECONDS:
                return (
                    False,
                    "Please wait before requesting another email change verification code.",
                )

        normalized_email = assert_email_available_globally(
            new_email,
            exclude_role="customer",
            exclude_id=customer._id,
        )
        if normalized_email == EmailUtils.normalize_email(customer.email):
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

        EmailUtils.send_email_change_verification(
            email=normalized_email,
            first_name=customer.first_name,
            token=otp,
        )
        return (True, "Verification OTP sent to the new email address")

    @staticmethod
    def confirm_email_change(customer, *, otp):
        pending_email = EmailUtils.normalize_email(
            getattr(customer, "pending_email", "")
        )
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
        if retention_days < 0:
            raise ValueError("ACCOUNT_DELETION_RETENTION_DAYS cannot be negative")
        scheduled_for = now + timedelta(days=retention_days)
        current_state = getattr(customer, "account_state", "active") or "active"
        state_query = {"_id": customer._id}
        if current_state == "active":
            state_query["$or"] = [
                {"account_state": "active"},
                {"account_state": {"$exists": False}},
            ]
        else:
            return None
        document = settings.MONGODB[Customer.collection_name].find_one_and_update(
            state_query,
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
    def cancel_deletion_with_password(email, password):
        """Restore a pending customer deletion after credential verification."""
        customer = AccountLifecycleService.get_customer_by_email(email)
        if not customer or not customer.check_password(password):
            return None
        if getattr(customer, "account_state", "active") != "pending_deletion":
            return None
        return AccountLifecycleService.cancel_deletion(customer)

    @staticmethod
    def is_deletion_due(customer):
        if getattr(customer, "account_state", "active") == "deleted" and (
            getattr(customer, "profile_cleanup_status", None) == "pending"
            or getattr(customer, "document_cleanup_status", None) in (None, "pending")
            or getattr(customer, "analytics_cleanup_status", None) in (None, "pending")
            or getattr(customer, "ai_cleanup_status", None) in (None, "pending")
            or getattr(customer, "loan_cleanup_status", None) in (None, "pending")
        ):
            return True
        scheduled_for = EmailUtils.to_aware_utc(
            getattr(customer, "deletion_scheduled_for", None)
        )
        return (
            getattr(customer, "account_state", "active") == "pending_deletion"
            and scheduled_for is not None
            and scheduled_for <= AccountLifecycleService._now()
        )

    @staticmethod
    def finalize_deletion(customer, *, reason=""):
        """Anonymize an account and irreversibly delete its profile-domain data.

        Account anonymization is committed first with a durable pending cleanup
        marker. Profile cleanup is idempotent and can be retried by the scheduled
        task or administrative endpoint if a database error interrupts it.
        """

        now = AccountLifecycleService._now()
        placeholder_email = (
            f"deleted-{customer.id}-{uuid.uuid4().hex[:8]}@deleted.local"
        )
        collection = settings.MONGODB[Customer.collection_name]
        document = collection.find_one_and_update(
            {
                "_id": customer._id,
                "account_state": "pending_deletion",
                "deletion_scheduled_for": {"$lte": now},
            },
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
                    "password_reset_attempt_count": 0,
                    "password_reset_last_attempt": None,
                    "password_reset_last_sent_at": None,
                    "password_reset_window_started_at": None,
                    "password_reset_issue_count": 0,
                    "password_reset_delivery_status": None,
                    "password_reset_delivery_attempts": 0,
                    "password_reset_delivery_last_error": "",
                    "password_reset_delivery_updated_at": None,
                    "password_reset_delivery_next_attempt_at": None,
                    "pending_email": None,
                    "pending_email_otp": None,
                    "pending_email_otp_expires": None,
                    "pending_email_requested_at": None,
                    "pending_email_attempt_count": 0,
                    "pending_email_last_attempt": None,
                    "two_factor_recovery_requested_at": None,
                    "two_factor_recovery_verified_at": None,
                    "two_factor_recovery_otp": None,
                    "two_factor_recovery_otp_expires": None,
                    "two_factor_recovery_attempt_count": 0,
                    "two_factor_recovery_last_attempt": None,
                    "two_factor_recovery_issue_count": 0,
                    "two_factor_recovery_window_started_at": None,
                    "two_factor_enabled": False,
                    "two_factor_secret": None,
                    "backup_codes": [],
                    "last_totp_timestep": None,
                    "two_factor_setup_id": None,
                    "two_factor_setup_expires_at": None,
                    "failed_login_attempts": 0,
                    "locked_until": None,
                    "account_state": "deleted",
                    "account_state_reason": str(reason or "").strip(),
                    "account_state_changed_at": now,
                    "deleted_at": now,
                    "anonymized_at": now,
                    "profile_cleanup_status": "pending",
                    "profile_cleanup_counts": {},
                    "profile_cleanup_attempts": 0,
                    "profile_cleanup_last_error": "",
                    "profile_cleanup_last_attempt_at": None,
                    "profile_cleanup_completed_at": None,
                    "document_cleanup_status": "pending",
                    "document_cleanup_counts": {},
                    "document_cleanup_attempts": 0,
                    "document_cleanup_last_error": "",
                    "document_cleanup_last_attempt_at": None,
                    "document_cleanup_completed_at": None,
                    "analytics_cleanup_status": "pending",
                    "analytics_cleanup_counts": {},
                    "analytics_cleanup_attempts": 0,
                    "analytics_cleanup_last_error": "",
                    "analytics_cleanup_last_attempt_at": None,
                    "analytics_cleanup_completed_at": None,
                    "ai_cleanup_status": "pending",
                    "ai_cleanup_counts": {},
                    "ai_cleanup_attempts": 0,
                    "ai_cleanup_last_error": "",
                    "ai_cleanup_last_attempt_at": None,
                    "ai_cleanup_completed_at": None,
                    "loan_cleanup_status": "pending",
                    "loan_cleanup_counts": {},
                    "loan_cleanup_attempts": 0,
                    "loan_cleanup_last_error": "",
                    "loan_cleanup_last_attempt_at": None,
                    "loan_cleanup_completed_at": None,
                    "active": False,
                    "updated_at": now,
                },
                "$inc": {"security_version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            document = collection.find_one(
                {
                    "_id": customer._id,
                    "account_state": "deleted",
                    "$or": [
                        {"profile_cleanup_status": "pending"},
                        {"document_cleanup_status": "pending"},
                        {"document_cleanup_status": {"$exists": False}},
                        {"analytics_cleanup_status": "pending"},
                        {"analytics_cleanup_status": {"$exists": False}},
                        {"ai_cleanup_status": "pending"},
                        {"ai_cleanup_status": {"$exists": False}},
                        {"loan_cleanup_status": "pending"},
                        {"loan_cleanup_status": {"$exists": False}},
                    ],
                }
            )
            if not document:
                return None

        updated = Customer.from_dict(document)
        TokenUtils.revoke_all_sessions(updated.id, "customer")

        if updated.profile_cleanup_status == "pending":
            from profiles.services.lifecycle import delete_customer_profile_data

            cleanup_attempted_at = AccountLifecycleService._now()
            collection.update_one(
                {
                    "_id": updated._id,
                    "account_state": "deleted",
                    "profile_cleanup_status": "pending",
                },
                {
                    "$set": {
                        "profile_cleanup_last_attempt_at": cleanup_attempted_at,
                        "updated_at": cleanup_attempted_at,
                    },
                    "$inc": {"profile_cleanup_attempts": 1},
                },
            )
            try:
                cleanup_counts = delete_customer_profile_data(
                    settings.MONGODB, updated.id
                )
            except Exception as exc:
                collection.update_one(
                    {"_id": updated._id, "profile_cleanup_status": "pending"},
                    {
                        "$set": {
                            "profile_cleanup_last_error": type(exc).__name__,
                            "updated_at": AccountLifecycleService._now(),
                        }
                    },
                )
                raise

            cleanup_completed_at = AccountLifecycleService._now()
            collection.update_one(
                {"_id": updated._id, "profile_cleanup_status": "pending"},
                {
                    "$set": {
                        "profile_cleanup_status": "complete",
                        "profile_cleanup_counts": cleanup_counts,
                        "profile_cleanup_last_error": "",
                        "profile_cleanup_completed_at": cleanup_completed_at,
                        "updated_at": cleanup_completed_at,
                    }
                },
            )

        updated = Customer.from_dict(collection.find_one({"_id": updated._id}))
        if updated.ai_cleanup_status in (None, "pending"):
            from ai_assistant.services.lifecycle import delete_customer_ai_data

            attempted_at = AccountLifecycleService._now()
            collection.update_one(
                {
                    "_id": updated._id,
                    "$or": [
                        {"ai_cleanup_status": "pending"},
                        {"ai_cleanup_status": {"$exists": False}},
                    ],
                },
                {
                    "$set": {
                        "ai_cleanup_last_attempt_at": attempted_at,
                        "updated_at": attempted_at,
                    },
                    "$inc": {"ai_cleanup_attempts": 1},
                },
            )
            try:
                counts = delete_customer_ai_data(settings.MONGODB, updated.id)
            except Exception as exc:
                collection.update_one(
                    {"_id": updated._id},
                    {
                        "$set": {
                            "ai_cleanup_status": "pending",
                            "ai_cleanup_last_error": type(exc).__name__,
                            "updated_at": AccountLifecycleService._now(),
                        }
                    },
                )
                raise
            cleanup_complete = counts["remaining"] == 0
            ai_update = {
                "ai_cleanup_status": "complete" if cleanup_complete else "pending",
                "ai_cleanup_counts": counts,
                "ai_cleanup_last_error": "",
                "updated_at": AccountLifecycleService._now(),
            }
            if cleanup_complete:
                ai_update["ai_cleanup_completed_at"] = ai_update["updated_at"]
            collection.update_one({"_id": updated._id}, {"$set": ai_update})

        updated = Customer.from_dict(collection.find_one({"_id": updated._id}))
        if updated.document_cleanup_status in (None, "pending"):
            from documents.services.lifecycle import schedule_customer_document_cleanup

            attempted_at = AccountLifecycleService._now()
            collection.update_one(
                {
                    "_id": updated._id,
                    "$or": [
                        {"document_cleanup_status": "pending"},
                        {"document_cleanup_status": {"$exists": False}},
                    ],
                },
                {
                    "$set": {
                        "document_cleanup_last_attempt_at": attempted_at,
                        "updated_at": attempted_at,
                    },
                    "$inc": {"document_cleanup_attempts": 1},
                },
            )
            try:
                counts = schedule_customer_document_cleanup(
                    settings.MONGODB, updated.id
                )
            except Exception as exc:
                collection.update_one(
                    {
                        "_id": updated._id,
                        "$or": [
                            {"document_cleanup_status": "pending"},
                            {"document_cleanup_status": {"$exists": False}},
                        ],
                    },
                    {
                        "$set": {
                            "document_cleanup_last_error": type(exc).__name__,
                            "updated_at": AccountLifecycleService._now(),
                        }
                    },
                )
                raise
            update = {
                "document_cleanup_status": counts["status"],
                "document_cleanup_counts": counts,
                "document_cleanup_last_error": "",
                "updated_at": AccountLifecycleService._now(),
            }
            if counts["status"] == "complete":
                update["document_cleanup_completed_at"] = update["updated_at"]
            collection.update_one({"_id": updated._id}, {"$set": update})

        updated = Customer.from_dict(collection.find_one({"_id": updated._id}))
        if updated.loan_cleanup_status in (None, "pending"):
            from loans.services.lifecycle import pseudonymize_customer_loan_data

            attempted_at = AccountLifecycleService._now()
            collection.update_one(
                {"_id": updated._id},
                {
                    "$set": {
                        "loan_cleanup_last_attempt_at": attempted_at,
                        "updated_at": attempted_at,
                    },
                    "$inc": {"loan_cleanup_attempts": 1},
                },
            )
            try:
                counts = pseudonymize_customer_loan_data(
                    settings.MONGODB, updated.id
                )
            except Exception as exc:
                collection.update_one(
                    {"_id": updated._id},
                    {"$set": {
                        "loan_cleanup_status": "pending",
                        "loan_cleanup_last_error": type(exc).__name__,
                        "updated_at": AccountLifecycleService._now(),
                    }},
                )
                raise
            cleanup_complete = counts["remaining"] == 0
            loan_update = {
                "loan_cleanup_status": "complete" if cleanup_complete else "pending",
                "loan_cleanup_counts": counts,
                "loan_cleanup_last_error": "",
                "updated_at": AccountLifecycleService._now(),
            }
            if cleanup_complete:
                loan_update["loan_cleanup_completed_at"] = loan_update["updated_at"]
            collection.update_one({"_id": updated._id}, {"$set": loan_update})

        updated = Customer.from_dict(collection.find_one({"_id": updated._id}))
        if updated.analytics_cleanup_status in (None, "pending"):
            from analytics.services.lifecycle import pseudonymize_customer_audit_data

            attempted_at = AccountLifecycleService._now()
            collection.update_one(
                {"_id": updated._id},
                {
                    "$set": {
                        "analytics_cleanup_last_attempt_at": attempted_at,
                        "updated_at": attempted_at,
                    },
                    "$inc": {"analytics_cleanup_attempts": 1},
                },
            )
            try:
                counts = pseudonymize_customer_audit_data(
                    settings.MONGODB, updated.id
                )
            except Exception as exc:
                collection.update_one(
                    {"_id": updated._id},
                    {
                        "$set": {
                            "analytics_cleanup_status": "pending",
                            "analytics_cleanup_last_error": type(exc).__name__,
                            "updated_at": AccountLifecycleService._now(),
                        }
                    },
                )
                raise
            cleanup_complete = counts["remaining"] == 0
            analytics_update = {
                "analytics_cleanup_status": (
                    "complete" if cleanup_complete else "pending"
                ),
                "analytics_cleanup_counts": counts,
                "analytics_cleanup_last_error": "",
                "updated_at": AccountLifecycleService._now(),
            }
            if cleanup_complete:
                analytics_update["analytics_cleanup_completed_at"] = analytics_update[
                    "updated_at"
                ]
            collection.update_one({"_id": updated._id}, {"$set": analytics_update})

        return Customer.from_dict(collection.find_one({"_id": updated._id}))

    @staticmethod
    def request_two_factor_recovery(email, password):
        customer = AccountLifecycleService.get_customer_by_email(email)
        if not customer or not customer.check_password(password):
            return (
                True,
                None,
                "If the account is eligible, a recovery OTP has been sent.",
            )
        if (
            getattr(customer, "account_state", "active") != "active"
            or not getattr(customer, "active", True)
            or not getattr(customer, "verified", True)
            or not customer.two_factor_enabled
        ):
            return (
                True,
                None,
                "If the account is eligible, a recovery OTP has been sent.",
            )

        now = AccountLifecycleService._now()
        otp = OTPService.generate_otp()
        expires_at = OTPService.get_otp_expiry(minutes=15)
        customer.two_factor_recovery_otp = otp
        encrypted_otp = customer.to_dict()["two_factor_recovery_otp"]

        collection = settings.MONGODB[Customer.collection_name]
        cooldown_cutoff = now - timedelta(
            seconds=ACCOUNT_RECOVERY_ISSUE_COOLDOWN_SECONDS
        )
        window_cutoff = now - timedelta(seconds=TWO_FACTOR_RECOVERY_WINDOW_SECONDS)
        active_window = collection.find_one_and_update(
            {
                "_id": customer._id,
                "account_state": "active",
                "active": True,
                "two_factor_enabled": True,
                "$or": [
                    {"two_factor_recovery_requested_at": None},
                    {"two_factor_recovery_requested_at": {"$exists": False}},
                    {"two_factor_recovery_requested_at": {"$lte": cooldown_cutoff}},
                ],
                "two_factor_recovery_window_started_at": {"$gt": window_cutoff},
                "two_factor_recovery_issue_count": {
                    "$lt": TWO_FACTOR_RECOVERY_MAX_ISSUES_PER_WINDOW
                },
            },
            {
                "$set": {
                    "two_factor_recovery_requested_at": now,
                    "two_factor_recovery_verified_at": None,
                    "two_factor_recovery_otp": encrypted_otp,
                    "two_factor_recovery_otp_expires": expires_at,
                    "two_factor_recovery_attempt_count": 0,
                    "two_factor_recovery_last_attempt": None,
                    "updated_at": now,
                },
                "$inc": {"two_factor_recovery_issue_count": 1},
            },
            return_document=ReturnDocument.AFTER,
        )

        if not active_window:
            active_window = collection.find_one_and_update(
                {
                    "_id": customer._id,
                    "account_state": "active",
                    "active": True,
                    "two_factor_enabled": True,
                    "$or": [
                        {"two_factor_recovery_window_started_at": None},
                        {"two_factor_recovery_window_started_at": {"$exists": False}},
                        {
                            "two_factor_recovery_window_started_at": {
                                "$lte": window_cutoff
                            }
                        },
                    ],
                    "$and": [
                        {
                            "$or": [
                                {"two_factor_recovery_requested_at": None},
                                {
                                    "two_factor_recovery_requested_at": {
                                        "$exists": False
                                    }
                                },
                                {
                                    "two_factor_recovery_requested_at": {
                                        "$lte": cooldown_cutoff
                                    }
                                },
                            ]
                        }
                    ],
                },
                {
                    "$set": {
                        "two_factor_recovery_requested_at": now,
                        "two_factor_recovery_verified_at": None,
                        "two_factor_recovery_otp": encrypted_otp,
                        "two_factor_recovery_otp_expires": expires_at,
                        "two_factor_recovery_attempt_count": 0,
                        "two_factor_recovery_last_attempt": None,
                        "two_factor_recovery_issue_count": 1,
                        "two_factor_recovery_window_started_at": now,
                        "updated_at": now,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )

        if not active_window:
            return (
                True,
                None,
                "If the account is eligible, a recovery OTP has been sent.",
            )

        EmailUtils.send_verification_email(customer.email, customer.first_name, otp)
        return (
            True,
            customer,
            "If the account is eligible, a recovery OTP has been sent.",
        )

    @staticmethod
    def verify_two_factor_recovery(email, otp):
        customer = AccountLifecycleService.get_customer_by_email(email)
        if (
            not customer
            or getattr(customer, "account_state", "active") != "active"
            or not getattr(customer, "active", True)
            or not getattr(customer, "verified", True)
            or not customer.two_factor_enabled
        ):
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
        if not OTPService.consume_otp(
            customer,
            otp,
            "two_factor_recovery_otp",
            "two_factor_recovery_otp_expires",
            success_updates={
                "two_factor_recovery_attempt_count": 0,
                "two_factor_recovery_last_attempt": None,
                "two_factor_recovery_verified_at": now,
            },
        ):
            return (False, customer, "Invalid email or OTP")
        return (
            True,
            AccountLifecycleService.get_customer_by_id(customer.id),
            "Recovery request verified and queued",
        )

    @staticmethod
    def is_two_factor_recovery_request_valid(customer):
        verified_at = EmailUtils.to_aware_utc(
            getattr(customer, "two_factor_recovery_verified_at", None)
        )
        if not verified_at:
            return False
        approval_hours = int(
            getattr(settings, "TWO_FACTOR_RECOVERY_APPROVAL_HOURS", 24)
        )
        return (
            verified_at + timedelta(hours=approval_hours)
            > AccountLifecycleService._now()
        )

    @staticmethod
    def decide_two_factor_recovery(customer, *, approve):
        now = AccountLifecycleService._now()
        if not AccountLifecycleService.is_two_factor_recovery_request_valid(customer):
            return None
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
                    "two_factor_recovery_issue_count": 0,
                    "two_factor_recovery_window_started_at": None,
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
                    "two_factor_recovery_issue_count": 0,
                    "two_factor_recovery_window_started_at": None,
                    "updated_at": now,
                }
            }

        document = settings.MONGODB[Customer.collection_name].find_one_and_update(
            {
                "_id": customer._id,
                "two_factor_recovery_verified_at": customer.two_factor_recovery_verified_at,
            },
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
        from ai_assistant.services.lifecycle import export_customer_ai_history
        from analytics.services.lifecycle import export_customer_audit_data
        from documents.services.lifecycle import export_customer_documents
        from loans.services.lifecycle import export_customer_loan_data

        consent = Consent.find_by_user(customer.id, "customer")
        sessions = ActiveSession.find(
            {"user_id": customer.id}, sort=[("created_at", -1)]
        )
        login_activity = LoginActivity.find({"user_id": customer.id}, limit=200)
        notifications = Notification.find_by_user(
            customer.id, limit=200, user_type="customer"
        )

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
                "created_at": AccountLifecycleService._serialize_datetime(
                    customer.created_at
                ),
                "updated_at": AccountLifecycleService._serialize_datetime(
                    customer.updated_at
                ),
            },
            "consent": consent.to_dict() if consent else None,
            "active_sessions": [session.to_dict() for session in sessions],
            "login_activity": [entry.to_dict() for entry in login_activity],
            "audit_logs": export_customer_audit_data(
                settings.MONGODB, customer.id
            ),
            "ai_history": export_customer_ai_history(
                settings.MONGODB, customer.id
            ),
            "notifications": [item.to_dict() for item in notifications],
            "documents": export_customer_documents(settings.MONGODB, customer.id),
            "loans": export_customer_loan_data(settings.MONGODB, customer.id),
        }
        return AccountLifecycleService._serialize_document(payload)
