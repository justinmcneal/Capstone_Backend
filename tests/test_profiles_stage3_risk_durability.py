"""Stage 3 risk contract, explainability, revision, and durability tests."""

from datetime import datetime, timedelta, timezone
from io import StringIO
from types import SimpleNamespace

import pytest
from bson import ObjectId
from django.conf import settings
from django.core.management import call_command

from analytics.models import AuditLog
from profiles.models import AlternativeData
from profiles.serializers import AlternativeDataSerializer
from profiles.services.risk_scoring import (
    RISK_SCORING_POLICY_VERSION,
    _digital_score,
    _housing_score,
    _income_score,
    _loan_history_score,
    _payment_behavior_score,
    calculate_risk_score,
)
from profiles.tasks import (
    calculate_risk_score_task,
    enqueue_risk_score_calculation,
    reconcile_risk_scores_task,
)


def _alternative(customer_id=None, **kwargs):
    defaults = {
        "customer_id": customer_id or str(ObjectId()),
        "education_level": "college_graduate",
        "employment_status": "self_employed",
        "housing_status": "rented",
        "years_at_current_address": 2,
        "monthly_rent": 10_000,
        "household_income": 40_000,
        "has_existing_loans": True,
        "existing_loan_amount": 5_000,
        "existing_loan_source": "cooperative",
        "loan_payment_history": "sometimes_late",
        "has_bank_account": True,
        "bank_account_duration": 2,
        "has_ewallet": True,
        "ewallet_usage": "weekly",
        "pays_utilities": True,
        "utility_payment_history": "on_time",
        "is_coop_member": True,
        "community_involvement": ["cooperative"],
    }
    defaults.update(kwargs)
    return AlternativeData(**defaults).save()


def test_every_canonical_scoring_value_has_an_explicit_rule():
    assert _income_score(SimpleNamespace(household_income=50_000)) == 80.0
    assert _loan_history_score(
        SimpleNamespace(
            has_existing_loans=True,
            loan_payment_history="sometimes_late",
        )
    ) == 60.0
    assert _loan_history_score(
        SimpleNamespace(has_existing_loans=True, loan_payment_history="often_late")
    ) == 30.0
    assert _payment_behavior_score(
        SimpleNamespace(
            loan_payment_history="sometimes_late",
            utility_payment_history="often_late",
        )
    ) == 45.0
    assert _housing_score(
        SimpleNamespace(
            housing_status="company_provided",
            years_at_current_address=3,
            monthly_rent=None,
            household_income=30_000,
        )
    ) == pytest.approx(63.33, abs=0.01)
    assert _digital_score(
        SimpleNamespace(
            has_bank_account=False,
            bank_account_duration=None,
            has_ewallet=True,
            ewallet_usage="never",
        )
    ) == pytest.approx(17.5, abs=0.01)


def test_serializer_valid_payload_flows_through_versioned_scoring():
    customer_id = str(ObjectId())
    serializer = AlternativeDataSerializer(
        data={
            "housing_status": "company_provided",
            "household_income": 50_000,
            "has_existing_loans": True,
            "loan_payment_history": "often_late",
            "pays_utilities": True,
            "utility_payment_history": "sometimes_late",
            "has_ewallet": True,
            "ewallet_usage": "never",
        }
    )
    assert serializer.is_valid(), serializer.errors

    alternative = AlternativeData(customer_id=customer_id).save()
    updated = alternative.update_inputs(serializer.validated_data)
    result = calculate_risk_score_task(customer_id, updated.risk_input_revision)
    stored = AlternativeData.find_by_customer(customer_id)

    assert result["scored"] is True
    assert stored.risk_score_status == "complete"
    assert stored.risk_score_policy_version == RISK_SCORING_POLICY_VERSION
    assert stored.risk_calculated_revision == stored.risk_input_revision == 1


def test_score_explanation_is_versioned_and_contains_no_raw_financial_values():
    alternative = _alternative(household_income=43_210, existing_loan_amount=9_876)
    result = calculate_risk_score(alternative)

    assert result["policy_version"] == RISK_SCORING_POLICY_VERSION
    assert result["reason_codes"]
    assert all(
        dimension["reason_codes"] for dimension in result["dimensions"].values()
    )
    serialized = str(result)
    assert "43210" not in serialized
    assert "9876" not in serialized
    assert "Informational profile score only" in result["notes"][0]


def test_out_of_order_task_cannot_publish_for_a_newer_revision():
    alternative = _alternative()
    revision_one = alternative.update_inputs({"household_income": 30_000})
    revision_two = revision_one.update_inputs({"housing_status": "owned"})

    stale = calculate_risk_score_task(
        alternative.customer_id,
        revision_one.risk_input_revision,
    )
    current = calculate_risk_score_task(
        alternative.customer_id,
        revision_two.risk_input_revision,
    )
    stored = AlternativeData.find_by_customer(alternative.customer_id)

    assert stale["stale"] is True
    assert current["scored"] is True
    assert stored.housing_status == "owned"
    assert stored.risk_input_revision == 2
    assert stored.risk_calculated_revision == 2
    assert stored.risk_score_last_stale_revision == 1


