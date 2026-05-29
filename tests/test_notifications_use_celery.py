from unittest.mock import patch
from notifications.services.email_sender import EmailSender


def test_send_uses_celery_delay_called():
    sender = EmailSender(use_celery=True)

    with patch("notifications.services.email_tasks.send_email_task.delay") as mock_delay:
        result = sender.send(
            to_email="user@example.com",
            subject="Test",
            template_name="loan_submitted",
            context={"name": "User"},
            notification=None,
        )

        assert result is True
        mock_delay.assert_called_once()


def test_send_uses_celery_marks_failed_on_enqueue_error():
    sender = EmailSender(use_celery=True)

    class FakeNotification:
        def __init__(self):
            self._id = "507f1f77bcf86cd799439011"
            self.failed = False

        def mark_failed(self, reason=None):
            self.failed = True

    fake_notif = FakeNotification()

    # Make delay raise an exception to exercise the error path
    with patch("notifications.services.email_tasks.send_email_task.delay", side_effect=Exception("boom")) as mock_delay:
        result = sender.send(
            to_email="user@example.com",
            subject="Test",
            template_name="loan_submitted",
            context={"name": "User"},
            notification=fake_notif,
        )

        assert result is False
        assert fake_notif.failed is True