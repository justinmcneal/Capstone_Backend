import json
import re

import pytest

from ai_assistant.services.officer_review_brief import (
    InvalidReviewBrief,
    build_review_brief,
    validate_review_brief,
)


def evidence(tool_name, result):
    return {"tool_name": tool_name, "success": True, "result": json.dumps(result)}


def test_brief_has_opaque_revision_and_snapshot_time():
    brief = build_review_brief(
        [
            evidence(
                "get_repayment_summary",
                {
                    "schedule_available": False,
                },
            )
        ],
        language="en",
        as_of="2026-09-01T00:00:00Z",
    )
    assert brief["as_of"] == "2026-09-01T00:00:00Z"
    assert re.fullmatch(r"[a-f0-9]{64}", brief["evidence_revision"])
    assert brief["freshness"]["state"] == "current"


def test_profile_revision_mismatch_warns_without_inventing_reason():
    brief = build_review_brief(
        [
            evidence(
                "get_profile_readiness",
                {
                    "personal": {"available": True, "complete": True, "completion_percentage": 100, "missing_fields": []},
                    "business": {"available": True, "complete": True, "completion_percentage": 100, "missing_fields": []},
                    "alternative": {
                        "available": True,
                        "complete": True,
                        "completion_percentage": 100,
                        "missing_fields": [],
                        "risk_status": "complete",
                        "risk_score_status": "complete",
                        "risk_category": "low",
                        "manual_review_required": False,
                        "manual_review_flags": [],
                        "risk_input_revision": 4,
                        "risk_calculated_revision": 3,
                    },
                },
            )
        ],
    )
    assert brief["freshness"]["state"] == "stale"
    assert brief["freshness"]["warnings"]
    assert not any(reason["code"] == "evidence_stale" for reason in brief["reasons"])


def test_navigation_actions_are_allowlisted_links():
    brief = build_review_brief(
        [
            evidence(
                "get_application_summary",
                {"review_readiness": {"status": "ready_for_review", "is_reviewable": True, "manual_review_required": False}},
            )
        ],
        actions=[
            {"id": "open_profile", "label": "Open profile", "href": "/officer/profiles/customer-1"},
        ],
    )
    assert brief["actions"][0]["id"] == "open_profile"
    with pytest.raises(InvalidReviewBrief):
        validate_review_brief({**brief, "actions": [{"id": "open_profile", "label": "Open", "href": "https://evil.test"}]})
