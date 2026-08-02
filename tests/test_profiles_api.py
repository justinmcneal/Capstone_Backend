"""
Profiles API tests for /api/profile/ endpoints.

Coverage:
- Customer profile GET/PUT
- Business profile GET/PUT
- Alternative data GET/PUT
- Profile summary GET
- Notification preferences GET/PUT
- Role enforcement (customer allowed, non-customer returns 403)
- Auth enforcement (unauthenticated returns 401)
- Validation errors (invalid payloads)
"""

from unittest.mock import MagicMock

from bson import ObjectId
from django.core.cache import cache
from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Admin, Customer, LoanOfficer
from accounts.utils.throttles import ProfileRateThrottle
from profiles.models import AlternativeData, BusinessProfile, CustomerProfile
from profiles.views.profile_views import (
    AlternativeDataView,
    BusinessProfileView,
    CustomerProfileView,
    NotificationPreferencesView,
    OfficerCustomerProfilesListView,
    OfficerProfileView,
    ProfileSummaryView,
)


def _create_customer(customer_id=None):
    customer = Customer(
        first_name="Test",
        last_name="User",
        email=f"profile_customer_{ObjectId()}@example.com",
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
        email=f"profile_officer_{ObjectId()}@example.com",
        password="hashed",
        department="Operations",
    ).save()
    return officer


def _create_admin(permissions=None):
    admin = Admin(
        username=f"profile_admin_{ObjectId()}",
        email=f"profile_admin_{ObjectId()}@example.com",
        password="hashed",
        first_name="Admin",
        last_name="Test",
        permissions=permissions or ["manage_loans"],
        super_admin=False,
    ).save()
    return admin


def _auth_customer(customer):
    return AuthenticatedUser(
        customer_id=str(customer.id),
        email=customer.email,
        verified=True,
        role="customer",
    )


def _auth_officer(officer):
    return AuthenticatedUser(
        customer_id=str(officer.id),
        email=officer.email,
        verified=True,
        role="loan_officer",
    )


def _auth_admin(admin):
    return AuthenticatedUser(
        customer_id=str(admin.id),
        email=admin.email,
        verified=True,
        role="admin",
    )


def _get(path, user, query=None):
    factory = APIRequestFactory()
    request = factory.get(path, query or {}, format="json")
    force_authenticate(request, user=user)
    return request


def _put(path, payload, user):
    factory = APIRequestFactory()
    request = factory.put(path, payload, format="json")
    force_authenticate(request, user=user)
    return request


def test_all_profile_views_use_profile_rate_throttle():
    profile_views = (
        CustomerProfileView,
        BusinessProfileView,
        AlternativeDataView,
        ProfileSummaryView,
        NotificationPreferencesView,
        OfficerCustomerProfilesListView,
        OfficerProfileView,
    )

    assert all(
        ProfileRateThrottle in view.throttle_classes for view in profile_views
    )


# ── Customer profile ───────────────────────────────────────────────

