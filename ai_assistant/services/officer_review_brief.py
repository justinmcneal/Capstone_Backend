"""Deterministic, localized public contract for the officer review copilot."""

import json
import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ai_assistant.services.officer_evidence_contract import (
    DOCUMENT_STATUSES,
    INSTALLMENT_STATUSES,
    RISK_SCORE_STATUSES,
    SCHEDULE_STATUSES,
)


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "officer_review_brief.schema.json"
)
OFFICER_REVIEW_BRIEF_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
OFFICER_REVIEW_BRIEF_CONTRACT_VERSION = OFFICER_REVIEW_BRIEF_SCHEMA["properties"][
    "contract_version"
]["const"]
PUBLIC_REVIEW_STATES = frozenset(
    OFFICER_REVIEW_BRIEF_SCHEMA["properties"]["review_state"]["enum"]
)
PUBLIC_REASON_CODES = frozenset(
    OFFICER_REVIEW_BRIEF_SCHEMA["properties"]["reasons"]["items"]["properties"][
        "code"
    ]["enum"]
)
PUBLIC_REVIEW_BRIEF_FIELDS = frozenset(OFFICER_REVIEW_BRIEF_SCHEMA["required"])
PUBLIC_SOURCE_LABELS = {
    "en": {
        "get_application_summary": "Application summary",
        "get_profile_readiness": "Profile readiness",
        "get_document_review_status": "Document review",
        "get_repayment_summary": "Repayment summary",
    },
    "fil": {
        "get_application_summary": "Buod ng aplikasyon",
        "get_profile_readiness": "Kahandaan ng profile",
        "get_document_review_status": "Pagsusuri ng mga dokumento",
        "get_repayment_summary": "Buod ng pagbabayad",
    },
}

_DOCUMENT_LABELS = {
    "en": {
        "valid_id": "Valid government ID",
        "selfie_with_id": "Selfie with ID",
        "proof_of_address": "Proof of address",
        "business_permit": "Business permit",
        "business_photo": "Business photo",
        "income_proof": "Proof of income",
        "other": "Other supporting document",
    },
    "fil": {
        "valid_id": "Balidong government ID",
        "selfie_with_id": "Selfie kasama ang ID",
        "proof_of_address": "Patunay ng tirahan",
        "business_permit": "Permit ng negosyo",
        "business_photo": "Larawan ng negosyo",
        "income_proof": "Patunay ng kita",
        "other": "Iba pang pansuportang dokumento",
    },
}

_PROFILE_FIELD_LABELS = {
    "en": {
        "personal.gender": "Gender",
        "personal.civil_status": "Civil status",
        "personal.nationality": "Nationality",
        "business.business_type": "Business type",
        "business.business_age_months": "Business age",
        "business.is_registered": "Business registration status",
        "business.estimated_monthly_income": "Monthly income",
        "business.income_range": "Income range",
        "business.estimated_monthly_expenses": "Monthly expenses",
        "business.number_of_employees": "Number of employees",
        "alternative.education_level": "Education level",
        "alternative.employment_status": "Employment status",
        "alternative.years_of_experience": "Business experience",
        "alternative.housing_status": "Housing status",
        "alternative.number_of_dependents": "Number of dependents",
        "alternative.has_existing_loans": "Existing loans status",
        "alternative.has_bank_account": "Bank account status",
        "alternative.has_ewallet": "E-wallet status",
        "alternative.pays_utilities": "Utility payment status",
        "alternative.is_coop_member": "Cooperative membership",
    },
    "fil": {
        "personal.gender": "Kasarian",
        "personal.civil_status": "Katayuang sibil",
        "personal.nationality": "Nasyonalidad",
        "business.business_type": "Uri ng negosyo",
        "business.business_age_months": "Tagal ng negosyo",
        "business.is_registered": "Katayuan ng pagpaparehistro ng negosyo",
        "business.estimated_monthly_income": "Buwanang kita",
        "business.income_range": "Saklaw ng kita",
        "business.estimated_monthly_expenses": "Buwanang gastusin",
        "business.number_of_employees": "Bilang ng mga empleyado",
        "alternative.education_level": "Antas ng edukasyon",
        "alternative.employment_status": "Katayuan sa trabaho",
        "alternative.years_of_experience": "Karanasan sa negosyo",
        "alternative.housing_status": "Katayuan ng tirahan",
        "alternative.number_of_dependents": "Bilang ng mga dependente",
        "alternative.has_existing_loans": "Katayuan ng kasalukuyang pautang",
        "alternative.has_bank_account": "Katayuan ng bank account",
        "alternative.has_ewallet": "Katayuan ng e-wallet",
        "alternative.pays_utilities": "Katayuan ng pagbabayad ng utilities",
        "alternative.is_coop_member": "Pagiging kasapi ng kooperatiba",
    },
}

