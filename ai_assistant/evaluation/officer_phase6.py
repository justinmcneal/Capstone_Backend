"""Synthetic Phase 6 coverage matrix and release-gate validation."""

import hashlib
import json
from pathlib import Path

from ai_assistant.services.officer_evidence_contract import (
    APPLICATION_STATUSES,
    DOCUMENT_STATUSES,
    INSTALLMENT_STATUSES,
    SCHEDULE_STATUSES,
)

DEFAULT_OFFICER_PHASE6_MATRIX_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "officer_ai_phase6_evaluation_matrix.json"
)
REQUIRED_EVIDENCE_QUALITIES = {"complete", "incomplete", "unavailable", "stale", "contradictory"}
REQUIRED_CATEGORIES = {
    "lifecycle", "evidence_quality", "document_status", "repayment_status",
    "provider_availability", "privacy", "scope", "prompt_injection",
    "decision_safety", "contract", "browser", "usability",
}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_officer_phase6_matrix(path=DEFAULT_OFFICER_PHASE6_MATRIX_PATH):
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_officer_phase6_matrix(payload)
    payload["matrix_sha256"] = _sha256(path)
    return payload


def validate_officer_phase6_matrix(matrix):
    if not isinstance(matrix, dict) or matrix.get("schema_version") != 1:
        raise ValueError("Unsupported officer Phase 6 matrix schema")
    if matrix.get("data_classification") != "synthetic_only":
        raise ValueError("Officer Phase 6 matrix must be synthetic_only")
    if set(matrix.get("languages") or []) != {"en", "fil"}:
        raise ValueError("Officer Phase 6 matrix must cover English and Filipino")
    golden_outputs = matrix.get("golden_outputs")
    if (
        not isinstance(golden_outputs, dict)
        or set(golden_outputs) != {"en", "fil"}
        or any(
            not isinstance(golden_outputs[language], dict)
            or not str(golden_outputs[language].get("headline") or "").strip()
            or not str(golden_outputs[language].get("disclaimer") or "").strip()
            for language in ("en", "fil")
        )
    ):
        raise ValueError("Officer Phase 6 golden outputs are incomplete")
    categories = set(matrix.get("required_categories") or [])
    if categories != REQUIRED_CATEGORIES:
        raise ValueError("Officer Phase 6 matrix categories are incomplete")
    cases = matrix.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Officer Phase 6 matrix must contain cases")
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(cases) or any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Officer Phase 6 case IDs must be present and unique")
    for case in cases:
        if case.get("language") not in {"en", "fil"}:
            raise ValueError(f"Invalid language for case {case['id']}")
        if case.get("category") not in REQUIRED_CATEGORIES:
            raise ValueError(f"Invalid category for case {case['id']}")
        if not str(case.get("value") or "").strip() or not str(case.get("expected") or "").strip():
            raise ValueError(f"Incomplete case {case['id']}")

    values = {
        "lifecycle": {case["value"] for case in cases if case["category"] == "lifecycle"},
        "document_status": {case["value"] for case in cases if case["category"] == "document_status"},
        "repayment_status": {case["value"] for case in cases if case["category"] == "repayment_status"},
        "evidence_quality": {case["value"] for case in cases if case["category"] == "evidence_quality"},
    }
    if values["lifecycle"] != set(APPLICATION_STATUSES):
        raise ValueError("Officer Phase 6 matrix does not cover every application lifecycle state")
    if values["document_status"] != set(DOCUMENT_STATUSES):
        raise ValueError("Officer Phase 6 matrix does not cover every document state")
    if not INSTALLMENT_STATUSES.issubset(values["repayment_status"]):
        raise ValueError("Officer Phase 6 matrix does not cover every installment state")
    if not SCHEDULE_STATUSES.issubset(values["repayment_status"]):
        raise ValueError("Officer Phase 6 matrix does not cover every schedule state")
    if values["evidence_quality"] != REQUIRED_EVIDENCE_QUALITIES:
        raise ValueError("Officer Phase 6 matrix does not cover every evidence quality")
    return True
