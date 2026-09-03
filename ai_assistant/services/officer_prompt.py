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


# Leading conversational wrappers officers naturally type ("how about the",
# "can you", "please", ...) that carry no routing signal on their own.
_LEADING_CONVERSATIONAL_FILLERS = (
    "how about",
    "how bout",
    "what about",
    "can you",
    "can u",
    "could you",
    "would you",
    "will you",
    "do you",
    "did you",
    "do u",
    "please",
    "pls",
    "kindly",
    "paki",
    "pakibuod",
    "show me",
    "tell me about",
    "tell me",
    "give me the",
    "give me",
    "i want",
    "i need",
    "i d like",
    "id like",
    "let me know",
    "what is",
    "what s",
    "whats",
    "what are",
    "where is",
    "where s",
    "wheres",
    "how is",
    "how s",
    "hows",
    "kamusta ang",
    "kumusta ang",
)

# Leading articles/determiners stripped only after a filler (or on their own
# for terse inputs like "the repayment schedule").
_LEADING_ARTICLES = ("the", "a", "an", "this", "that", "ang", "yung")

# Trailing politeness particles ("profile summary please", "... po").
_TRAILING_POLITENESS_FILLERS = ("please", "thanks", "thank you", "po", "pa", "naman")


def _strip_conversational_fillers(normalized):
    """Remove conversational wrappers around an already-normalized message."""
    text = normalized
    changed = True
    while changed and text:
        changed = False
        for filler in _LEADING_CONVERSATIONAL_FILLERS:
            if text.startswith(filler + " ") and len(text) > len(filler) + 1:
                text = text[len(filler) + 1 :]
                changed = True
                break
        for article in _LEADING_ARTICLES:
            if text.startswith(article + " ") and len(text) > len(article) + 1:
                text = text[len(article) + 1 :]
                changed = True
                break
        for filler in _TRAILING_POLITENESS_FILLERS:
            if text.endswith(" " + filler):
                text = text[: -(len(filler) + 1)]
                changed = True
                break
    return text


# Whole-word keyword signals per intent, used only when deterministic matching
# and the LLM planner both fail to resolve a policy-clean message. Ties and
# zero-signal messages stay unresolved so unrelated requests remain
# scope-limited.
_OFFICER_KEYWORD_SIGNALS = (
    (
        "profile_readiness",
        frozenset(
            {
                "profile",
                "personal",
                "business",
                "income",
                "gaps",
                "incomplete",
                "kulang",
            }
        ),
    ),
    (
        "document_status",
        frozenset(
            {
                "document",
                "documents",
                "docs",
                "doc",
                "requirement",
                "requirements",
                "permit",
                "selfie",
                "proof",
                "id",
                "ids",
                "dokumento",
            }
        ),
    ),
    (
        "repayment_summary",
        frozenset(
            {
                "repayment",
                "repay",
                "payment",
                "payments",
                "schedule",
                "installment",
                "installments",
                "balance",
                "overdue",
                "due",
                "hulog",
                "bayad",
                "pagbabayad",
                "bayaran",
            }
        ),
    ),
    (
        "application_readiness",
        frozenset(
            {"application", "applications", "aplikasyon", "readiness", "approval"}
        ),
    ),
)


