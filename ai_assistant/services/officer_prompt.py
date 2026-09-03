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

OFFICER_CANONICAL_QUESTIONS = {
    "en": {
        "application_readiness": "Summarize this application's review readiness.",
        "profile_readiness": "What profile information is still incomplete?",
        "document_status": "Summarize the required document review statuses.",
        "repayment_summary": "Explain the current repayment summary.",
    },
    "tl": {
        "application_readiness": "Ibuod ang kahandaan ng aplikasyon para sa pagsusuri.",
        "profile_readiness": "Ano pa ang kulang sa profile bago ang pagsusuri?",
        "document_status": "Ibuod ang katayuan ng mga kinakailangang dokumento.",
        "repayment_summary": "Ipaliwanag ang kasalukuyang buod ng pagbabayad.",
    },
}

OFFICER_DISPLAY_LABELS = {
    "en": {
        "application_readiness": "Review readiness",
        "profile_readiness": "Profile gaps",
        "document_status": "Document status",
        "repayment_summary": "Review repayments",
    },
    "tl": {
        "application_readiness": "Suriin ang kahandaan",
        "profile_readiness": "Kulang sa profile",
        "document_status": "Katayuan ng dokumento",
        "repayment_summary": "Suriin ang bayaran",
    },
}

OFFICER_LIFECYCLE_DISPLAY_LABELS = {
    "en": {
        "approved": ("application_readiness", "Review approval conditions"),
        "disbursed": ("repayment_summary", "Review repayments"),
        "active": ("repayment_summary", "Review repayments"),
        "completed": ("repayment_summary", "Review repayment completion"),
        "rejected": ("application_readiness", "Review recorded reasons"),
        "cancelled": ("application_readiness", "Review cancellation"),
    },
    "tl": {
        "approved": ("application_readiness", "Suriin ang kondisyon ng pag-apruba"),
        "disbursed": ("repayment_summary", "Suriin ang bayaran"),
        "active": ("repayment_summary", "Suriin ang bayaran"),
        "completed": ("repayment_summary", "Buod ng nakumpletong bayaran"),
        "rejected": ("application_readiness", "Suriin ang naitalang dahilan"),
        "cancelled": ("application_readiness", "Suriin ang pagkansela"),
    },
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

_LEGACY_ACTION_LABELS = {
    "en": {
        "application_readiness": frozenset(
            {
                "Review approval conditions and disbursement readiness.",
                "Review recorded reasons and permitted follow-up.",
                "Review cancellation state and administrative follow-up.",
            }
        ),
        "profile_readiness": frozenset(),
        "document_status": frozenset(),
        "repayment_summary": frozenset(
            {
                "Review repayment health, next installment, and overdue status.",
                "Summarize repayment completion.",
            }
        ),
    },
    "tl": {
        "application_readiness": frozenset(
            {
                "Suriin ang mga kondisyon ng pag-apruba at kahandaan sa pag-release.",
                "Suriin ang naitalang dahilan at pinapahintulutang follow-up.",
                "Suriin ang pagkansela at administratibong follow-up.",
            }
        ),
        "profile_readiness": frozenset(),
        "document_status": frozenset(),
        "repayment_summary": frozenset(
            {
                "Suriin ang kalagayan ng bayaran, susunod na hulog, at overdue.",
                "Ibuod ang pagkumpleto ng bayaran.",
            }
        ),
    },
}

_LANGUAGE_ACTION_ALIASES = {
    "en": {
        "application_readiness": frozenset(
            {
                "summarize this application's review readiness",
                "summarize review readiness",
                "review summary",
                "review this application",
                "what is the current application status",
                "current application status",
            }
        ),
        "profile_readiness": frozenset(
            {
                "what profile information is still incomplete",
                "what is missing from the profile",
                "what is incomplete in the profile",
            }
        ),
        "document_status": frozenset(
            {
                "summarize the required document review statuses",
                "summarize the required document review status",
                "what documents are present",
                "what documents still need review",
            }
        ),
        "repayment_summary": frozenset(
            {
                "explain the current repayment summary",
                "what is the current repayment status",
                "show the repayment summary",
            }
        ),
    },
    "tl": {
        "application_readiness": frozenset(
            {"ibuod ang kahandaan ng aplikasyon para sa pagsusuri"}
        ),
        "profile_readiness": frozenset(
            {"ano pa ang kulang sa profile bago ang pagsusuri"}
        ),
        "document_status": frozenset(
            {
                "ibuod ang katayuan ng mga kinakailangang dokumento",
                "ibuod ang mga katayuan ng pagsusuri ng kinakailangang dokumento",
            }
        ),
        "repayment_summary": frozenset(
            {"ipaliwanag ang kasalukuyang buod ng pagbabayad"}
        ),
    },
}


def canonical_officer_question(intent, language="en"):
    """Return the server-owned question for an allowlisted review intent."""
    normalized_language = "tl" if str(language or "en").lower() == "tl" else "en"
    return OFFICER_CANONICAL_QUESTIONS[normalized_language][intent]


def _all_action_message_aliases(intent, language):
    normalized_language = "tl" if str(language or "en").lower() == "tl" else "en"
    aliases = set(_LANGUAGE_ACTION_ALIASES[normalized_language][intent])
    aliases.add(_normalize_intent_message(canonical_officer_question(intent, normalized_language)))
    aliases.add(_normalize_intent_message(OFFICER_DISPLAY_LABELS[normalized_language][intent]))
    aliases.update(
        _normalize_intent_message(label)
        for lifecycle_intent, label in OFFICER_LIFECYCLE_DISPLAY_LABELS[
            normalized_language
        ].values()
        if lifecycle_intent == intent
    )
    aliases.update(
        _normalize_intent_message(label)
        for label in _LEGACY_ACTION_LABELS[normalized_language][intent]
    )
    return aliases


def officer_action_intent_for_message(message, language="en"):
    """Return an intent only for an exact approved action/canonical label."""
    normalized = _normalize_intent_message(message)
    for intent in OFFICER_SUGGESTION_INTENTS:
        if normalized in _all_action_message_aliases(intent, language):
            return intent
    return None


def is_approved_officer_action_message(message, intent, language="en"):
    return intent in OFFICER_SUGGESTION_INTENTS and (
        _normalize_intent_message(message)
        in _all_action_message_aliases(intent, language)
    )


def route_officer_intent(message):
    """Return a server-owned intent for a known safe question variant."""
    normalized = _normalize_intent_message(message)
    for intent, aliases in _DETERMINISTIC_INTENT_ALIASES.items():
        if normalized in aliases:
            return intent
    return None


def officer_suggestions(language, status=None):
    normalized_language = "tl" if str(language or "en").lower() == "tl" else "en"
    labels = OFFICER_DISPLAY_LABELS[normalized_language]
    suggestions = [
        {"id": intent, "label": labels[intent]}
        for intent in OFFICER_SUGGESTION_INTENTS
    ]
    if status is None:
        return suggestions

    normalized_status = str(status or "").strip().lower()
    if normalized_status in {"draft", "submitted", "under_review"}:
        return suggestions[:3]

    lifecycle_suggestion = OFFICER_LIFECYCLE_DISPLAY_LABELS[
        normalized_language
    ].get(normalized_status)
    if lifecycle_suggestion is None:
        return suggestions[:3]
    intent, label = lifecycle_suggestion
    return [{"id": intent, "label": label}]