_TEXT = {
    "en": {
        "disclaimer": "AI assistance is advisory only. Verify details against the application record.",
        "review_label": "Review readiness",
        "next_label": "Next step",
        "next_plural_label": "Next steps",
        "sources_label": "Sources checked",
        "ready_headline": "Ready for review",
        "attention_headline": "Not ready for review",
        "post_review_headline": "Review completed",
        "summary_headline": "Application review summary",
        "profile_headline": "Profile readiness summary",
        "document_headline": "Document review summary",
        "repayment_headline": "Repayment summary",
        "repayment_attention_headline": "Repayment needs attention",
        "application_unavailable": "Application summary unavailable",
        "profile_unavailable": "Profile summary unavailable",
        "document_unavailable": "Document summary unavailable",
        "repayment_unavailable": "Repayment summary unavailable",
        "general_unavailable": "Review summary unavailable",
        "scope_headline": "Request outside this review brief",
        "scope_step": "Ask about this application's review readiness, profile, documents, or repayment summary.",
        "retry_step": "Retry the request or verify the application record manually.",
        "repayment_retry_step": "Retry the request or verify the repayment record manually.",
        "ready_label": "The application is ready for officer review",
        "ready_detail": "The current application record is in a reviewable workflow stage.",
        "not_ready_label": "The application is not ready for officer review",
        "not_ready_detail": "The current application record is not in a reviewable workflow stage.",
        "post_review_label": "The application has moved beyond active officer review",
        "post_review_detail": "The current application record is no longer in the active review workflow.",
        "manual_label": "Manual review is required",
        "manual_detail": "Use the established portal workflow for manual review.",
        "application_next": "Verify the application record before continuing the review workflow.",
        "post_review_next": "Verify the application record before taking further workflow action.",
        "purpose_label": "Loan purpose is incomplete",
        "purpose_detail": "Complete or verify the loan purpose in the application workflow.",
        "income_missing_label": "Income information is missing",
        "income_missing_detail": "Provide or verify income information before continuing review.",
        "profile_next": "Complete or verify the identified profile information before continuing review.",
        "profile_complete_next": "No required profile information is missing. Continue with the established review workflow.",
        "document_next": "Resolve the identified document requirements in the established portal workflow.",
        "document_complete_next": "All required documents have been reviewed. Continue with the established review workflow.",
        "repayment_next": "Verify the repayment record before taking workflow action.",
        "profile_unavailable_label": "{profile} profile is unavailable",
        "profile_unavailable_detail": "The current record does not contain an available {profile_lower} profile.",
        "field_label": "{field} is incomplete",
        "field_detail": "Complete or verify {field_lower} in the established profile workflow.",
        "missing_document_label": "{document} is missing",
        "missing_document_detail": "Provide or verify the required {document_lower} before continuing document review.",
        "document_status_label": "{document} requires attention",
        "document_status_detail": "The current {document_lower} status is {status}.",
        "repayment_available_label": "A repayment schedule is available",
        "repayment_available_detail": "{paid_count} of {installment_count} installments are paid; the remaining balance is {remaining_balance}.",
        "next_due_detail": "Next due date: {date}.",
        "repayment_missing_label": "No repayment schedule is available",
        "repayment_missing_detail": "The current application record does not contain a repayment schedule.",
        "repayment_overdue_label": "The repayment schedule requires attention",
        "repayment_overdue_detail": "{count} installment(s) are currently overdue or partially overdue.",
        "personal": "Personal",
        "business": "Business",
        "alternative": "Alternative-data",
        "pending": "pending review",
        "needs_review": "flagged for review",
        "rejected": "rejected",
        "expired": "expired",
        "and": "and",
        "freshness_stale_profile": "Profile risk results may be out of date. Verify the latest profile assessment.",
        "freshness_stale_evidence": "Application evidence may be out of date. Verify the latest application record.",
        "action_open_profile": "Open profile",
        "action_review_documents": "Review documents",
        "action_view_repayment": "View repayment schedule",
    },
    "fil": {
        "disclaimer": "Ang tulong ng AI ay para lamang sa gabay. Beripikahin ang mga detalye sa talaan ng aplikasyon.",
        "review_label": "Kahandaan para sa pagsusuri",
        "next_label": "Susunod na hakbang",
        "next_plural_label": "Mga susunod na hakbang",
        "sources_label": "Mga pinagkunang sinuri",
        "ready_headline": "Handa para sa pagsusuri",
        "attention_headline": "Hindi pa handa para sa pagsusuri",
        "post_review_headline": "Nakumpleto na ang pagsusuri",
        "summary_headline": "Buod ng pagsusuri ng aplikasyon",
        "profile_headline": "Buod ng kahandaan ng profile",
        "document_headline": "Buod ng pagsusuri ng mga dokumento",
        "repayment_headline": "Buod ng pagbabayad",
        "repayment_attention_headline": "Kailangang suriin ang pagbabayad",
        "application_unavailable": "Hindi makuha ang buod ng aplikasyon",
        "profile_unavailable": "Hindi makuha ang buod ng profile",
        "document_unavailable": "Hindi makuha ang buod ng mga dokumento",
        "repayment_unavailable": "Hindi makuha ang buod ng pagbabayad",
        "general_unavailable": "Hindi makuha ang buod ng pagsusuri",
        "scope_headline": "Wala sa saklaw ng review brief ang kahilingan",
        "scope_step": "Magtanong tungkol sa kahandaan para sa pagsusuri, profile, mga dokumento, o buod ng pagbabayad ng aplikasyong ito.",
        "retry_step": "Subukang muli ang kahilingan o beripikahin nang manu-mano ang talaan ng aplikasyon.",
        "repayment_retry_step": "Subukang muli ang kahilingan o beripikahin nang manu-mano ang talaan ng pagbabayad.",
        "ready_label": "Handa ang aplikasyon para sa pagsusuri ng loan officer",
        "ready_detail": "Ang kasalukuyang talaan ng aplikasyon ay nasa yugto na maaari nang suriin.",
        "not_ready_label": "Hindi pa handa ang aplikasyon para sa pagsusuri ng loan officer",
        "not_ready_detail": "Ang kasalukuyang talaan ng aplikasyon ay wala pa sa yugto na maaari nang suriin.",
        "post_review_label": "Lumampas na ang aplikasyon sa aktibong pagsusuri ng loan officer",
        "post_review_detail": "Ang kasalukuyang talaan ng aplikasyon ay wala na sa aktibong workflow ng pagsusuri.",
        "manual_label": "Kailangan ang manu-manong pagsusuri",
        "manual_detail": "Gamitin ang itinakdang workflow ng portal para sa manu-manong pagsusuri.",
        "application_next": "Beripikahin ang talaan ng aplikasyon bago ipagpatuloy ang workflow ng pagsusuri.",
        "post_review_next": "Beripikahin ang talaan ng aplikasyon bago gumawa ng karagdagang aksyon sa workflow.",
        "purpose_label": "Hindi pa kumpleto ang layunin ng pautang",
        "purpose_detail": "Kumpletuhin o beripikahin ang layunin ng pautang gamit ang application workflow.",
        "income_missing_label": "Kulang ang impormasyon tungkol sa kita",
        "income_missing_detail": "Ibigay o beripikahin ang impormasyon tungkol sa kita bago ipagpatuloy ang pagsusuri.",
        "profile_next": "Kumpletuhin o beripikahin ang natukoy na impormasyon sa profile bago ipagpatuloy ang pagsusuri.",
        "profile_complete_next": "Walang kulang na kinakailangang impormasyon sa profile. Ipagpatuloy ang itinakdang workflow ng pagsusuri.",
        "document_next": "Ayusin ang natukoy na kinakailangan sa dokumento gamit ang itinakdang workflow ng portal.",
        "document_complete_next": "Nasuri na ang lahat ng kinakailangang dokumento. Ipagpatuloy ang itinakdang workflow ng pagsusuri.",
        "repayment_next": "Beripikahin ang talaan ng pagbabayad bago gumawa ng aksyon sa workflow.",
        "profile_unavailable_label": "Hindi available ang {profile} profile",
        "profile_unavailable_detail": "Walang available na {profile_lower} profile sa kasalukuyang talaan.",
        "field_label": "Hindi pa kumpleto ang {field}",
        "field_detail": "Kumpletuhin o beripikahin ang {field_lower} gamit ang itinakdang workflow ng profile.",
        "missing_document_label": "Kulang ang {document}",
        "missing_document_detail": "Ibigay o beripikahin ang kinakailangang {document_lower} bago ipagpatuloy ang pagsusuri ng dokumento.",
        "document_status_label": "Kailangang suriin ang {document}",
        "document_status_detail": "Ang kasalukuyang katayuan ng {document_lower} ay {status}.",
        "repayment_available_label": "Available ang iskedyul ng pagbabayad",
        "repayment_available_detail": "Bayad na ang {paid_count} sa {installment_count} hulog; ang natitirang balanse ay {remaining_balance}.",
        "next_due_detail": "Susunod na takdang petsa ng bayad: {date}.",
        "repayment_missing_label": "Walang available na iskedyul ng pagbabayad",
        "repayment_missing_detail": "Walang iskedyul ng pagbabayad sa kasalukuyang talaan ng aplikasyon.",
        "repayment_overdue_label": "Kailangang suriin ang iskedyul ng pagbabayad",
        "repayment_overdue_detail": "May {count} hulog na overdue o bahagyang overdue.",
        "personal": "Personal",
        "business": "Negosyo",
        "alternative": "Alternatibong datos",
        "pending": "naghihintay ng pagsusuri",
        "needs_review": "minarkahan para sa pagsusuri",
        "rejected": "tinanggihan",
        "expired": "nag-expire",
        "and": "at",
        "freshness_stale_profile": "Maaaring luma na ang resulta ng panganib sa profile. Beripikahin ang pinakabagong pagtatasa ng profile.",
        "freshness_stale_evidence": "Maaaring luma na ang ebidensya ng aplikasyon. Beripikahin ang pinakabagong talaan ng aplikasyon.",
        "action_open_profile": "Buksan ang profile",
        "action_review_documents": "Suriin ang mga dokumento",
        "action_view_repayment": "Tingnan ang iskedyul ng pagbabayad",
    },
}

