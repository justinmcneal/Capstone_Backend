import logging
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from celery import shared_task
from django.conf import settings

from accounts.models import Admin, Customer, LoanOfficer
from accounts.services.account_lifecycle_service import AccountLifecycleService
from accounts.services.audit import record_account_audit
from accounts.utils.email_utils import EmailUtils

logger = logging.getLogger(__name__)

PASSWORD_RESET_MODELS = {
    "customer": Customer,
    "loan_officer": LoanOfficer,
    "admin": Admin,
}
PASSWORD_RESET_DELIVERY_RETRY_SECONDS = 60

try:
    from prometheus_client import Counter

    PASSWORD_RESET_EMAIL_SUCCESS = Counter(
        "accounts_password_reset_email_success_total",
        "Password reset email task successes",
    )
    PASSWORD_RESET_EMAIL_FAILURE = Counter(
        "accounts_password_reset_email_failure_total",
        "Password reset email task failures",
    )
except ImportError:
    PASSWORD_RESET_EMAIL_SUCCESS = None
    PASSWORD_RESET_EMAIL_FAILURE = None


def _password_reset_model(user_type):
    return PASSWORD_RESET_MODELS.get(str(user_type or "").strip().lower())


def _password_reset_object_id(user_id):
    try:
        return ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None


def queue_password_reset_delivery(*, user_id, user_type, expected_expiry):
    """Claim and enqueue one reset-email delivery without placing the OTP in Celery."""
    model = _password_reset_model(user_type)
    object_id = _password_reset_object_id(user_id)
    if model is None or object_id is None or expected_expiry is None:
        return False

    now = datetime.now(timezone.utc)
    collection = settings.MONGODB[model.collection_name]
    claimed = collection.update_one(
        {
            "_id": object_id,
            "password_reset_otp": {"$ne": None},
            "password_reset_otp_expires": expected_expiry,
            "password_reset_delivery_status": {"$in": ["pending", "failed"]},
            "$or": [
                {"password_reset_delivery_next_attempt_at": {"$exists": False}},
                {"password_reset_delivery_next_attempt_at": None},
                {"password_reset_delivery_next_attempt_at": {"$lte": now}},
            ],
        },
        {
            "$set": {
                "password_reset_delivery_status": "queued",
                "password_reset_delivery_updated_at": now,
                "updated_at": now,
            }
        },
    )
    if claimed.modified_count != 1:
        return False

    try:
        send_password_reset_email_task.delay(
            str(object_id),
            str(user_type),
            expected_expiry.isoformat(),
        )
        return True
    except Exception as exc:
        retry_at = now + timedelta(seconds=PASSWORD_RESET_DELIVERY_RETRY_SECONDS)
        collection.update_one(
            {
                "_id": object_id,
                "password_reset_otp_expires": expected_expiry,
                "password_reset_delivery_status": "queued",
            },
            {
                "$set": {
                    "password_reset_delivery_status": "pending",
                    "password_reset_delivery_last_error": type(exc).__name__,
                    "password_reset_delivery_next_attempt_at": retry_at,
                    "password_reset_delivery_updated_at": now,
                    "updated_at": now,
                }
            },
        )
        logger.exception(
            "Password reset email enqueue failed for %s account %s",
            user_type,
            user_id,
        )
        return False


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    name="accounts.tasks.send_password_reset_email_task",
)
def send_password_reset_email_task(
    self, user_id: str, user_type: str, expected_expiry_iso: str
):
    """Send the currently reserved reset OTP and persist delivery observability."""
    model = _password_reset_model(user_type)
    object_id = _password_reset_object_id(user_id)
    if model is None or object_id is None:
        logger.warning("Ignoring invalid password reset delivery identity")
        return False

    try:
        expected_expiry = datetime.fromisoformat(expected_expiry_iso)
    except (TypeError, ValueError):
        logger.warning("Ignoring password reset delivery with invalid expiry")
        return False
    if expected_expiry.tzinfo is None:
        expected_expiry = expected_expiry.replace(tzinfo=timezone.utc)

    collection = settings.MONGODB[model.collection_name]
    user = model.find_one(
        {"_id": object_id, "password_reset_otp_expires": expected_expiry}
    )
    now = datetime.now(timezone.utc)
    if not user or not user.password_reset_otp:
        return False
    expiry = EmailUtils.to_aware_utc(user.password_reset_otp_expires)
    if expiry is None or expiry <= now:
        collection.update_one(
            {"_id": object_id, "password_reset_otp_expires": expected_expiry},
            {
                "$set": {
                    "password_reset_delivery_status": "expired",
                    "password_reset_delivery_updated_at": now,
                    "updated_at": now,
                }
            },
        )
        return False

    first_name = getattr(user, "first_name", None) or getattr(
        user, "username", "User"
    )
    try:
        sent = EmailUtils.send_password_reset_email(
            email=user.email,
            first_name=first_name,
            otp=user.password_reset_otp,
        )
        if not sent:
            raise RuntimeError("password reset email provider returned failure")
    except Exception as exc:
        retry_at = now + timedelta(seconds=PASSWORD_RESET_DELIVERY_RETRY_SECONDS)
        collection.update_one(
            {"_id": object_id, "password_reset_otp_expires": expected_expiry},
            {
                "$set": {
                    "password_reset_delivery_status": "failed",
                    "password_reset_delivery_last_error": type(exc).__name__,
                    "password_reset_delivery_next_attempt_at": retry_at,
                    "password_reset_delivery_updated_at": now,
                    "updated_at": now,
                },
                "$inc": {"password_reset_delivery_attempts": 1},
            },
        )
        if PASSWORD_RESET_EMAIL_FAILURE is not None:
            PASSWORD_RESET_EMAIL_FAILURE.inc()
        raise

    updated = collection.update_one(
        {
            "_id": object_id,
            "password_reset_otp_expires": expected_expiry,
            "password_reset_otp": {"$ne": None},
        },
        {
            "$set": {
                "password_reset_delivery_status": "sent",
                "password_reset_delivery_last_error": "",
                "password_reset_delivery_next_attempt_at": None,
                "password_reset_delivery_updated_at": now,
                "updated_at": now,
            },
            "$inc": {"password_reset_delivery_attempts": 1},
        },
    )
    if updated.modified_count == 1 and PASSWORD_RESET_EMAIL_SUCCESS is not None:
        PASSWORD_RESET_EMAIL_SUCCESS.inc()
    logger.info("Password reset email delivered for %s account %s", user_type, user_id)
    return updated.modified_count == 1