class TestCustomerProfileView:
    def test_profile_rate_throttle_returns_429(self, monkeypatch):
        customer = _create_customer()
        profile = CustomerProfile(customer_id=str(customer.id), gender="male")

        monkeypatch.setattr(
            CustomerProfile,
            "get_or_create",
            staticmethod(lambda customer_id: profile),
            raising=False,
        )
        monkeypatch.setattr(
            CustomerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            CustomerProfileView, "permission_classes", [], raising=False
        )
        monkeypatch.setattr(ProfileRateThrottle, "rate", "2/hour")
        cache.clear()

        try:
            view = CustomerProfileView.as_view()
            responses = [
                view(_get("/api/profile/", _auth_customer(customer)))
                for _ in range(3)
            ]
        finally:
            cache.clear()

        assert [response.status_code for response in responses] == [200, 200, 429]

    def test_get_returns_profile_for_customer(self, monkeypatch):
        customer = _create_customer()
        profile = CustomerProfile(
            customer_id=str(customer.id),
            gender="male",
            barangay="Test Barangay",
        )

        monkeypatch.setattr(
            CustomerProfile,
            "get_or_create",
            staticmethod(lambda customer_id: profile),
            raising=False,
        )

        request = _get("/api/profile/", _auth_customer(customer))
        monkeypatch.setattr(
            CustomerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            CustomerProfileView, "permission_classes", [], raising=False
        )

        response = CustomerProfileView.as_view()(request)
        assert response.status_code == 200
        assert response.data["data"]["gender"] == "male"
        assert response.data["data"]["barangay"] == "Test Barangay"
        assert "profile_completed" in response.data["data"]

    def test_put_updates_profile_fields(self, monkeypatch):
        customer = _create_customer()
        profile = MagicMock()

        monkeypatch.setattr(
            CustomerProfile,
            "get_or_create",
            staticmethod(lambda customer_id: profile),
            raising=False,
        )
        monkeypatch.setattr(
            "profiles.views.profile_views.AuditLog.log_action",
            staticmethod(lambda *args, **kwargs: None),
            raising=False,
        )
        monkeypatch.setattr(
            CustomerProfile,
            "save",
            staticmethod(lambda self: self),
            raising=False,
        )

        payload = {
            "gender": "female",
            "civil_status": "single",
            "barangay": "New Barangay",
        }
        request = _put("/api/profile/", payload, _auth_customer(customer))
        monkeypatch.setattr(
            CustomerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            CustomerProfileView, "permission_classes", [], raising=False
        )

        response = CustomerProfileView.as_view()(request)
        assert response.status_code == 200
        assert profile.gender == "female"
        assert profile.barangay == "New Barangay"

    def test_officer_returns_403(self, monkeypatch):
        officer = _create_officer()
        request = _get("/api/profile/", _auth_officer(officer))
        monkeypatch.setattr(
            CustomerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            CustomerProfileView, "permission_classes", [], raising=False
        )

        response = CustomerProfileView.as_view()(request)
        assert response.status_code == 403

    def test_admin_returns_403(self, monkeypatch):
        admin = _create_admin()
        request = _get("/api/profile/", _auth_admin(admin))
        monkeypatch.setattr(
            CustomerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            CustomerProfileView, "permission_classes", [], raising=False
        )

        response = CustomerProfileView.as_view()(request)
        assert response.status_code == 403

    def test_put_validates_mobile_number(self, monkeypatch):
        customer = _create_customer()
        profile = CustomerProfile(customer_id=str(customer.id))

        monkeypatch.setattr(
            CustomerProfile,
            "get_or_create",
            staticmethod(lambda customer_id: profile),
            raising=False,
        )

        payload = {"mobile_number": "invalid"}
        request = _put("/api/profile/", payload, _auth_customer(customer))
        monkeypatch.setattr(
            CustomerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            CustomerProfileView, "permission_classes", [], raising=False
        )

        response = CustomerProfileView.as_view()(request)
        assert response.status_code == 400
        assert "mobile_number" in response.data["errors"]

    def test_put_validates_wallet_address(self, monkeypatch):
        customer = _create_customer()
        profile = CustomerProfile(customer_id=str(customer.id))

        monkeypatch.setattr(
            CustomerProfile,
            "get_or_create",
            staticmethod(lambda customer_id: profile),
            raising=False,
        )

        payload = {"wallet_address": "not-a-valid-address"}
        request = _put("/api/profile/", payload, _auth_customer(customer))
        monkeypatch.setattr(
            CustomerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            CustomerProfileView, "permission_classes", [], raising=False
        )

        response = CustomerProfileView.as_view()(request)
        assert response.status_code == 400
        assert "wallet_address" in response.data["errors"]


# ── Business profile ──────────────────────────────────────────────

