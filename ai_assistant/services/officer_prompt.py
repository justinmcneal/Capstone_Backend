"""Static, identifier-free guidance for the loan-officer AI assistant."""


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


def officer_suggestions(language):
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
    return [
        {"id": intent, "label": label}
        for intent, label in zip(OFFICER_SUGGESTION_INTENTS, labels)
    ]
