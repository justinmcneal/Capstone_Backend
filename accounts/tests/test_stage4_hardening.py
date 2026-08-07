import os
from datetime import datetime, timedelta, timezone

import pytest
from django.conf import settings
from django.test import RequestFactory, override_settings

from accounts.models import Customer
from accounts.services.auth_service import AuthService
from accounts.services.lockout_service import LockoutService
from accounts.services.password_service import PasswordService
from accounts.services.two_factor_service import TwoFactorService
from accounts.tasks import (
    reconcile_password_reset_email_deliveries_task,
    send_password_reset_email_task,
)
from accounts.utils.request_utils import get_client_ip
from accounts.utils.throttles import (
    AdminLoginRateThrottle,
    ForgotPasswordRateThrottle,
    LoanOfficerLoginRateThrottle,
    LoginIdentifierRateThrottle,
    LoginRateThrottle,
    OTPIdentifierRateThrottle,
    OTPResendRateThrottle,
    OTPVerificationRateThrottle,
    PasswordResetRateThrottle,
    RefreshTokenRateThrottle,
    SignUpIdentifierRateThrottle,
    SignUpRateThrottle,
    TwoFactorRateThrottle,
    TwoFactorTokenRateThrottle,
)
from accounts.views.admin_views import AdminLoginView
from accounts.views.auth_views import (
    LoginView,
    RefreshTokenView,
    ResendOTP,
    SignUpView,
    VerifyOTP,
)
from accounts.views.loan_officer_views import LoanOfficerLoginView
from accounts.views.password_views import (
    ForgotPasswordView,
    ResetPasswordView,
    VerifyResetOTPView,
)
from accounts.views.two_factor_views import Verify2FAView


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


def _customer(email="stage4@example.com", *, verified=True):
    customer = Customer(
        first_name="Stage",
        last_name="Four",
        email=email,
        verified=verified,
    )
    customer.set_password("OldPass123!")
    customer.save()
    return customer


def test_all_auth_throttles_remain_100_per_hour():
    throttle_classes = (
        SignUpRateThrottle,
        LoginRateThrottle,
        LoanOfficerLoginRateThrottle,
        AdminLoginRateThrottle,
        OTPVerificationRateThrottle,
        OTPResendRateThrottle,
        TwoFactorRateThrottle,
        PasswordResetRateThrottle,
        ForgotPasswordRateThrottle,
        LoginIdentifierRateThrottle,
        OTPIdentifierRateThrottle,
        TwoFactorTokenRateThrottle,
        SignUpIdentifierRateThrottle,
        RefreshTokenRateThrottle,
    )
    assert {throttle.rate for throttle in throttle_classes} == {"100/hour"}


def test_public_auth_endpoints_use_compound_ip_and_subject_throttles():
    expected = {
        SignUpView: (SignUpRateThrottle, SignUpIdentifierRateThrottle),
        LoginView: (LoginRateThrottle, LoginIdentifierRateThrottle),
        LoanOfficerLoginView: (
            LoanOfficerLoginRateThrottle,
            LoginIdentifierRateThrottle,
        ),
        AdminLoginView: (AdminLoginRateThrottle, LoginIdentifierRateThrottle),
        VerifyOTP: (OTPVerificationRateThrottle, OTPIdentifierRateThrottle),
        ResendOTP: (OTPResendRateThrottle, OTPIdentifierRateThrottle),
        ForgotPasswordView: (ForgotPasswordRateThrottle, OTPIdentifierRateThrottle),
        VerifyResetOTPView: (
            OTPVerificationRateThrottle,
            OTPIdentifierRateThrottle,
        ),
        ResetPasswordView: (
            OTPVerificationRateThrottle,
            OTPIdentifierRateThrottle,
        ),
        Verify2FAView: (TwoFactorRateThrottle, TwoFactorTokenRateThrottle),
        RefreshTokenView: (RefreshTokenRateThrottle,),
    }

    for view, throttle_classes in expected.items():
        assert view.throttle_classes == throttle_classes


def test_mongodb_lockout_is_authoritative_over_django_axes():
    assert settings.AXES_LOCK_OUT_AT_FAILURE is False
    assert LockoutService.MAX_ATTEMPTS == 5
    assert LockoutService.LOCKOUT_DURATION == timedelta(minutes=15)


def test_login_failure_increment_is_atomic_across_stale_instances():
    customer = _customer("atomic-login@example.com")
    first = Customer.find_one({"_id": customer._id})
    second = Customer.find_one({"_id": customer._id})

    LockoutService.record_failed_attempt(first)
    LockoutService.record_failed_attempt(second)

    stored = Customer.find_one({"_id": customer._id})
    assert stored.failed_login_attempts == 2


def test_email_verification_otp_has_only_one_winner():
    customer = _customer("atomic-verification@example.com", verified=False)
    customer.verification_token = "123456"
    customer.verification_token_expires = datetime.now(timezone.utc) + timedelta(
        minutes=10
    )
    customer.save()
    first = Customer.find_one({"_id": customer._id})
    second = Customer.find_one({"_id": customer._id})

    assert AuthService.verify_customer_otp(first, "123456") is first
    assert AuthService.verify_customer_otp(second, "123456") is None