class TestBusinessProfileView:
    def test_get_returns_business_profile(self, monkeypatch):
        customer = _create_customer()
        profile = BusinessProfile(
            customer_id=str(customer.id),
            business_name="Test Store",
            business_type="sari_sari_store",
        )

        monkeypatch.setattr(
            BusinessProfile,
            "get_or_create",
            staticmethod(lambda customer_id: profile),
            raising=False,
        )

        request = _get("/api/profile/business/", _auth_customer(customer))
        monkeypatch.setattr(
            BusinessProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            BusinessProfileView, "permission_classes", [], raising=False
        )

        response = BusinessProfileView.as_view()(request)
        assert response.status_code == 200
        assert response.data["data"]["business_name"] == "Test Store"
        assert response.data["data"]["business_type"] == "sari_sari_store"

    def test_put_creates_business_profile(self, monkeypatch):
        customer = _create_customer()
        profile = MagicMock()

        monkeypatch.setattr(
            BusinessProfile,
            "get_or_create",
            staticmethod(lambda customer_id: profile),
            raising=False,
        )
        monkeypatch.setattr(
            "profiles.views.profile_views.AuditLog.log_action",
            staticmethod(lambda *args, **kwargs: None),
            raising=False,
        )
        monkeypatch.setattr(
            BusinessProfile,
            "save",
            staticmethod(lambda self: self),
            raising=False,
        )

        payload = {
            "business_name": "New Store",
            "business_type": "market_vendor",
            "business_age_months": 24,
        }
        request = _put("/api/profile/business/", payload, _auth_customer(customer))
        monkeypatch.setattr(
            BusinessProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            BusinessProfileView, "permission_classes", [], raising=False
        )

        response = BusinessProfileView.as_view()(request)
        assert response.status_code == 200
        assert profile.business_name == "New Store"
        assert profile.business_age_months == 24

    def test_put_requires_business_type_other_when_type_is_other(self, monkeypatch):
        customer = _create_customer()
        profile = BusinessProfile(customer_id=str(customer.id))

        monkeypatch.setattr(
            BusinessProfile,
            "get_or_create",
            staticmethod(lambda customer_id: profile),
            raising=False,
        )

        payload = {"business_type": "other"}
        request = _put("/api/profile/business/", payload, _auth_customer(customer))
        monkeypatch.setattr(
            BusinessProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            BusinessProfileView, "permission_classes", [], raising=False
        )

        response = BusinessProfileView.as_view()(request)
        assert response.status_code == 400
        assert "business_type_other" in response.data["errors"]


# ── Alternative data ──────────────────────────────────────────────

class TestAlternativeDataView:
    def test_get_returns_alternative_data(self, monkeypatch):
        customer = _create_customer()
        data = AlternativeData(
            customer_id=str(customer.id),
            education_level="college_graduate",
            employment_status="employed",
        )

        monkeypatch.setattr(
            AlternativeData,
            "get_or_create",
            staticmethod(lambda customer_id: data),
            raising=False,
        )

        request = _get("/api/profile/alternative-data/", _auth_customer(customer))
        monkeypatch.setattr(
            AlternativeDataView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            AlternativeDataView, "permission_classes", [], raising=False
        )

        response = AlternativeDataView.as_view()(request)
        assert response.status_code == 200
        assert response.data["data"]["education_level"] == "college_graduate"
        assert response.data["data"]["employment_status"] == "employed"

    def test_put_updates_alternative_data(self, monkeypatch):
        customer = _create_customer()
        data = AlternativeData(customer_id=str(customer.id))

        monkeypatch.setattr(
            AlternativeData,
            "get_or_create",
            staticmethod(lambda customer_id: data),
            raising=False,
        )
        monkeypatch.setattr(
            "profiles.views.profile_views.AuditLog.log_action",
            staticmethod(lambda *args, **kwargs: None),
            raising=False,
        )

        payload = {
            "education_level": "postgraduate",
            "employment_status": "self_employed",
            "years_of_experience": 5,
        }
        request = _put(
            "/api/profile/alternative-data/", payload, _auth_customer(customer)
        )
        monkeypatch.setattr(
            AlternativeDataView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            AlternativeDataView, "permission_classes", [], raising=False
        )

        response = AlternativeDataView.as_view()(request)
        assert response.status_code == 200
        assert data.education_level == "postgraduate"
        assert data.years_of_experience == 5