_OUT_OF_SCOPE_PATTERNS = (
    re.compile(
        r"\b(?:approval odds|odds of approval|chance of approval|likelihood of approval|"
        r"probability[^?.!]{0,50}approv\w*|(?:will|would|can|could|likely)[^?.!]{0,50}approv\w*|"
        r"approv\w*[^?.!]{0,30}(?:odds|chance|likelihood|probability))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:another|other|last|previous|prior|earlier|peer|historical|past)"
        r"[^?.!]{0,15}(?:applicants?|applications?|borrowers?|customers?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:tsansa|posibilidad|probabilidad|malamang)[^?.!]{0,50}"
        r"(?:ma+aprubahan|aprubahan|approval)|"
        r"(?:ma+aprubahan|aprubahan)[^?.!]{0,30}(?:ba|kaya|tsansa|posibilidad))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ibang|iba|nakaraang|nakaraan|huling|nauna|naunang)"
        r"[^?.!]{0,15}(?:aplikante|aplikasyon|customer|borrower)\b",
        re.IGNORECASE,
    ),
)
STALE_EVIDENCE_AFTER_SECONDS = 15 * 60


class InvalidReviewBrief(ValueError):
    """Raised when data is not safe enough to enter the narration boundary."""

    def __init__(self, message, *, code="brief_contract_invalid"):
        super().__init__(message)
        self.code = code


