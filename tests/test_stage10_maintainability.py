"""Stage 10 boundaries for product rules, bulk loading, imports, and config."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mongomock
import pytest
from bson import ObjectId

from config.mongodb import LazyMongoDatabase
from loans.models import LoanApplication, LoanProduct
from loans.services.product_rules import (
    ProductRuleViolation,
    normalized_recommendation,
    validate_application_terms,
    validate_product_bounds,
)
from loans.services.related_data import application_related_maps


def test_product_rules_are_shared_for_bounds_requests_and_recommendations():
    product = SimpleNamespace(
        min_amount=5_000,
        max_amount=50_000,
        min_term_months=3,
        max_term_months=24,
    )
    assert validate_product_bounds(
        {"min_amount": 60_000, "max_amount": 50_000}, product
    ) == {
        "max_amount": "Maximum amount must be greater than or equal to minimum amount"
    }
    with pytest.raises(ProductRuleViolation) as amount_error:
        validate_application_terms(product, 4_999, 12)
    assert amount_error.value.field == "requested_amount"
    with pytest.raises(ProductRuleViolation) as term_error:
        validate_application_terms(product, 10_000, 25)
    assert term_error.value.field == "term_months"
    assert (
        normalized_recommendation(
            product,
            20_000,
            {"eligible": True, "recommended_amount": 90_000},
        )
        == 20_000
    )


def test_related_application_data_is_loaded_in_three_bulk_queries(settings):
    database = mongomock.MongoClient()["stage10"]
    settings.MONGODB = database
    customer_id = ObjectId()
    officer_id = ObjectId()
    product = LoanProduct(name="Batch Product").save()
    database["customer"].insert_one(
        {
            "_id": customer_id,
            "first_name": "Batch",
            "last_name": "Customer",
        }
    )
    database["loan_officer"].insert_one(
        {
            "_id": officer_id,
            "first_name": "Batch",
            "last_name": "Officer",
            "email": "batch-officer@example.test",
        }
    )
    application = LoanApplication(
        customer_id=str(customer_id),
        product_id=product.id,
        assigned_officer=str(officer_id),
    ).save()

    from loans.services import related_data

    with patch.object(
        related_data,
        "model_map_by_ids",
        wraps=related_data.model_map_by_ids,
    ) as bulk_loader:
        related = application_related_maps([application])

    assert related["customers"][str(customer_id)].full_name == "Batch Customer"
    assert related["products"][product.id].name == "Batch Product"
    assert bulk_loader.call_count == 3


def test_customer_view_groups_preserve_compatibility_imports():
    from loans.views.customer import LoanApplyView as focused
    from loans.views.customer_views import LoanApplyView as compatibility

    assert focused is compatibility


def test_lazy_mongodb_does_not_construct_client_until_first_use():
    database = MagicMock()
    client = MagicMock()
    client.__getitem__.return_value = database
    with patch("config.mongodb.MongoClient", return_value=client) as constructor:
        lazy = LazyMongoDatabase("mongodb://example.invalid", "capstone")
        constructor.assert_not_called()
        assert lazy["loan_applications"] is database["loan_applications"]
        constructor.assert_called_once_with("mongodb://example.invalid")


def test_production_dependency_lock_uses_exact_pins():
    from pathlib import Path

    lines = Path("requirements.lock").read_text(encoding="utf-8").splitlines()
    requirements = [line for line in lines if line and not line.startswith("#")]
    assert requirements
    assert all("==" in requirement for requirement in requirements)
