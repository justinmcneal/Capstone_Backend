from email.message import MIMEPart

from django.conf import settings
from django.template.loader import render_to_string

from accounts.services.email_service import CentralizedEmailService


def test_verification_template_uses_signup_copy_and_inline_logo():
    html = render_to_string(
        "email/verification.html",
        {
            "first_name": "Maria",
            "otp": "123456",
            "brand_logo_cid": "msme-pathways-logo",
        },
    )

    assert "Welcome to MSME Pathways!" in html
    assert "VERIFY EMAIL" in html
    assert "cid:msme-pathways-logo" in html
    assert "123456" in html


def test_email_change_template_has_distinct_security_copy_and_inline_logo():
    html = render_to_string(
        "email/email_change_verification.html",
        {
            "first_name": "Maria",
            "otp": "654321",
            "brand_logo_cid": "msme-pathways-logo",
        },
    )

    assert "Confirm your new email address" in html
    assert "EMAIL CHANGE" in html
    assert "current account email will stay active" in html
    assert "cid:msme-pathways-logo" in html
    assert "654321" in html


def test_temporary_password_template_displays_inline_logo():
    html = render_to_string(
        "email/loan_officer_temp_password.html",
        {
            "first_name": "Josh",
            "temporary_password": "temporary-secret",
            "brand_logo_cid": "msme-pathways-logo",
        },
    )

    assert 'src="cid:msme-pathways-logo"' in html
    assert ">MP</div>" not in html


def test_template_email_attaches_backend_owned_logo(mailoutbox):
    service = CentralizedEmailService()

    sent = service.send_template_email(
        to_emails=["customer@example.com"],
        subject="Verify Your Email Address",
        template_name="verification",
        context={"first_name": "Maria", "otp": "123456"},
    )

    assert sent is True
    assert len(mailoutbox) == 1

    inline_logo = next(
        attachment
        for attachment in mailoutbox[0].attachments
        if isinstance(attachment, MIMEPart)
        and attachment.get("Content-ID") == "<msme-pathways-logo>"
    )
    expected_logo = (
        settings.BASE_DIR / "accounts" / "static" / "email" / "msmeLogo.png"
    ).read_bytes()

    assert inline_logo.get_content_disposition() == "inline"
    assert inline_logo.get_content_type() == "image/png"
    assert inline_logo.get_payload(decode=True) == expected_logo
