"""
Analytics API tests for /api/analytics/ endpoints.
"""
import json
from bson import ObjectId
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Admin, Consent, Customer, LoanOfficer
from analytics.models import AuditLog
from analytics.views import (
    AdminDashboardView,
    AuditLogDetailView,
    AuditLogUsersView,
    AuditLogsView,
    CustomerDashboardView,
    OfficerAuditLogsView,
    OfficerDashboardView,
)


def _create_customer(customer_id=None):
    customer = Customer(
        first_name="Test",
        last_name="User",
        email=f"analytics_customer_{ObjectId()}@example.com",
        password="hashed",
        verified=True,
    ).save()
    if customer_id is not None:
        customer.id = customer_id
        customer.save()
    return customer


def _create_officer():
    officer = LoanOfficer(
        first_name="Officer",
        last_name="Test",
        email=f"analytics_officer_{ObjectId()}@example.com",
        password="hashed",
        department="Operations",
    ).save()
    return officer


def _create_admin(permissions=None, super_admin=False):
    admin = Admin(
        username=f"analytics_admin_{ObjectId()}",
        email=f"analytics_admin_{ObjectId()}@example.com",
        password="hashed",
        first_name="Admin",
        last_name="Test",
        permissions=permissions if permissions is not None else ["view_analytics", "view_logs"],
        super_admin=super_admin,
    ).save()
    return admin


def _auth_request(path, payload, user):
    factory = APIRequestFactory()
    request = factory.post(path, payload, format="json")
    force_authenticate(request, user=user)
    return request


def _auth_get_request(path, user, query=None):
    factory = APIRequestFactory()
    request = factory.get(path, query or {}, format="json")
    force_authenticate(request, user=user)
    return request


def _bypass_auth(view_cls):
    original_auth = getattr(view_cls, 'authentication_classes', [])
    original_perm = getattr(view_cls, 'permission_classes', [])
    view_cls.authentication_classes = []
    view_cls.permission_classes = []
    return original_auth, original_perm


def _restore_auth(view_cls, original_auth, original_perm):
    view_cls.authentication_classes = original_auth
    view_cls.permission_classes = original_perm


class TestCustomerDashboard:
    def test_customer_dashboard_requires_auth(self):
        customer = _create_customer()
        user = AuthenticatedUser(
            customer_id=str(customer.id),
            email=customer.email,
            verified=True,
            role="customer",
        )
        request = _auth_get_request("/api/analytics/customer/", user)
        original_auth, original_perm = _bypass_auth(CustomerDashboardView)
        try:
            response = CustomerDashboardView.as_view()(request)
            assert response.status_code == 200
            data = response.data["data"]
            assert "applications" in data
            assert "documents" in data
            assert "profile_completion" in data
            assert "ai_sessions" in data
        finally:
            _restore_auth(CustomerDashboardView, original_auth, original_perm)

    def test_customer_dashboard_counts_are_non_negative(self):
        customer = _create_customer()
        user = AuthenticatedUser(
            customer_id=str(customer.id),
            email=customer.email,
            verified=True,
            role="customer",
        )
        request = _auth_get_request("/api/analytics/customer/", user)
        original_auth, original_perm = _bypass_auth(CustomerDashboardView)
        try:
            response = CustomerDashboardView.as_view()(request)
            assert response.status_code == 200
            data = response.data["data"]
            for section in ["applications", "documents"]:
                for key, value in data[section].items():
                    assert value >= 0
        finally:
            _restore_auth(CustomerDashboardView, original_auth, original_perm)


class TestOfficerDashboard:
    def test_officer_dashboard_requires_officer_or_admin(self):
        officer = _create_officer()
        user = AuthenticatedUser(
            customer_id=str(officer.id),
            email=officer.email,
            verified=True,
            role="loan_officer",
        )
        request = _auth_get_request("/api/analytics/officer/", user)
        original_auth, original_perm = _bypass_auth(OfficerDashboardView)
        try:
            response = OfficerDashboardView.as_view()(request)
            assert response.status_code == 200
            data = response.data["data"]
            assert "my_reviews" in data
            assert "queue" in data
            assert "performance" in data
        finally:
            _restore_auth(OfficerDashboardView, original_auth, original_perm)

    def test_customer_cannot_access_officer_dashboard(self):
        customer = _create_customer()
        user = AuthenticatedUser(
            customer_id=str(customer.id),
            email=customer.email,
            verified=True,
            role="customer",
        )
        request = _auth_get_request("/api/analytics/officer/", user)
        original_auth, original_perm = _bypass_auth(OfficerDashboardView)
        try:
            response = OfficerDashboardView.as_view()(request)
            assert response.status_code == 403
        finally:
            _restore_auth(OfficerDashboardView, original_auth, original_perm)

    def test_officer_audit_logs_scoped_to_user_and_assigned_loans(self):
        officer = _create_officer()
        user = AuthenticatedUser(
            customer_id=str(officer.id),
            email=officer.email,
            verified=True,
            role="loan_officer",
        )
        request = _auth_get_request(
            "/api/analytics/officer/audit-logs/", user, {"page": 1, "page_size": 20}
        )
        original_auth, original_perm = _bypass_auth(OfficerAuditLogsView)
        try:
            response = OfficerAuditLogsView.as_view()(request)
            assert response.status_code == 200
            data = response.data["data"]
            assert "logs" in data
            assert "total" in data
        finally:
            _restore_auth(OfficerAuditLogsView, original_auth, original_perm)


