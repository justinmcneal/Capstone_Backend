import json
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from django.conf import settings

from ai_assistant.services.officer_scope import OfficerAssistantScope
from loans.models import LoanApplication

from ai_assistant.services.officer_tools import (
    OFFICER_TOOL_SCHEMAS,
    execute_officer_tool_result,
)


@pytest.fixture
def officer_scope(monkeypatch):
    application = LoanApplication(
        customer_id="customer-42",
        product_id=str(ObjectId()),
        requested_amount=10000,
        recommended_amount=9000,
        approved_amount=8500,
        term_months=12,
        purpose="inventory",
        eligibility_score=78,
        risk_category="medium",
        status="under_review",
        assigned_officer="officer-1",
    ).save()
    settings.MONGODB["loan_products"].insert_one(
        {"_id": ObjectId(application.product_id), "name": "Working Capital"}
    )
    settings.MONGODB["customer_profiles"].insert_one(
        {
            "customer_id": "customer-42",
            "completion_percentage": 70,
            "profile_completed": False,
            "profile_missing_fields": [
                "personal.first_name",
                "personal.address",
                "personal.date_of_birth",
            ],
            "email": "customer@example.com",
            "mobile_number": "09171234567",
            "address": "Sensitive address",
            "date_of_birth": "1990-01-01",
            "wallet_address": "0xsecret",
        }
    )
    settings.MONGODB["business_profiles"].insert_one(
        {
            "customer_id": "customer-42",
            "completion_percentage": 80,
            "profile_completed": False,
            "profile_missing_fields": ["business.business_type"],
            "business_name": "Sensitive business name",
            "business_address": "Sensitive business address",
        }
    )
    settings.MONGODB["alternative_data"].insert_one(
        {
            "customer_id": "customer-42",
            "completion_percentage": 100,
            "profile_completed": True,
            "profile_missing_fields": [],
            "risk_score_status": "calculated",
            "risk_category": "medium",
            "risk_score_manual_review_required": True,
            "household_income": 50000,
            "existing_loan_source": "Sensitive lender",
        }
    )
    settings.MONGODB["documents"].insert_one(
        {
            "customer_id": "customer-42",
            "document_type": "valid_id",
            "status": "approved",
            "verified": True,
            "verified_at": datetime.now(timezone.utc),
            "original_filename": "identity-card.png",
            "file_path": "private/customer-42/id.png",
            "storage_state": "available",
            "notes": "Internal review note",
            "description": "Document content must not reach the provider",
        }
    )
    settings.MONGODB["repayment_schedules"].insert_one(
        {
            "loan_id": str(application.id),
            "customer_id": "customer-42",
            "status": "active",
            "monthly_payment": 1000,
            "installments": [
                {
                    "number": 1,
                    "status": "paid",
                    "due_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
                    "total_amount": 1000,
                    "paid_amount": 1000,
                    "reference": "payment-ref-1",
                },
                {
                    "number": 2,
                    "status": "pending",
                    "due_date": datetime(2026, 2, 1, tzinfo=timezone.utc),
                    "total_amount": 1000,
                    "paid_amount": 0,
                    "wallet": "0xwallet",
                },
            ],
            "blockchain_schedule_tx": "0xtx",
            "applied_payment_tokens": ["private-token"],
        }
    )
    monkeypatch.setattr(
        "ai_assistant.services.officer_tools.has_current_ai_consent",
        lambda scope: True,
    )
    return OfficerAssistantScope(
        officer_id="officer-1",
        application_id=str(application.id),
        customer_id="customer-42",
        application=application,
    )


def _reassign(application_id, officer_id):
    settings.MONGODB[LoanApplication.collection_name].update_one(
        {"_id": ObjectId(application_id)}, {"$set": {"assigned_officer": officer_id}}
    )


def test_officer_tool_schemas_expose_only_four_parameterless_tools():
    assert {schema["function"]["name"] for schema in OFFICER_TOOL_SCHEMAS} == {
        "get_application_summary",
        "get_profile_readiness",
        "get_document_review_status",
        "get_repayment_summary",
    }
    for schema in OFFICER_TOOL_SCHEMAS:
        parameters = schema["function"]["parameters"]
        assert parameters["properties"] == {}
        assert parameters["required"] == []


def test_officer_tools_return_only_allowlisted_application_bound_summaries(officer_scope):
    results = {
        tool_name: execute_officer_tool_result(
            tool_name, {}, officer_scope, request_id="request-1"
        )
        for tool_name in (
            "get_application_summary",
            "get_profile_readiness",
            "get_document_review_status",
            "get_repayment_summary",
        )
    }

    assert all(result["success"] is True for result in results.values())
    serialized = json.dumps(results).lower()
    for forbidden in (
        "customer-42",
        "officer-1",
        "email",
        "phone",
        "address",
        "date_of_birth",
        "wallet",
        "identity-card",
        "file_path",
        "storage",
        "document content",
        "internal review note",
        "payment-ref",
        "0xtx",
        "private-token",
    ):
        assert forbidden not in serialized


def test_officer_tool_rejects_scope_after_reassignment(officer_scope):
    _reassign(officer_scope.application_id, "another-officer")

    result = execute_officer_tool_result(
        "get_application_summary", {}, officer_scope, request_id="request-1"
    )

    assert result == {
        "success": False,
        "error": "Officer access to this application is no longer available.",
        "code": "AI_OFFICER_SCOPE_CHANGED",
    }


def test_officer_tool_rechecks_current_customer_consent(officer_scope, monkeypatch):
    monkeypatch.setattr(
        "ai_assistant.services.officer_tools.has_current_ai_consent",
        lambda scope: False,
    )

    result = execute_officer_tool_result(
        "get_application_summary", {}, officer_scope, request_id="request-1"
    )

    assert result == {
        "success": False,
        "error": "Customer AI consent is no longer available.",
        "code": "AI_OFFICER_CONSENT_CHANGED",
    }


def test_officer_tool_fails_closed_when_scope_revalidation_cannot_complete(
    officer_scope, monkeypatch
):
    def unavailable(scope):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "ai_assistant.services.officer_tools.revalidate_officer_scope", unavailable
    )

    result = execute_officer_tool_result(
        "get_application_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["code"] == "AI_OFFICER_SCOPE_CHANGED"


def test_officer_tool_rejects_unknown_names_and_scope_shaped_arguments(officer_scope):
    unknown = execute_officer_tool_result(
        "get_every_customer", {}, officer_scope, request_id="request-1"
    )
    invalid_args = execute_officer_tool_result(
        "get_application_summary",
        {"customer_id": "another-customer"},
        officer_scope,
        request_id="request-1",
    )

    assert unknown["code"] == "AI_OFFICER_TOOL_UNKNOWN"
    assert invalid_args["code"] == "AI_OFFICER_TOOL_VALIDATION_FAILED"