def _locale(language):
    return "fil" if str(language or "en").lower() in {"tl", "fil"} else "en"


def _is_out_of_scope(message):
    normalized = str(message or "")
    return any(pattern.search(normalized) for pattern in _OUT_OF_SCOPE_PATTERNS)


def _base_brief(
    *,
    state,
    headline,
    reasons,
    next_steps,
    sources,
    locale,
    as_of=None,
    evidence_revision=None,
    freshness=None,
    actions=None,
):
    if evidence_revision is None:
        evidence_revision = hashlib.sha256(b"unknown").hexdigest()
    if freshness is None:
        freshness = {"state": "unknown", "warnings": []}
    return {
        "contract_version": OFFICER_REVIEW_BRIEF_CONTRACT_VERSION,
        "review_state": state,
        "headline": headline,
        "reasons": reasons,
        "next_steps": next_steps,
        "sources": sources,
        "advisory_only": True,
        "disclaimer": _TEXT[locale]["disclaimer"],
        "as_of": as_of,
        "evidence_revision": evidence_revision,
        "freshness": freshness,
        "actions": list(actions or []),
    }


def build_unavailable_review_brief(
    language, *, topic=None, as_of=None, evidence_revision=None, actions=None
):
    locale = _locale(language)
    text = _TEXT[locale]
    topic_key = topic if topic in {"application", "profile", "document", "repayment"} else "general"
    return _base_brief(
        state="unavailable",
        headline=text[f"{topic_key}_unavailable"],
        reasons=[],
        next_steps=[
            text["repayment_retry_step"] if topic_key == "repayment" else text["retry_step"]
        ],
        sources=[],
        locale=locale,
        as_of=as_of,
        evidence_revision=None,
        freshness={"state": "unavailable", "warnings": []},
        actions=actions,
    )


def build_scope_limit_review_brief(language, *, as_of=None):
    locale = _locale(language)
    text = _TEXT[locale]
    return _base_brief(
        state="scope_limited",
        headline=text["scope_headline"],
        reasons=[],
        next_steps=[text["scope_step"]],
        sources=[],
        locale=locale,
        as_of=as_of,
    )


def _decode_evidence(entry):
    if not isinstance(entry, dict):
        raise InvalidReviewBrief("Evidence must be an object")
    tool_name = entry.get("tool_name")
    if tool_name not in PUBLIC_SOURCE_LABELS["en"]:
        raise InvalidReviewBrief("Unknown evidence source")
    if entry.get("success") is not True:
        return tool_name, None
    raw = entry.get("result")
    try:
        decoded = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidReviewBrief("Malformed evidence") from exc
    if not isinstance(decoded, dict):
        raise InvalidReviewBrief("Evidence result must be an object")
    return tool_name, decoded


def _application_fragment(result, locale):
    text = _TEXT[locale]
    readiness = result.get("review_readiness")
    if not isinstance(readiness, dict):
        raise InvalidReviewBrief("Missing review readiness")
    status = readiness.get("status")
    if status == "ready_for_review" and readiness.get("is_reviewable") is True:
        state = "ready"
        reasons = [
            {
                "code": "review_stage_ready",
                "label": text["ready_label"],
                "detail": text["ready_detail"],
            }
        ]
    elif status == "not_ready_for_review" and readiness.get("is_reviewable") is False:
        state = "needs_attention"
        reasons = [
            {
                "code": "review_stage_not_ready",
                "label": text["not_ready_label"],
                "detail": text["not_ready_detail"],
            }
        ]
    elif status == "review_complete" and readiness.get("is_reviewable") is False:
        state = "informational"
        reasons = [
            {
                "code": "review_stage_complete",
                "label": text["post_review_label"],
                "detail": text["post_review_detail"],
            }
        ]
    else:
        raise InvalidReviewBrief("Unknown review readiness")
    if "purpose" in result:
        purpose = result["purpose"]
        if purpose is not None and purpose not in {
            "inventory",
            "working_capital",
            "equipment",
            "expansion",
            "operations",
        }:
            raise InvalidReviewBrief("Unknown application purpose")
        if purpose is None:
            reasons.append(
                {
                    "code": "application_field_incomplete",
                    "label": text["purpose_label"],
                    "detail": text["purpose_detail"],
                }
            )
    reason_codes = result.get("reason_codes", [])
    if not isinstance(reason_codes, list) or any(
        not isinstance(code, str) for code in reason_codes
    ):
        raise InvalidReviewBrief("Malformed application reason codes")
    if readiness.get("manual_review_required") is True:
        reasons.append(
            {
                "code": "manual_check_needed",
                "label": text["manual_label"],
                "detail": text["manual_detail"],
            }
        )
    if "income_missing" in reason_codes:
        reasons.append(
            {
                "code": "manual_check_needed",
                "label": text["income_missing_label"],
                "detail": text["income_missing_detail"],
            }
        )
    return state, reasons, [
        text["post_review_next"] if state == "informational" else text["application_next"]
    ]


