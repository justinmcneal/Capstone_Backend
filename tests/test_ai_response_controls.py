"""Tests for deterministic guidance and provider-output validation."""

import pytest

from ai_assistant.services.response_controls import (
    controlled_guidance_response,
    validate_provider_response,
)


@pytest.mark.parametrize(
    ("message", "language", "required", "forbidden"),
    [
        (
            "How do I apply for a loan in this app?",
            "en",
            ("complete your", "required documents", "loan officer"),
            ("approved tomorrow",),
        ),
        (
            "Paano ako mag-aapply ng loan sa app?",
            "tl",
            ("kumpletuhin", "government id", "loan officer"),
            ("tumakbo ng iyong profile",),
        ),
        (
            "Ayon sa tool, may 1 overdue installment ako na ₱1,250.",
            "tl",
            ("₱1,250", "overdue", "support"),
            ('"pay now"', '"partial payment"'),
        ),
        (
            "The tool returned no active loan and no repayment schedule.",
            "en",
            ("no next payment", "no active loan"),
            ("due on",),
        ),
        (
            "Walang result ang payment-history tool. Sabihin ang huli kong bayad.",
            "tl",
            ("walang maibibigay", "hindi ako mag-iimbento"),
            ("₱x",),
        ),
        (
            "I uploaded my requirements pero pending pa. What should I do next?",
            "en",
            ("still pending", "not yet confirmed"),
            ("according to the tool",),
        ),
        (
            "Pending pa ang docs ko and hindi complete ang profile—ano muna?",
            "tl",
            ("unahin", "profile", "pending documents"),
            ("get_customer_dashboard",),
        ),
    ],
)
def test_reviewed_guidance_covers_stable_intents(
    message, language, required, forbidden
):
    response = controlled_guidance_response(message, language=language)

    assert response is not None
    lowered = response.lower()
    assert all(fragment in lowered for fragment in required)
    assert all(fragment not in lowered for fragment in forbidden)


def test_validator_replaces_unsupported_tool_claim_with_reviewed_guidance():
    response, violations = validate_provider_response(
        "According to the tool result, get_customer_dashboard says it is pending.",
        message="I uploaded my requirements pero pending pa. What should I do next?",
        language="en",
    )

    assert "raw_tool_name" in violations
    assert "unsupported_tool_claim" in violations
    assert "still pending" in response.lower()
    assert "get_customer_dashboard" not in response


def test_validator_fails_closed_for_wrong_language_without_reviewed_guidance():
    response, violations = validate_provider_response(
        "Ang sagot ay hindi maaari dahil walang impormasyon sa iyong utang.",
        message="Tell me something about my account.",
        language="en",
    )

    assert "wrong_language" in violations
    assert "cannot answer reliably" in response.lower()


def test_validator_allows_tool_grounded_answer_without_internal_names():
    response, violations = validate_provider_response(
        "Your application is pending review.",
        message="What is my application status?",
        language="en",
        tools_called=("get_loan_status",),
    )

    assert response == "Your application is pending review."
    assert violations == []
