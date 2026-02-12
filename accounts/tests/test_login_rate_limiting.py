from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient


class FakeCustomer:
    def __init__(self, email):
        self.email = email
        self.verified = True
        self.last_login_attempt = None
        self.failed_login_attempts = 0
        self.locked_until = None
        self.two_factor_enabled = False
        self.id = "fake-customer-id"

    def save(self):
        return self

    def check_password(self, _raw_password):
        return False


class FakeAdmin:
    def __init__(self):
        self.active = True
        self.failed_login_attempts = 0
        self.locked_until = None
        self.two_factor_enabled = False
        self.super_admin = False
        self.permissions = []
        self.email = "admin@example.com"
        self.username = "admin"

    def save(self):
        return self

    def check_password(self, _raw_password):
        return False


class FakeLoanOfficer:
    def __init__(self):
        self.active = True
        self.failed_login_attempts = 0
        self.locked_until = None
        self.two_factor_enabled = False
        self.email = "officer@example.com"
        self.must_change_password = False
        self.verified = True

    def save(self):
        return self

    def check_password(self, _raw_password):
        return False


class LoginRateLimitingTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient(HTTP_HOST="localhost")
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_customer_ip_throttle_returns_429_after_10_requests(self):
        statuses = []
        response_body = None

        with patch(
            "accounts.views.auth_views.AuthService.get_customer_by_email",
            return_value=None,
        ):
            for _ in range(11):
                response = self.client.post(
                    "/api/auth/login/",
                    {"email": "missing@example.com", "password": "WrongPass123!"},
                    format="json",
                    REMOTE_ADDR="10.20.30.40",
                )
                statuses.append(response.status_code)
                response_body = response.json()

        self.assertEqual(statuses[:10], [401] * 10)
        self.assertEqual(statuses[10], 429)
        self.assertIn("throttled", response_body["detail"].lower())

    def test_customer_per_user_short_window_returns_429(self):
        customer = FakeCustomer(email="rate@example.com")

        with patch(
            "accounts.views.auth_views.AuthService.get_customer_by_email",
            return_value=customer,
        ):
            first = self.client.post(
                "/api/auth/login/",
                {"email": customer.email, "password": "WrongPass123!"},
                format="json",
                REMOTE_ADDR="10.20.30.41",
            )

        with patch(
            "accounts.views.auth_views.AuthService.get_customer_by_email",
            return_value=customer,
        ):
            second = self.client.post(
                "/api/auth/login/",
                {"email": customer.email, "password": "WrongPass123!"},
                format="json",
                REMOTE_ADDR="10.20.30.41",
            )

        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 429)
        message = second.json()["message"]
        self.assertIn("Please try again in", message)
        self.assertIn("seconds", message)

    def test_admin_login_uses_lockout_not_drf_ip_throttle(self):
        admin = FakeAdmin()
        statuses = []
        messages = []

        with patch("accounts.views.admin_views.Admin.find_one", return_value=admin):
            for _ in range(6):
                response = self.client.post(
                    "/api/auth/admin/login/",
                    {"username": "admin", "password": "WrongPass123!"},
                    format="json",
                    REMOTE_ADDR="10.20.30.42",
                )
                statuses.append(response.status_code)
                messages.append(response.json()["message"])

        self.assertNotIn(429, statuses)
        self.assertEqual(statuses[:4], [401, 401, 401, 401])
        self.assertEqual(statuses[4:], [403, 403])
        self.assertIn("Account locked due to too many failed attempts", messages[4])
        self.assertIn("Account is locked", messages[5])

    def test_loan_officer_login_uses_lockout_not_drf_ip_throttle(self):
        officer = FakeLoanOfficer()
        statuses = []
        messages = []

        with patch(
            "accounts.views.loan_officer_views.LoanOfficer.find_one",
            return_value=officer,
        ):
            for _ in range(6):
                response = self.client.post(
                    "/api/auth/loan-officer/login/",
                    {"email": officer.email, "password": "WrongPass123!"},
                    format="json",
                    REMOTE_ADDR="10.20.30.43",
                )
                statuses.append(response.status_code)
                messages.append(response.json()["message"])

        self.assertNotIn(429, statuses)
        self.assertEqual(statuses[:4], [401, 401, 401, 401])
        self.assertEqual(statuses[4:], [403, 403])
        self.assertIn("Account locked due to too many failed attempts", messages[4])
        self.assertIn("Account is locked", messages[5])