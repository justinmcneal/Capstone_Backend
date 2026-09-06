"""Recipient resolution for document review notifications.

Implements D-014: assigned customers notify only their currently assigned
officer(s); unassigned customers fall back to permitted admins.
Pure helper kept separate from persistence/broker calls for testability.
"""


def _dedupe(recipients, seen_emails):
    deduped = []
    for recipient in recipients:
        email = (recipient.get("email") or "").strip()
        if not email:
            continue
        key = email.lower()
        if key in seen_emails:
            continue
        seen_emails.add(key)
        deduped.append(recipient)
    return deduped


def resolve_review_recipients(
    *, assigned_officer_ids, officers, admins, get_display_name
):
    """Resolve officer/admin recipients without touching the database.

    Args:
        assigned_officer_ids: set of currently assigned officer id strings.
        officers: iterable of LoanOfficer-like objects (id, email, has_permission).
        admins: iterable of Admin-like objects (used only when unassigned).
        get_display_name: callable(user, fallback) -> str.

    Returns:
        dict with officers, admins, reason.
    """
    seen_emails = set()

    if assigned_officer_ids:
        officers_out = []
        for officer in officers or []:
            if not officer.has_permission("review_documents"):
                continue
            if str(officer.id) not in assigned_officer_ids:
                continue
            officers_out.append(
                {
                    "email": (officer.email or "").strip(),
                    "name": get_display_name(officer, fallback="Loan Officer"),
                    "user_id": officer.id,
                    "user_type": "loan_officer",
                }
            )
        officers_out = _dedupe(officers_out, seen_emails)
        if officers_out:
            return {
                "officers": officers_out,
                "admins": [],
                "reason": "assigned_ok",
            }
        return {"officers": [], "admins": [], "reason": "no_eligible_officer"}

    admins_out = []
    for admin in admins or []:
        if not admin.has_permission("review_documents"):
            continue
        admins_out.append(
            {
                "email": (admin.email or "").strip(),
                "name": get_display_name(admin, fallback="Admin"),
                "user_id": admin.id,
                "user_type": "admin",
            }
        )
    admins_out = _dedupe(admins_out, seen_emails)
    if admins_out:
        return {
            "officers": [],
            "admins": admins_out,
            "reason": "unassigned_admin_fallback",
        }
    return {"officers": [], "admins": [], "reason": "no_eligible_admin"}