def _profile_fragment(result, locale):
    text = _TEXT[locale]
    reasons = []
    profile_requires_completion = False
    for profile_name in ("personal", "business", "alternative"):
        profile = result.get(profile_name)
        if not isinstance(profile, dict) or not isinstance(profile.get("available"), bool):
            raise InvalidReviewBrief("Malformed profile evidence")
        if not profile["available"]:
            profile_requires_completion = True
            label = text[profile_name]
            reasons.append(
                {
                    "code": f"{profile_name}_profile_unavailable",
                    "label": text["profile_unavailable_label"].format(profile=label),
                    "detail": text["profile_unavailable_detail"].format(
                        profile_lower=label.lower()
                    ),
                }
            )
            continue
        complete = profile.get("complete")
        completion_percentage = profile.get("completion_percentage")
        missing_fields = profile.get("missing_fields", [])
        if (
            not isinstance(complete, bool)
            or not isinstance(completion_percentage, int)
            or isinstance(completion_percentage, bool)
            or not 0 <= completion_percentage <= 100
            or not isinstance(missing_fields, list)
            or (complete and (completion_percentage != 100 or missing_fields))
            or (not complete and (completion_percentage >= 100 or not missing_fields))
        ):
            raise InvalidReviewBrief("Malformed profile fields")
        for field in missing_fields:
            profile_requires_completion = True
            code = field.get("code") if isinstance(field, dict) else None
            label = _PROFILE_FIELD_LABELS[locale].get(code)
            if not label:
                raise InvalidReviewBrief("Unknown profile field")
            reasons.append(
                {
                    "code": "profile_field_incomplete",
                    "label": text["field_label"].format(field=label),
                    "detail": text["field_detail"].format(field_lower=label.lower()),
                }
            )
        if profile_name == "alternative":
            risk_status = profile.get("risk_status")
            if (
                risk_status
                not in RISK_SCORE_STATUSES
                or profile.get("risk_score_status") != risk_status
                or profile.get("risk_category")
                not in {"unknown", "low", "medium", "high"}
                or (
                    risk_status == "complete"
                    and profile.get("risk_category") == "unknown"
                )
                or not isinstance(profile.get("manual_review_required"), bool)
                or not isinstance(profile.get("manual_review_flags"), list)
                or profile.get("manual_review_flags")
                != (["risk_score"] if profile["manual_review_required"] else [])
            ):
                raise InvalidReviewBrief("Malformed alternative profile evidence")
            if profile["manual_review_required"]:
                reasons.append(
                    {
                        "code": "manual_check_needed",
                        "label": text["manual_label"],
                        "detail": text["manual_detail"],
                    }
                )
    return (
        "needs_attention" if reasons else "ready",
        reasons,
        [
            text["profile_next"]
            if profile_requires_completion
            else text["profile_complete_next"]
        ],
    )


def _document_fragment(result, locale):
    text = _TEXT[locale]
    required = result.get("required_document_types")
    documents = result.get("documents")
    if (
        not isinstance(required, list)
        or not isinstance(documents, list)
        or result.get("truncated") is not False
    ):
        raise InvalidReviewBrief("Malformed document evidence")
    required_codes = []
    for required_document in required:
        code = required_document.get("code") if isinstance(required_document, dict) else None
        if code not in _DOCUMENT_LABELS[locale] or code in required_codes:
            raise InvalidReviewBrief("Unknown required document type")
        required_codes.append(code)
    submitted = {}
    for document in documents:
        if not isinstance(document, dict):
            raise InvalidReviewBrief("Malformed document item")
        code = document.get("type_code")
        status = document.get("status")
        verified = document.get("verified")
        if (
            code not in required_codes
            or status not in DOCUMENT_STATUSES
            or not isinstance(verified, bool)
            or verified != (status == "approved")
        ):
            raise InvalidReviewBrief("Unknown document type")
        submitted.setdefault(code, []).append(document)
    reasons = []
    for required_document in required:
        code = required_document.get("code") if isinstance(required_document, dict) else None
        label = _DOCUMENT_LABELS[locale].get(code)
        if not label:
            raise InvalidReviewBrief("Unknown required document type")
        matching = submitted.get(code, [])
        if not matching:
            reasons.append(
                {
                    "code": "document_missing",
                    "label": text["missing_document_label"].format(document=label),
                    "detail": text["missing_document_detail"].format(
                        document_lower=label.lower()
                    ),
                }
            )
            continue
        statuses = {
            str(document.get("status") or "")
            for document in matching
            if document.get("verified") is not True
        }
        for status in ("pending", "needs_review", "rejected", "expired"):
            if status not in statuses:
                continue
            reasons.append(
                {
                    "code": {
                        "pending": "document_pending_review",
                        "needs_review": "document_needs_review",
                        "rejected": "document_rejected",
                        "expired": "document_expired",
                    }[status],
                    "label": text["document_status_label"].format(document=label),
                    "detail": text["document_status_detail"].format(
                        document_lower=label.lower(), status=text[status]
                    ),
                }
            )
    return (
        "needs_attention" if reasons else "ready",
        reasons,
        [text["document_next"] if reasons else text["document_complete_next"]],
    )


def _money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidReviewBrief("Invalid repayment amount") from exc
    if not amount.is_finite() or amount < 0:
        raise InvalidReviewBrief("Invalid repayment amount")
    return f"₱{amount:,.2f}"


def _format_due_date(value, locale):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InvalidReviewBrief("Invalid repayment due date")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidReviewBrief("Invalid repayment due date") from exc
    if locale == "fil":
        month = (
            "Enero",
            "Pebrero",
            "Marso",
            "Abril",
            "Mayo",
            "Hunyo",
            "Hulyo",
            "Agosto",
            "Setyembre",
            "Oktubre",
            "Nobyembre",
            "Disyembre",
        )[parsed.month - 1]
        return f"{parsed.day} {month} {parsed.year}"
    month = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )[parsed.month - 1]
    return f"{month} {parsed.day}, {parsed.year}"


