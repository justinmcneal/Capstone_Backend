import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_assistant.services.officer_review_brief import (
    InvalidReviewBrief,
    build_review_brief,
    build_unavailable_review_brief,
    render_review_brief,
    validate_narration,
    validate_review_brief,
)
from ai_assistant.services.officer_audit import record_officer_review_brief


def _evidence(tool_name, result, *, success=True, code=None):
    evidence = {
        "tool_name": tool_name,
        "success": success,
    }
    if success:
        evidence["result"] = json.dumps(result)
    if code:
        evidence["code"] = code
    return evidence


def test_application_brief_localizes_internal_readiness_without_leaking_it():
    brief = build_review_brief(
        [
            _evidence(
                "get_application_summary",
                {
                    "review_readiness": {
                        "status": "not_ready_for_review",
                        "is_reviewable": False,
                        "manual_review_required": False,
                    }
                },
            )
        ],
        language="en",
        message="Summarize this application's review readiness.",
    )

    assert brief == {
        "review_state": "needs_attention",
        "headline": "Not ready for review",
        "reasons": [
            {
                "code": "review_stage_not_ready",
                "label": "The application is not ready for officer review",
                "detail": "The current application record is not in a reviewable workflow stage.",
            }
        ],
        "next_steps": ["Verify the application record before continuing the review workflow."],
        "sources": ["Application summary"],
        "advisory_only": True,
        "disclaimer": "AI assistance is advisory only. Verify details against the application record.",
    }
    serialized = json.dumps(brief)
    for internal in (
        "get_application_summary",
        "not_ready_for_review",
        "is_reviewable",
    ):
        assert internal not in serialized


def test_filipino_brief_uses_backend_localized_templates():
    brief = build_review_brief(
        [
            _evidence(
                "get_application_summary",
                {
                    "review_readiness": {
                        "status": "ready_for_review",
                        "is_reviewable": True,
                        "manual_review_required": True,
                    }
                },
            )
        ],
        language="tl",
        message="Ibuod ang kahandaan ng aplikasyon para sa pagsusuri.",
    )

    assert brief["review_state"] == "ready"
    assert brief["headline"] == "Handa para sa pagsusuri"
    assert brief["reasons"] == [
        {
            "code": "review_stage_ready",
            "label": "Handa ang aplikasyon para sa pagsusuri ng loan officer",
            "detail": "Ang kasalukuyang talaan ng aplikasyon ay nasa yugto na maaari nang suriin.",
        },
        {
            "code": "manual_check_needed",
            "label": "Kailangan ang manu-manong pagsusuri",
            "detail": "Gamitin ang itinakdang workflow ng portal para sa manu-manong pagsusuri.",
        },
    ]
    assert brief["sources"] == ["Buod ng aplikasyon"]
    assert brief["disclaimer"] == (
        "Ang tulong ng AI ay para lamang sa gabay. Beripikahin ang mga detalye sa talaan ng aplikasyon."
    )


def test_failed_subsystem_returns_unavailable_brief_without_partial_content():
    brief = build_review_brief(
        [
            _evidence(
                "get_repayment_summary",
                {},
                success=False,
                code="AI_OFFICER_TOOL_READ_FAILED",
            )
        ],
        language="en",
        message="Explain the current repayment summary.",
    )

    assert brief == build_unavailable_review_brief("en", topic="repayment")
    assert brief["review_state"] == "unavailable"
    assert brief["reasons"] == []
    assert brief["sources"] == []


@pytest.mark.parametrize(
    "evidence",
    [
        [{"tool_name": "unknown_tool", "success": True, "result": "{}"}],
        [{"tool_name": "get_application_summary", "success": True, "result": "{"}],
        [
            {
                "tool_name": "get_application_summary",
                "success": True,
                "result": json.dumps(
                    {"review_readiness": {"status": "unexpected_state"}}
                ),
            }
        ],
    ],
)
def test_malformed_or_unknown_evidence_fails_closed(evidence):
    brief = build_review_brief(
        evidence,
        language="en",
        message="Summarize review readiness.",
    )

    assert brief["review_state"] == "unavailable"
    assert brief["headline"] == "Application summary unavailable"
    assert brief["reasons"] == []
    assert brief["sources"] == []


