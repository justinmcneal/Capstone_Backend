from datetime import datetime, timezone

from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Consent, ConsentEvent, Customer
from accounts.views import consent_views


def _auth_admin():
    return AuthenticatedUser(
        customer_id="admin-1",
        email="admin@example.test",
        verified=True,
        role="admin",
    )


def _customer(first_name, created_day):
    return Customer(
        first_name=first_name,
        last_name="Customer",
        email=f"{first_name.lower()}@example.test",
        verified=True,
        created_at=datetime(2026, 8, created_day, tzinfo=timezone.utc),
    ).save()


def _request(monkeypatch, path):
    monkeypatch.setattr(
        consent_views.AccessControlMixin,
        "require_admin",
        lambda self, request, required_permissions=None, super_admin_only=False: (
            True,
            object(),
        ),
    )
    request = APIRequestFactory().get(path)
    force_authenticate(request, user=_auth_admin())
    return consent_views.ConsentAuditView.as_view()(request)


def _seed_consent_audit(settings):
    settings.CONSENT_POLICY_VERSION = "policy-v2"
    alice = _customer("Alice", 1)
    bob = _customer("Bob", 2)
    carol = _customer("Carol", 3)

    Consent(
        user_id=alice._id,
        user_type="customer",
        data_consent=False,
        ai_consent=False,
        consent_version="legacy-policy",
    ).save()
    ConsentEvent(
        event_id=f"customer:{alice.id}:1",
        user_id=alice._id,
        revision=1,
        data_consent=False,
        ai_consent=False,
        consent_version="policy-v1",
        recorded_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    ).save()
    ConsentEvent(
        event_id=f"customer:{alice.id}:2",
        user_id=alice._id,
        revision=2,
        data_consent=True,
        ai_consent=True,
        consent_version="policy-v2",
        recorded_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    ).save()
    Consent(
        user_id=bob._id,
        user_type="customer",
        data_consent=True,
        ai_consent=False,
        consent_version="policy-v2",
    ).save()
    return alice, bob, carol


def test_consent_audit_paginates_rows_but_summarizes_all_customers(
    monkeypatch, settings
):
    _seed_consent_audit(settings)

    response = _request(monkeypatch, "/api/auth/consent/audit/?page=1&page_size=2")

    assert response.status_code == 200
    data = response.data["data"]
    assert data["summary"] == {
        "total_customers": 3,
        "ai_consent_true": 1,
        "ai_consent_false": 2,
        "missing_consent_records": 1,
    }
    assert [row["full_name"] for row in data["customers"]] == [
        "Carol Customer",
        "Bob Customer",
    ]
    assert data["customers"][0]["has_consent_record"] is False
    assert data["customers"][1]["data_consent"] is True
    assert data["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total_items": 3,
        "total_pages": 2,
        "has_next": True,
        "has_previous": False,
    }


def test_consent_audit_uses_a_constant_number_of_database_reads(
    monkeypatch, settings
):
    _seed_consent_audit(settings)
    read_count = 0

    def count_reads(collection, method_names):
        for method_name in method_names:
            original = getattr(collection, method_name)

            def counted(*args, _original=original, **kwargs):
                nonlocal read_count
                read_count += 1
                return _original(*args, **kwargs)

            monkeypatch.setattr(collection, method_name, counted)

    count_reads(settings.MONGODB["customer"], ("find",))
    # MongoMock implements aggregate by calling find internally. Count only the
    # public aggregate operation, which is one database command in PyMongo.
    count_reads(settings.MONGODB["consent_events"], ("aggregate",))
    count_reads(settings.MONGODB["consents"], ("find",))

    response = _request(monkeypatch, "/api/auth/consent/audit/?page=1&page_size=2")

    assert response.status_code == 200
    assert read_count <= 3


def test_consent_audit_rejects_invalid_pagination(monkeypatch):
    response = _request(monkeypatch, "/api/auth/consent/audit/?page=0")

    assert response.status_code == 400
    assert response.data["errors"] == {"page": "page must be at least 1"}