@shared_task(name="accounts.tasks.reconcile_password_reset_email_deliveries_task")
def reconcile_password_reset_email_deliveries_task():
    """Requeue recoverable reset emails that were not durably published or sent."""
    now = datetime.now(timezone.utc)
    stale_queued_at = now - timedelta(minutes=5)
    queued = 0

    for user_type, model in PASSWORD_RESET_MODELS.items():
        collection = settings.MONGODB[model.collection_name]
        query = {
            "password_reset_otp": {"$ne": None},
            "password_reset_otp_expires": {"$gt": now},
            "$or": [
                {
                    "password_reset_delivery_status": {"$in": ["pending", "failed"]},
                    "password_reset_delivery_next_attempt_at": {"$lte": now},
                },
                {
                    "password_reset_delivery_status": "queued",
                    "password_reset_delivery_updated_at": {"$lte": stale_queued_at},
                },
            ],
        }
        for document in collection.find(query, {"password_reset_otp_expires": 1}):
            if document.get("password_reset_delivery_status") == "queued":
                collection.update_one(
                    {"_id": document["_id"], "password_reset_delivery_status": "queued"},
                    {"$set": {"password_reset_delivery_status": "failed"}},
                )
            if queue_password_reset_delivery(
                user_id=str(document["_id"]),
                user_type=user_type,
                expected_expiry=document.get("password_reset_otp_expires"),
            ):
                queued += 1

    logger.info("Requeued %s password reset email delivery task(s)", queued)
    return queued


@shared_task
def cleanup_unverified_accounts_task():
    hours = 12
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    unverified_customers = Customer.find(
        {"verified": False, "created_at": {"$lte": cutoff_time}}
    )

    count = len(unverified_customers)

    if count == 0:
        logger.info("Cleanup task: No unverified accounts to delete")
        return f"No unverified accounts older than {hours} hours found"

    deleted_emails = [c.email for c in unverified_customers]

    # Delete each customer
    for customer in unverified_customers:
        customer.delete()

    logger.info(
        f'Cleanup task: Deleted {count} unverified accounts: {", ".join(deleted_emails)}'
    )
    return f"Successfully deleted {count} unverified accounts"


@shared_task
def finalize_scheduled_customer_deletions_task():
    """Finalize customer deletion requests whose retention period has elapsed."""
    now = datetime.now(timezone.utc)
    customers = Customer.find(
        {
            "$or": [
                {
                    "account_state": "pending_deletion",
                    "deletion_scheduled_for": {"$lte": now},
                },
                {
                    "account_state": "deleted",
                    "$or": [
                        {"profile_cleanup_status": "pending"},
                        {"document_cleanup_status": "pending"},
                        {"document_cleanup_status": {"$exists": False}},
                        {"analytics_cleanup_status": "pending"},
                        {"analytics_cleanup_status": {"$exists": False}},
                    ],
                },
            ]
        }
    )

    finalized = 0
    for customer in customers:
        original_email = customer.email
        try:
            updated = AccountLifecycleService.finalize_deletion(
                customer,
                reason="Retention period elapsed",
            )
            if not updated:
                continue

            record_account_audit(
                action="account_deleted",
                user_id=updated.id,
                user_type="system",
                user_email=original_email,
                description="Finalized scheduled customer account deletion",
                resource_type="customer",
                resource_id=updated.id,
                details={"automated": True, "retention_period_elapsed": True},
                ip_address="",
            )
            finalized += 1
        except Exception as exc:  # noqa: BLE001 - one record must not stop the batch
            logger.error(
                "Scheduled customer deletion failed for %s: %s", customer.id, exc
            )

    logger.info("Scheduled customer deletion task finalized %s account(s)", finalized)
    return f"Finalized {finalized} scheduled customer deletion(s)"


@shared_task
def invalidate_ai_consent_cache(user_id: str) -> str:
    """
    Clear the Redis-cached AI consent entry for a user.

    Dispatched by ConsentService.update_consent() whenever a customer
    revokes ai_consent (True → False), ensuring the AI assistant cannot
    serve a stale cached 'allowed' value.

    Safe even if nothing is cached — cache.delete() is a no-op on a miss.
    """
    from django.core.cache import cache

    cache_key = f"ai_consent:{user_id}"
    cache.delete(cache_key)
    logger.info("AI consent cache invalidated for user %s", user_id)
    return f"Invalidated ai_consent cache for user {user_id}"