def _repayment_fragment(result, locale):
    text = _TEXT[locale]
    available = result.get("schedule_available")
    if available is False:
        if set(result) != {"schedule_available"}:
            raise InvalidReviewBrief("Malformed repayment evidence")
        return (
            "informational",
            [
                {
                    "code": "repayment_schedule_missing",
                    "label": text["repayment_missing_label"],
                    "detail": text["repayment_missing_detail"],
                }
            ],
            [text["repayment_next"]],
        )
    if available is not True:
        raise InvalidReviewBrief("Malformed repayment evidence")
    progress = result.get("schedule_progress")
    summaries = result.get("payment_status_summaries", [])
    if (
        result.get("schedule_status") not in SCHEDULE_STATUSES
        or result.get("payments_truncated") is not False
        or not isinstance(progress, dict)
        or not isinstance(summaries, list)
    ):
        raise InvalidReviewBrief("Malformed repayment evidence")
    paid_count = progress.get("paid_count")
    installment_count = progress.get("installment_count")
    completed_percentage = progress.get("completed_percentage")
    if (
        not isinstance(paid_count, int)
        or isinstance(paid_count, bool)
        or not isinstance(installment_count, int)
        or isinstance(installment_count, bool)
        or not isinstance(completed_percentage, int)
        or isinstance(completed_percentage, bool)
        or paid_count < 0
        or installment_count < 0
        or paid_count > installment_count
        or completed_percentage
        != (int(paid_count * 100 / installment_count) if installment_count else 0)
    ):
        raise InvalidReviewBrief("Malformed repayment progress")
    reasons = [
        {
            "code": "repayment_schedule_available",
            "label": text["repayment_available_label"],
            "detail": text["repayment_available_detail"].format(
                paid_count=paid_count,
                installment_count=installment_count,
                remaining_balance=_money(result.get("remaining_balance")),
            ),
        }
    ]
    if "next_due_date" in result:
        due_date = _format_due_date(result["next_due_date"], locale)
        if due_date:
            reasons[0]["detail"] += " " + text["next_due_detail"].format(date=due_date)
    overdue_count = 0
    summarized_count = 0
    summarized_paid_count = 0
    seen_statuses = set()
    for summary in summaries:
        status = summary.get("status") if isinstance(summary, dict) else None
        count = summary.get("count") if isinstance(summary, dict) else None
        if (
            status not in INSTALLMENT_STATUSES
            or status in seen_statuses
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
        ):
            raise InvalidReviewBrief("Malformed repayment status")
        seen_statuses.add(status)
        summarized_count += count
        if status == "paid":
            summarized_paid_count = count
        if status in {"overdue", "partial_overdue"}:
            overdue_count += count
    if summarized_count != installment_count or summarized_paid_count != paid_count:
        raise InvalidReviewBrief("Inconsistent repayment status")
    if overdue_count:
        reasons.append(
            {
                "code": "repayment_overdue",
                "label": text["repayment_overdue_label"],
                "detail": text["repayment_overdue_detail"].format(count=overdue_count),
            }
        )
    return (
        "needs_attention" if overdue_count else "informational",
        reasons,
        [text["repayment_next"]],
    )


_FRAGMENT_BUILDERS = {
    "get_application_summary": _application_fragment,
    "get_profile_readiness": _profile_fragment,
    "get_document_review_status": _document_fragment,
    "get_repayment_summary": _repayment_fragment,
}


def _topic_for_tool(tool_name):
    return {
        "get_application_summary": "application",
        "get_profile_readiness": "profile",
        "get_document_review_status": "document",
        "get_repayment_summary": "repayment",
    }.get(tool_name)


def _evidence_revision(evidence):
    """Return a deterministic, non-identifying digest for the evidence snapshot."""
    sanitized = []
    for entry in evidence if isinstance(evidence, list) else []:
        if not isinstance(entry, dict):
            sanitized.append({"valid": False})
            continue
        item = {"tool_name": entry.get("tool_name"), "success": entry.get("success") is True}
        if item["success"]:
            raw = entry.get("result")
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                parsed = None
            item["result"] = parsed
        else:
            item["code"] = entry.get("code")
        sanitized.append(item)
    canonical = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _freshness_for_evidence(evidence, locale):
    stale_profile = False
    stale_application = False
    for entry in evidence if isinstance(evidence, list) else []:
        if not isinstance(entry, dict) or entry.get("success") is not True:
            continue
        raw = entry.get("result")
        try:
            result = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            result = {}
        if not isinstance(result, dict):
            continue
        tool_name = entry.get("tool_name")
        if tool_name == "get_profile_readiness":
            alternative = result.get("alternative")
            if isinstance(alternative, dict):
                risk_status = alternative.get("risk_status") or alternative.get("risk_score_status")
                if risk_status == "stale" or (
                    alternative.get("risk_input_revision") is not None
                    and alternative.get("risk_calculated_revision") is not None
                    and alternative.get("risk_input_revision") != alternative.get("risk_calculated_revision")
                ):
                    stale_profile = True
            for profile_value in result.values():
                if isinstance(profile_value, dict) and isinstance(profile_value.get("evidence_updated_at"), str):
                    try:
                        profile_updated = datetime.fromisoformat(profile_value["evidence_updated_at"].replace("Z", "+00:00"))
                        if profile_updated.tzinfo is None:
                            profile_updated = profile_updated.replace(tzinfo=timezone.utc)
                        if (datetime.now(timezone.utc) - profile_updated).total_seconds() > STALE_EVIDENCE_AFTER_SECONDS:
                            stale_application = True
                    except ValueError:
                        pass
        if result.get("stale") is True or result.get("evidence_stale") is True:
            stale_application = True
        updated_at = result.get("evidence_updated_at")
        if isinstance(updated_at, str):
            try:
                parsed_updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if parsed_updated_at.tzinfo is None:
                    parsed_updated_at = parsed_updated_at.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - parsed_updated_at).total_seconds() > STALE_EVIDENCE_AFTER_SECONDS:
                    stale_application = True
            except ValueError:
                pass
    warnings = []
    text = _TEXT[locale]
    if stale_profile:
        warnings.append(text["freshness_stale_profile"])
    if stale_application:
        warnings.append(text["freshness_stale_evidence"])
    return {"state": "stale" if warnings else "current", "warnings": warnings}