def test_backup_code_can_only_be_consumed_once():
    customer = _customer("atomic-backup@example.com")
    plain_codes, hashed_codes = TwoFactorService.generate_backup_codes(count=1)
    customer.backup_codes = hashed_codes
    customer.save()
    first = Customer.find_one({"_id": customer._id})
    second = Customer.find_one({"_id": customer._id})

    assert TwoFactorService.use_backup_code(first, plain_codes[0]) is True
    assert TwoFactorService.use_backup_code(second, plain_codes[0]) is False


def test_password_reset_issuance_cooldown_suppresses_duplicate_email(monkeypatch):
    customer = _customer("reset-cooldown@example.com")
    queued = []
    monkeypatch.setattr(
        "accounts.services.password_service.queue_password_reset_delivery",
        lambda **kwargs: queued.append(kwargs) or True,
    )

    assert PasswordService.initiate_password_reset(customer.email)[0] is True
    first_otp = Customer.find_one({"_id": customer._id}).password_reset_otp
    assert PasswordService.initiate_password_reset(customer.email)[0] is True
    stored = Customer.find_one({"_id": customer._id})

    assert len(queued) == 1
    assert stored.password_reset_otp == first_otp
    assert stored.password_reset_issue_count == 1
    assert stored.password_reset_delivery_status == "pending"


def test_password_reset_email_task_loads_otp_from_database(monkeypatch):
    customer = _customer("reset-task@example.com")
    monkeypatch.setattr(
        "accounts.services.password_service.queue_password_reset_delivery",
        lambda **_kwargs: True,
    )
    PasswordService.initiate_password_reset(customer.email)
    stored = Customer.find_one({"_id": customer._id})
    delivered = []
    monkeypatch.setattr(
        "accounts.tasks.EmailUtils.send_password_reset_email",
        lambda **kwargs: delivered.append(kwargs) or True,
    )

    result = send_password_reset_email_task.run(
        customer.id,
        "customer",
        stored.password_reset_otp_expires.isoformat(),
    )
    raw = settings.MONGODB[Customer.collection_name].find_one({"_id": customer._id})

    assert result is True
    assert delivered == [
        {
            "email": customer.email,
            "first_name": customer.first_name,
            "otp": stored.password_reset_otp,
        }
    ]
    assert raw["password_reset_delivery_status"] == "sent"
    assert raw["password_reset_delivery_attempts"] == 1


def test_password_reset_enqueue_failure_is_recoverable(monkeypatch):
    customer = _customer("reset-reconcile@example.com")
    monkeypatch.setattr(
        "accounts.tasks.send_password_reset_email_task.delay",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    PasswordService.initiate_password_reset(customer.email)
    collection = settings.MONGODB[Customer.collection_name]
    pending = collection.find_one({"_id": customer._id})
    assert pending["password_reset_delivery_status"] == "pending"

    collection.update_one(
        {"_id": customer._id},
        {
            "$set": {
                "password_reset_delivery_next_attempt_at": datetime.now(timezone.utc)
                - timedelta(seconds=1)
            }
        },
    )
    requeued = []
    monkeypatch.setattr(
        "accounts.tasks.send_password_reset_email_task.delay",
        lambda *args, **_kwargs: requeued.append(args),
    )

    assert reconcile_password_reset_email_deliveries_task.run() == 1
    recovered = collection.find_one({"_id": customer._id})
    assert recovered["password_reset_delivery_status"] == "queued"
    assert len(requeued) == 1


def test_password_reset_otp_has_only_one_password_update_winner(monkeypatch):
    customer = _customer("atomic-reset@example.com")
    monkeypatch.setattr(
        "accounts.services.password_service.queue_password_reset_delivery",
        lambda **_kwargs: True,
    )
    PasswordService.initiate_password_reset(customer.email)
    first = Customer.find_one({"_id": customer._id})
    second = Customer.find_one({"_id": customer._id})
    otp = first.password_reset_otp

    first_result = PasswordService.reset_password(first.email, otp, "FirstNewPass123!")
    second_result = PasswordService.reset_password(
        second.email, otp, "SecondNewPass123!"
    )
    stored = Customer.find_one({"_id": customer._id})

    assert first_result[0] is True
    assert second_result[0] is False
    assert stored.check_password("FirstNewPass123!") is True
    assert stored.check_password("SecondNewPass123!") is False


@override_settings(REST_FRAMEWORK={"NUM_PROXIES": 0})
def test_client_ip_ignores_forwarded_header_when_no_proxy_is_trusted():
    request = RequestFactory().get(
        "/", REMOTE_ADDR="203.0.113.10", HTTP_X_FORWARDED_FOR="198.51.100.4"
    )
    assert get_client_ip(request) == "203.0.113.10"


@override_settings(REST_FRAMEWORK={"NUM_PROXIES": 2})
def test_client_ip_uses_configured_trusted_proxy_depth():
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="192.0.2.20",
        HTTP_X_FORWARDED_FOR="198.51.100.4, 192.0.2.10",
    )
    assert get_client_ip(request) == "198.51.100.4"
