"""Static, identifier-free guidance for the loan-officer AI assistant."""

import re
import unicodedata


def build_officer_system_prompt():
    return """You are an advisory, read-only loan-officer assistant bound to one application.
You may use only these four capabilities:
- get_application_summary
- get_profile_readiness
- get_document_review_status
- get_repayment_summary
Clearly distinguish retrieved source data from explanation and state uncertainty.
You must not make approval or rejection decisions.
You must not mutate loan, profile, document, repayment, or account state.
Direct the loan officer to established workflow controls for any action.
"""


OFFICER_SYSTEM_PROMPT = build_officer_system_prompt()


OFFICER_SUGGESTION_INTENTS = {
    "application_readiness": (
        "get_application_summary",
        "get_profile_readiness",
        "get_document_review_status",
    ),
    "profile_readiness": ("get_profile_readiness",),
    "document_status": ("get_document_review_status",),
    "repayment_summary": ("get_repayment_summary",),
}


def _normalize_intent_message(message):
    normalized = unicodedata.normalize("NFKC", str(message or "")).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


_DETERMINISTIC_INTENT_ALIASES = {
    "application_readiness": frozenset(
        {
            "summarize this application s review readiness",
            "review this application",
            "what is the current application status",
            "current application status",
            "ibuod ang kahandaan ng aplikasyon para sa pagsusuri",
        }
    ),
    "profile_readiness": frozenset(
        {
            "what profile information is still incomplete",
            "what is missing from the profile",
            "what is incomplete in the profile",
            "ano pa ang kulang sa profile bago ang pagsusuri",
        }
    ),
    "document_status": frozenset(
        {
            "summarize the required document review statuses",
            "summarize the required document review status",
            "what documents are present",
            "what documents still need review",
            "ibuod ang katayuan ng mga kinakailangang dokumento",
            "ibuod ang mga katayuan ng pagsusuri ng kinakailangang dokumento",
        }
    ),
    "repayment_summary": frozenset(
        {
            "explain the current repayment summary",
            "what is the current repayment status",
            "show the repayment summary",
            "ipaliwanag ang kasalukuyang buod ng pagbabayad",
        }
    ),
}


def route_officer_intent(message):
    """Return a server-owned intent for a known safe question variant."""
    normalized = _normalize_intent_message(message)
    for intent, aliases in _DETERMINISTIC_INTENT_ALIASES.items():
        if normalized in aliases:
            return intent
    return None


def officer_suggestions(language, status=None):
    labels = (
        [
            "Ibuod ang kahandaan ng aplikasyon para sa pagsusuri.",
            "Ano pa ang kulang sa profile bago ang pagsusuri?",
            "Ibuod ang katayuan ng mga kinakailangang dokumento.",
            "Ipaliwanag ang kasalukuyang buod ng pagbabayad.",
        ]
        if str(language or "en").lower() == "tl"
        else [
            "Summarize this application's review readiness.",
            "What profile information is still incomplete?",
            "Summarize the required document review statuses.",
            "Explain the current repayment summary.",
        ]
    )
    suggestions = [
        {"id": intent, "label": label}
        for intent, label in zip(OFFICER_SUGGESTION_INTENTS, labels)
    ]
    if status is None:
        return suggestions

    normalized_status = str(status or "").strip().lower()
    if normalized_status in {"draft", "submitted", "under_review"}:
        return suggestions[:3]

    lifecycle_labels = {
        "en": {
            "approved": (
                "application_readiness",
                "Review approval conditions and disbursement readiness.",
            ),
            "disbursed": (
                "repayment_summary",
                "Review repayment health, next installment, and overdue status.",
            ),
            "active": (
                "repayment_summary",
                "Review repayment health, next installment, and overdue status.",
            ),
            "completed": ("repayment_summary", "Summarize repayment completion."),
            "rejected": (
                "application_readiness",
                "Review recorded reasons and permitted follow-up.",
            ),
            "cancelled": (
                "application_readiness",
                "Review cancellation state and administrative follow-up.",
            ),
        },
        "tl": {
            "approved": (
                "application_readiness",
                "Suriin ang mga kondisyon ng pag-apruba at kahandaan sa pag-release.",
            ),
            "disbursed": (
                "repayment_summary",
                "Suriin ang kalagayan ng bayaran, susunod na hulog, at overdue.",
            ),
            "active": (
                "repayment_summary",
                "Suriin ang kalagayan ng bayaran, susunod na hulog, at overdue.",
            ),
            "completed": ("repayment_summary", "Ibuod ang pagkumpleto ng bayaran."),
            "rejected": (
                "application_readiness",
                "Suriin ang naitalang dahilan at pinapahintulutang follow-up.",
            ),
            "cancelled": (
                "application_readiness",
                "Suriin ang pagkansela at administratibong follow-up.",
            ),
        },
    }
    lifecycle_suggestion = lifecycle_labels[
        "tl" if str(language or "en").lower() == "tl" else "en"
    ].get(normalized_status)
    if lifecycle_suggestion is None:
        return suggestions[:3]
    intent, label = lifecycle_suggestion
    return [{"id": intent, "label": label}]