def build_review_brief(
    evidence,
    *,
    language="en",
    message="",
    diagnostics=None,
    as_of=None,
    actions=None,
):
    locale = _locale(language)
    text = _TEXT[locale]
    if _is_out_of_scope(message):
        return build_scope_limit_review_brief(locale, as_of=as_of)
    if not isinstance(evidence, list) or not evidence:
        return build_unavailable_review_brief(
            locale,
            topic="application",
            as_of=as_of,
            evidence_revision=_evidence_revision(evidence),
            actions=actions,
        )

    fragments = []
    tools = []
    try:
        for entry in evidence:
            tool_name, result = _decode_evidence(entry)
            if result is None:
                if diagnostics is not None:
                    diagnostics.append("tool_read_unavailable")
                return build_unavailable_review_brief(
                    locale,
                    topic=_topic_for_tool(tool_name),
                    as_of=as_of,
                    evidence_revision=_evidence_revision(evidence),
                    actions=actions,
                )
            fragments.append(_FRAGMENT_BUILDERS[tool_name](result, locale))
            tools.append(tool_name)
    except InvalidReviewBrief as exc:
        if diagnostics is not None:
            diagnostics.append(exc.code)
        topic = (
            _topic_for_tool(evidence[0].get("tool_name")) or "application"
            if evidence and isinstance(evidence[0], dict)
            else "application"
        )
        return build_unavailable_review_brief(
            locale,
            topic=topic,
            as_of=as_of,
            evidence_revision=_evidence_revision(evidence),
            actions=actions,
        )

    states = {fragment[0] for fragment in fragments}
    if "needs_attention" in states:
        state = "needs_attention"
    elif any(fragment[0] == "informational" for fragment in fragments):
        state = "informational"
    else:
        state = "ready"
    reasons = []
    next_steps = []
    for _state, fragment_reasons, fragment_steps in fragments:
        reasons.extend(fragment_reasons)
        for step in fragment_steps:
            if step not in next_steps:
                next_steps.append(step)
    sources = [PUBLIC_SOURCE_LABELS[locale][tool] for tool in PUBLIC_SOURCE_LABELS[locale] if tool in tools]

    if tools == ["get_application_summary"]:
        headline = (
            text["ready_headline"]
            if state == "ready"
            else text["post_review_headline"]
            if state == "informational"
            else text["attention_headline"]
        )
    elif tools == ["get_profile_readiness"]:
        headline = text["profile_headline"]
    elif tools == ["get_document_review_status"]:
        headline = text["document_headline"]
    elif tools == ["get_repayment_summary"]:
        headline = text["repayment_attention_headline"] if state == "needs_attention" else text["repayment_headline"]
    else:
        headline = text["summary_headline"]
    brief = _base_brief(
        state=state,
        headline=headline,
        reasons=reasons,
        next_steps=next_steps,
        sources=sources,
        locale=locale,
        as_of=as_of,
        evidence_revision=_evidence_revision(evidence),
        freshness=_freshness_for_evidence(evidence, locale),
        actions=actions,
    )
    return validate_review_brief(brief)


def _brief_locale(brief):
    disclaimer = brief.get("disclaimer") if isinstance(brief, dict) else None
    for locale, text in _TEXT.items():
        if disclaimer == text["disclaimer"]:
            return locale
    raise InvalidReviewBrief("Unknown review brief locale")


