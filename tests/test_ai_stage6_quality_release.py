"""Offline Stage 6 quality-gate and release-check coverage."""

import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from ai_assistant.evaluation import (
    evaluate_assessments,
    load_dataset,
    validate_quality_report,
)
from ai_assistant.services.operations import EXPECTED_INDEXES, ai_release_readiness


def _perfect_submission(dataset):
    return {
        "provider": "groq",
        "model": "release-model",
        "reviewer": "approved-reviewer",
        "assessments": [
            {
                "case_id": case["id"],
                "response": "Synthetic reviewed response",
                "scores": {dimension: 4 for dimension in case["dimensions"]},
                "critical_failure": False,
            }
            for case in dataset["cases"]
        ],
    }


def test_versioned_dataset_is_balanced_synthetic_and_complete():
    dataset = load_dataset()
    cases = dataset["cases"]

    assert dataset["dataset_sha256"]
    assert len(cases) == 18
    assert sum(case["language"] == "en" for case in cases) == 9
    assert sum(case["language"] == "tl" for case in cases) == 9
    assert {case["category"] for case in cases} == set(
        dataset["thresholds"]["category_pass_rates"]
    )
    assert dataset["data_classification"] == "synthetic_only"


def test_perfect_review_produces_bound_versioned_report(settings):
    dataset = load_dataset()
    report = evaluate_assessments(dataset, _perfect_submission(dataset))
    settings.LLM_PROVIDER = "groq"
    settings.GROQ_CHAT_MODEL = "release-model"

    assert report["ready"] is True
    assert report["dataset_sha256"] == dataset["dataset_sha256"]
    assert validate_quality_report(report, dataset)["ready"] is True


def test_critical_failure_fails_release_even_with_high_scores():
    dataset = load_dataset()
    submission = _perfect_submission(dataset)
    critical_id = next(case["id"] for case in dataset["cases"] if case["critical"])
    target = next(
        item for item in submission["assessments"] if item["case_id"] == critical_id
    )
    target["critical_failure"] = True

    report = evaluate_assessments(dataset, submission)

    assert report["ready"] is False
    assert report["checks"]["critical_pass_rate"] is False


def test_evaluation_rejects_missing_case_and_incomplete_scores():
    dataset = load_dataset()
    submission = _perfect_submission(dataset)
    submission["assessments"].pop()
    with pytest.raises(ValueError, match="every case exactly once"):
        evaluate_assessments(dataset, submission)

    submission = _perfect_submission(dataset)
    submission["assessments"][0]["scores"] = {}
    with pytest.raises(ValueError, match="incomplete dimension scores"):
        evaluate_assessments(dataset, submission)


def test_evaluate_command_uses_default_dataset(tmp_path):
    dataset = load_dataset()
    assessment_path = tmp_path / "assessments.json"
    report_path = tmp_path / "report.json"
    assessment_path.write_text(
        json.dumps(_perfect_submission(dataset)), encoding="utf-8"
    )

    call_command(
        "evaluate_ai_quality",
        assessment_path,
        output=report_path,
        stdout=StringIO(),
    )

    assert json.loads(report_path.read_text(encoding="utf-8"))["ready"] is True


def test_live_collection_requires_explicit_cost_acknowledgement(tmp_path):
    with pytest.raises(CommandError, match="provider-costs"):
        call_command(
            "collect_ai_quality_responses",
            output=tmp_path / "responses.json",
            stdout=StringIO(),
        )


def test_release_command_is_read_only_and_fails_closed(settings):
    report = {"ready": False, "checks": {"quality_report_approved": False}}
    with (
        patch(
            "ai_assistant.management.commands.ai_release_check.ai_release_readiness",
            return_value=report,
        ) as readiness,
        pytest.raises(CommandError, match="readiness checks failed"),
    ):
        call_command("ai_release_check", stdout=StringIO())
    readiness.assert_called_once_with(settings.MONGODB)


def test_release_readiness_passes_only_with_all_bound_evidence(settings, tmp_path):
    dataset = load_dataset()
    quality_report = evaluate_assessments(dataset, _perfect_submission(dataset))
    report_path = tmp_path / "quality-report.json"
    report_path.write_text(json.dumps(quality_report), encoding="utf-8")
    settings.DEBUG = False
    settings.FIELD_ENCRYPTION_KEY = "configured"
    settings.FIELD_ENCRYPTION_STRICT_DECRYPTION = True
    settings.USE_REDIS_CACHE = True
    settings.PROMETHEUS_METRICS_ENABLED = True
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.LLM_PROVIDER = "groq"
    settings.GROQ_API_KEY = "configured"
    settings.GROQ_CHAT_MODEL = "release-model"
    settings.AI_ASSISTANT_QUALITY_REPORT_PATH = str(report_path)
    settings.AI_ASSISTANT_PROVIDER_PRIVACY_APPROVED = True
    settings.AI_ASSISTANT_PROVIDER_CONTRACT_VERIFIED = True
    settings.AI_ASSISTANT_REDIS_VERIFIED = True
    settings.AI_ASSISTANT_PROXY_STREAMING_VERIFIED = True
    settings.AI_ASSISTANT_LOAD_TEST_VERIFIED = True
    settings.AI_ASSISTANT_BACKUP_RESTORE_VERIFIED = True
    settings.AI_ASSISTANT_SECRET_ROTATION_VERIFIED = True
    settings.AI_ASSISTANT_INCIDENT_ROLLBACK_APPROVED = True
    db = MagicMock()
    validator_result = {
        "cursor": {"firstBatch": [{"options": {"validator": {"$jsonSchema": {}}}}]}
    }
    db.command.side_effect = [{"ok": 1}, validator_result, validator_result, validator_result]
    collections = {}
    for collection, names in EXPECTED_INDEXES.items():
        collections[collection] = MagicMock()
        collections[collection].index_information.return_value = {
            name: {} for name in names
        }
    db.__getitem__.side_effect = collections.__getitem__

    report = ai_release_readiness(db)

    assert report["ready"] is True
    assert all(report["checks"].values())