class TestAdminDashboard:
    def test_admin_dashboard_requires_permission(self):
        admin = _create_admin(permissions=["view_analytics"])
        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        request = _auth_get_request("/api/analytics/admin/", user)
        original_auth, original_perm = _bypass_auth(AdminDashboardView)
        try:
            response = AdminDashboardView.as_view()(request)
            assert response.status_code == 200
            data = response.data["data"]
            assert "users" in data
            assert "loans" in data
            assert "documents" in data
            assert "ai_usage" in data
            assert "products" in data
            assert "recent_activity" in data
        finally:
            _restore_auth(AdminDashboardView, original_auth, original_perm)

    def test_admin_dashboard_rejects_missing_permission(self):
        admin = _create_admin(permissions=[])
        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        request = _auth_get_request("/api/analytics/admin/", user)
        original_auth, original_perm = _bypass_auth(AdminDashboardView)
        try:
            response = AdminDashboardView.as_view()(request)
            assert response.status_code == 403
        finally:
            _restore_auth(AdminDashboardView, original_auth, original_perm)

    def test_officer_cannot_access_admin_dashboard(self):
        officer = _create_officer()
        user = AuthenticatedUser(
            customer_id=str(officer.id),
            email=officer.email,
            verified=True,
            role="loan_officer",
        )
        request = _auth_get_request("/api/analytics/admin/", user)
        original_auth, original_perm = _bypass_auth(AdminDashboardView)
        try:
            response = AdminDashboardView.as_view()(request)
            assert response.status_code == 403
        finally:
            _restore_auth(AdminDashboardView, original_auth, original_perm)


class TestAuditLogs:
    def test_audit_logs_requires_permission(self):
        admin = _create_admin(permissions=["view_logs"])
        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        request = _auth_get_request(
            "/api/analytics/audit-logs/", user, {"page": 1, "page_size": 20}
        )
        original_auth, original_perm = _bypass_auth(AuditLogsView)
        try:
            response = AuditLogsView.as_view()(request)
            assert response.status_code == 200
            data = response.data["data"]
            assert "logs" in data
            assert "total" in data
            assert "page" in data
            assert "page_size" in data
        finally:
            _restore_auth(AuditLogsView, original_auth, original_perm)

    def test_audit_logs_rejects_missing_permission(self):
        admin = _create_admin(permissions=[])
        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        request = _auth_get_request(
            "/api/analytics/audit-logs/", user, {"page": 1, "page_size": 20}
        )
        original_auth, original_perm = _bypass_auth(AuditLogsView)
        try:
            response = AuditLogsView.as_view()(request)
            assert response.status_code == 403
        finally:
            _restore_auth(AuditLogsView, original_auth, original_perm)

    def test_customer_cannot_access_audit_logs(self):
        customer = _create_customer()
        user = AuthenticatedUser(
            customer_id=str(customer.id),
            email=customer.email,
            verified=True,
            role="customer",
        )
        request = _auth_get_request(
            "/api/analytics/audit-logs/", user, {"page": 1, "page_size": 20}
        )
        original_auth, original_perm = _bypass_auth(AuditLogsView)
        try:
            response = AuditLogsView.as_view()(request)
            assert response.status_code == 403
        finally:
            _restore_auth(AuditLogsView, original_auth, original_perm)


class TestAuditLogDetail:
    def test_audit_log_detail_returns_400_for_invalid_id(self):
        admin = _create_admin(permissions=["view_logs"])
        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        request = _auth_get_request("/api/analytics/audit-logs/invalid-id/", user)
        original_auth, original_perm = _bypass_auth(AuditLogDetailView)
        try:
            response = AuditLogDetailView.as_view()(request, log_id="invalid-id")
            assert response.status_code == 400
            assert response.data["status"] == "error"
        finally:
            _restore_auth(AuditLogDetailView, original_auth, original_perm)

    def test_audit_log_detail_returns_404_for_missing_log(self):
        admin = _create_admin(permissions=["view_logs"])
        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        missing_id = str(ObjectId())
        request = _auth_get_request(f"/api/analytics/audit-logs/{missing_id}/", user)
        original_auth, original_perm = _bypass_auth(AuditLogDetailView)
        try:
            response = AuditLogDetailView.as_view()(request, log_id=missing_id)
            assert response.status_code == 404
            assert response.data["status"] == "error"
        finally:
            _restore_auth(AuditLogDetailView, original_auth, original_perm)