def validate_review_brief(brief, *, require_narration=False):
    if not isinstance(brief, dict):
        raise InvalidReviewBrief("Review brief must be an object")
    required = set(PUBLIC_REVIEW_BRIEF_FIELDS)
    if not require_narration:
        required.discard("narration")
    if not require_narration:
        allowed_fields = required
    else:
        allowed_fields = set(PUBLIC_REVIEW_BRIEF_FIELDS)
    if set(brief) != allowed_fields:
        raise InvalidReviewBrief("Review brief fields are invalid")
    if brief.get("contract_version") != OFFICER_REVIEW_BRIEF_CONTRACT_VERSION:
        raise InvalidReviewBrief("Review brief contract version is invalid")
    if brief["review_state"] not in PUBLIC_REVIEW_STATES:
        raise InvalidReviewBrief("Unknown review state")
    if not isinstance(brief["headline"], str) or not brief["headline"].strip():
        raise InvalidReviewBrief("Review headline is invalid")
    if brief["advisory_only"] is not True:
        raise InvalidReviewBrief("Review brief must be advisory")
    if brief.get("as_of") is not None:
        if (
            not isinstance(brief["as_of"], str)
            or not brief["as_of"].strip()
            or "T" not in brief["as_of"]
        ):
            raise InvalidReviewBrief("Review as_of is invalid")
        try:
            datetime.fromisoformat(brief["as_of"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidReviewBrief("Review as_of is invalid") from exc
    evidence_revision = brief.get("evidence_revision")
    if not isinstance(evidence_revision, str) or not re.fullmatch(r"[a-f0-9]{64}", evidence_revision):
        raise InvalidReviewBrief("Review evidence revision is invalid")
    freshness = brief.get("freshness")
    if (
        not isinstance(freshness, dict)
        or set(freshness) != {"state", "warnings"}
        or freshness.get("state") not in {"current", "stale", "unavailable", "unknown"}
        or not isinstance(freshness.get("warnings"), list)
        or len(freshness["warnings"]) > 8
        or any(not isinstance(warning, str) or not warning.strip() for warning in freshness["warnings"])
    ):
        raise InvalidReviewBrief("Review freshness is invalid")
    if freshness["state"] == "stale" and not freshness["warnings"]:
        raise InvalidReviewBrief("Stale review freshness requires warnings")
    actions = brief.get("actions")
    allowed_actions = {
        "open_profile",
        "review_documents",
        "view_repayment_schedule",
    }
    if not isinstance(actions, list) or len(actions) > 3:
        raise InvalidReviewBrief("Review actions are invalid")
    seen_actions = set()
    for action in actions:
        if (
            not isinstance(action, dict)
            or set(action) != {"id", "label", "href"}
            or action["id"] not in allowed_actions
            or action["id"] in seen_actions
            or not isinstance(action["label"], str)
            or not action["label"].strip()
            or not isinstance(action["href"], str)
            or not (
                (action["id"] == "open_profile" and re.fullmatch(r"/officer/profiles/[^/?#]+", action["href"]))
                or (action["id"] == "review_documents" and re.fullmatch(r"/officer/documents(?:\?applicationId=[^&#]+)?", action["href"]))
                or (action["id"] == "view_repayment_schedule" and re.fullmatch(r"/officer/payment-history(?:\?applicationId=[^&#]+)?", action["href"]))
            )
        ):
            raise InvalidReviewBrief("Review actions are invalid")
        seen_actions.add(action["id"])
    locale = _brief_locale(brief)
    if brief["disclaimer"] != _TEXT[locale]["disclaimer"]:
        raise InvalidReviewBrief("Review disclaimer is invalid")
    if not isinstance(brief["reasons"], list) or len(brief["reasons"]) > 40:
        raise InvalidReviewBrief("Review reasons are invalid")
    for reason in brief["reasons"]:
        if not isinstance(reason, dict) or set(reason) != {"code", "label", "detail"}:
            raise InvalidReviewBrief("Review reason is invalid")
        if reason["code"] not in PUBLIC_REASON_CODES:
            raise InvalidReviewBrief("Unknown review reason")
        if not all(isinstance(reason[key], str) and reason[key].strip() for key in ("label", "detail")):
            raise InvalidReviewBrief("Review reason text is invalid")
    if not isinstance(brief["next_steps"], list) or not all(
        isinstance(step, str) and step.strip() for step in brief["next_steps"]
    ):
        raise InvalidReviewBrief("Review next steps are invalid")
    allowed_sources = set(PUBLIC_SOURCE_LABELS[locale].values())
    if not isinstance(brief["sources"], list) or any(
        source not in allowed_sources for source in brief["sources"]
    ):
        raise InvalidReviewBrief("Review sources are invalid")
    if require_narration and (
        not isinstance(brief.get("narration"), str)
        or not brief["narration"].strip()
        or not brief["narration"].strip().endswith(brief["disclaimer"])
    ):
        raise InvalidReviewBrief("Review narration is invalid")
    serialized = json.dumps(brief, ensure_ascii=False).lower()
    if re.search(r"\bget_[a-z][a-z0-9_]*\b", serialized) or any(
        internal in serialized
        for internal in (
            "not_ready_for_review",
            "ready_for_review",
            "is_reviewable",
            "manual_review_required",
        )
    ):
        raise InvalidReviewBrief("Internal identifiers are not public")
    return brief


def _join(values, conjunction):
    if len(values) <= 1:
        return "".join(values)
    if len(values) == 2:
        return f"{values[0]} {conjunction} {values[1]}"
    return f"{', '.join(values[:-1])}, {conjunction} {values[-1]}"


def render_review_brief(brief):
    validate_review_brief(brief)
    locale = _brief_locale(brief)
    text = _TEXT[locale]
    if brief["review_state"] in {"unavailable", "scope_limited"}:
        return "\n".join(
            [brief["headline"], _join(brief["next_steps"], text["and"]), brief["disclaimer"]]
        )
    lines = [f'{text["review_label"]}: {brief["headline"]}']
    if brief["reasons"]:
        lines.extend(
            f'• {reason["label"]}: {reason["detail"]}'
            for reason in brief["reasons"]
        )
    next_label = text["next_label"] if len(brief["next_steps"]) == 1 else text["next_plural_label"]
    lines.append(f"{next_label}:")
    lines.extend(f"• {step}" for step in brief["next_steps"])
    if brief["sources"]:
        lines.append(f'{text["sources_label"]}: {" · ".join(brief["sources"])}')
    lines.append(brief["disclaimer"])
    return "\n".join(lines)