@pytest.mark.parametrize(
    "message",
    [
        "What are the approval odds?",
        "What is the probability this gets approved?",
        "Will this application be approved?",
        "Compare this application to the last applicant.",
        "How does this differ from other applications?",
        "Compare this application against another borrower.",
        "Ano ang tsansang maaprubahan ito?",
        "Ikumpara ito sa ibang aplikante.",
        "Paano ito naiiba sa huling aplikasyon?",
    ],
)
def test_out_of_scope_question_returns_scope_limit_brief(message):
    brief = build_review_brief([], language="en", message=message)

    assert brief == {
        "review_state": "scope_limited",
        "headline": "Request outside this review brief",
        "reasons": [],
        "next_steps": [
            "Ask about this application's review readiness, profile, documents, or repayment summary."
        ],
        "sources": [],
        "advisory_only": True,
        "disclaimer": "AI assistance is advisory only. Verify details against the application record.",
    }


@pytest.mark.parametrize(
    "message",
    [
        "What different documents does this application need?",
        "What other documents still need review for this application?",
        "Compare the profile and document readiness for this application.",
        "Ikumpara ang profile at mga dokumento ng aplikasyong ito.",
        "Ikumpara ang profile at mga dokumento ng aplikasyon na ito.",
    ],
)
def test_same_application_comparison_questions_remain_in_scope(message):
    brief = build_review_brief([], language="en", message=message)

    assert brief["review_state"] == "unavailable"
    assert brief["review_state"] != "scope_limited"


def test_profile_evidence_cannot_report_ready_when_incomplete_fields_are_unknown():
    brief = build_review_brief(
        [
            _evidence(
                "get_profile_readiness",
                {
                    "personal": {
                        "available": True,
                        "completion_percentage": 70,
                        "complete": False,
                        "missing_fields": [],
                    },
                    "business": {"available": False},
                    "alternative": {"available": False},
                },
            )
        ],
        language="en",
        message="What profile information is still incomplete?",
    )

    assert brief == build_unavailable_review_brief("en", topic="profile")


def test_profile_manual_check_uses_a_public_semantic_code():
    brief = build_review_brief(
        [
            _evidence(
                "get_profile_readiness",
                {
                    "personal": {
                        "available": True,
                        "completion_percentage": 100,
                        "complete": True,
                        "missing_fields": [],
                    },
                    "business": {
                        "available": True,
                        "completion_percentage": 100,
                        "complete": True,
                        "missing_fields": [],
                    },
                    "alternative": {
                        "available": True,
                        "completion_percentage": 100,
                        "complete": True,
                        "missing_fields": [],
                        "risk_status": "calculated",
                        "risk_score_status": "calculated",
                        "risk_category": "medium",
                        "manual_review_required": True,
                        "manual_review_flags": ["risk_score"],
                    },
                },
            )
        ],
        language="en",
        message="What profile information is still incomplete?",
    )

    assert brief["review_state"] == "needs_attention"
    assert [reason["code"] for reason in brief["reasons"]] == [
        "manual_check_needed"
    ]
    assert "manual_review_required" not in json.dumps(brief)


@pytest.mark.parametrize(
    "result",
    [
        {
            "required_document_types": [
                {"code": "valid_id", "label": "Valid Government ID"}
            ],
            "documents": [
                {
                    "type_code": "valid_id",
                    "status": "unknown",
                    "verified": False,
                }
            ],
            "truncated": False,
        },
        {
            "required_document_types": [
                {"code": "valid_id", "label": "Valid Government ID"}
            ],
            "documents": [
                {
                    "type_code": "valid_id",
                    "status": "approved",
                    "verified": False,
                }
            ],
            "truncated": False,
        },
        {
            "required_document_types": [
                {"code": "valid_id", "label": "Valid Government ID"}
            ],
            "documents": [],
            "truncated": True,
        },
    ],
)
def test_unknown_contradictory_or_truncated_document_evidence_fails_closed(result):
    brief = build_review_brief(
        [_evidence("get_document_review_status", result)],
        language="en",
        message="Summarize required documents.",
    )

    assert brief == build_unavailable_review_brief("en", topic="document")