def guess_officer_intent_by_keywords(message):
    """Return the best keyword-supported intent, or None when unclear/tied."""
    tokens = set(_normalize_intent_message(message).split())
    if not tokens:
        return None
    scored = [
        (intent, len(tokens & signals))
        for intent, signals in _OFFICER_KEYWORD_SIGNALS
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    if scored[0][1] == 0:
        return None
    if len(scored) > 1 and scored[0][1] == scored[1][1]:
        return None
    return scored[0][0]


_DETERMINISTIC_INTENT_ALIASES = {
    "application_readiness": frozenset(
        {
            "summarize this application s review readiness",
            "review this application",
            "what is the current application status",
            "current application status",
            "application summary",
            "application status",
            "app summary",
            "app status",
            "summarize application",
            "summarize the application",
            "review readiness summary",
            "review summary application",
            "ibuod ang kahandaan ng aplikasyon para sa pagsusuri",
            "buod ng aplikasyon",
            "buod ng application",
            "katayuan ng aplikasyon",
        }
    ),
    "profile_readiness": frozenset(
        {
            "what profile information is still incomplete",
            "what is missing from the profile",
            "what is incomplete in the profile",
            "profile summary",
            "show profile summary",
            "profile gaps",
            "profile readiness",
            "profile readiness summary",
            "show profile",
            "summarize profile",
            "ano pa ang kulang sa profile bago ang pagsusuri",
            "buod ng profile",
        }
    ),
    "document_status": frozenset(
        {
            "summarize the required document review statuses",
            "summarize the required document review status",
            "what documents are present",
            "what documents still need review",
            "document status",
            "docs status",
            "show document status",
            "document summary",
            "required documents status",
            "ibuod ang katayuan ng mga kinakailangang dokumento",
            "ibuod ang mga katayuan ng pagsusuri ng kinakailangang dokumento",
            "katayuan ng dokumento",
            "katayuan ng mga dokumento",
        }
    ),
    "repayment_summary": frozenset(
        {
            "explain the current repayment summary",
            "what is the current repayment status",
            "show the repayment summary",
            "repayment summary",
            "repayment status",
            "repayment schedule",
            "show repayment schedule",
            "show repayment status",
            "schedule repayment",
            "schedule in repayment",
            "repayment progress",
            "ipaliwanag ang kasalukuyang buod ng pagbabayad",
            "iskedyul ng pagbabayad",
            "buod ng pagbabayad",
            "katayuan ng pagbabayad",
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
                "application summary",
                "application status",
                "app summary",
                "app status",
                "summarize application",
                "summarize the application",
                "review readiness summary",
            }
        ),
        "profile_readiness": frozenset(
            {
                "what profile information is still incomplete",
                "what is missing from the profile",
                "what is incomplete in the profile",
                "profile summary",
                "show profile summary",
                "profile gaps",
                "profile readiness",
                "show profile",
                "summarize profile",
            }
        ),
        "document_status": frozenset(
            {
                "summarize the required document review statuses",
                "summarize the required document review status",
                "what documents are present",
                "what documents still need review",
                "document status",
                "docs status",
                "show document status",
                "document summary",
                "required documents status",
            }
        ),
        "repayment_summary": frozenset(
            {
                "explain the current repayment summary",
                "what is the current repayment status",
                "show the repayment summary",
                "repayment summary",
                "repayment status",
                "repayment schedule",
                "show repayment schedule",
                "show repayment status",
                "schedule repayment",
                "schedule in repayment",
                "repayment progress",
            }
        ),
    },
    "tl": {
        "application_readiness": frozenset(
            {
                "ibuod ang kahandaan ng aplikasyon para sa pagsusuri",
                "buod ng aplikasyon",
                "buod ng application",
                "katayuan ng aplikasyon",
            }
        ),
        "profile_readiness": frozenset(
            {
                "ano pa ang kulang sa profile bago ang pagsusuri",
                "buod ng profile",
            }
        ),
        "document_status": frozenset(
            {
                "ibuod ang katayuan ng mga kinakailangang dokumento",
                "ibuod ang mga katayuan ng pagsusuri ng kinakailangang dokumento",
                "katayuan ng dokumento",
                "katayuan ng mga dokumento",
            }
        ),
        "repayment_summary": frozenset(
            {
                "ipaliwanag ang kasalukuyang buod ng pagbabayad",
                "iskedyul ng pagbabayad",
                "buod ng pagbabayad",
                "katayuan ng pagbabayad",
            }
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


def _intent_for_normalized_message(normalized, language):
    for intent in OFFICER_SUGGESTION_INTENTS:
        if normalized in _all_action_message_aliases(intent, language):
            return intent
    return None


def officer_action_intent_for_message(message, language="en"):
    """Return an intent only for an exact approved action/canonical label."""
    normalized = _normalize_intent_message(message)
    intent = _intent_for_normalized_message(normalized, language)
    if intent:
        return intent
    stripped = _strip_conversational_fillers(normalized)
    if stripped and stripped != normalized:
        return _intent_for_normalized_message(stripped, language)
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
    stripped = _strip_conversational_fillers(normalized)
    if stripped and stripped != normalized:
        for intent, aliases in _DETERMINISTIC_INTENT_ALIASES.items():
            if stripped in aliases:
                return intent
    return None


def officer_suggestions(language, status=None):
    normalized_language = "tl" if str(language or "en").lower() == "tl" else "en"
    labels = OFFICER_DISPLAY_LABELS[normalized_language]
    if status is None:
        return [
            {"id": intent, "label": labels[intent]}
            for intent in OFFICER_SUGGESTION_INTENTS
        ]

    normalized_status = str(status or "").strip().lower()
    lifecycle_suggestion = OFFICER_LIFECYCLE_DISPLAY_LABELS[
        normalized_language
    ].get(normalized_status)
    if lifecycle_suggestion is None:
        # Draft, submitted, under_review, and unknown statuses show all four
        # actions with their default labels.
        return [
            {"id": intent, "label": labels[intent]}
            for intent in OFFICER_SUGGESTION_INTENTS
        ]
    # Post-review lifecycles lead with the contextual action but still offer
    # the other three one-click review actions.
    intent, label = lifecycle_suggestion
    ordered = [intent] + [
        other for other in OFFICER_SUGGESTION_INTENTS if other != intent
    ]
    return [
        {"id": item, "label": label if item == intent else labels[item]}
        for item in ordered
    ]
