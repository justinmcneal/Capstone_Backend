"""Administrator product catalog filter and pagination contracts."""

from types import SimpleNamespace

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from loans.views.admin.products import AdminProductListView


@pytest.mark.parametrize(
    ("active", "expected_query"),
    [
        ("all", {}),
        ("true", {"active": True}),
        ("false", {"active": False}),
    ],
)
def test_admin_product_status_filters_are_distinct(
    monkeypatch, active, expected_query
):
    calls = {}

    def count(query, active_only):
        calls["count"] = {"query": dict(query), "active_only": active_only}
        return 0

    def find(query, active_only, skip, limit):
        calls["find"] = {
            "query": dict(query),
            "active_only": active_only,
            "skip": skip,
            "limit": limit,
        }
        return []

    monkeypatch.setattr(
        "loans.views.admin.products.LoanProduct.count", staticmethod(count)
    )
    monkeypatch.setattr(
        "loans.views.admin.products.LoanProduct.find", staticmethod(find)
    )
    monkeypatch.setattr(
        AdminProductListView,
        "check_admin_permission",
        lambda self, request: (True, request.user),
    )

    user = SimpleNamespace(
        customer_id="admin-products",
        role="admin",
        is_authenticated=True,
    )
    request = APIRequestFactory().get(
        f"/api/loans/admin/products/?active={active}&page=2&page_size=20"
    )
    force_authenticate(request, user=user)

    response = AdminProductListView.as_view()(request)

    assert response.status_code == 200
    assert calls == {
        "count": {"query": expected_query, "active_only": False},
        "find": {
            "query": expected_query,
            "active_only": False,
            "skip": 20,
            "limit": 20,
        },
    }
    assert response.data["data"] == {
        "products": [],
        "total": 0,
        "page": 2,
        "page_size": 20,
        "total_pages": 0,
    }
