from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bson import ObjectId
from rest_framework.test import APIRequestFactory

from accounts.models import LoanOfficer
from accounts.services.lockout_service import LockoutService
from accounts.services.password_service import PasswordService
from accounts.views.admin_views import AdminLoginView
from accounts.views.loan_officer_views import LoanOfficerLoginView


def _naive_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _loan_officer(locked_until):
    return SimpleNamespace(
        id="officer-id",
        email="officer@example.com",
        active=True,
        locked_until=locked_until,
        failed_login_attempts=0,
        check_password=Mock(return_value=False),
        save=Mock(),
    )


def _login_request():
    django_request = APIRequestFactory().post(
        "/api/auth/loan-officer/login/",
        {"email": "officer@example.com", "password": "incorrect"},
        format="json",
    )
    return LoanOfficerLoginView().initialize_request(django_request)


def _admin_login_request():
    django_request = APIRequestFactory().post(
        "/api/auth/admin/login/",
        {"username": "admin", "password": "incorrect"},
        format="json",
    )
    return AdminLoginView().initialize_request(django_request)


@patch("accounts.views.loan_officer_views._log_loan_officer_login_failure")
@patch("accounts.views.loan_officer_views.LoanOfficer.find_one")
def test_loan_officer_login_handles_active_naive_utc_lockout(find_one, log_failure):
    officer = _loan_officer(_naive_utc_now() + timedelta(minutes=5))
    find_one.return_value = officer

    response = LoanOfficerLoginView().post(_login_request())

    assert response.status_code == 401
    officer.check_password.assert_not_called()
    log_failure.assert_called_once()


@patch("accounts.views.loan_officer_views._log_loan_officer_login_failure")
@patch("accounts.views.loan_officer_views.LockoutService.record_failed_attempt")
@patch("accounts.views.loan_officer_views.LoanOfficer.find_one")
def test_loan_officer_login_handles_expired_naive_utc_lockout(
    find_one, record_failed, log_failure
):
    officer = _loan_officer(_naive_utc_now() - timedelta(minutes=5))
    find_one.return_value = officer
    record_failed.return_value = (False, 4)

    response = LoanOfficerLoginView().post(_login_request())

    assert response.status_code == 401
    officer.check_password.assert_called_once_with("incorrect")
    record_failed.assert_called_once_with(officer)
    officer.save.assert_not_called()
    log_failure.assert_called_once()


@patch("accounts.views.admin_views._log_admin_login_failure")
@patch("accounts.views.admin_views.Admin.find_one")
def test_admin_login_handles_active_naive_utc_lockout(find_one, log_failure):
    admin = SimpleNamespace(
        id="admin-id",
        email="admin@example.com",
        active=True,
        locked_until=_naive_utc_now() + timedelta(minutes=5),
    )
    find_one.return_value = admin

    response = AdminLoginView().post(_admin_login_request())

    assert response.status_code == 401
    log_failure.assert_called_once()


def test_customer_lockout_service_handles_active_naive_utc_lockout():
    customer = SimpleNamespace(
        locked_until=_naive_utc_now() + timedelta(minutes=5),
        failed_login_attempts=5,
        save=Mock(),
    )

    is_locked, seconds_remaining = LockoutService.is_account_locked(customer)

    assert is_locked is True
    assert 0 < seconds_remaining <= 300
    customer.save.assert_not_called()


def test_customer_lockout_service_resets_expired_naive_utc_lockout(settings):
    customer_id = ObjectId()
    expired_at = _naive_utc_now() - timedelta(minutes=5)
    settings.MONGODB["customer"].insert_one(
        {
            "_id": customer_id,
            "locked_until": expired_at,
            "failed_login_attempts": 5,
        }
    )
    customer = SimpleNamespace(
        _id=customer_id,
        collection_name="customer",
        email="customer@example.com",
        locked_until=expired_at,
        failed_login_attempts=5,
        save=Mock(),
    )

    is_locked, seconds_remaining = LockoutService.is_account_locked(customer)

    assert (is_locked, seconds_remaining) == (False, 0)
    assert customer.locked_until is None
    assert customer.failed_login_attempts == 0
    customer.save.assert_not_called()


@patch("accounts.services.password_service.LoanOfficer.find_one")
@patch("accounts.services.password_service.AuthService.get_customer_by_email")
def test_password_reset_role_selects_officer_when_customer_uses_same_email(
    get_customer, find_officer
):
    customer = object()
    officer = object()
    get_customer.return_value = customer
    find_officer.return_value = officer

    user, user_type = PasswordService._find_user_by_email(
        "officer@example.com", "loan_officer"
    )

    assert (user, user_type) == (officer, "loan_officer")
    get_customer.assert_not_called()


@patch("accounts.services.password_service.OTPService.validate_otp")
@patch("accounts.services.password_service.PasswordService._find_user_by_email")
def test_successful_officer_password_reset_clears_login_lockout(
    find_user, validate_otp, monkeypatch
):
    monkeypatch.setenv("SECRET_PEPPER", "a" * 64)
    officer = LoanOfficer(
        first_name="Test",
        last_name="Officer",
        email="officer@example.com",
        employee_id="LOCKOUT-001",
        department="Loans",
        failed_login_attempts=5,
        locked_until=_naive_utc_now() + timedelta(minutes=5),
        must_change_password=True,
        password_reset_attempt_count=0,
        password_reset_last_attempt=None,
        password_reset_otp="123456",
        password_reset_otp_expires=_naive_utc_now() + timedelta(minutes=5),
    )
    officer.set_password("OldPassword123!")
    officer.save()
    find_user.return_value = (officer, "loan_officer")
    validate_otp.return_value = (True, "OTP is valid")

    success, message = PasswordService.reset_password(
        officer.email, "123456", "NewPassword123!", "loan_officer"
    )

    assert success is True
    assert message == "Password has been reset successfully"
    stored = LoanOfficer.find_one({"_id": officer._id})
    assert stored.check_password("NewPassword123!") is True
    assert stored.failed_login_attempts == 0
    assert stored.locked_until is None
    assert stored.must_change_password is False
    assert stored.password_reset_otp is None
    assert stored.password_reset_otp_expires is None