# ── Profile summary ───────────────────────────────────────────────

class TestProfileSummaryView:
    def test_get_returns_summary(self, monkeypatch):
        customer = _create_customer()
        personal = CustomerProfile(
            customer_id=str(customer.id),
            profile_completed=True,
            completion_percentage=100,
        )
        business = BusinessProfile(
            customer_id=str(customer.id),
            business_type="sari_sari_store",
            income_range="30000_50000",
            profile_completed=True,
            completion_percentage=100,
        )
        alternative = AlternativeData(
            customer_id=str(customer.id),
            education_level="college_graduate",
            housing_status="owned",
            profile_completed=True,
            completion_percentage=100,
        )
        docs = []

        monkeypatch.setattr(
            CustomerProfile,
            "get_or_create",
            staticmethod(lambda customer_id: personal),
            raising=False,
        )
        monkeypatch.setattr(
            BusinessProfile,
            "get_or_create",
            staticmethod(lambda customer_id: business),
            raising=False,
        )
        monkeypatch.setattr(
            AlternativeData,
            "get_or_create",
            staticmethod(lambda customer_id: alternative),
            raising=False,
        )
        monkeypatch.setattr(
            "documents.models.Document.find_by_customer",
            staticmethod(lambda customer_id: docs),
            raising=False,
        )

        request = _get("/api/profile/summary/", _auth_customer(customer))
        monkeypatch.setattr(
            ProfileSummaryView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            ProfileSummaryView, "permission_classes", [], raising=False
        )

        response = ProfileSummaryView.as_view()(request)
        assert response.status_code == 200
        data = response.data["data"]
        assert data["personal_profile"]["completed"] is True
        assert data["business_profile"]["completed"] is True
        assert data["alternative_data"]["completed"] is True
        assert data["overall"]["ready_for_loan"] is True
        assert data["overall"]["completion_percentage"] == 100

    def test_get_returns_403_for_officer(self, monkeypatch):
        officer = _create_officer()
        request = _get("/api/profile/summary/", _auth_officer(officer))
        monkeypatch.setattr(
            ProfileSummaryView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            ProfileSummaryView, "permission_classes", [], raising=False
        )

        response = ProfileSummaryView.as_view()(request)
        assert response.status_code == 403


# ── Notification preferences ──────────────────────────────────────

