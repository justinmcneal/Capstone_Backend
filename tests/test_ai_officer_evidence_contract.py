from ai_assistant.services.officer_review_brief import build_review_brief
from ai_assistant.services.officer_evidence_contract import (
    normalize_risk_status,
    normalize_status,
)


def test_normalize_risk_status_accepts_canonical_and_legacy_values():
    assert normalize_risk_status("complete") == "complete"
    assert normalize_risk_status("calculated") == "complete"


def test_normalize_status_fails_closed_for_unknown_values():
    assert normalize_status("unexpected", {"pending", "approved"}) == "unknown"
    assert normalize_status(None, {"pending", "approved"}) == "unknown"


def test_brief_failure_reports_only_an_allowlisted_internal_diagnostic():
    diagnostics = []
    brief = build_review_brief(
        [{"tool_name": "get_profile_readiness", "success": False}],
        diagnostics=diagnostics,
    )

    assert brief["review_state"] == "unavailable"
    assert diagnostics == ["tool_read_unavailable"]
