from types import SimpleNamespace
import pytest
from unittest.mock import MagicMock

import notifications.services.email_sender as es_module


class DummyEmail:
    def __init__(self):
        self.alternatives = []
        self.sent = False

    def attach_alternative(self, html, mime):
        self.alternatives.append((html, mime))

    def send(self, fail_silently=False):
        self.sent = True
        return 1


class DummyNotification:
    def __init__(self):
        self.sent = False
        self.failed = False
        self.error = None

    def save(self):
        return self

    def mark_sent(self):
        self.sent = True
        return self

    def mark_failed(self, err):
        self.failed = True
        self.error = err
        return self


def test_send_success(monkeypatch):
    # Arrange
    monkeypatch.setattr(es_module, "render_to_string", lambda tpl, ctx: f"rendered:{tpl}")
    monkeypatch.setattr(es_module, "EmailMultiAlternatives", lambda **kwargs: DummyEmail())

    sender = es_module.EmailSender()
    notif = DummyNotification()

    # Act
    ok = sender.send(
        to_email="user@example.com",
        subject="Test",
        template_name="loan_submitted",
        context={"name": "Test"},
        notification=notif,
    )

    # Assert
    assert ok is True
    assert notif.sent is True
    assert notif.failed is False


def test_send_failure_marks_notification(monkeypatch):
    # Arrange
    monkeypatch.setattr(es_module, "render_to_string", lambda tpl, ctx: f"rendered:{tpl}")

    class BadEmail(DummyEmail):
        def send(self, fail_silently=False):
            raise RuntimeError("SMTP down")

    monkeypatch.setattr(es_module, "EmailMultiAlternatives", lambda **kwargs: BadEmail())

    sender = es_module.EmailSender()
    notif = DummyNotification()

    # Act
    ok = sender.send(
        to_email="user@example.com",
        subject="Test",
        template_name="loan_submitted",
        context={"name": "Test"},
        notification=notif,
    )

    # Assert
    assert ok is False
    assert notif.sent is False
    assert notif.failed is True
    assert "SMTP" in notif.error


def test_missing_template_increments_failure_metric(monkeypatch):
    # Arrange
    failure_counter = MagicMock()

    def raise_missing_template(tpl, ctx):
        raise es_module.TemplateDoesNotExist(tpl)

    monkeypatch.setattr(es_module, "render_to_string", raise_missing_template)
    monkeypatch.setattr(es_module, "EMAIL_SEND_FAILURE_COUNTER", failure_counter)

    sender = es_module.EmailSender()
    notif = DummyNotification()

    # Act
    ok = sender.send(
        to_email="user@example.com",
        subject="Test",
        template_name="missing_template",
        context={},
        notification=notif,
    )

    # Assert
    assert ok is False
    assert notif.failed is True
    failure_counter.inc.assert_called_once_with()
