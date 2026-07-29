from unittest.mock import patch, MagicMock
from notifications.services.email_tasks import send_email_task


def test_send_email_task_calls_sender_send():
    fake_sender = MagicMock()
    fake_sender.send.return_value = True

    with patch("notifications.services.email_tasks.EmailSender", return_value=fake_sender):
        result = send_email_task(
            to_email="user@example.com",
            subject="Test",
            template_name="loan_submitted",
            context={"name": "User"},
            notification_id=None,
        )

    assert result is True
    fake_sender.send.assert_called_once_with(
        "user@example.com",
        "Test",
        "loan_submitted",
        {"name": "User"},
        None,
    )


def test_send_email_task_marks_notification_failed_on_send_failure():
    fake_sender = MagicMock()
    fake_sender.send.return_value = False

    fake_notif = MagicMock()
    fake_notif._id = "507f1f77bcf86cd799439011"
    fake_notif.mark_failed = MagicMock()
    fake_notif.mark_sent = MagicMock()

    fake_collection = MagicMock()
    fake_collection.find_one.return_value = {"_id": "507f1f77bcf86cd799439011"}

    fake_db = MagicMock()
    fake_db.__getitem__.return_value = fake_collection

    fake_notif_cls = MagicMock()
    fake_notif_cls.from_dict.return_value = fake_notif
    fake_notif_cls.collection_name = "notifications"

    with patch("notifications.services.email_tasks.EmailSender", return_value=fake_sender):
        with patch("notifications.services.email_tasks.Notification", fake_notif_cls):
            result = send_email_task(
                to_email="user@example.com",
                subject="Test",
                template_name="loan_submitted",
                context={"name": "User"},
                notification_id="507f1f77bcf86cd799439011",
            )

    assert result is False
    fake_notif.mark_failed.assert_called_once_with("async send failed")
    fake_notif.mark_sent.assert_not_called()