class TestNotificationPreferencesView:
    def test_get_returns_default_preferences(self, monkeypatch):
        customer = _create_customer()
        mock_customer = MagicMock()
        mock_customer.notification_preferences = {
            "email_loan_updates": True,
            "email_payment_reminders": True,
            "email_promotions": False,
        }

        monkeypatch.setattr(
            "accounts.services.AuthService.get_customer_by_id",
            staticmethod(lambda customer_id: mock_customer),
            raising=False,
        )

        request = _get("/api/profile/notifications/", _auth_customer(customer))
        monkeypatch.setattr(
            NotificationPreferencesView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            NotificationPreferencesView, "permission_classes", [], raising=False
        )

        response = NotificationPreferencesView.as_view()(request)
        assert response.status_code == 200
        assert response.data["data"]["preferences"]["email_promotions"] is False

    def test_put_updates_preferences(self, monkeypatch):
        customer = _create_customer()
        mock_customer = MagicMock()
        mock_customer.notification_preferences = {
            "email_loan_updates": True,
            "email_payment_reminders": True,
            "email_promotions": False,
        }

        monkeypatch.setattr(
            "accounts.services.AuthService.get_customer_by_id",
            staticmethod(lambda customer_id: mock_customer),
            raising=False,
        )

        payload = {
            "preferences": {
                "email_loan_updates": False,
                "email_payment_reminders": True,
                "email_promotions": True,
            }
        }
        request = _put(
            "/api/profile/notifications/", payload, _auth_customer(customer)
        )
        monkeypatch.setattr(
            NotificationPreferencesView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            NotificationPreferencesView, "permission_classes", [], raising=False
        )

        response = NotificationPreferencesView.as_view()(request)
        assert response.status_code == 200
        assert mock_customer.notification_preferences["email_promotions"] is True

    def test_put_rejects_unknown_keys(self, monkeypatch):
        customer = _create_customer()
        mock_customer = MagicMock()
        mock_customer.notification_preferences = {}

        monkeypatch.setattr(
            "accounts.services.AuthService.get_customer_by_id",
            staticmethod(lambda customer_id: mock_customer),
            raising=False,
        )

        payload = {
            "preferences": {
                "email_loan_updates": True,
                "unknown_key": True,
            }
        }
        request = _put(
            "/api/profile/notifications/", payload, _auth_customer(customer)
        )
        monkeypatch.setattr(
            NotificationPreferencesView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            NotificationPreferencesView, "permission_classes", [], raising=False
        )

        response = NotificationPreferencesView.as_view()(request)
        assert response.status_code == 400
        assert "unknown" in response.data["message"].lower()
        assert "keys" in response.data["message"].lower()

    def test_put_requires_preferences_object(self, monkeypatch):
        customer = _create_customer()

        request = _put(
            "/api/profile/notifications/",
            {"preferences": "not-an-object"},
            _auth_customer(customer),
        )
        monkeypatch.setattr(
            NotificationPreferencesView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            NotificationPreferencesView, "permission_classes", [], raising=False
        )

        response = NotificationPreferencesView.as_view()(request)
        assert response.status_code == 400
        assert "preferences must be an object" in response.data["message"].lower()