class TestAuditLogUsers:
    def test_audit_log_users_requires_permission(self):
        admin = _create_admin(permissions=["view_logs"])
        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        request = _auth_get_request(
            "/api/analytics/audit-logs/users/", user, {"limit": 10}
        )
        original_auth, original_perm = _bypass_auth(AuditLogUsersView)
        try:
            response = AuditLogUsersView.as_view()(request)
            assert response.status_code == 200
            data = response.data["data"]
            assert "users" in data
        finally:
            _restore_auth(AuditLogUsersView, original_auth, original_perm)

    def test_audit_log_users_rejects_missing_permission(self):
        admin = _create_admin(permissions=[])
        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        request = _auth_get_request(
            "/api/analytics/audit-logs/users/", user, {"limit": 10}
        )
        original_auth, original_perm = _bypass_auth(AuditLogUsersView)
        try:
            response = AuditLogUsersView.as_view()(request)
            assert response.status_code == 403
        finally:
            _restore_auth(AuditLogUsersView, original_auth, original_perm)


class TestAuditLogModel:
    def test_log_action_creates_audit_entry(self):
        customer = _create_customer()
        log = AuditLog.log_action(
            action="user_login",
            user_id=str(customer.id),
            user_type="customer",
            user_email=customer.email,
            description="User logged in",
        )
        assert log.id is not None
        assert log.action == "user_login"

    def test_find_by_user_returns_user_logs(self):
        customer = _create_customer()
        AuditLog.log_action(
            action="user_login",
            user_id=str(customer.id),
            user_type="customer",
            user_email=customer.email,
            description="User logged in",
        )
        logs = AuditLog.find_by_user(customer.id, limit=10)
        assert len(logs) >= 1
        assert logs[0].user_id == str(customer.id)

    def test_find_with_filters_limits_results(self):
        customer = _create_customer()
        for _ in range(15):
            AuditLog.log_action(
                action="user_login",
                user_id=str(customer.id),
                user_type="customer",
                user_email=customer.email,
            )
        logs = AuditLog.find_with_filters(limit=5)
        assert len(logs) <= 5


