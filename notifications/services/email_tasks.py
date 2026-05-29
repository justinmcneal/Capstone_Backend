from config.celery import app
from notifications.models.notification import Notification
from notifications.services.email_sender import EmailSender
from datetime import timezone
from bson import ObjectId
from django.conf import settings
import logging

logger = logging.getLogger("notifications.tasks")

# Prometheus metrics
try:
    from prometheus_client import Counter

    EMAIL_TASK_SUCCESS = Counter(
        "notifications_email_task_success_total", "Email task successes"
    )
    EMAIL_TASK_FAILURE = Counter(
        "notifications_email_task_failure_total", "Email task failures"
    )
except Exception:
    EMAIL_TASK_SUCCESS = None
    EMAIL_TASK_FAILURE = None


@app.task(
    bind=True,
    name="notifications.services.email_tasks.send_email_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_email_task(self, to_email: str, subject: str, template_name: str, context: dict, notification_id: str | None = None) -> bool:
    """Celery task to send email using EmailSender.

    Retries on failure with exponential backoff and logs simple success/failure metrics.
    """
    sender = EmailSender()
    notif = None
    if notification_id:
        try:
            # Load notification from DB
            from notifications.models.notification import get_db

            db = get_db()
            collection = db[Notification.collection_name]
            doc = collection.find_one({"_id": ObjectId(notification_id)})
            notif = Notification.from_dict(doc)
        except Exception:
            notif = None

    success = sender._do_send(to_email, subject, template_name, context, notif)

    # Emit metrics
    try:
        if success:
            logger.info("email_task.success: to=%s template=%s", to_email, template_name)
            if EMAIL_TASK_SUCCESS is not None:
                EMAIL_TASK_SUCCESS.inc()
        else:
            logger.warning("email_task.failure: to=%s template=%s", to_email, template_name)
            if EMAIL_TASK_FAILURE is not None:
                EMAIL_TASK_FAILURE.inc()
    except Exception:
        logger.exception("Failed to log email task metric")

    # If notification provided and still present, mark accordingly
    try:
        if notif and getattr(notif, "_id", None):
            if success:
                notif.mark_sent()
            else:
                notif.mark_failed("async send failed")
    except Exception:
        logger.exception("Failed to update notification status after send")

    return success
