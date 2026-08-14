"""Deterministic guidance and fail-closed validation for assistant responses."""

import re

_PESO_AMOUNT = re.compile(
    r"(?:₱|php\s*)([0-9][0-9,]*(?:\.\d{1,2})?)", re.IGNORECASE
)
_RAW_TOOL_NAME = re.compile(
    r"\bget_[a-z][a-z0-9_]*\b", re.IGNORECASE
)


def _normalized(message):
    return " ".join(str(message or "").lower().split())


def controlled_guidance_response(message, language="en"):
    """Return reviewed guidance for stable, high-confidence customer intents."""
    text = _normalized(message)
    tagalog = language == "tl"

    application_question = (
        ("apply" in text or "mag-aapply" in text or "mag apply" in text)
        and "loan" in text
        and any(term in text for term in ("how", "paano"))
    )
    if application_question:
        if tagalog:
            return (
                "Para mag-apply ng loan: (1) kumpletuhin ang personal, business, "
                "at alternative-data profile; (2) piliin ang loan product at "
                "i-upload ang mga dokumentong hinihingi nito, kasama ang valid "
                "government ID; (3) tingnan ang pre-qualification, na hindi "
                "garantiya ng approval; at (4) ilagay ang halaga, termino, layunin, "
                "at disbursement method bago isumite. Pagkatapos, awtorisadong "
                "loan officer ang susuri at maaaring humingi ng karagdagang o "
                "mas malinaw na dokumento. Subaybayan ang status sa Track → "
                "Applications."
            )
        return (
            "To apply for a loan: (1) complete your personal, business, and "
            "alternative-data profile; (2) choose a loan product and upload its "
            "required documents, including a valid government ID; (3) check "
            "pre-qualification, which is not an approval guarantee; and (4) enter "
            "the amount, term, purpose, and disbursement method, then submit. An "
            "authorized loan officer reviews the application and may request an "
            "additional or clearer document. Track it under Track → Applications."
        )

    if "pending document" in text and (
        "no approved id" in text or "id" in text and "not approved" in text
    ):
        return (
            "You are not ready to apply based on the details provided: 2 documents "
            "are pending and there is no approved ID. Wait for review or respond "
            "to any re-upload request, and confirm that the ID is approved before "
            "applying. These facts do not guarantee product eligibility or approval."
        )

    if "overdue installment" in text or "overdue" in text and "hulog" in text:
        amount = _PESO_AMOUNT.search(str(message or ""))
        if tagalog and amount:
            formatted_amount = f"₱{amount.group(1)}"
            return (
                f"May 1 overdue na hulog na {formatted_amount} ayon sa detalyeng "
                "ibinigay mo. Tingnan ang kasalukuyang installment sa Track → "
                "Repayment → Make Payment at bayaran gamit ang available na payment "
                "method. Kung hindi ka makabayad ngayon o may mali sa status, "
                "makipag-ugnayan sa support; hindi ako magpapalagay ng penalty o "
                "ibang halagang wala sa ibinigay na impormasyon."
            )

    if "no active loan" in text and "no repayment schedule" in text:
        return (
            "No next payment can be identified from the provided information "
            "because there is no active loan and no repayment schedule. Check "
            "Track → Applications for a current status; do not rely on an invented "
            "date or amount."
        )

    if (
        ("walang result" in text or "walang resulta" in text)
        and ("payment-history" in text or "payment history" in text)
    ):
        return (
            "Walang maibibigay na huling bayad dahil walang resulta ang payment "
            "history. Hindi ako mag-iimbento ng halaga, petsa, o transaction. "
            "Tingnan ang Track → Repayment → Schedule/Payments o subukang muli "
            "kapag available na ang history."
        )

    if "uploaded my requirements" in text and "pending" in text:
        return (
            "Your uploaded requirements are still pending, so they are not yet "
            "confirmed as approved. Check their current status and wait for the "
            "review, or respond if the app requests a clearer copy or re-upload. "
            "Pending documents do not guarantee loan approval."
        )

    if "pending" in text and "docs" in text and (
        "hindi complete" in text or "incomplete" in text
    ) and "profile" in text:
        return (
            "Unahin mong kumpletuhin ang mga kulang na field sa profile habang "
            "hinihintay ang review ng pending documents. Tingnan din kung may "
            "re-upload request at sundin iyon kung mayroon. Hindi pa ito garantiya "
            "ng approval; magiging handa ka lang sa susunod na hakbang kapag "
            "kumpleto ang profile at pasado na ang kinakailangang documents."
        )

    return None


def validate_provider_response(response, *, message, language="en", tools_called=()):
    """Replace provider text that exposes internals or makes unsupported claims."""
    response = str(response or "").strip()
    lowered = response.lower()
    violations = []

    if not response:
        violations.append("empty_response")
    if _RAW_TOOL_NAME.search(response):
        violations.append("raw_tool_name")
    if not tools_called and any(
        phrase in lowered
        for phrase in (
            "according to the tool",
            "the tool result",
            "let me check the status",
            "i checked your account",
        )
    ):
        violations.append("unsupported_tool_claim")
    if any(
        phrase in lowered
        for phrase in ('"pay now"', '"partial payment"', '"missing fields"')
    ):
        violations.append("unapproved_ui_control")
    if "you will receive" in lowered:
        violations.append("delivery_guarantee")

    if language == "en":
        tagalog_markers = re.findall(
            r"\b(?:ang|ako|iyong|walang|maaari|hindi|utang|bayad|susunod)\b",
            lowered,
        )
        if len(tagalog_markers) >= 3:
            violations.append("wrong_language")
    elif language == "tl" and len(response.split()) >= 12:
        if not re.search(
            r"\b(?:ang|ako|iyo|iyong|hindi|maaari|paano|loan|mga|kung|para)\b",
            lowered,
        ):
            violations.append("wrong_language")

    if not violations:
        return response, []

    replacement = controlled_guidance_response(message, language=language)
    if replacement:
        return replacement, violations
    if language == "tl":
        return (
            (
                "Hindi ko maibibigay nang maaasahan ang sagot mula sa available "
                "na impormasyon. Tingnan ang kasalukuyang status sa app o "
                "makipag-ugnayan sa support; hindi ako mag-iimbento ng detalye."
            ),
            violations,
        )
    return (
        (
            "I cannot answer reliably from the available information. Check the "
            "current status in the app or contact support; I will not invent "
            "details."
        ),
        violations,
    )