def test_unknown_repayment_status_fails_closed():
    brief = build_review_brief(
        [
            _evidence(
                "get_repayment_summary",
                {
                    "schedule_available": True,
                    "schedule_status": "unknown",
                    "payments_truncated": False,
                    "remaining_balance": 1000,
                    "schedule_progress": {
                        "paid_count": 0,
                        "installment_count": 1,
                        "completed_percentage": 0,
                    },
                    "payment_status_summaries": [
                        {"status": "unknown", "count": 1}
                    ],
                },
            )
        ],
        language="en",
        message="Explain the current repayment summary.",
    )

    assert brief == build_unavailable_review_brief("en", topic="repayment")


def test_no_schedule_evidence_rejects_contradictory_schedule_content():
    brief = build_review_brief(
        [
            _evidence(
                "get_repayment_summary",
                {
                    "schedule_available": False,
                    "schedule_status": "active",
                    "schedule_progress": {
                        "paid_count": 0,
                        "installment_count": 1,
                        "completed_percentage": 0,
                    },
                    "payment_status_summaries": [
                        {"status": "pending", "count": 1}
                    ],
                },
            )
        ],
        language="en",
        message="Explain the current repayment summary.",
    )

    assert brief == build_unavailable_review_brief("en", topic="repayment")


def test_minimal_no_schedule_evidence_stays_informational():
    brief = build_review_brief(
        [_evidence("get_repayment_summary", {"schedule_available": False})],
        language="en",
        message="Explain the current repayment summary.",
    )

    assert brief["review_state"] == "informational"
    assert [reason["code"] for reason in brief["reasons"]] == [
        "repayment_schedule_missing"
    ]


def test_review_brief_validation_rejects_missing_fields_and_unknown_reason_codes():
    with pytest.raises(InvalidReviewBrief):
        validate_review_brief({"review_state": "ready"})

    with pytest.raises(InvalidReviewBrief):
        validate_review_brief(
            {
                "review_state": "ready",
                "headline": "Ready for review",
                "reasons": [
                    {
                        "code": "provider_invented_code",
                        "label": "Invented",
                        "detail": "Invented detail.",
                    }
                ],
                "next_steps": [],
                "sources": [],
                "advisory_only": True,
                "disclaimer": "AI assistance is advisory only. Verify details against the application record.",
            }
        )


def test_narration_must_match_the_localized_brief_exactly():
    brief = build_review_brief(
        [
            _evidence(
                "get_application_summary",
                {
                    "review_readiness": {
                        "status": "ready_for_review",
                        "is_reviewable": True,
                        "manual_review_required": False,
                    }
                },
            )
        ],
        language="en",
        message="Summarize review readiness.",
    )
    expected = render_review_brief(brief)

    assert validate_narration(expected, brief) == expected
    assert validate_narration(
        expected.replace(
            "The current application record is in a reviewable workflow stage.",
            "Approval is likely.",
        ),
        brief,
    ) is None
    assert validate_narration(expected.rsplit("\n", 1)[0], brief) is None


def test_viewed_review_brief_audit_persists_reconstructable_public_metadata(
    monkeypatch,
):
    writer = Mock(return_value=SimpleNamespace(id="audit-1"))
    monkeypatch.setattr(
        "ai_assistant.services.officer_audit.AuditLog.log_action", writer
    )
    scope = SimpleNamespace(
        officer_id="officer-1",
        application_id="application-1",
    )
    brief = build_review_brief(
        [
            _evidence(
                "get_application_summary",
                {
                    "review_readiness": {
                        "status": "ready_for_review",
                        "is_reviewable": True,
                        "manual_review_required": False,
                    }
                },
            )
        ],
        language="en",
        message="Summarize review readiness.",
    )

    record_officer_review_brief(
        scope,
        "request-1",
        "en",
        brief=brief,
    )

    payload = writer.call_args.kwargs
    assert payload["action"] == "ai_officer_review_brief_viewed"
    assert payload["resource_id"] == "application-1"
    assert payload["user_id"] != "officer-1"
    assert payload["details"] == {
        "application_id": "application-1",
        "request_id": "request-1",
        "language": "en",
        "review_state": "ready",
        "reasons": brief["reasons"],
        "sources": ["Application summary"],
        "narration_version": "review-brief-v1",
    }