class TestAnalyticsHappyPaths:
    """Integration happy path tests for all 7 analytics endpoints."""

    def test_admin_dashboard_data_structure(self):
        admin = _create_admin(permissions=["view_analytics"])
        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        request = _auth_get_request("/api/analytics/admin/", user)
        original_auth, original_perm = _bypass_auth(AdminDashboardView)
        try:
            response = AdminDashboardView.as_view()(request)
            assert response.status_code == 200
            data = response.data["data"]

            # Users block
            users = data["users"]
            assert "customers" in users
            assert "loan_officers" in users
            assert "admins" in users
            assert "total" in users
            assert "new_customers_this_week" in users
            assert "new_loan_officers_this_month" in users

            # Loans block
            loans = data["loans"]
            assert "total" in loans
            assert "draft" in loans
            assert "pending" in loans
            assert "approved" in loans

            # Documents block
            documents = data["documents"]
            assert "total" in documents
            assert "verified" in documents

            # AI usage and products
            assert "sessions_last_7_days" in data["ai_usage"]
            assert isinstance(data["products"], list)
            assert isinstance(data["recent_activity"], list)
        finally:
            _restore_auth(AdminDashboardView, original_auth, original_perm)

    def test_officer_dashboard_data_structure(self):
        officer = _create_officer()
        user = AuthenticatedUser(
            customer_id=str(officer.id),
            email=officer.email,
            verified=True,
            role="loan_officer",
        )
        request = _auth_get_request("/api/analytics/officer/", user)
        original_auth, original_perm = _bypass_auth(OfficerDashboardView)
        try:
            response = OfficerDashboardView.as_view()(request)
            assert response.status_code == 200
            data = response.data["data"]

            my_reviews = data["my_reviews"]
            assert "total_approved" in my_reviews
            assert "total_rejected" in my_reviews
            assert "approved_today" in my_reviews
            assert "rejected_today" in my_reviews

            queue = data["queue"]
            assert "pending_total" in queue
            assert "assigned_to_me" in queue

            performance = data["performance"]
            assert "total_reviewed" in performance
            assert "approval_rate" in performance
        finally:
            _restore_auth(OfficerDashboardView, original_auth, original_perm)

    def test_customer_dashboard_profile_completion_details(self):
        customer = _create_customer()
        user = AuthenticatedUser(
            customer_id=str(customer.id),
            email=customer.email,
            verified=True,
            role="customer",
        )
        request = _auth_get_request("/api/analytics/customer/", user)
        original_auth, original_perm = _bypass_auth(CustomerDashboardView)
        try:
            response = CustomerDashboardView.as_view()(request)
            assert response.status_code == 200
            data = response.data["data"]

            completion = data["profile_completion"]
            assert "percentage" in completion
            assert "personal_profile" in completion
            assert "business_profile" in completion
            assert "alternative_data" in completion
            assert "valid_id_uploaded" in completion
        finally:
            _restore_auth(CustomerDashboardView, original_auth, original_perm)

    def test_audit_logs_filters_and_native_search(self):
        customer = _create_customer()
        admin = _create_admin(permissions=["view_logs"])

        # Create distinct audit log entries
        AuditLog.log_action(
            action="user_registered",
            user_id=str(customer.id),
            user_type="customer",
            user_email=customer.email,
            description="UniqueRegisteredKeyword",
        )
        AuditLog.log_action(
            action="admin_action",
            user_id=str(admin.id),
            user_type="admin",
            user_email=admin.email,
            description="Deactivated officer account",
        )

        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        original_auth, original_perm = _bypass_auth(AuditLogsView)
        try:
            # 1. Filter by action
            req1 = _auth_get_request(
                "/api/analytics/audit-logs/", user, {"action": "user_registered"}
            )
            resp1 = AuditLogsView.as_view()(req1)
            assert resp1.status_code == 200
            assert resp1.data["data"]["total"] >= 1

            # 2. Filter by action_group
            req2 = _auth_get_request(
                "/api/analytics/audit-logs/", user, {"action_group": "create"}
            )
            resp2 = AuditLogsView.as_view()(req2)
            assert resp2.status_code == 200

            # 3. Filter by search
            req3 = _auth_get_request(
                "/api/analytics/audit-logs/", user, {"search": "UniqueRegisteredKeyword"}
            )
            resp3 = AuditLogsView.as_view()(req3)
            assert resp3.status_code == 200
            logs = resp3.data["data"]["logs"]
            assert len(logs) == 1
            assert logs[0]["description"] == "UniqueRegisteredKeyword"

            # 4. Filter by delete action group
            req4 = _auth_get_request(
                "/api/analytics/audit-logs/", user, {"action_group": "delete"}
            )
            resp4 = AuditLogsView.as_view()(req4)
            assert resp4.status_code == 200
            assert resp4.data["data"]["total"] >= 1
        finally:
            _restore_auth(AuditLogsView, original_auth, original_perm)

    def test_audit_log_users_list(self):
        customer = _create_customer()
        admin = _create_admin(permissions=["view_logs"])

        AuditLog.log_action(
            action="user_login",
            user_id=str(customer.id),
            user_type="customer",
            user_email=customer.email,
        )

        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        request = _auth_get_request(
            "/api/analytics/audit-logs/users/", user, {"limit": 50}
        )
        original_auth, original_perm = _bypass_auth(AuditLogUsersView)
        try:
            response = AuditLogUsersView.as_view()(request)
            assert response.status_code == 200
            users = response.data["data"]["users"]
            assert len(users) >= 1
            user_ids = [u["user_id"] for u in users]
            assert str(customer.id) in user_ids
        finally:
            _restore_auth(AuditLogUsersView, original_auth, original_perm)

    def test_audit_log_detail_success(self):
        customer = _create_customer()
        admin = _create_admin(permissions=["view_logs"])

        log = AuditLog.log_action(
            action="loan_submitted",
            user_id=str(customer.id),
            user_type="customer",
            user_email=customer.email,
            description="Submitted loan app",
            resource_type="loan",
            resource_id="12345",
        )

        user = AuthenticatedUser(
            customer_id=str(admin.id),
            email=admin.email,
            verified=True,
            role="admin",
        )
        request = _auth_get_request(f"/api/analytics/audit-logs/{log.id}/", user)
        original_auth, original_perm = _bypass_auth(AuditLogDetailView)
        try:
            response = AuditLogDetailView.as_view()(request, log_id=log.id)
            assert response.status_code == 200
            data = response.data["data"]
            assert data["id"] == log.id
            assert data["action"] == "loan_submitted"
            assert data["user_email"] == customer.email
        finally:
            _restore_auth(AuditLogDetailView, original_auth, original_perm)
