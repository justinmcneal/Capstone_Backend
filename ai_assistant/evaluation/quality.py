"""Versioned, synthetic, human-scored AI quality release gate."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

DEFAULT_DATASET_PATH = Path(__file__).with_name("quality_gate_v1.json")
ALLOWED_LANGUAGES = {"en", "tl"}
ALLOWED_DIMENSIONS = {
    "accuracy",
    "groundedness",
    "language_quality",
    "privacy",
    "safety",
}


def _file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_dataset(path=DEFAULT_DATASET_PATH):
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not payload.get("dataset_version"):
        raise ValueError("Unsupported AI quality dataset schema")
    if payload.get("data_classification") != "synthetic_only":
        raise ValueError("AI quality datasets must be classified synthetic_only")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("AI quality dataset must contain cases")
    identifiers = [case.get("id") for case in cases]
    if any(not value for value in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("AI quality case IDs must be present and unique")
    languages = {case.get("language") for case in cases}
    if languages != ALLOWED_LANGUAGES:
        raise ValueError("AI quality dataset must cover English and Tagalog")
    for case in cases:
        if not str(case.get("prompt") or "").strip():
            raise ValueError(f"AI quality case {case['id']} has no prompt")
        dimensions = set(case.get("dimensions") or [])
        if not dimensions or not dimensions.issubset(ALLOWED_DIMENSIONS):
            raise ValueError(f"AI quality case {case['id']} has invalid dimensions")
        if not str(case.get("expected_behavior") or "").strip():
            raise ValueError(f"AI quality case {case['id']} has no rubric")
    thresholds = payload.get("thresholds") or {}
    required_thresholds = {"overall_pass_rate", "critical_pass_rate"}
    if not required_thresholds.issubset(thresholds):
        raise ValueError("AI quality thresholds are incomplete")
    payload["dataset_sha256"] = _file_sha256(path)
    return payload


def evaluate_assessments(dataset, submission):
    """Evaluate human-reviewed synthetic outputs against approved thresholds."""
    cases = {case["id"]: case for case in dataset["cases"]}
    assessments = submission.get("assessments")
    if not isinstance(assessments, list):
        raise TypeError("assessments must be a list")
    supplied = {item.get("case_id"): item for item in assessments}
    if set(supplied) != set(cases) or len(supplied) != len(assessments):
        raise ValueError("assessments must cover every case exactly once")
    provider = str(submission.get("provider") or "").strip()
    model = str(submission.get("model") or "").strip()
    reviewer = str(submission.get("reviewer") or "").strip()
    if not provider or not model or not reviewer:
        raise ValueError("provider, model, and reviewer are required")

    case_results = []
    dimension_totals = {name: [0, 0] for name in ALLOWED_DIMENSIONS}
    category_totals = {}
    critical_total = 0
    critical_passed = 0
    for case_id, case in cases.items():
        assessment = supplied[case_id]
        response = str(assessment.get("response") or "").strip()
        if not response:
            raise ValueError(f"assessment {case_id} requires a synthetic response")
        scores = assessment.get("scores") or {}
        expected_dimensions = set(case["dimensions"])
        if set(scores) != expected_dimensions:
            raise ValueError(f"assessment {case_id} has incomplete dimension scores")
        normalized_scores = {}
        for dimension, score in scores.items():
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 4:
                raise ValueError(f"assessment {case_id} scores must be integers from 0 to 4")
            normalized_scores[dimension] = score
            dimension_totals[dimension][0] += score
            dimension_totals[dimension][1] += 4
        critical_failure = bool(assessment.get("critical_failure", False))
        passed = not critical_failure and all(
            score >= int(case.get("minimum_dimension_score", 3))
            for score in normalized_scores.values()
        )
        category = case["category"]
        category_totals.setdefault(category, [0, 0])
        category_totals[category][1] += 1
        category_totals[category][0] += int(passed)
        if case.get("critical"):
            critical_total += 1
            critical_passed += int(passed)
        case_results.append({
            "case_id": case_id,
            "language": case["language"],
            "category": category,
            "critical": bool(case.get("critical")),
            "passed": passed,
            "scores": normalized_scores,
            "critical_failure": critical_failure,
        })

    total = len(case_results)
    passed_count = sum(int(item["passed"]) for item in case_results)
    overall_pass_rate = passed_count / total
    critical_pass_rate = critical_passed / critical_total if critical_total else 1.0
    dimension_rates = {
        name: (earned / possible if possible else None)
        for name, (earned, possible) in dimension_totals.items()
    }
    category_pass_rates = {
        name: passed / count for name, (passed, count) in category_totals.items()
    }
    thresholds = dataset["thresholds"]
    checks = {
        "overall_pass_rate": overall_pass_rate >= thresholds["overall_pass_rate"],
        "critical_pass_rate": critical_pass_rate >= thresholds["critical_pass_rate"],
    }
    for dimension, threshold in thresholds.get("dimension_minimums", {}).items():
        rate = dimension_rates.get(dimension)
        checks[f"dimension_{dimension}"] = rate is not None and rate >= threshold
    for category, threshold in thresholds.get("category_pass_rates", {}).items():
        rate = category_pass_rates.get(category)
        checks[f"category_{category}"] = rate is not None and rate >= threshold

    return {
        "report_schema_version": 1,
        "dataset_version": dataset["dataset_version"],
        "dataset_sha256": dataset["dataset_sha256"],
        "provider": provider,
        "model": model,
        "reviewer": reviewer,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": total,
        "passed_count": passed_count,
        "overall_pass_rate": overall_pass_rate,
        "critical_pass_rate": critical_pass_rate,
        "dimension_rates": dimension_rates,
        "category_pass_rates": category_pass_rates,
        "checks": checks,
        "ready": all(checks.values()),
        "case_results": case_results,
    }


def validate_quality_report(report, dataset=None):
    dataset = dataset or load_dataset()
    provider = str(getattr(settings, "LLM_PROVIDER", "") or "").strip()
    model = str(
        getattr(
            settings,
            "GROQ_CHAT_MODEL" if provider == "groq" else "OLLAMA_MODEL",
            "",
        )
        or ""
    ).strip()
    checks = {
        "report_schema": report.get("report_schema_version") == 1,
        "dataset_version": report.get("dataset_version") == dataset["dataset_version"],
        "dataset_hash": report.get("dataset_sha256") == dataset["dataset_sha256"],
        "provider": report.get("provider") == provider,
        "model": report.get("model") == model,
        "all_quality_checks": bool(report.get("ready")) and all(
            (report.get("checks") or {}).values()
        ),
    }
    return {"ready": all(checks.values()), "checks": checks}
