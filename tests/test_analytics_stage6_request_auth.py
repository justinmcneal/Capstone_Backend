"""Stage 6 request-level JWT, URL routing, and role-permission evidence."""

from io import StringIO
from unittest.mock import patch

import pytest
from bson import ObjectId
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Admin, Customer, LoanOfficer
from accounts.utils.token_utils import TokenUtils


def _authorized_client(account, role):
    if role == "customer":
        tokens = TokenUtils.generate_jwt_tokens(account)
    else:
        tokens = TokenUtils.generate_tokens(
            user_id=account.id,
            email=account.email,
            verified=True,
            role=role,
            security_version=account.security_version,
        )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


def _admin(permissions):
    return Admin(
        username=f"analytics-admin-{ObjectId()}",
        email=f"analytics-admin-{ObjectId()}@example.test",
        password="hashed",
        first_name="Analytics",
        last_name="Admin",
        permissions=permissions,
        active=True,
    ).save()


def _officer():
    return LoanOfficer(
        employee_id=f"EMP-{ObjectId()}",
        first_name="Analytics",
        last_name="Officer",
        email=f"analytics-officer-{ObjectId()}@example.test",
        password="hashed",
        active=True,
        verified=True,
        must_change_password=False,
    ).save()


def _customer():
    return Customer(
        first_name="Analytics",
        last_name="Customer",
        email=f"analytics-customer-{ObjectId()}@example.test",
        password="hashed",
        verified=True,
        active=True,
        account_state="active",
    ).save()


def test_all_routes_reject_missing_jwt():
    client = APIClient()
    for url in (
        reverse("analytics:admin-dashboard"),
        reverse("analytics:audit-logs"),
        reverse("analytics:audit-log-users"),
        reverse("analytics:audit-log-detail", kwargs={"log_id": str(ObjectId())}),
        reverse("analytics:officer-dashboard"),
        reverse("analytics:officer-audit-logs"),
        reverse("analytics:customer-dashboard"),
    ):
        assert client.get(url).status_code in {401, 403}


def test_live_admin_jwt_enforces_named_permissions_through_urls():
    analytics_only = _authorized_client(_admin(["view_analytics"]), "admin")
    logs_only = _authorized_client(_admin(["view_logs"]), "admin")

    dashboard = analytics_only.get(reverse("analytics:admin-dashboard"))
    assert dashboard.status_code == 200
    assert dashboard.json()["data"]["recent_activity_restricted"] is True
    assert analytics_only.get(reverse("analytics:audit-logs")).status_code == 403

    assert logs_only.get(reverse("analytics:audit-logs")).status_code == 200
    assert logs_only.get(reverse("analytics:audit-log-users")).status_code == 200
    assert logs_only.get(reverse("analytics:admin-dashboard")).status_code == 403


def test_live_role_jwts_enforce_customer_officer_and_admin_boundaries():
    customer_client = _authorized_client(_customer(), "customer")
    officer_client = _authorized_client(_officer(), "loan_officer")
    admin_client = _authorized_client(
        _admin(["view_analytics", "view_logs"]), "admin"
    )

    assert customer_client.get(reverse("analytics:customer-dashboard")).status_code == 200
    assert customer_client.get(reverse("analytics:officer-dashboard")).status_code == 403
    assert customer_client.get(reverse("analytics:admin-dashboard")).status_code == 403

    assert officer_client.get(reverse("analytics:officer-dashboard")).status_code == 200
    assert officer_client.get(reverse("analytics:officer-audit-logs")).status_code == 200
    assert officer_client.get(reverse("analytics:customer-dashboard")).status_code == 403
    assert officer_client.get(reverse("analytics:audit-logs")).status_code == 403

    assert admin_client.get(reverse("analytics:admin-dashboard")).status_code == 200
    assert admin_client.get(reverse("analytics:audit-logs")).status_code == 200
    assert admin_client.get(reverse("analytics:officer-dashboard")).status_code == 403
    assert admin_client.get(reverse("analytics:customer-dashboard")).status_code == 403


def test_revoked_session_is_rejected_by_full_authentication_stack():
    admin = _admin(["view_analytics"])
    client = _authorized_client(admin, "admin")
    assert client.get(reverse("analytics:admin-dashboard")).status_code == 200

    TokenUtils.revoke_all_sessions(admin.id, "admin")
    assert client.get(reverse("analytics:admin-dashboard")).status_code == 401


def test_release_check_is_read_only_and_fails_when_a_gate_is_missing(settings):
    report = {
        "ready": False,
        "checks": {"validator_present": False},
        "health": {"ready": False},
    }
    with (
        patch(
            "analytics.management.commands.analytics_release_check.analytics_release_readiness",
            return_value=report,
        ) as readiness,
        pytest.raises(CommandError, match="readiness checks failed"),
    ):
        call_command("analytics_release_check", stdout=StringIO())
    readiness.assert_called_once_with(settings.MONGODB)
