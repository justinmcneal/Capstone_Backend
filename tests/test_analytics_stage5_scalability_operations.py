"""Stage 5 query bounds, aggregation, throttling, and operations tests."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from bson import ObjectId
from pymongo.errors import ServerSelectionTimeoutError

from accounts.authentication import AuthenticatedUser
from accounts.utils.throttles import AnalyticsReadRateThrottle
from analytics.models import AuditLog
from analytics.services.operations import analytics_health_summary, bounded_count
from analytics.tasks import (
    audit_integrity_inventory_task,
    collect_operational_metrics_task,
)
from analytics.views import (
    AdminDashboardView,
    AuditLogDetailView,
    AuditLogsView,
    AuditLogUsersView,
    CustomerDashboardView,
    OfficerAuditLogsView,
    OfficerDashboardView,
)
from tests.test_analytics_api import (
    _auth_get_request,
    _bypass_auth,
    _create_admin,
    _restore_auth,
)


def _admin_user():
    admin = _create_admin(permissions=["view_analytics", "view_logs"])
    return AuthenticatedUser(
        customer_id=str(admin.id),
        email=admin.email,
        verified=True,
        role="admin",
    )


def _call(view, path, user, query=None):
    original_auth, original_perm = _bypass_auth(view)
    try:
        return view.as_view()(_auth_get_request(path, user, query))
    finally:
        _restore_auth(view, original_auth, original_perm)


def test_all_analytics_views_use_dedicated_authenticated_throttle():
    for view in (
        AdminDashboardView,
        AuditLogsView,
        AuditLogUsersView,
        AuditLogDetailView,
        OfficerDashboardView,
        OfficerAuditLogsView,
        CustomerDashboardView,
    ):
        assert view.throttle_classes == (AnalyticsReadRateThrottle,)
    assert AnalyticsReadRateThrottle.rate == "300/hour"


def test_deep_page_window_is_rejected_before_querying():
    response = _call(
        AuditLogsView,
        "/api/analytics/audit-logs/",
        _admin_user(),
        {"page": 502, "page_size": 20},
    )
    assert response.status_code == 400
    assert response.data["errors"]["page"].startswith("Use narrower filters")


def test_audit_search_is_prefix_bounded():
    AuditLog.log_action(
        action="user_login", user_type="customer", resource_id="needle-visible"
    )
    AuditLog.log_action(
        action="user_login", user_type="customer", resource_id="hidden-needle"
    )
    response = _call(
        AuditLogsView,
        "/api/analytics/audit-logs/",
        _admin_user(),
        {"search": "needle"},
    )
    ids = [row["resource_id"] for row in response.data["data"]["logs"]]
    assert "needle-visible" in ids
    assert "hidden-needle" not in ids


def test_query_timeout_is_passed_to_mongodb(settings):
    collection = settings.MONGODB["timeout_probe"]
    with patch.object(collection, "count_documents", wraps=collection.count_documents) as count:
        assert bounded_count(collection, {}) == 0
    assert count.call_args.kwargs["maxTimeMS"] == settings.ANALYTICS_QUERY_TIMEOUT_MS


def test_audit_compound_indexes_cover_bounded_query_shapes(settings):
    AuditLog.create_indexes()
    names = set(settings.MONGODB["audit_logs"].index_information())
    assert {
        "audit_actor_filter_sort",
        "audit_action_filter_sort",
        "audit_resource_filter_sort",
        "audit_officer_event_scope",
        "audit_retention_cleanup",
    }.issubset(names)


def test_admin_product_metrics_use_one_bounded_aggregation(settings):
    product_ids = [
        settings.MONGODB["loan_products"].insert_one(
            {"name": f"Product {index}", "active": True}
        ).inserted_id
        for index in range(3)
    ]
    settings.MONGODB["loan_applications"].insert_many(
        [
            {"product_id": str(product_id), "status": "approved"}
            for product_id in product_ids
        ]
    )
    loans = settings.MONGODB["loan_applications"]
    with patch.object(loans, "aggregate", wraps=loans.aggregate) as aggregate:
        response = _call(
            AdminDashboardView, "/api/analytics/admin/", _admin_user()
        )
    assert response.status_code == 200
    assert len(response.data["data"]["products"]) == 3
    assert aggregate.call_count == 1
    assert aggregate.call_args.kwargs["maxTimeMS"] == settings.ANALYTICS_QUERY_TIMEOUT_MS


def test_mongodb_outage_returns_sanitized_stable_503(settings):
    collection = settings.MONGODB["customer"]
    with patch.object(
        collection,
        "count_documents",
        side_effect=ServerSelectionTimeoutError("mongodb.internal:27017 secret"),
    ):
        response = _call(
            AdminDashboardView, "/api/analytics/admin/", _admin_user()
        )
    assert response.status_code == 503
    assert response.data["message"] == "Analytics service is temporarily unavailable"
    assert "mongodb.internal" not in str(response.data)


def test_health_summary_reports_only_bounded_operational_state(settings):
    now = datetime.now(timezone.utc)
    settings.MONGODB["audit_write_failures"].insert_one(
        {
            "event_id": "evt-health",
            "domain": "accounts",
            "resolved_at": None,
            "occurred_at": now - timedelta(seconds=90),
        }
    )
    settings.MONGODB["analytics_operational_state"].insert_one(
        {
            "_id": "audit_integrity_inventory",
            "invalid_integrity": 0,
            "missing_integrity": 0,
            "collected_at": now,
        }
    )
    summary = analytics_health_summary(settings.MONGODB)
    assert summary["ready"] is False
    assert summary["audit_backlog"] == 1
    assert summary["oldest_backlog_age_seconds"] >= 90
    assert not {"event_id", "domain", "occurred_at"}.intersection(summary)


def test_scheduled_inventory_and_metrics_persist_sanitized_snapshots(settings):
    AuditLog.log_action(
        action="user_login", user_id=str(ObjectId()), user_type="customer"
    )
    inventory = audit_integrity_inventory_task.run(limit=100)
    summary = collect_operational_metrics_task.run()
    assert inventory["invalid_integrity"] == 0
    assert summary["ready"] is True
    state = settings.MONGODB["analytics_operational_state"].find_one(
        {"_id": "operational_metrics"}
    )
    assert state["collected_at"] is not None
    assert "event_id" not in state