def test_duplicate_task_is_idempotent():
    alternative = _alternative()
    pending = alternative.update_inputs({"household_income": 55_000})

    first = calculate_risk_score_task(
        alternative.customer_id, pending.risk_input_revision
    )
    first_timestamp = AlternativeData.find_by_customer(
        alternative.customer_id
    ).score_calculated_at
    second = calculate_risk_score_task(
        alternative.customer_id, pending.risk_input_revision
    )
    second_timestamp = AlternativeData.find_by_customer(
        alternative.customer_id
    ).score_calculated_at

    assert first["scored"] is True
    assert second["idempotent"] is True
    assert second_timestamp == first_timestamp


def test_enqueue_failure_is_persisted_without_losing_profile_update(monkeypatch):
    alternative = _alternative()
    pending = alternative.update_inputs({"household_income": 60_000})

    def broker_down(*args, **kwargs):
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(calculate_risk_score_task, "delay", broker_down)
    assert (
        enqueue_risk_score_calculation(
            alternative.customer_id, pending.risk_input_revision
        )
        is False
    )

    stored = AlternativeData.find_by_customer(alternative.customer_id)
    assert stored.household_income == 60_000
    assert stored.risk_score_status == "failed"
    assert stored.risk_score_error_code == "enqueue_ConnectionError"


def test_scoring_failure_records_retryable_state_and_audit(monkeypatch):
    alternative = _alternative()
    pending = alternative.update_inputs({"household_income": 60_000})

    def scoring_failure(_alternative):
        raise RuntimeError("temporary scoring failure")

    monkeypatch.setattr("profiles.tasks.calculate_risk_score", scoring_failure)
    with pytest.raises(RuntimeError, match="temporary scoring failure"):
        calculate_risk_score_task.run(
            alternative.customer_id,
            pending.risk_input_revision,
        )

    stored = AlternativeData.find_by_customer(alternative.customer_id)
    assert stored.risk_score_status == "failed"
    assert stored.risk_score_error_code == "RuntimeError"
    assert stored.risk_score_failed_at is not None
    audit = AuditLog.find_by_action("risk_score_failed", limit=1)[0]
    assert audit.details["error_code"] == "RuntimeError"
    assert "temporary scoring failure" not in str(audit.details)


def test_reconciler_requeues_failed_and_abandoned_revisions(monkeypatch):
    failed = _alternative()
    failed = failed.update_inputs({"household_income": 60_000})
    abandoned = _alternative()
    abandoned = abandoned.update_inputs({"household_income": 20_000})
    collection = settings.MONGODB[AlternativeData.collection_name]
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    collection.update_one(
        {"_id": failed._id}, {"$set": {"risk_score_status": "failed"}}
    )
    collection.update_one(
        {"_id": abandoned._id},
        {"$set": {"risk_score_status": "pending", "risk_score_requested_at": old}},
    )
    calls = []

    def fake_enqueue(customer_id, revision):
        calls.append((str(customer_id), revision))
        return True

    monkeypatch.setattr("profiles.tasks.enqueue_risk_score_calculation", fake_enqueue)

    assert reconcile_risk_scores_task() == 2
    assert set(calls) == {
        (failed.customer_id, failed.risk_input_revision),
        (abandoned.customer_id, abandoned.risk_input_revision),
    }


def test_successful_score_persists_explanation_and_audit():
    alternative = _alternative()
    pending = alternative.update_inputs({"household_income": 70_000})

    calculate_risk_score_task(alternative.customer_id, pending.risk_input_revision)
    stored = AlternativeData.find_by_customer(alternative.customer_id)

    assert stored.risk_score_breakdown["financial_stability"]["score"] >= 0
    assert stored.risk_score_reason_codes
    audit = AuditLog.find_by_action("risk_score_calculated", limit=1)[0]
    assert audit.details["revision"] == pending.risk_input_revision
    assert audit.details["policy_version"] == RISK_SCORING_POLICY_VERSION
    assert "household_income" not in str(audit.details)


def test_recalculation_command_is_dry_run_by_default(monkeypatch):
    alternative = _alternative()
    dry_output = StringIO()

    call_command("recalculate_profile_risk_scores", stdout=dry_output)

    assert "Dry run: 1 alternative-data record(s)" in dry_output.getvalue()
    assert AlternativeData.find_by_customer(
        alternative.customer_id
    ).risk_score_status == "not_calculated"

    queued = []

    def fake_enqueue(customer_id, revision):
        queued.append((str(customer_id), revision))
        return True

    monkeypatch.setattr(
        "profiles.management.commands.recalculate_profile_risk_scores.enqueue_risk_score_calculation",
        fake_enqueue,
    )
    apply_output = StringIO()
    call_command("recalculate_profile_risk_scores", apply=True, stdout=apply_output)

    assert "Queued 1 of 1" in apply_output.getvalue()
    assert queued == [(alternative.customer_id, 0)]
    stored = AlternativeData.find_by_customer(alternative.customer_id)
    assert stored.risk_score_status == "pending"
    assert stored.risk_score_requested_at is not None