class TestOfficerProfileView:
    def test_profile_route_uses_officer_namespace(self):
        match = resolve(f"/api/officer/profiles/{ObjectId()}/")
        assert match.func.view_class is OfficerProfileView

    def test_officer_can_view_customer_profile(self, monkeypatch):
        officer = _create_officer()
        customer = _create_customer()
        profile = CustomerProfile(
            customer_id=str(customer.id),
            gender="male",
            barangay="Test Barangay",
            profile_completed=True,
            completion_percentage=100,
        )

        monkeypatch.setattr(
            CustomerProfile,
            "find_by_customer",
            staticmethod(lambda customer_id: profile),
            raising=False,
        )

        request = _get(
            f"/api/officer/profiles/{customer.id}/",
            _auth_officer(officer),
        )
        monkeypatch.setattr(
            OfficerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            OfficerProfileView, "permission_classes", [], raising=False
        )

        response = OfficerProfileView.as_view()(request, customer_id=str(customer.id))
        assert response.status_code == 200
        assert response.data["data"]["personal_profile"]["profile_completed"] is True
        assert response.data["data"]["personal_profile"]["completion_percentage"] == 100

    def test_admin_cannot_view_customer_profile(self, monkeypatch):
        admin = _create_admin(permissions=["manage_loans"])
        customer = _create_customer()

        request = _get(
            f"/api/officer/profiles/{customer.id}/",
            _auth_admin(admin),
        )
        monkeypatch.setattr(
            OfficerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            OfficerProfileView, "permission_classes", [], raising=False
        )

        response = OfficerProfileView.as_view()(request, customer_id=str(customer.id))
        assert response.status_code == 403

    def test_customer_returns_403(self, monkeypatch):
        customer = _create_customer()
        request = _get(
            f"/api/profile/officer/{customer.id}/",
            _auth_customer(customer),
        )
        monkeypatch.setattr(
            OfficerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            OfficerProfileView, "permission_classes", [], raising=False
        )

        response = OfficerProfileView.as_view()(request, customer_id=str(customer.id))
        assert response.status_code == 403

    def test_invalid_customer_id_returns_400(self, monkeypatch):
        officer = _create_officer()
        request = _get(
            "/api/profile/officer/not-a-valid-id/",
            _auth_officer(officer),
        )
        monkeypatch.setattr(
            OfficerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            OfficerProfileView, "permission_classes", [], raising=False
        )

        response = OfficerProfileView.as_view()(request, customer_id="not-a-valid-id")
        assert response.status_code == 400
        assert "Invalid customer ID" in response.data["message"]

    def test_missing_customer_returns_404(self, monkeypatch):
        officer = _create_officer()
        customer_id = str(ObjectId())
        monkeypatch.setattr(
            Customer,
            "find_one",
            staticmethod(lambda query: None),
            raising=False,
        )

        request = _get(
            f"/api/officer/profiles/{customer_id}/",
            _auth_officer(officer),
        )
        monkeypatch.setattr(
            OfficerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            OfficerProfileView, "permission_classes", [], raising=False
        )

        response = OfficerProfileView.as_view()(request, customer_id=customer_id)
        assert response.status_code == 404
        assert response.data["message"] == "Customer not found"

    def test_response_excludes_wallet_and_account_secrets(self, monkeypatch):
        officer = _create_officer()
        customer = _create_customer()
        profile = CustomerProfile(
            customer_id=str(customer.id),
            mobile_number="+639171234567",
            wallet_address="0x1234567890abcdef1234567890abcdef12345678",
        )
        monkeypatch.setattr(
            CustomerProfile,
            "find_by_customer",
            staticmethod(lambda customer_id: profile),
            raising=False,
        )

        request = _get(
            f"/api/officer/profiles/{customer.id}/",
            _auth_officer(officer),
        )
        monkeypatch.setattr(
            OfficerProfileView, "authentication_classes", [], raising=False
        )
        monkeypatch.setattr(
            OfficerProfileView, "permission_classes", [], raising=False
        )

        response = OfficerProfileView.as_view()(request, customer_id=str(customer.id))
        data = response.data["data"]
        assert response.status_code == 200
        assert data["personal_profile"]["mobile_number"] == "+639171234567"
        assert "wallet_address" not in data["personal_profile"]
        assert "password" not in data
        assert "password_reset_otp" not in data

    def test_customer_directory_is_officer_only(self, monkeypatch):
        customer = _create_customer()
        request = _get("/api/officer/profiles/", _auth_customer(customer))
        monkeypatch.setattr(
            OfficerCustomerProfilesListView,
            "authentication_classes",
            [],
            raising=False,
        )
        monkeypatch.setattr(
            OfficerCustomerProfilesListView,
            "permission_classes",
            [],
            raising=False,
        )

        response = OfficerCustomerProfilesListView.as_view()(request)
        assert response.status_code == 403

    def test_officer_can_search_customer_directory(self, monkeypatch):
        officer = _create_officer()
        customer = _create_customer()
        profile = CustomerProfile(
            customer_id=str(customer.id),
            mobile_number="+639196331559",
        )
        monkeypatch.setattr(
            CustomerProfile,
            "find_by_customer",
            staticmethod(
                lambda customer_id: profile
                if str(customer_id) == str(customer.id)
                else None
            ),
            raising=False,
        )
        request = _get("/api/officer/profiles/", _auth_officer(officer))
        monkeypatch.setattr(
            OfficerCustomerProfilesListView,
            "authentication_classes",
            [],
            raising=False,
        )
        monkeypatch.setattr(
            OfficerCustomerProfilesListView,
            "permission_classes",
            [],
            raising=False,
        )

        response = OfficerCustomerProfilesListView.as_view()(request)
        assert response.status_code == 200
        assert any(
            item["customer_id"] == str(customer.id)
            and item["phone"] == "+639196331559"
            for item in response.data["data"]["customers"]
        )
