import json
from datetime import datetime, timezone

import mongomock.aggregate as mongomock_aggregate
import pytest
from bson import ObjectId
from bson.decimal128 import Decimal128
from cryptography.fernet import Fernet
from django.conf import settings

from ai_assistant.services import officer_tools
from ai_assistant.services.officer_scope import OfficerAssistantScope
from loans.models import LoanApplication, LoanPayment
from loans.models.repayment import RepaymentSchedule

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


@pytest.fixture
def encryption_enabled(monkeypatch):
    from config import field_encryption

    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    field_encryption._build_keyring.cache_clear()
    field_encryption._get_fernet.cache_clear()
    yield
    field_encryption._build_keyring.cache_clear()
    field_encryption._get_fernet.cache_clear()


@pytest.fixture
def mongomock_decimal128_aggregation(monkeypatch):
    """Let mongomock execute Decimal128 expressions as exact Decimal numbers."""
    original_parse = mongomock_aggregate._Parser.parse

    def parse_with_decimal128_numbers(parser, expression):
        value = original_parse(parser, expression)
        if isinstance(value, Decimal128):
            return value.to_decimal()
        return value

    monkeypatch.setattr(
        mongomock_aggregate._Parser,
        "parse",
        parse_with_decimal128_numbers,
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


def test_application_summary_matches_complete_safe_contract(officer_scope):
    settings.MONGODB[LoanApplication.collection_name].update_one(
        {"_id": ObjectId(officer_scope.application_id)},
        {
            "$set": {
                "ai_recommendation": {
                    "reason_codes": ["manual-review"],
                    "manual_review_required": True,
                }
            }
        },
    )
    settings.MONGODB["loan_products"].update_one(
        {"_id": ObjectId(officer_scope.application.product_id)},
        {"$set": {"code": "WCL"}},
    )

    result = execute_officer_tool_result(
        "get_application_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["product"] == {"category": "working_capital"}
    assert summary["requested_amount"] == 10000
    assert summary["recommended_amount"] == 9000
    assert summary["approved_amount"] == 8500
    assert summary["term_months"] == 12
    assert summary["purpose"] == "inventory"
    assert summary["eligibility_score"] == 78
    assert summary["risk_category"] == "medium"
    assert summary["reason_codes"] == ["manual-review"]
    assert summary["review_readiness"] == {
        "status": "ready_for_review",
        "is_reviewable": True,
        "manual_review_required": True,
    }


@pytest.mark.parametrize(
    ("application_status", "expected_readiness", "expected_reviewable"),
    [
        ("submitted", "ready_for_review", True),
        ("under_review", "ready_for_review", True),
        ("approved", "not_ready_for_review", False),
    ],
)
def test_application_summary_review_readiness_matches_lifecycle_status(
    officer_scope, application_status, expected_readiness, expected_reviewable
):
    settings.MONGODB[LoanApplication.collection_name].update_one(
        {"_id": ObjectId(officer_scope.application_id)},
        {"$set": {"status": application_status}},
    )

    result = execute_officer_tool_result(
        "get_application_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["review_readiness"] == {
        "status": expected_readiness,
        "is_reviewable": expected_reviewable,
        "manual_review_required": application_status == "under_review",
    }


def test_application_summary_omits_hostile_purpose_product_and_status_text(
    officer_scope,
):
    settings.MONGODB[LoanApplication.collection_name].update_one(
        {"_id": ObjectId(officer_scope.application_id)},
        {
            "$set": {
                "purpose": "Maria Santos needs funds at 123 Rizal",
                "status": "Approved for Maria Santos",
            }
        },
    )
    settings.MONGODB["loan_products"].update_one(
        {"_id": ObjectId(officer_scope.application.product_id)},
        {
            "$set": {
                "name": "Maria Santos Enterprise Loan",
                "code": "MARIA-SANTOS",
            }
        },
    )

    result = execute_officer_tool_result(
        "get_application_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    serialized = result["result"].lower()
    assert "maria santos" not in serialized
    assert "123 rizal" not in serialized
    assert summary["purpose"] is None
    assert summary["product"] == {"category": "other"}
    assert summary["status"] == "unknown"


def test_application_summary_bounds_hostile_persisted_scalars_and_reason_codes(
    officer_scope,
):
    settings.MONGODB[LoanApplication.collection_name].update_one(
        {"_id": ObjectId(officer_scope.application_id)},
        {
            "$set": {
                "requested_amount": -1,
                "recommended_amount": "Infinity",
                "approved_amount": Decimal128("1000000000000000000000000"),
                "term_months": 999999,
                "eligibility_score": "not-a-score",
                "risk_category": {"raw": "Maria Santos"},
                "status": "Approved for Maria Santos",
                "ai_recommendation": {
                    "reason_codes": [
                        "manual-review",
                        "income_high",
                        "unknown-code",
                        "Maria Santos",
                    ],
                    "manual_review_required": "false",
                },
            }
        },
    )

    result = execute_officer_tool_result(
        "get_application_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["status"] == "unknown"
    assert summary["risk_category"] == "unknown"
    assert summary["requested_amount"] == 0
    assert summary["recommended_amount"] == 0
    assert summary["approved_amount"] == 0
    assert summary["term_months"] == 0
    assert summary["eligibility_score"] == 0
    assert summary["reason_codes"] == ["manual-review", "income_high"]
    assert summary["review_readiness"]["manual_review_required"] is False
    assert "maria santos" not in result["result"].lower()


def test_profile_readiness_matches_complete_safe_contract(officer_scope):
    result = execute_officer_tool_result(
        "get_profile_readiness", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    readiness = json.loads(result["result"])
    assert readiness["personal"]["completion_percentage"] == 70
    assert readiness["business"]["missing_fields"] == [
        {"code": "business.business_type", "label": "Business type"}
    ]
    assert readiness["alternative"]["risk_status"] == "calculated"
    assert readiness["alternative"]["risk_score_status"] == "calculated"
    assert readiness["alternative"]["manual_review_required"] is True
    assert readiness["alternative"]["manual_review_flags"] == ["risk_score"]


def test_document_review_status_matches_complete_safe_contract(officer_scope):
    result = execute_officer_tool_result(
        "get_document_review_status", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    review = json.loads(result["result"])
    assert review["required_document_types"] == [
        {"code": "valid_id", "label": "Valid Government ID"}
    ]
    assert review["documents"] == [
        {
            "type_code": "valid_id",
            "type": "Valid Government ID",
            "status": "approved",
            "verified": True,
            "verification_status": "verified",
        }
    ]


def test_repayment_summary_matches_complete_safe_contract(officer_scope):
    settings.MONGODB["repayment_schedules"].update_one(
        {"loan_id": officer_scope.application_id},
        {
            "$set": {
                "term_months": 2,
                "total_amount": 2000,
                "monthly_payment": 1000,
            }
        },
    )

    result = execute_officer_tool_result(
        "get_repayment_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["schedule_progress"] == {
        "paid_count": 1,
        "installment_count": 2,
        "completed_percentage": 50,
    }
    assert summary["next_due_date"] == "2026-02-01T00:00:00"
    assert summary["payment_status_summaries"] == [
        {"status": "paid", "count": 1},
        {"status": "pending", "count": 1},
    ]
    assert summary["remaining_balance"] == 2000
    assert "reference" not in result["result"]
    assert "wallet" not in result["result"]


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


def test_officer_tool_fails_closed_when_consent_revalidation_cannot_complete(
    officer_scope, monkeypatch
):
    def unavailable(scope):
        raise RuntimeError("consent service unavailable")

    monkeypatch.setattr(
        "ai_assistant.services.officer_tools.has_current_ai_consent", unavailable
    )

    result = execute_officer_tool_result(
        "get_application_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["code"] == "AI_OFFICER_CONSENT_CHANGED"


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


def test_officer_tool_revalidates_scope_before_rejecting_nonempty_arguments(
    officer_scope,
):
    _reassign(officer_scope.application_id, "another-officer")

    result = execute_officer_tool_result(
        "get_application_summary",
        {"unexpected": True},
        officer_scope,
        request_id="request-1",
    )

    assert result["code"] == "AI_OFFICER_SCOPE_CHANGED"


def test_officer_tool_revalidates_consent_before_rejecting_nonempty_arguments(
    officer_scope, monkeypatch
):
    monkeypatch.setattr(
        "ai_assistant.services.officer_tools.has_current_ai_consent",
        lambda scope: False,
    )

    result = execute_officer_tool_result(
        "get_application_summary",
        {"unexpected": True},
        officer_scope,
        request_id="request-1",
    )

    assert result["code"] == "AI_OFFICER_CONSENT_CHANGED"


def test_profile_readiness_omits_unrecognized_or_identifier_missing_field_codes(
    officer_scope,
):
    unsafe_codes = [
        "personal.mobile_number",
        "personal.address_line1",
        "personal.city_municipality",
        "business.business_name",
        "legacy.field",
        "Free text supplied by Ana Santos",
        {"malformed": "missing code"},
    ]
    settings.MONGODB["customer_profiles"].update_one(
        {"customer_id": officer_scope.customer_id},
        {"$set": {"profile_missing_fields": unsafe_codes}},
    )
    settings.MONGODB["business_profiles"].update_one(
        {"customer_id": officer_scope.customer_id},
        {"$set": {"profile_missing_fields": unsafe_codes}},
    )

    result = execute_officer_tool_result(
        "get_profile_readiness", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    readiness = json.loads(result["result"])
    assert readiness["personal"]["missing_fields"] == []
    assert readiness["business"]["missing_fields"] == []
    serialized = result["result"].lower()
    for unsafe_value in (
        "mobile_number",
        "address_line1",
        "city_municipality",
        "business_name",
        "ana santos",
    ):
        assert unsafe_value not in serialized


def test_application_summary_omits_encrypted_customer_entered_fields(
    monkeypatch, encryption_enabled
):
    application = LoanApplication(
        customer_id="customer-99",
        product_id=str(ObjectId()),
        requested_amount=10000,
        purpose="Ana Santos needs funds at 123 PII Street",
        ai_recommendation={"reason_codes": ["manual-review"], "note": "Ana Santos"},
        assigned_officer="officer-99",
        status="under_review",
    ).save()
    raw = settings.MONGODB[LoanApplication.collection_name].find_one(
        {"_id": ObjectId(application.id)}
    )
    assert raw["purpose"].startswith("enc::")
    assert raw["ai_recommendation"].startswith("encbson::")
    scope = OfficerAssistantScope(
        officer_id="officer-99",
        application_id=application.id,
        customer_id="customer-99",
        application=application,
    )
    monkeypatch.setattr(
        "ai_assistant.services.officer_tools.has_current_ai_consent", lambda scope: True
    )

    result = execute_officer_tool_result(
        "get_application_summary", {}, scope, request_id="request-1"
    )

    assert result["success"] is True
    serialized = result["result"].lower()
    assert "ana santos" not in serialized
    assert "pii street" not in serialized
    assert "enc::" not in serialized
    assert "encbson::" not in serialized


def test_repayment_summary_uses_safe_aggregates_for_encrypted_long_schedules(
    officer_scope, monkeypatch, encryption_enabled
):
    installments = [
        {
            "number": number,
            "status": "paid" if number <= 6 else "pending",
            "total_amount": 1000,
            "paid_amount": 1000 if number <= 6 else 0,
            "reference": f"sensitive-reference-{number}",
        }
        for number in range(1, 31)
    ]
    settings.MONGODB["repayment_schedules"].delete_many(
        {"loan_id": officer_scope.application_id}
    )
    RepaymentSchedule(
        loan_id=officer_scope.application_id,
        customer_id=officer_scope.customer_id,
        term_months=30,
        monthly_payment=1000,
        total_amount=30000,
        installments=installments,
    ).save()
    settings.MONGODB["loan_payments"].insert_many(
        [
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount_centavos": 100000,
                "payment_status": "posted",
            }
            for _ in range(6)
        ]
    )
    raw = settings.MONGODB["repayment_schedules"].find_one(
        {"loan_id": officer_scope.application_id}
    )
    assert raw["installments"].startswith("encbson::")

    result = execute_officer_tool_result(
        "get_repayment_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["term_months"] == 30
    assert summary["total_amount"] == 30000
    assert summary["total_paid"] == 6000
    assert summary["remaining_balance"] == 24000
    assert "installments" not in summary
    assert "encbson::" not in result["result"]


def test_repayment_summary_counts_statusless_legacy_payments_as_posted(officer_scope):
    settings.MONGODB[LoanPayment.collection_name].insert_one(
        {
            "loan_id": officer_scope.application_id,
            "customer_id": officer_scope.customer_id,
            "amount_centavos": 125050,
        }
    )

    result = execute_officer_tool_result(
        "get_repayment_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["posted_payment_count"] == 1
    assert summary["total_paid"] == 1250.5


def test_repayment_summary_accurately_includes_amount_only_legacy_payments(
    officer_scope,
    mongomock_decimal128_aggregation,
):
    settings.MONGODB[LoanPayment.collection_name].insert_one(
        {
            "loan_id": officer_scope.application_id,
            "customer_id": officer_scope.customer_id,
            "amount": 1250.55,
        }
    )

    result = execute_officer_tool_result(
        "get_repayment_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["posted_payment_count"] == 1
    assert summary["total_paid"] == 1250.55


def test_repayment_summary_rounds_each_legacy_amount_before_aggregation(
    officer_scope,
    mongomock_decimal128_aggregation,
):
    settings.MONGODB[LoanPayment.collection_name].insert_many(
        [
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount": 0.005,
            },
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount": 0.005,
            },
        ]
    )

    result = execute_officer_tool_result(
        "get_repayment_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["posted_payment_count"] == 2
    assert summary["total_paid"] == 0.02


def test_repayment_summary_rejects_invalid_centavo_and_legacy_payment_rows(
    officer_scope,
    mongomock_decimal128_aggregation,
):
    settings.MONGODB[LoanPayment.collection_name].insert_many(
        [
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount_centavos": 101,
                "payment_status": "posted",
            },
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount_centavos": -50,
                "payment_status": "posted",
            },
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount_centavos": Decimal128("100.5"),
                "payment_status": "posted",
            },
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount_centavos": Decimal128("1000000000000000000000000"),
                "payment_status": "posted",
            },
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount": Decimal128("0.005"),
                "payment_status": "posted",
            },
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount": Decimal128("-1"),
                "payment_status": "posted",
            },
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount": "not-a-number",
                "payment_status": "posted",
            },
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount": Decimal128("NaN"),
                "payment_status": "posted",
            },
        ]
    )

    result = execute_officer_tool_result(
        "get_repayment_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["posted_payment_count"] == 2
    assert summary["total_paid"] == 1.02


def test_repayment_summary_bounds_invalid_schedule_centavos_and_dates(
    officer_scope,
):
    settings.MONGODB["repayment_schedules"].delete_many(
        {"loan_id": officer_scope.application_id}
    )
    settings.MONGODB["repayment_schedules"].insert_one(
        {
            "loan_id": officer_scope.application_id,
            "customer_id": officer_scope.customer_id,
            "status": {"raw": "private"},
            "term_months": "999999",
            "monthly_payment_centavos": Decimal128("100.5"),
            "total_amount_centavos": -1,
            "total_amount": "not-a-total",
            "installments": [
                {
                    "status": "paid",
                    "due_date": "not-a-date",
                    "total_amount_centavos": Decimal128("10.5"),
                },
                {
                    "status": "pending",
                    "due_date": "2026-02-01",
                    "total_amount_centavos": -10,
                },
            ],
        }
    )

    result = execute_officer_tool_result(
        "get_repayment_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["schedule_status"] == "unknown"
    assert summary["term_months"] == 0
    assert summary["monthly_amount"] == 0
    assert summary["total_amount"] == 0
    assert summary["next_due_date"] == "2026-02-01T00:00:00"
    assert summary["schedule_progress"]["paid_count"] == 1


def test_repayment_aggregate_rounds_one_point_zero_zero_five_to_101_centavos(
    officer_scope,
    mongomock_decimal128_aggregation,
):
    settings.MONGODB[LoanPayment.collection_name].insert_one(
        {
            "loan_id": officer_scope.application_id,
            "customer_id": officer_scope.customer_id,
            "amount": 1.005,
        }
    )

    summary = officer_tools._summarize_posted_payments(
        officer_scope.application_id,
        officer_scope.customer_id,
    )

    assert summary == {"count": 1, "total_centavos": 101}


def test_repayment_summary_uses_centavos_for_exact_remaining_balance(officer_scope):
    settings.MONGODB["repayment_schedules"].delete_many(
        {"loan_id": officer_scope.application_id}
    )
    settings.MONGODB["repayment_schedules"].insert_one(
        {
            "loan_id": officer_scope.application_id,
            "customer_id": officer_scope.customer_id,
            "status": "active",
            "term_months": 1,
            "monthly_payment": 30000.30,
            "monthly_payment_centavos": 3000030,
            "total_amount": 30000.30,
            "total_amount_centavos": 3000030,
        }
    )
    settings.MONGODB[LoanPayment.collection_name].insert_one(
        {
            "loan_id": officer_scope.application_id,
            "customer_id": officer_scope.customer_id,
            "amount_centavos": 3000020,
            "payment_status": "posted",
        }
    )

    result = execute_officer_tool_result(
        "get_repayment_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["total_amount"] == 30000.3
    assert summary["total_paid"] == 30000.2
    assert summary["remaining_balance"] == 0.1


def test_repayment_summary_excludes_non_posted_payment_statuses(officer_scope):
    settings.MONGODB[LoanPayment.collection_name].insert_many(
        [
            {
                "loan_id": officer_scope.application_id,
                "customer_id": officer_scope.customer_id,
                "amount_centavos": 10000,
                "payment_status": status,
            }
            for status in ("failed", "reversed", "pending_verification")
        ]
    )

    result = execute_officer_tool_result(
        "get_repayment_summary", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    summary = json.loads(result["result"])
    assert summary["posted_payment_count"] == 0
    assert summary["total_paid"] == 0


def test_repayment_payment_aggregate_is_grouped_and_never_falls_back_to_find(
    monkeypatch,
):
    class AggregateOnlyPayments:
        def __init__(self):
            self.pipeline = None
            self.find_called = False

        def aggregate(self, pipeline):
            self.pipeline = pipeline
            return iter(
                [
                    {
                        "count": 2,
                        "total_centavos": 12050,
                    }
                ]
            )

        def find(self, *args, **kwargs):
            self.find_called = True
            raise AssertionError("Officer repayment summary must not use find()")

    collection = AggregateOnlyPayments()
    monkeypatch.setattr(
        officer_tools.settings,
        "MONGODB",
        {LoanPayment.collection_name: collection},
    )

    summary = officer_tools._summarize_posted_payments("loan-1", "customer-1")

    assert summary == {"count": 2, "total_centavos": 12050}
    assert collection.find_called is False
    assert collection.pipeline[0] == {
        "$match": {
            "loan_id": "loan-1",
            "customer_id": "customer-1",
            "$or": [
                {"payment_status": "posted"},
                {"payment_status": {"$exists": False}},
            ],
        }
    }
    assert collection.pipeline[-1] == {"$limit": 1}
    assert any("$group" in stage for stage in collection.pipeline)


@pytest.mark.parametrize("product_id", ["not-an-object-id", str(ObjectId())])
def test_document_review_status_fails_closed_without_a_bound_product(
    officer_scope, monkeypatch, product_id
):
    settings.MONGODB[LoanApplication.collection_name].update_one(
        {"_id": ObjectId(officer_scope.application_id)},
        {"$set": {"product_id": product_id}},
    )

    class TrackingDatabase:
        def __init__(self, database):
            self.database = database
            self.document_collection_accesses = 0

        def __getitem__(self, collection_name):
            if collection_name == "documents":
                self.document_collection_accesses += 1
            return self.database[collection_name]

    database = TrackingDatabase(settings.MONGODB)
    monkeypatch.setattr(officer_tools.settings, "MONGODB", database)

    result = execute_officer_tool_result(
        "get_document_review_status", {}, officer_scope, request_id="request-1"
    )

    assert result["code"] == "AI_OFFICER_TOOL_READ_FAILED"
    assert "result" not in result
    assert database.document_collection_accesses == 0


def test_document_review_status_excludes_unrequired_customer_documents(officer_scope):
    settings.MONGODB["documents"].insert_many(
        [
            {
                "customer_id": officer_scope.customer_id,
                "document_type": "valid_id",
                "status": "approved",
                "verified": True,
            },
            {
                "customer_id": officer_scope.customer_id,
                "document_type": "business_photo",
                "status": "rejected",
                "verified": False,
            },
        ]
    )

    result = execute_officer_tool_result(
        "get_document_review_status", {}, officer_scope, request_id="request-1"
    )

    assert result["success"] is True
    document_types = {
        document["type"] for document in json.loads(result["result"])["documents"]
    }
    assert document_types == {"Valid Government ID"}
